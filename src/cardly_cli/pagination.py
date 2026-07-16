from __future__ import annotations

from typing import Any, Callable, Iterator

from cardly_cli.client import CardlyClient

# Measured 2026-07-15 against api.card.ly with a real sandbox key: `limit` is
# honoured but clamped server-side to a floor of 5 (asking for 1-5 all return
# 5) and a ceiling of 250 (asking for 251-300 all return 250; meta.limit
# echoes the clamped value). 250 is the server's actual maximum for a single
# page, so defaulting lower would needlessly truncate every listing.
DEFAULT_LIMIT = 250


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

    NOTE: measured 2026-07-15 against a real sandbox key: `limit` is honoured
    (floor 5, ceiling 250) but `offset` is ignored on every endpoint tested
    with enough records to tell (/media, /fonts, /doodles) — the server
    always returns page 1. That means no more than 250 records can ever be
    retrieved from a Cardly list endpoint; `--all` cannot page past the
    ceiling once an account has more than 250 of something. Everything
    defensive below follows from that.
    """
    base_params = dict(params or {})
    offset = 0
    seen_signature: str | None = None
    yielded = 0

    while True:
        page_params = dict(base_params)
        page_params["limit"] = limit
        page_params["offset"] = offset
        data = client.get(endpoint, params=page_params)
        results = extract_results(data)

        if not results:
            return

        # Guard: an endpoint that ignores `offset` returns page 1 forever.
        # Without this we loop until Cardly rate-limits us (429). Compare the
        # FULL page: a true stall returns a byte-identical page, while two
        # legitimately different pages differ somewhere — so this cannot
        # false-positive and silently drop real records.
        signature = repr(results)
        if signature == seen_signature:
            if warn:
                total = total_records(data)
                warn(
                    f"{endpoint} returned an identical page for offset={offset}, so it "
                    f"appears to ignore `offset`. Stopping after {yielded} record(s) to "
                    f"avoid an endless loop — the result may be INCOMPLETE"
                    + (f" (the API reports {total} total)" if total is not None else "")
                    + ". Cardly does not declare limit/offset on its list endpoints; try a "
                    "larger --limit to fetch more in one page."
                )
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
        yielded += len(results)

        # Advance by what we RECEIVED, never by what we asked for. If the
        # server clamps `limit`, advancing by the request skips the difference
        # silently (ask 100, get 25, jump 100 -> records 26-100 vanish).
        offset += len(results)

        total = total_records(data)
        if total is not None and offset >= total:
            return
