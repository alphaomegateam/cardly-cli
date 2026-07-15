# cardly-cli — Design

**Date:** 2026-07-15
**Status:** Approved, pending implementation plan

## Summary

`cardly-cli` is an unofficial command-line interface for the Cardly API (v2), the
physical greeting-card sending service at cardly.net. It provides even coverage of
the full API surface — 31 paths / 49 operations — modelled closely on the existing
`loxo-cli` (Typer + httpx + pydantic + rich).

Distribution: public GitHub repo under `alphaomegateam`, MIT licensed, published to
PyPI as `cardly-cli` with a `cardly` entry point. Hatchling build, GitHub Actions,
`src/` layout — identical to loxo-cli.

## Motivation

No open-source CLI or SDK for the Cardly API exists in any package registry
(verified 2026-07-15 across npm, PyPI, crates.io, RubyGems, Packagist, and GitHub).
The only published integrations bind to a workflow platform: `@pipedream/cardly`,
Zapier/Pabbly connectors, a Composio MCP toolkit, and our own `n8n-nodes-cardly`.
There is no way to drive this API from a terminal or a shell script.

## Prior art and sources

Two independent sources informed this design, and they resolve each other's gaps:

1. **`alphaomegateam/n8n-nodes-cardly`** (MIT, ours) — the authoritative record of
   how the API *actually behaves*. Its hard-won quirks are carried over wholesale
   and cited throughout this document.
2. **The official OpenAPI 3.1.0 spec** at
   `https://api.card.ly/openapi/en-AU/2.2.0/json` (note: root host, **not** under
   `/v2`; locale and version are path segments). Spec version 2.2.0, single server
   `https://api.card.ly/v2`.

Prose-only concerns — errors, idempotency, pagination, webhook signing — appear in
the docs page's embedded JS blob and **not** in the spec. Both sources were needed.

The spec is used as a **development-time reference only** — to cross-check paths and
enums. It is not generated from and is not a runtime dependency. Rationale in
"Alternatives considered".

## Decisions

| Decision | Choice |
|---|---|
| Scope | Full, even API coverage — no privileged workflow |
| Distribution | Public GitHub (`alphaomegateam`), MIT, PyPI `cardly-cli`, entry point `cardly` |
| Config | `--api-key` > `CARDLY_API_KEY` > `~/.config/cardly/config.toml` profiles with `api_key_cmd` |
| Order input | Typed flags merged over `--data` JSON |
| Idempotency | Auto-generated v4 UUID on every POST; `--idempotency-key` override |
| Retries | Bounded exponential backoff + jitter on 429/5xx; `--no-retry`, `--max-retries` |
| Signature verify | Yes — `cardly webhooks verify` |
| Tests | Mocked only (respx). **No 1Password coupling anywhere in the codebase.** |

## Architecture

```
src/cardly_cli/
  __main__.py          # app, AppState, global flags, sub-app registration
  config.py            # profiles, CARDLY_API_KEY, api_key_cmd  (no slug)
  client.py            # httpx wrapper: API-Key header, envelope unwrap, idempotency, retry
  errors.py            # CardlyError + exit-code mapping (adds 402)
  envelope.py          # {state, data} unwrap; ValidationStatus flattening
  pagination.py        # single offset/limit scheme
  retry.py             # bounded backoff w/ jitter for 429/5xx
  signature.py         # md5(secret.timestamp.raw_data) verify + raw-slice extraction
  output.py            # render/--jq  (ported ~unchanged from loxo-cli)
  models/              # base, order, contact, contact_list, webhook, art, account,
                       # user, invitation
  commands/
    _app.py _helpers.py
    configure.py orders.py contacts.py lists.py webhooks.py
    art.py ref.py account.py users.py invitations.py echo.py api.py
```

The spine is loxo-cli's: `AppState` on the Typer context with lazily-resolved
settings, a `CardlyGroup(TyperGroup)` mapping domain errors to exit codes (Typer does
not honour a raised `ClickException.exit_code`), `render()` for `--json`/`--jq`/table
output, and TOML profiles.

### New modules (vs. loxo-cli)

- **`envelope.py`** — every Cardly response is `{state, data}`. Unwrapping lives in
  one place, not sprinkled through commands. Also owns 422 `ValidationStatus`
  flattening.
- **`pagination.py`** — collapses loxo's three schemes to one (offset/limit).
- **`retry.py`** — new capability.
- **`signature.py`** — new capability.

