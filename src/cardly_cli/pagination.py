from __future__ import annotations

from typing import Any, Callable, Iterator

from cardly_cli.client import CardlyClient

# The documented default is 25; we ask for more to cut round trips. See the
# clamp cross-check below for why asking is not the same as receiving.
DEFAULT_LIMIT = 100


def extract_results(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return data["results"]
    return []


def total_records(data: Any) -> int | None:
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("totalRecords"), int):
        return meta["totalRecords"]
    if isinstance(data.get("totalRecords"), int):
        return data["totalRecords"]
    return None


def paginate(
    client: CardlyClient,
    endpoint: str,
    *,
    params: dict[str, Any] | None = None,
    limit: int = DEFAULT_LIMIT,
    warn: Callable[[str], None] | None = None,
) -> Iterator[Any]:
    """Walk a Cardly list endpoint via offset/limit.

    NOTE: `limit`/`offset` are documented in the API's prose but are NOT
    declared as parameters on any list endpoint in the OpenAPI spec, and remain
    unverified against /contact-lists, /contact-lists/{id}/contacts and
    /webhooks. Everything defensive below follows from that uncertainty.
    """
    base_params = dict(params or {})
    offset = 0
    seen_signature: tuple | None = None

    while True:
        page_params = dict(base_params)
        page_params["limit"] = limit
        page_params["offset"] = offset
        data = client.get(endpoint, params=page_params)
        results = extract_results(data)

        if not results:
            return

        # Guard: an endpoint that ignores `offset` returns page 1 forever.
        # Without this we loop until Cardly rate-limits us (429).
        signature = (offset, len(results), repr(results[0]))
        if seen_signature is not None and signature[1:] == seen_signature[1:]:
            return
        seen_signature = signature

        meta = data.get("meta") if isinstance(data, dict) else None
        if warn and isinstance(meta, dict):
            served = meta.get("limit")
            if isinstance(served, int) and served != limit:
                warn(
                    f"Cardly clamped limit {limit} to {served} on {endpoint}; "
                    f"paging by the returned page size."
                )

        yield from results

        # Advance by what we RECEIVED, never by what we asked for. If the
        # server clamps `limit`, advancing by the request skips the difference
        # silently (ask 100, get 25, jump 100 -> records 26-100 vanish).
        offset += len(results)

        total = total_records(data)
        if total is not None and offset >= total:
            return
