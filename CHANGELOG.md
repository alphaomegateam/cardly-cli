# Changelog

## 0.2.1 — Unreleased

### Fixed

- `paginate()` now detects when a list endpoint ignores `offset` (an identical
  page repeating) and warns that the result may be incomplete, instead of
  looping until Cardly rate-limits the client or silently under-returning.

### Changed

- Raised `DEFAULT_LIMIT` from 100 to **250**. Live testing against the real
  Cardly API (2026-07-15, real sandbox key) measured `limit` clamped to a
  floor of 5 and a ceiling of 250, so 250 is the server's actual per-page
  maximum — defaulting lower needlessly truncated every listing.
- Documented, with measured evidence, that `offset` is ignored on every
  Cardly list endpoint tested with enough records to tell (`/media`,
  `/fonts`, `/doodles` — 3 of 3), and that combined with the 250 ceiling on
  `limit`, **no more than 250 records can ever be retrieved from a single
  Cardly list endpoint** — `--all` cannot page past that.

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