### Divergences from loxo-cli's client

- **No `slug`.** Cardly's base URL is flat; `url_for()` loses a path segment and
  config drops a required field.
- **No `put()`.** Cardly uses POST for updates throughout — there is no PUT or PATCH
  anywhere in the API. Exposing `put` would only invite mistakes.

### Models

Nine model modules. Cardly's `Order` nests four levels deep
(`order.items[].delivery.tracking`). Model the top two levels as typed fields and let
`extra="allow"` carry the rest — full fidelity for fields people actually read, no
schema-chasing every time Cardly ships a build. Same approach as loxo-cli's
`LoxoModel`.

## Authentication

Header: **`API-Key: <key>`** — not `Authorization: Bearer`. HTTPS required.

Keys are prefixed `test_` or `live_`. Test keys execute and validate everything but
**perform no mutations**: a test-mode Place Order validates and returns a
near-identical response with **`testMode: true`**, no order placed, no credit spent.
When a response carries `testMode: true`, output leads with a banner so a test key is
never mistaken for a real send.

Test keys **cannot create webhooks** — a live key is required.

Credential check / smoke test: `GET /account/balance` (free, no credit).

**Unresolved conflict:** the docs prose says to send `Content-type: text/json`; the
spec declares request bodies as `application/json`. The n8n node sends
`application/json` and works, so the spec wins. JSON only — form-encoded is not
supported.

## Command groups

| Group | Operations |
|---|---|
| `orders` | `place`, `preview`, `preview --download`, `get {id}`, `list` |
| `contacts` | `create`, `sync`, `get`, `list`, `find`, `update`, `delete`, bulk delete-by-body |
| `lists` | `list`, `get`, `create`, `delete` (**no update — endpoint does not exist**) |
| `webhooks` | `list`, `get`, `create`, `update`, `delete`, `verify` |
| `art` | `list`, `get`, `upload`, `delete` |
| `ref` | `fonts`, `writing-styles`, `doodles`, `templates`, `media` |
| `account` | `balance`, `credit-history`, `gift-credit-history` |
| `users` | `list`, `get`, `find`, `delete {id}`, `delete --email` |
| `invitations` | `list`, `get`, `create`, `find`, `resend`, `delete {id}`, `delete --email` |
| `echo` | connectivity/auth smoke check |
| `configure` | profile management |
| `api` | generic escape hatch (any method/path) |

## Orders

`place` and `preview` share one flag set and one `build_line()` builder, differing
only at the final wrap:

- `place` → `POST /orders/place` with `{lines: [line], purchaseOrderNumber}`
- `preview` → `POST /orders/preview` with the line **flat, not wrapped**

```
cardly orders place --artwork thank-you-01 \
  --to-first-name Ada --to-last-name Lovelace \
  --to-address "12 Analytical Way" --to-city Melbourne \
  --to-region VIC --to-postcode 3000 --to-country AU \
  --message "Thanks for everything!" --shipping standard

cardly orders place --data @order.json     # full control / multi-line
```

### Flags

- `--to-*` / `--from-*` prefixes mirror `recipient` / `sender`.
- `--message` is repeatable, building `messages.pages[]` positionally (first
  `--message` → `page: 1`, the front). `--message-page N=text` to skip or reorder.
  The key is **`page`** (1-based int), *not* `name`.
- `--var k=v` → template `variables` (flat key→value map).
- `--style k=v` → card-level `Style` (`align`, `color`, `font`, `size`,
  `verticalAlign`, `writing`).
- `--artwork` accepts a **UUID or a slug** (e.g. `happy-birthday`).
- Merge precedence via loxo-cli's `build_payload`: typed flags > `--data` > defaults.

### Client-side validation (before spending a request)

- **Sender is all-or-nothing.** If any `--from-*` is set, the required set must be
  complete → fail locally with a clear message. If none are set, omit the key
  entirely so Cardly's org defaults apply.
- **Shipping is region-gated.** `standard` = all regions; `tracked` = **AU only**;
  `express` = **AU and US only**. Checked against `--to-country` to preempt a 422.

### Deliberately NOT validated

**`region`/`postcode` conditional requirement by country.** The spec contradicts
itself (`sender.required` lists them while `x-conditionallyRequired` also lists
them), no country table exists, and the API is the only authority. Guessing would
reject valid addresses. Flags stay optional; the 422 surfaces cleanly.

### Preview

