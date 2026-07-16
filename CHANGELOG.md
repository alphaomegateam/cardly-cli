# Changelog

## 0.2.1 — Unreleased

### Fixed

- **`--all` was only ever returning the first page of any list endpoint,
  silently.** `paginate()` walked pages by sending `limit` + `offset`, per
  Cardly's documentation — but Cardly does not paginate by `offset`; it
  paginates by `page`. `offset` is a response-only field and is silently
  ignored as a request parameter, so every "next page" request was
  identical to the first and `--all` just re-fetched page 1 forever.
  `paginate()` now sends `page` (starting at 1, incrementing by 1) and
  terminates on an empty page, `meta.lastRecord >= meta.totalRecords`, or a
  page shorter than the requested `limit`. Verified live 2026-07-15: walking
  `page=1..5` against a 443-record `/doodles` list retrieves all 443 unique
  records.
- Simplified `paginate()` accordingly: the old offset-stall guard and
  clamp-mismatch warning existed only to cope with the `offset` bug (pages
  repeating forever) and are no longer needed with real termination
  conditions — removed, along with the `warn` parameter and every call
  site's `warn=state.warn`.

### Changed

- Raised `DEFAULT_LIMIT` from 100 to **250**. Live testing against the real
  Cardly API (2026-07-15, real sandbox key) measured `limit` clamped to a
  floor of 5 and a ceiling of 250 per page, so 250 minimises round trips —
  it is the max **page size**, not a cap on total records retrievable. The
  clamp is harmless under page-based paging: a smaller-than-requested page
  just means the walk takes more pages.
- Documented that **Cardly's own documentation is wrong about pagination**:
  it says list endpoints "accept limit and offset" and instructs walking
  pages by increasing `offset`, with a worked example that does not work
  against the live API. We now follow the API's actual behaviour (`page`)
  instead of the documented one, with a note in both the README and
  `pagination.py` warning against reverting this.

## [0.2.0] — 2026-07-15

Completes API coverage.

### Added

- `users` — list, get, find, delete (by ID or email)
- `invitations` — list (with accepted/expired filters), get, find, create, resend
  (by ID or email), delete (by ID or email)
- `art` — upload, update, delete. Images are base64-encoded into a JSON body;
  `--media` is required and its UUID comes from `cardly ref media`.
- `invitations list` hides accepted invitations unless `--include-accepted` is
  passed — this is Cardly's default, surfaced in the help text.

## [0.1.0] — 2026-07-15

### Added

- Initial release of `cardly-cli`. Unofficial CLI for the Cardly API v2.
- `orders` — place, preview (with `--download` proof PDF), get, list.
- `contacts` — create, sync, get, list, find, update, delete, delete-all.
- `lists` — list, get, create, delete.
- `webhooks` — list, get, create, update, delete, and dual-scheme `verify`.
- `account` — balance, credit-history, gift-credit-history.
- `ref` — fonts, writing-styles, doodles, templates, media.
- `art` — list, get.
- `echo`, `configure`, and a generic `api` escape hatch for any endpoint.
- Idempotency keys on every POST; retry on 429/5xx and POST timeouts.
- Exit code 8 for 402 insufficient credit.
