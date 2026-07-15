# cardly-cli

Unofficial command-line interface for the [Cardly](https://www.cardly.net) API v2 —
send real, physical cards from your terminal.

**Not affiliated with Cardly.** MIT licensed.

## Install

```bash
uv tool install cardly-cli
```

## Configure

The API key is resolved in this order: `--api-key` > `CARDLY_API_KEY` > a profile in
`~/.config/cardly/config.toml`.

```bash
cardly configure set prod --api-key live_xxx --default
cardly configure set sandbox --api-key test_xxx
```

Rather than storing the key on disk, point a profile at any command that prints it
on stdout:

```bash
cardly configure set prod --api-key-cmd 'your-secret-tool read cardly/api-key'
```

`cardly configure list` never prints stored keys — it shows an array of row objects
(`[{name, base_url, has_key, default}]`), one per profile.

Verify with a free call that spends no credit:

```bash
cardly echo
cardly account balance
```

### Test mode

Keys prefixed `test_` validate everything and mutate nothing: `orders place` returns
`testMode: true`, no card is sent, no credit is spent. The CLI prints a banner
whenever a response is test-mode, so a test key can't be mistaken for a real send.

Note that test keys **cannot create webhooks** — that needs a `live_` key.

## Usage

```bash
# Preview before spending credit — returns a watermarked proof and the cost
cardly orders preview --artwork thank-you-01 \
  --to-first-name Ada --to-address "12 Analytical Way" \
  --to-city Melbourne --to-country AU \
  --message "Thanks for everything!" \
  --download proof.pdf

# Send
cardly orders place --artwork thank-you-01 \
  --to-first-name Ada --to-address "12 Analytical Way" \
  --to-city Melbourne --to-country AU \
  --message "Thanks for everything!"

# Anything without a dedicated command
cardly api GET users
```

`orders place`/`orders preview` also accept a raw `--data`/`-d` JSON body (inline,
`@file`, or `-` for stdin). A body carrying `lines[]` is treated as the complete
request and is **mutually exclusive** with the card-shaping flags (`--artwork`,
`--to-*`, `--message`, ...) — mixing the two errors rather than silently picking one.
`place` sends `lines[]` as-is (it's already the shape the endpoint wants); `preview`
takes a single flat card, so it **unwraps** a one-element `lines[]` rather than
rejecting it — `--data lines[]` with more or fewer than one element is an error.

Global flags: `--json`, `--jq`, `--quiet`, `--verbose`, `--no-color`, `--profile`,
`--api-key`, `--base-url`, `--config-path`, `--no-retry`, `--max-retries`,
`--idempotency-key`.

Environment variables: `CARDLY_API_KEY`, `CARDLY_BASE_URL`, `CARDLY_PROFILE`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Generic failure (includes 422 validation) |
| 2 | Config/credential resolution |
| 3 | 401/403 — bad key or insufficient privileges |
| 4 | 404 |
| 5 | 429 after retries |
| 6 | 5xx after retries |
| 7 | Network failure or timeout |
| 8 | **402 — insufficient credit** |

`8` is separate because it's the one failure a scheduled job must treat differently:
not transient, not a bug, and no amount of retrying will conjure credit.

## Safety

Every POST carries an `Idempotency-Key` (a fresh UUID per invocation, reused across
that invocation's retries). Pin one with `--idempotency-key` for scripted retries.
This is what makes retrying a timed-out `orders place` safe: if the order landed and
only the response was lost, the replay returns the stored result rather than sending
a second card.

### If a POST times out

If every retry attempt on a POST (e.g. `orders place`) times out, the CLI cannot tell
you whether the card was mailed — only that the response never came back. It exits 7
with a message like:

```
Error: Cardly POST orders/place timed out after 4 attempts. The order MAY have been
placed — check `cardly orders list` before retrying. To retry safely, re-run with
--idempotency-key <the-key-that-was-used>
```

Do this, in order:

1. **Check first**: run `cardly orders list` (or `cardly orders get <id>` if you have
   reason to guess an id) before doing anything else. If the order is there, you're
   done — do not resend.
2. **If you must retry**, re-run the exact same command with
   `--idempotency-key <the-key-printed-above>`. Cardly will replay the stored result
   from the original attempt instead of mailing a second card, if the first attempt
   actually landed.
3. **Never** just re-run the bare command. Each invocation mints a fresh
   `Idempotency-Key` by default — a second invocation with no key pinned is a
   genuinely new write, and if the first one landed, you now have two cards mailed
   and two charges.

Run with `--verbose` up front on anything that spends credit if you want the key
logged as it's used, rather than only after a timeout.

`contacts update` sends whatever fields you pass as a `POST` — it is documented and
tested against the belief that this **merges** rather than replaces the contact.
That belief is unverified (see "Known-unverified" below); if it turns out to replace,
a single-field edit would silently wipe the rest.

`contacts delete-all` requires an explicit `--data` body — Cardly's docs don't say
what a bodyless call to that endpoint does, and it could mean "delete every contact
in the list." The CLI refuses to guess. `cardly api DELETE contact-lists/<id>/contacts`
remains the escape hatch if you need to call it bodyless anyway.

## Verifying webhook postbacks

```bash
cardly webhooks verify postback.json --secret sh-xxx
```

Cardly's docs describe **two** signing schemes and share one worked example between
them, so the example can't tell them apart. This command tries whichever the inputs
allow and tells you which matched:

```bash
# Body scheme: timestamp/data/signatures inside the payload
cardly webhooks verify postback.json --secret sh-xxx

# Header scheme: Cardly-Timestamp + Cardly-Signatures
cardly webhooks verify body.json --secret sh-xxx \
  --header "Cardly-Timestamp=$TS" --header "Cardly-Signatures=$SIGS"
```

If you run a real postback through it, **we'd love to know which scheme matched** —
see "Known-unverified" below.

## Known-unverified

This CLI's tests are fully mocked, by design. That means they confirm we send what we
*believe* Cardly wants — they can't confirm the belief. These points are recorded
from Cardly's docs and a working n8n integration, but are **not** confirmed against
the live API. Passing CI must not be read as having checked any of these:

- **Which webhook signature scheme is live.** Cardly's docs describe two schemes and
  both cite the same worked example, so the example can't discriminate between them,
  and neither has been validated against a real postback. `webhooks verify` tries
  both and reports which matched.
- **Pagination on `/contact-lists`, `/contact-lists/{id}/contacts`, and `/webhooks`.**
  `limit`/`offset` are documented in prose but declared on no list endpoint in
  Cardly's OpenAPI spec. We send them anyway and page defensively — advancing by the
  returned page size, warning if the server clamps `limit`, and stopping if an
  endpoint appears to ignore `offset`.
- **Whether credit-history accepts date-only filters.** We pad to midnight rather
  than find out in production.
- **Rate limits.** A 429 exists; no numbers and no `RateLimit-*` headers are
  documented. We back off adaptively.
- **Whether `contacts update` merges or replaces.** If it replaces, a single-field
  edit via the CLI would wipe every other field on the contact. The command's help
  text documents this uncertainty; treat a partial update as a full overwrite until
  proven otherwise.
- **What a bodyless `contacts delete-all` does.** It could mean "delete every
  contact in the list." The CLI requires an explicit `--data` body rather than find
  out; `cardly api DELETE contact-lists/<id>/contacts` remains the escape hatch.
- **Which `Content-Type` Cardly's live API actually wants.** Cardly's prose docs say
  `text/json`; the OpenAPI schema says `application/json`. We send
  `application/json` because a working n8n integration uses it successfully — that's
  the only evidence we have, and it has not been verified directly against the live
  API here.

Issues and corrections very welcome.

## Deliberate omissions

These are facts about the API, not gaps:

- **No `orders cancel`** — cancellation is portal-only, despite a
  `contact.order.refunded` webhook event existing.
- **No `lists update`** — Cardly has no contact-list update endpoint; a list's name
  and description can't be edited via the API.
- **No gift-card flag** — gift cards attach by selecting a template that contains
  one. There's no API to mint or choose one ad hoc.
- **No `PUT`** — Cardly uses `POST` for updates throughout.

## Coming in v0.2

`users`, `invitations`, and `art upload/update/delete`. All reachable today via
`cardly api`.

## Development

```bash
uv sync --all-extras --dev
uv run pytest -q
uv run ruff check src tests && uv run black --check src tests && uv run mypy
```

Tests never touch the network and require no credentials.