Response: `data.preview.urls.card`, `data.preview.urls.envelope` (absent for
postcards), `data.preview.expires`, `data.order.creditCost`. Previews are
low-quality and watermarked.

Three carried-over traps:
1. URLs are returned as `http://` — force-upgrade to `https://`.
2. They **expire** (`preview.expires`) — never cache across runs; regenerate.
3. They live on `api.card.ly`, not a pre-signed CDN link — the PDF fetch needs the
   `API-Key` header too.

### Not built (no API surface exists)

- **Order cancel** — portal-only, despite the `contact.order.refunded` event.
- **Gift-card selection** — there is no gift-card field in the Place Order body.
  Gift cards ride along by selecting a `Template` that contains one
  (`Template.giftCard`). Consumption surfaces as `costs.giftCredit` against a
  separate gift-credit balance. No API mints or chooses one ad hoc.

## Contacts and lists

**Contacts get their own address model, separate from orders.** This is the single
most important modelling decision here.

| Concept | Orders | Contacts |
|---|---|---|
| City | `city` | **`locality`** |
| Region (read) | `region` | **`adminAreaLevel1`** |

The n8n design spec is blunt: "The request builders must not share a single address
shape or contact creation will 422." `models/contact.py` and `models/order.py` each
own their address vocabulary. **Add a code comment recording why** — the DRY instinct
to unify them is a trap, and this looks like duplication to a well-meaning cleanup.

Contact fields: `externalId`, `firstName` (req), `lastName`, `email`, `company`,
`address` (req), `address2`, `locality` (req), `region`, `country` (req), `postcode`,
`fields` (map keyed by Cardly field code).

```
cardly contacts create <list-id> --first-name Ada --email ada@example.com \
    --address "12 Analytical Way" --locality Melbourne --country AU
cardly contacts sync <list-id> --external-id crm-42 ...   # upsert
cardly contacts find <list-id> --query ada@example.com
```

- **`sync` requires at least one of `--external-id` / `--email`** — it's the match
  key. Enforced client-side; no point spending a round trip.
- **`create` rejects duplicates** server-side on those same fields. The error message
  should point at `sync` as the fix.
- **Contact `update` is a POST** to the contact path, not PUT/PATCH.

**Lists** get list/get/create/delete and pointedly **no update** — a list's
name/description cannot be edited via the API. Create body:
`{name, description?, fields: [{name, type: text|date|number|url, description?}]}`.

## Webhooks

Nine events: `contact.order.created`, `contact.order.sent`, `contact.order.refunded`,
`giftCard.redeemed`, `qrCode.scanned`, `contact.undeliverable`,
`contact.changeOfAddress`, `consignment.undeliverable`,
`consignment.changeOfAddress`.

- Create requires `targetUrl` + `events[]`; optional `description`, `metadata`.
- **The `secret` is returned only once, at creation.** Surface it prominently. The
  only recovery from losing it is delete + recreate.
- **Update requires `--target-url`** even when only toggling `disabled`.
- `Webhook.protected` (bool) marks webhooks created by Zapier etc. — don't clobber.
- **Limit: 10** active-or-disabled webhooks (excludes Zapier-created).
- Delivery: HTTPS + valid SSL required. Retries on non-200 for up to 3 days with
  exponential backoff, then email warning, then auto-disable. **Order is not
  guaranteed; at-least-once, so duplicates are possible.**

### Signature verification

The docs give **two contradictory algorithms** (a body `signatures` array vs. a
`Cardly-Signatures` header). **The n8n node settled this empirically** — it shipped
the header guess first, then commit `1e826ef` replaced it with the real scheme. We
take the n8n version as ground truth:

```
signature = md5(secret + "." + timestamp + "." + <JSON-encoded data>)
```

- It is **not a header**. The postback body carries `timestamp`, `data`, and a
  `signatures` **array**; a match against any entry passes (compare with a
  constant-time comparison).
- Golden vector: `md5('secretabc.1234567890.{"test":true}')` →
  `6ef4f0658ff7bb880fc3ae0cf7db3b2a`.
- Cardly signs `data` **as transmitted**, so extract the **raw byte slice** of the
  top-level `data` property rather than re-serializing — re-`json.dumps()` changes
  key order and whitespace and silently breaks the hash. Extraction must be
  depth-aware so a nested `"data"` key isn't mistaken for the root one.
- Fail closed.
- MD5, not HMAC — weak by modern standards, but it is what Cardly implements.

**The postback payload has no schema in the spec** — prose only mentions `timestamp`,
event type, webhook `metadata`, `data`, and `signatures`.

