from __future__ import annotations

from typing import Any, Iterator

from cardly_cli.client import CardlyClient

# Measured 2026-07-15 against api.card.ly with a real sandbox key: `limit` is
# honoured but clamped server-side to a floor of 5 (asking for 1-5 all return
# 5) and a ceiling of 250 (asking for 251-300 all return 250; meta.limit
# echoes the clamped value). 250 is the server's actual maximum for a single
# page, so defaulting lower would needlessly truncate every listing. The
# clamp is harmless for pagination: if a page comes back smaller than
# requested, the walk below just takes more pages.
#
# Pagination itself is by `page`, NOT `offset`. CARDLY'S OWN DOCUMENTATION IS
# WRONG ABOUT THIS: it states that list endpoints "accept limit and offset"
# and instructs you to "increase the offset parameter by the limit value" to
# walk pages, with a worked example (`?limit=10&offset=20`). That documented
# contract does not work — `offset` is a RESPONSE field only (computed
# server-side as `(page-1) * limit`) and is silently ignored as a request
# parameter. `page` is what actually advances the result set. Verified live
# 2026-07-15: `?limit=5&page=2` returns records 6-10; the equivalent
# `?limit=5&offset=5` returns records 1-5 again (page 1, offset ignored
# entirely). Walking `page=1..5` against a 443-record /doodles list
# retrieved all 443 unique records, no duplicates.
#
# DO NOT "fix" this back to offset-based paging because Cardly's docs say
# so — the docs are wrong, and doing so will silently reintroduce the bug
# where `--all` only ever returned the first page.
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


def _last_record(data: Any) -> int | None:
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("lastRecord"), int):
        return meta["lastRecord"]
    return None


def paginate(
    client: CardlyClient,
    endpoint: str,
    *,
    params: dict[str, Any] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> Iterator[Any]:
    """Walk a Cardly list endpoint by `page` (not `offset` — see module comment).

    Sends `page=1, 2, 3, ...` with `limit` on every request. Stops when a
    page comes back empty, when `meta.lastRecord >= meta.totalRecords`, or
    when a page comes back shorter than the requested `limit`.
    """
    base_params = dict(params or {})
    page = 1

    while True:
        page_params = dict(base_params)
        page_params["limit"] = limit
        page_params["page"] = page
        data = client.get(endpoint, params=page_params)
        results = extract_results(data)

        if not results:
            return

        yield from results

        total = total_records(data)
        last_record = _last_record(data)
        if total is not None and last_record is not None and last_record >= total:
            return

        if len(results) < limit:
            return

        page += 1
