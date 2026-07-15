# Changelog

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
