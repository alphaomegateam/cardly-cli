from __future__ import annotations

import sys
import time
import uuid
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

import httpx

from cardly_cli.config import CardlySettings
from cardly_cli.envelope import flatten_validation, raise_for_state, state_messages, unwrap
from cardly_cli.errors import CardlyError
from cardly_cli.retry import AttemptResult, RetryPolicy, is_cached_replay

TIMEOUT = 30.0


def url_for(settings: CardlySettings, endpoint: str) -> str:
    # Absolute URLs pass through unchanged: Task 13's preview-PDF download
    # follows a fully-qualified URL returned by an earlier API call, which
    # must not be re-prefixed with base_url.
    if endpoint.startswith("http://"):
        # Cardly returns preview URLs as http://; upgrade so the API key
        # (attached only when the host matches ours) never crosses in
        # plaintext.
        return "https://" + endpoint[len("http://") :]
    if endpoint.startswith("https://"):
        return endpoint
    # Flat join: Cardly has no per-tenant path segment (loxo's `slug`).
    return f"{settings.base_url}/{endpoint.lstrip('/')}"


class CardlyClient:
    """httpx wrapper owning auth, the response envelope, idempotency, and retry.

    Deliberately has no `put()`: Cardly uses POST for updates throughout, and
    exposing PUT would only invite mistakes.
    """

    def __init__(
        self,
        settings: CardlySettings,
        *,
        verbose: bool = False,
        retry: RetryPolicy | None = None,
        idempotency_key: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._verbose = verbose
        self._retry = retry if retry is not None else RetryPolicy()
        self._sleep = sleep
        # ONE key per client instance == one per CLI invocation, reused across
        # every retry of every POST in that invocation. Regenerating per attempt
        # would destroy duplicate protection: Cardly only replays a stored
        # response when the key matches. (Replaying a key with a *changed* body
        # is a hard error, so the key is bound to the invocation, not reused
        # across different bodies in a way we'd have to reason about — each
        # command issues one logical write.)
        self._idempotency_key = idempotency_key or str(uuid.uuid4())
        self.last_request_id: str | None = None
        self._cardly_host = urlparse(settings.base_url).hostname
        self._http = httpx.Client(
            headers={"Accept": "application/json"},
            # Never follow redirects: httpx's `_redirect_headers` strips only
            # `Authorization` on a cross-origin redirect, not a custom
            # `API-Key` header. Following one would silently deliver the live
            # key to whatever the redirect points at. A 3xx now surfaces as a
            # normal non-success response -> a loud CardlyError instead of a
            # silent leak.
            follow_redirects=False,
            timeout=TIMEOUT,
        )

    def __enter__(self) -> "CardlyClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _headers_for(self, method: str, json: Any | None, target: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        if json is not None:
            # Cardly's prose docs say `text/json`; the OpenAPI schema declares
            # `application/json`. The n8n integration sends `application/json`
            # successfully, which is the only evidence we have — this has NOT
            # been verified against the live API directly (see README's
            # Known-unverified section, open question on Content-Type).
            headers["Content-Type"] = "application/json"
        if method.upper() == "POST":
            # POST only — Cardly ignores the header on other verbs.
            headers["Idempotency-Key"] = self._idempotency_key
        target_host = urlparse(target).hostname
        if target_host is not None and self._cardly_host is not None:
            if target_host.lower() == self._cardly_host.lower():
                # Only attach the key to our own host. Task 13's preview/PDF
                # download and any other absolute-URL target (e.g. a CDN)
                # must never receive it.
                headers["API-Key"] = self._settings.api_key
        return headers

    def _error_from_response(
        self, response: httpx.Response, method: str, endpoint: str
    ) -> CardlyError:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        messages = state_messages(payload)
        detail = " ".join(messages) if messages else response.text[:500]
        if response.status_code == 422 and isinstance(payload, dict):
            flattened = flatten_validation(payload.get("data"))
            if flattened:
                detail = f"{detail} ({flattened})" if messages else flattened
        return CardlyError(
            f"Cardly {method.upper()} {endpoint} returned {response.status_code}: {detail}",
            status_code=response.status_code,
        )

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        raw: bool = False,
    ) -> Any:
        target = url_for(self._settings, endpoint)
        # Resolved once, outside the retry loop: the target doesn't change
        # across retries, and this is what keeps the idempotency key stable
        # across every retry of a given POST.
        headers = self._headers_for(method, json, target)
        previous: AttemptResult | None = None
        attempt = 0

        while True:
            started = time.monotonic()
            try:
                response = self._http.request(
                    method, target, params=params, json=json, headers=headers or None
                )
            except httpx.TimeoutException as exc:
                if self._retry.should_retry(status_code=None, is_timeout=True, method=method) and (
                    attempt < self._retry.max_retries
                ):
                    self._log(method, target, note="timeout, retrying")
                    self._sleep(self._retry.delay_for(attempt))
                    attempt += 1
                    continue
                attempts_made = attempt + 1
                if method.upper() == "POST":
                    # A POST timeout is uniquely dangerous: the request may
                    # have reached Cardly and mailed the card before the
                    # response was lost. The idempotency key is what makes a
                    # retry safe, and it is otherwise never surfaced anywhere
                    # (C1) — print it here, the one moment it matters.
                    message = (
                        f"Cardly POST {endpoint} timed out after {attempts_made} attempts. "
                        f"The order MAY have been placed — check `cardly orders list` before "
                        f"retrying. To retry safely, re-run with --idempotency-key "
                        f"{self._idempotency_key}"
                    )
                else:
                    message = f"Cardly {method.upper()} {endpoint} timed out"
                raise CardlyError(
                    message,
                    status_code=None,
                    is_timeout=True,
                ) from exc
            except httpx.HTTPError as exc:
                raise CardlyError(
                    f"Cardly {method.upper()} {endpoint} request failed: {exc}", status_code=None
                ) from exc

            elapsed = time.monotonic() - started
            self.last_request_id = response.headers.get("Request-Id")
            self._log(method, target, request_id=self.last_request_id)

            if response.is_success:
                if raw:
                    return response
                if not response.content:
                    return None
                try:
                    payload = response.json()
                except ValueError as exc:
                    # A 200 with a non-JSON body (proxy/WAF interstitial, etc.)
                    # must degrade to a clean CardlyError, not a bare traceback.
                    raise CardlyError(
                        f"Cardly {method.upper()} {endpoint} returned 200 with a "
                        f"non-JSON body.",
                        status_code=response.status_code,
                    ) from exc
                raise_for_state(payload, status_code=response.status_code)
                return unwrap(payload)

            current = AttemptResult(status_code=response.status_code, body=response.content)
            # Only POST carries an Idempotency-Key, so only POST can be a
            # replay served from Cardly's idempotency store. A GET/DELETE
            # that returns two identical fast 5xx responses is an ordinary
            # transient condition (e.g. a load balancer), not a replay — it
            # must retry the full budget, not abort early.
            if method.upper() == "POST" and is_cached_replay(previous, current, elapsed):
                # Cardly stored this failure against our idempotency key and is
                # replaying it without reprocessing. More retries cannot help.
                # Build on the normal error so the server's actual message
                # (state.messages) survives instead of being discarded.
                err = self._error_from_response(response, method, endpoint)
                raise CardlyError(
                    f"{err.message} — replayed from the idempotency store; retrying cannot "
                    f"change it. Use a new --idempotency-key to force reprocessing.",
                    status_code=response.status_code,
                )

            retryable = self._retry.should_retry(
                status_code=response.status_code, is_timeout=False, method=method
            )
            if retryable and attempt < self._retry.max_retries:
                previous = current
                self._sleep(self._retry.delay_for(attempt))
                attempt += 1
                continue

            raise self._error_from_response(response, method, endpoint)

    def _log(
        self, method: str, target: str, *, request_id: str | None = None, note: str | None = None
    ) -> None:
        if not self._verbose:
            return
        # Method + URL + Request-Id + (POST only) Idempotency-Key. NEVER log
        # headers wholesale: that would leak the API key into logs and bug
        # reports. The idempotency key is logged explicitly and only it — it
        # is a random UUID, not a secret, and surfacing it here is what lets
        # `--verbose` answer "what key do I retry with" before a timeout ever
        # happens (C1).
        line = f"{method.upper()} {target}"
        if request_id:
            line += f" (Request-Id: {request_id})"
        if method.upper() == "POST":
            line += f" (Idempotency-Key: {self._idempotency_key})"
        if note:
            line += f" [{note}]"
        print(line, file=sys.stderr)

    def get(self, endpoint: str, **kw: Any) -> Any:
        return self.request("GET", endpoint, **kw)

    def post(self, endpoint: str, **kw: Any) -> Any:
        return self.request("POST", endpoint, **kw)

    def delete(self, endpoint: str, **kw: Any) -> Any:
        return self.request("DELETE", endpoint, **kw)


def build_client(
    settings: CardlySettings,
    *,
    verbose: bool = False,
    retry: RetryPolicy | None = None,
    idempotency_key: str | None = None,
) -> CardlyClient:
    return CardlyClient(settings, verbose=verbose, retry=retry, idempotency_key=idempotency_key)
