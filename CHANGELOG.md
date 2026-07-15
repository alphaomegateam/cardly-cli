# Changelog

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