## Reference and account

`ref` mirrors loxo-cli's reference group: `fonts`, `writing-styles`, `doodles`,
`templates`, `media`. `--organisation-only` is exposed **only** on fonts, doodles,
and media — the three that support it.

`account` gets `balance` (returns credit plus a `giftCredit` {balance, currency}
sub-object — two separate currencies of value) and the two credit histories.

**Credit-history date filters** use dotted comparison operators with a
space-separated, second-precision datetime — `YYYY-MM-DD HH:MM:SS`, *not* ISO-T:

```
effectiveTime.gte=2026-07-01 00:00:00
effectiveTime.lte=2026-07-31 23:59:59
```

The CLI accepts a normal ISO date and converts (`.replace("T", " ")[:19]`).

## Users and invitations

Both expose **two delete forms**: by id (`delete <id>`) and by email at the
collection root (`delete --email`). Invitations additionally get `create`, `resend`
(both collection-level and `resend/{id}`), and `find --email`.

## Pagination

**Offset/limit — not cursor.** Params `limit` and `offset`. Envelope:

```json
{"state": {"status": "OK", "messages": [], "version": 1234},
 "data": {"meta": {"orderBy": "name", "orderDirection": "asc",
                   "startRecord": 21, "lastRecord": 30, "limit": 10,
                   "page": 3, "offset": 20, "totalRecords": 395},
          "results": []}}
```

Default `limit` = **100** (fewer round trips; the documented default is 25).

**⚠️ `limit`/`offset` are documented in prose but NOT declared as parameters on any
list endpoint in the OpenAPI spec.** Spec-driven codegen would silently omit them —
one of the reasons codegen was rejected. The n8n node sends them anyway and its
maintainer flagged that pagination on `/contact-lists`, `/contact-lists/{id}/contacts`
and `/webhooks` **needs live confirmation**. Treat as unverified; document as such in
the README rather than let passing mocked tests imply otherwise.

**Termination is defensive:** stop when `results` comes back empty **or**
`totalRecords` is reached. If an endpoint ignores `offset` and returns the same page
forever, we terminate rather than loop and hammer the API into a 429. Same instinct
as loxo-cli's `after_id` cursor-stall guard.

## Errors and exit codes

Cardly signals failure in two places at once: the HTTP status, and a `state.status`
of `OK|WARN|ERROR` with human-readable `state.messages[]` inside a 200-shaped
envelope. `envelope.py` normalizes both into one `CardlyError` so commands never
parse response shapes themselves.

Exit codes extend loxo-cli's, keeping every existing number stable:

| Code | Meaning |
|---|---|
| 1 | Generic failure |
| 2 | Config/credential resolution |
| 3 | 401/403 — bad key, or key lacking privileges |
| 4 | 404 |
| 5 | 429 — after retries exhausted |
| 6 | 5xx — after retries exhausted |
| 7 | Network failure or timeout |
| **8** | **402 — insufficient credit** |

402 earns its own code because it is the one failure a scheduled job must treat
differently: not a bug, not transient, retrying will never help — top up the account.
Folding it into generic 1 makes it invisible to exactly the automation that needs to
see it.

Special handling:
- **422** — `data` is a flat `{field: reason}` map. Flatten to
  `field: reason; field: reason`, don't dump JSON at the user.
- **402** — join `state.messages` and append cost-vs-balance from the body, so the
  message says what it needed and what you had.
- **429/5xx** — retry with bounded exponential backoff + jitter before reaching the
  user. Exit code reflects the *final* failure.

## Idempotency and retries

Header: `Idempotency-Key: <key>`, **POST only** (other verbs ignore it). Max 64
chars; v4 UUID. Replays return the stored status + body without re-processing.

Every POST carries an auto-generated v4 UUID; `--idempotency-key` overrides for
scripts that want to pin one.

**The safety case for retrying POSTs rests entirely on this**, so precision matters:

- A key is **not consumed** when the request fails before processing (bad
  credentials, missing params) — those retries are free.
- Replaying a key with a **changed body is a hard error** (request-signature
  mismatch). Therefore the key is generated **once per invocation and reused across
  that invocation's retries**, never regenerated per attempt. Get this backwards and
  the protection silently evaporates.

**Rate limits are undocumented** — a 429 exists, but no numbers and no
`RateLimit-*`/`X-RateLimit-*` headers anywhere in spec or docs. Treat 429 adaptively
via backoff rather than budgeting against a known ceiling.

