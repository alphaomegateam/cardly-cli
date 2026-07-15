from __future__ import annotations

import sys
import time
import uuid
from typing import Any, Callable, Mapping

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
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
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
        self._http = httpx.Client(
            headers={
                # NOT `Authorization: Bearer`. Cardly uses a bare API-Key header.
                "API-Key": settings.api_key,
                "Accept": "application/json",
            },
            follow_redirects=True,
            timeout=TIMEOUT,
        )

    def __enter__(self) -> "CardlyClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _headers_for(self, method: str, json: Any | None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if json is not None:
            # The docs' prose says `text/json`; the OpenAPI declares
            # application/json, and that is what actually works.
            headers["Content-Type"] = "application/json"
        if method.upper() == "POST":
            # POST only — Cardly ignores the header on other verbs.
            headers["Idempotency-Key"] = self._idempotency_key
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
        headers = self._headers_for(method, json)
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
                raise CardlyError(
                    f"Cardly {method.upper()} {endpoint} timed out",
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
                payload = response.json()
                raise_for_state(payload, status_code=response.status_code)
                return unwrap(payload)

            current = AttemptResult(status_code=response.status_code, body=response.content)
            if is_cached_replay(previous, current, elapsed):
                # Cardly stored this failure against our idempotency key and is
                # replaying it without reprocessing. More retries cannot help.
                raise CardlyError(
                    f"Cardly {method.upper()} {endpoint} returned {response.status_code} "
                    f"replayed from the idempotency store; retrying cannot change it. "
                    f"Use a new --idempotency-key to force reprocessing.",
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
        # Method + URL + Request-Id only. NEVER headers: that would leak the
        # API key into logs and bug reports.
        line = f"{method.upper()} {target}"
        if request_id:
            line += f" (Request-Id: {request_id})"
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