## Observability and secrets

- `--verbose` logs method, URL, and the **`Request-Id`** response header (which
  Cardly's support portal indexes on) — but **never headers**, which would leak the
  API key. Same reasoning as loxo-cli's bearer-token comment.
- JSON output **bypasses Rich's colorizer entirely**: Rich reports
  `is_terminal=True` under `FORCE_COLOR` even into a pipe, wrapping output in ANSI
  escapes that break `json.loads` and `--jq` consumers.

## Testing

pytest + respx mocking httpx at the transport layer. One `test_cmd_*.py` per command
module, plus unit tests for shared machinery. Typer's `CliRunner` drives real
invocations, so tests exercise flag parsing, payload building, and exit codes end to
end without network.

**No 1Password coupling anywhere in the codebase** — no `op://` references, no live
API tests, nothing shelling out to `op` in fixtures. `config.py` keeps the generic
`api_key_cmd` shell-out (a neutral mechanism; pointing it at `op read` lives in the
user's own config file, outside the repo). Tests cover `api_key_cmd` with a trivial
`echo`-style command.

Beyond straight loxo-cli parity, these each map to a specific way this API bites:

- **The two order body shapes** — `place` wraps in `lines[]`, `preview` is flat, from
  one shared builder. Asserting both shapes from identical flags is what stops a
  future refactor from "unifying" them.
- **The address vocabulary split** — contacts serialize `locality`, orders serialize
  `city`. This is the documented 422, and it looks like duplication to a cleanup.
- **Signature golden vector** — plus a test that the raw byte slice of `data` is used
  rather than re-`json.dumps()`, and that extraction is depth-aware.
- **Idempotency key stability across retries** — one key per invocation, reused every
  attempt. The whole POST-retry safety case collapses if a retry mints a fresh key,
  and nothing else would catch that.
- **Pagination termination** — including an endpoint that ignores `offset` and
  returns the same page forever.
- **Sender all-or-nothing**, both directions: partial fails locally; fully-empty
  omits the key.
- **Exit-code mapping** — one test per code, especially the new 402.

### Known limitation of mocked tests

Mocks confirm we send what we *believe* we send; they cannot confirm our recorded API
behavior is still true. The n8n node is strong evidence for the shapes, but
pagination on `/contact-lists` and `/webhooks` is flagged unverified there too, and
mocks won't settle it. **Note it in the README as known-unverified** rather than let
passing tests imply we checked. Settling it would take a `test_` key against `/echo`
and a list endpoint in one manual pass — outside the test suite, no 1P in the repo.

## Alternatives considered

**Generate the client from the OpenAPI spec.** Tempting — 31 paths, 30 schemas, free
typed models, updates as Cardly ships. Rejected because the spec is wrong in exactly
the places that matter: `limit`/`offset` are undeclared, so every list command would
silently lose pagination; no field in `lines[]` is marked required, so generated
validation would be vacuous; `sender` contradicts itself on `region`/`postcode`; the
webhook postback has no schema at all. We'd inherit a locale- and version-pinned URL
(`en-AU/2.2.0`) and still hand-write every workaround. Codegen's output would be
wrong precisely where the n8n node learned the truth the hard way. The spec is a map,
not a foundation.

**Declarative endpoint table + generic dispatcher.** Shortest code for even coverage.
Rejected because the interesting parts of this API are all irregular — `place` wraps
in `lines[]` while `preview` is flat, contacts use `locality` where orders use
`city`, artwork upload is multipart, webhook create returns a write-once secret. A
generic table handles the boring 70% and fights you on the 30% that matters.

## Open questions / unverified

Carried forward explicitly rather than guessed:

1. **Pagination on `/contact-lists`, `/contact-lists/{id}/contacts`, `/webhooks`** —
   `limit`/`offset` undeclared in spec; unconfirmed live. Document as unverified.
2. **`Content-type: text/json`** (docs prose) vs `application/json` (spec). Using
   `application/json`, which the n8n node proves works.
3. **Webhook signature** — resolved in favour of the n8n scheme (body `signatures`
   array), but the docs' header variant (`Cardly-Signatures` + `Cardly-Timestamp`)
   remains documented. Fallback if postbacks fail verification.
4. **Webhook postback payload** — no formal schema.
5. **Rate limits** — no numbers, no headers.
6. **Which endpoints return 201** — spec shows 200 on inspected creates, though 201
   is documented as in use.
