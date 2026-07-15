# cardly-cli — Design

**Date:** 2026-07-15
**Status:** Approved, pending implementation plan
**Revision:** 2 — incorporates an adversarial review that fact-checked r1 against the
live docs prose and OpenAPI JSON. See "Review corrections" for what changed and why.

## Summary

`cardly-cli` is an unofficial command-line interface for the Cardly API (v2), the
physical greeting-card sending service at cardly.net. It targets even coverage of the
full API surface — 31 paths / **48 operations** — modelled closely on the existing
`loxo-cli` (Typer + httpx + pydantic + rich).

Distribution: public GitHub repo under `alphaomegateam`, MIT licensed, published to
PyPI as `cardly-cli` with a `cardly` entry point. Hatchling build, GitHub Actions,
`src/` layout — identical to loxo-cli.

**Shipped in two stages** (see "Scope and staging"): v0.1 delivers the core value;
v0.2 completes coverage.

## Motivation

No open-source CLI or SDK for the Cardly API exists in any package registry
(verified 2026-07-15 across npm, PyPI, crates.io, RubyGems, Packagist, and GitHub).
The only published integrations bind to a workflow platform: `@pipedream/cardly`,
Zapier/Pabbly connectors, a Composio MCP toolkit, and our own `n8n-nodes-cardly`.
There is no way to drive this API from a terminal or a shell script.

## Prior art and sources

Three sources informed this design:

1. **The official OpenAPI 3.1.0 spec** at
   `https://api.card.ly/openapi/en-AU/2.2.0/json` (note: root host, **not** under
   `/v2`; locale and version are path segments). Spec version 2.2.0, single server
   `https://api.card.ly/v2`. Authoritative for **paths, schemas, and enums**.
2. **The docs page prose** at `https://api.card.ly/v2/docs`. Errors, idempotency,
   pagination, and webhook signing are documented **here and nowhere else** — they do
   not appear in the OpenAPI spec. Authoritative for **semantics**.
3. **`alphaomegateam/n8n-nodes-cardly`** (MIT, ours) — a working implementation
   against the same API. Strong evidence for request/response shapes, and the source
   of several hard-won quirks carried over below.

**On the weight given to (3):** the n8n node is a careful reading of the same docs,
not an oracle. Where this spec cites it, it is corroboration — not proof. Revision 1
of this document wrongly claimed the node had "settled empirically" a question it had
only re-read the docs on. That claim has been removed. See "Webhooks → Signature
verification".

The OpenAPI spec is used as a **development-time reference only** — to cross-check
paths and enums. It is not generated from and is not a runtime dependency. Rationale
in "Alternatives considered".

## Decisions

| Decision | Choice |
|---|---|
| Scope | Full, even API coverage — no privileged workflow. Staged v0.1 / v0.2. |
| Distribution | Public GitHub (`alphaomegateam`), MIT, PyPI `cardly-cli`, entry point `cardly` |
| Config | `--api-key` > `CARDLY_API_KEY` > `~/.config/cardly/config.toml` profiles with `api_key_cmd`; plus `--base-url`/`CARDLY_BASE_URL`, `--profile`/`CARDLY_PROFILE` |
| Order input | Typed flags merged over `--data` JSON |
| Idempotency | Auto-generated v4 UUID on every POST; `--idempotency-key` override |
| Retries | Bounded backoff + jitter on 429/5xx **and POST timeouts**; cached-replay detection; `--no-retry`, `--max-retries` |
| Signature verify | Yes — `cardly webhooks verify`, **tolerant of both documented schemes** |
| Tests | Mocked only (respx). **No 1Password coupling anywhere in the codebase.** |

## Scope and staging

Full coverage remains the goal; it ships in two stages so review checkpoints stay
tractable and value lands sooner.

- **v0.1 (core):** `configure`, `echo`, `account`, `orders`, `contacts`, `lists`,
  `webhooks`, `ref`, `art list/get`, `api`.
- **v0.2 (completion):** `users`, `invitations`, `art upload/update/delete`.

The v0.2 split is not arbitrary. `users`/`invitations` are an admin surface that is
trivially regular (list/get/find/delete ×2 forms) and adds no new machinery. `art`
upload/update is the one genuinely novel I/O path in the whole API — base64-embedded
image payloads (see "Artwork") — and deserves its own attention rather than being
rushed alongside 40 other operations.

## Architecture

```
src/cardly_cli/
  __main__.py          # app, AppState, global flags, sub-app registration
  config.py            # profiles, CARDLY_API_KEY, CARDLY_BASE_URL, api_key_cmd (no slug)
  client.py            # httpx wrapper: API-Key header, envelope unwrap, idempotency, retry
  errors.py            # CardlyError + exit-code mapping (adds 402)
  envelope.py          # {state, data} unwrap; ValidationStatus flattening
  pagination.py        # single offset/limit scheme
  retry.py             # bounded backoff w/ jitter; cached-replay detection
  signature.py         # md5 postback verification (both documented schemes)
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
- **`retry.py`** and **`signature.py`** — new capabilities.

### Divergences from loxo-cli's client

- **No `slug`.** Cardly's base URL is flat; `url_for()` loses a path segment and
  config drops a required field.
- **No `put()`.** Cardly uses POST for updates throughout — there is no PUT or PATCH
  anywhere in the API. Exposing `put` would only invite mistakes.

### Ported from loxo-cli — explicitly kept

These exist in loxo-cli and are **not** dropped:

- **`--base-url` / `CARDLY_BASE_URL`** — needed to point at a mock server, and the
  n8n credential kept a baseUrl override for the same future-proofing reason.
- **`--profile` / `CARDLY_PROFILE`**, `--quiet`, `--verbose`, `--no-color`,
  `--json`, `--jq`.
- **`--filter`** client-side exact-match post-filtering on list commands
  (`_helpers.py:apply_filters`).

**`build_payload` must be adapted, not ported.** loxo's version returns
`{resource_key: merged}` — Cardly's bodies are **top-level, unwrapped**. Porting it
verbatim ships `{"order": {...}}` and 422s everything. The merge *precedence* is what
carries over: typed flags > `--data` > defaults.

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

Test keys **cannot create webhooks** (the docs' general "no mutations" rule; the n8n
node guards for it explicitly).

Credential check / smoke test: `GET /account/balance` (free, no credit).

**Unresolved conflict:** the API's own description text says to send
`Content-type: text/json`; the OpenAPI declares request bodies as
`application/json`. The n8n node sends `application/json` and works, so we do too.
JSON only — form-encoded is not supported.

## Command groups

| Group | Operations | Stage |
|---|---|---|
| `orders` | `place`, `preview`, `preview --download`, `get {id}`, `list` | v0.1 |
| `contacts` | `create`, `sync`, `get`, `list`, `find`, `update`, `delete`, bulk delete-by-body | v0.1 |
| `lists` | `list`, `get`, `create`, `delete` (**no update — endpoint does not exist**) | v0.1 |
| `webhooks` | `list`, `get`, `create`, `update`, `delete`, `verify` | v0.1 |
| `ref` | `fonts`, `writing-styles`, `doodles`, `templates`, `media` | v0.1 |
| `account` | `balance`, `credit-history`, `gift-credit-history` | v0.1 |
| `echo` | connectivity/auth smoke check | v0.1 |
| `configure` | profile management | v0.1 |
| `api` | generic escape hatch (any method/path) | v0.1 |
| `art` | `list --own-only`, `get` | v0.1 |
| `art` | `upload`, `update`, `delete` | v0.2 |
| `users` | `list`, `get`, `find`, `delete {id}`, `delete --email` | v0.2 |
| `invitations` | `list`, `get`, `create`, `find`, `resend`, `delete {id}`, `delete --email` | v0.2 |

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

Complete typed coverage of the line body — every field below is a first-class flag,
not `--data`-only:

- `--artwork` — **UUID or slug** (e.g. `happy-birthday`).
- `--template` — template ID. Without it, only main text panels are used and no
  variable substitution happens.
- `--quantity` — min 1, default 1. Same template/vars for every copy; **not** a
  personalisation mechanism.
- `--to-*` / `--from-*` — mirror `recipient` / `sender`.
- `--message` — repeatable, building `messages.pages[]` positionally (first
  `--message` → `page: 1`, the front). `--message-page N=text` to skip or reorder.
  The key is **`page`** (1-based int), *not* `name`. Cardly's own OpenAPI example
  mixes `{"page":1}` with `{"name":2}` — the buggy example is precisely why this
  warning exists.
- `--var k=v` → template `variables` (flat key→value map).
- `--style k=v` → card-level `Style` (`align`, `color`, `font`, `size`,
  `verticalAlign`, `writing`).
- `--shipping` — `standard` | `tracked` | `express`.
- `--ship-to-me` — recipient is sender; adds a blank envelope and **extra credit cost
  per card**.
- `--requested-arrival` — future arrival date (the scheduling field).
- `--purchase-order-number` — top-level on `place`, alongside `lines`.

Merge precedence: typed flags > `--data` > defaults.

### Client-side validation (before spending a request)

- **Sender is all-or-nothing.** If any `--from-*` is set, the required set must be
  complete → fail locally with a clear message. If none are set, omit the key
  entirely so Cardly's org defaults apply.
- **Shipping is region-gated.** `standard` = all regions; `tracked` = **AU only**;
  `express` = **AU and US only**. Checked against `--to-country` to preempt a 422.

### Deliberately NOT validated: region/postcode

The OpenAPI contradicts itself. For order `sender`, `required` lists
`firstName, address, city, region, postcode, country` while `x-conditionallyRequired`
*also* lists `region, postcode`. For **contacts it is worse**: `required` =
`[firstName, address, locality, region, country, postcode]` with **no**
`x-conditionallyRequired` marker at all — yet region/postcode plainly cannot be
required for every country (UK/NZ don't use `region`; some countries have no
postcode).

No country table exists and the API is the only authority. Guessing rejects valid
addresses. **Flags stay optional in both orders and contacts; the 422 surfaces
cleanly.** Record this in the models so nobody later "fixes" them against the
OpenAPI `required` list.

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

Contact fields: `externalId`, `firstName`, `lastName`, `email`, `company`, `address`,
`address2`, `locality`, `region`, `country`, `postcode`, `fields` (map keyed by
Cardly field code). On required-ness, see "Deliberately NOT validated" above —
`firstName`/`address`/`locality`/`country` are always needed; `region`/`postcode`
are left to the API.

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

## Artwork

`GET /art` takes **`ownOnly`** (not `organisationOnly` — that param belongs to the
`ref` endpoints), exposed as `art list --own-only`. `GET /art/{id}` accepts a **UUID
or slug**.

**`POST /art` and `POST /art/{id}` (Edit Artwork) are `application/json`, not
multipart.** The body carries an `artwork` array of `{page, image}` where `image` is
a **base64-encoded string of the image file contents**. The CLI accepts file paths
and does the base64 encoding itself.

This is the only place in the API where request-body size is a real concern —
base64 inflates payloads ~33%, and a multi-page card of print-resolution images is
not small. v0.2 should measure before assuming it's fine.

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

**The docs describe two different schemes and we do not know which is live.** Both
appear on the docs page; both cite the *same* golden vector, so the vector cannot
discriminate between them.

| | Scheme A — "Verify Postback Signatures" (Best Practices) | Scheme B — "Secure Your Endpoint" (Using Webhooks) |
|---|---|---|
| Timestamp from | postback body's `timestamp` property | `Cardly-Timestamp` **header** |
| Payload | JSON-encoded `data` **object** | **raw request body** |
| Compare against | body's `signatures` **array** | `Cardly-Signatures` JSON-encoded **header** |

Shared primitive: `md5(secret + "." + timestamp + "." + payload)`.
Shared golden vector: `md5('secretabc.1234567890.{"test":true}')` →
`6ef4f0658ff7bb880fc3ae0cf7db3b2a` (recomputed and confirmed).

**Neither scheme has been validated against a live postback.** The n8n node
implements Scheme A, having initially shipped a different guess and then corrected it
against the docs — a docs-reading correction, *not* an empirical test. Its own design
spec planned a live-key validation and there is no record it happened. Revision 1 of
this document wrongly reported this as settled; it is not.

**Therefore `cardly webhooks verify` is dual-scheme tolerant:** it accepts optional
headers alongside the body, tries whichever schemes the available inputs permit, and
reports **which one matched**. If none match, the error names the schemes tried
rather than asserting the signature is bad. This is strictly better than picking one
and being wrong — and the command doubles as the instrument that finally settles the
question the first time a real postback runs through it.

Implementation constraints (both schemes):
- Cardly signs the payload **as transmitted** — extract the **raw byte slice** rather
  than re-serializing. Re-`json.dumps()` changes key order and whitespace and
  silently breaks the hash. Extraction must be depth-aware so a nested `"data"` key
  isn't mistaken for the root one. (The n8n `signature.ts` does exactly this.)
- Constant-time comparison; a match against **any** entry in the signatures array
  passes.
- Fail closed.
- MD5, not HMAC — weak by modern standards, but it is what Cardly implements.

**The postback payload has no schema in the OpenAPI** — prose only mentions
`timestamp`, event type, webhook `metadata`, `data`, and `signatures`.

## Reference and account

`ref` mirrors loxo-cli's reference group: `fonts`, `writing-styles`, `doodles`,
`templates`, `media`. **`--organisation-only` is exposed only on fonts, doodles, and
media** — the three that declare it. (`/art` uses a different param, `ownOnly`.)

`account` gets `balance` (returns credit plus a `giftCredit` {balance, currency}
sub-object — two separate currencies of value) and the two credit histories.

**Credit-history date filters** use dotted comparison operators with a
space-separated, second-precision datetime — `YYYY-MM-DD HH:MM:SS`, *not* ISO-T.
**All four operators are declared** (`.lt`, `.lte`, `.gt`, `.gte`) and all four are
exposed:

```
effectiveTime.gte=2026-07-01 00:00:00
effectiveTime.lte=2026-07-31 23:59:59
```

The CLI accepts a normal ISO datetime and converts (`.replace("T", " ")[:19]`).
**Date-only input must be padded to midnight** — a bare `2026-07-01` passes through
as a 10-char string, and it is unconfirmed whether the API accepts that. Pad
explicitly rather than find out in production.

## Users and invitations (v0.2)

Both expose **two delete forms**: by id (`delete <id>`) and by email at the
collection root (`delete --email`, a JSON body). Invitations additionally get
`create`, `resend` (both collection-level and `resend/{id}`), and `find --email`.

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
list endpoint in the OpenAPI spec** (0 occurrences). Spec-driven codegen would
silently omit them — one reason codegen was rejected. The n8n node sends them anyway
and its maintainer flagged pagination on `/contact-lists`,
`/contact-lists/{id}/contacts` and `/webhooks` as **needing live confirmation**.
Treat as unverified; document as such in the README rather than let passing mocked
tests imply otherwise.

**Advance `offset` by `len(results)`, never by the requested `limit`.** The n8n node
does `offset += limit` (`GenericFunctions.ts:96`). If a server clamps `limit` below
what we asked for — plausible, given the param is undeclared and unverified — that
silently skips records: ask for 100, get 25, jump offset by 100, lose records 26–100.
Advancing by the returned page size is correct under clamping and identical when
there's none.

**Cross-check `meta.limit` against the requested limit** and warn on mismatch, so
clamping is visible rather than silent.

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
see it. (402 is declared only on `/orders/place`.)

Special handling:
- **422** — `data` is a flat `{field: reason}` map. Flatten to
  `field: reason; field: reason`, don't dump JSON at the user.
- **402** — join `state.messages`. The docs say the 402 carries "detail on the
  required credit cost and your current balance," but **the declared 402 schema
  contains only `state`** — that detail plausibly lives in the message text. Surface
  structured cost/balance **when present**; never depend on it.
- **429/5xx** — retry with bounded exponential backoff + jitter before reaching the
  user. Exit code reflects the *final* failure.

## Idempotency and retries

Header: `Idempotency-Key: <key>`, **POST only** (other verbs ignore it). Max 64
chars; v4 UUID. Every POST carries an auto-generated key; `--idempotency-key`
overrides for scripts that want to pin one.

Cardly's documented semantics, and what each implies:

- **The result is stored regardless of success**, once the request "started
  processing." Subsequent requests with the same key **return the stored result
  without hitting the processing layer**.
  → *A 5xx that lands after processing begins is cached against the key.* Retrying
  with the same key replays that 5xx forever. Such a retry is duplicate-**safe** but
  **futile**. `retry.py` therefore detects a cached replay — an instantly-returned
  identical response — and **bails immediately with a clear message** instead of
  burning the backoff budget.
- **A key is not consumed** when the request fails before processing (bad
  credentials, missing params). → those retries are free.
- **Replaying a key with a changed body is a hard error** (request-signature
  mismatch). → the key is generated **once per invocation and reused across that
  invocation's retries**, never regenerated per attempt. Get this backwards and
  duplicate-protection silently evaporates.
- **Timeouts are the canonical use case.** The docs: *"if a request to the Place
  Order endpoint does not result in a response, or the response times out, you can
  retry the exact same request again and receive the response you would have
  otherwise missed."*
  → **POST timeouts are retried**, reusing the key. This is the case the mechanism
  exists for, and it is exactly the case where a naive CLI double-charges: the order
  landed, the response was lost, the user re-runs. Timeouts on non-POST verbs, and
  POST timeouts after retries are exhausted, still exit 7.

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
- **`build_payload` emits an unwrapped body** — no `{"order": {...}}` resource key.
  Guards against a too-faithful port of loxo's version.
- **Signature golden vector**, plus: raw byte slice rather than re-`json.dumps()`;
  depth-aware extraction; and **both schemes verified**, with the report naming which
  matched.
- **Idempotency key stability across retries** — one key per invocation, reused every
  attempt. The whole POST-retry safety case collapses if a retry mints a fresh key,
  and nothing else would catch that.
- **POST timeout triggers a retry carrying the same key**; a cached-replay response
  aborts the backoff loop instead of exhausting it.
- **Pagination**: offset advances by `len(results)` under a clamped `limit` (the
  record-skipping regression); termination when an endpoint ignores `offset`.
- **Sender all-or-nothing**, both directions: partial fails locally; fully-empty
  omits the key.
- **Exit-code mapping** — one test per code, especially the new 402.

### Known limitation of mocked tests

Mocks confirm we send what we *believe* we send; they cannot confirm our recorded API
behavior is still true. **Note in the README as known-unverified:** pagination on
`/contact-lists`, `/contact-lists/{id}/contacts` and `/webhooks`; which webhook
signature scheme is live; whether `limit` is clamped. Settling these takes a `test_`
key against `/echo` and a list endpoint, plus one real postback through
`webhooks verify` — a manual pass, outside the test suite, no 1P in the repo.

## Alternatives considered

**Generate the client from the OpenAPI spec.** Tempting — 31 paths, 30 schemas, free
typed models, updates as Cardly ships. Rejected because the spec is wrong in exactly
the places that matter: `limit`/`offset` are undeclared, so every list command would
silently lose pagination; no field in `lines[]` is marked required, so generated
validation would be vacuous; `sender` and the contact bodies contradict themselves on
`region`/`postcode`; the webhook postback has no schema at all; and the `messages`
example ships `{"name":2}` where the field is `page`. We'd inherit a locale- and
version-pinned URL (`en-AU/2.2.0`) and still hand-write every workaround. The spec is
a map, not a foundation.

**Declarative endpoint table + generic dispatcher.** Shortest code for even coverage.
Rejected because the interesting parts of this API are all irregular — `place` wraps
in `lines[]` while `preview` is flat, contacts use `locality` where orders use
`city`, webhook create returns a write-once secret, artwork carries base64-embedded
images, users/invitations have two delete forms each. A generic table handles the
boring 70% and fights you on the 30% that matters.

## Open questions / unverified

Carried forward explicitly rather than guessed:

1. **Which webhook signature scheme is live.** Two documented, both plausible, same
   golden vector, never tested against a real postback. Mitigated by making `verify`
   accept both and report which matched.
2. **Pagination on `/contact-lists`, `/contact-lists/{id}/contacts`, `/webhooks`** —
   `limit`/`offset` undeclared in the OpenAPI; unconfirmed live. Mitigated by
   advancing on `len(results)` and cross-checking `meta.limit`.
3. **`Content-type: text/json`** (API description text) vs `application/json`
   (OpenAPI). Using `application/json`, which the n8n node proves works.
4. **Webhook postback payload** — no formal schema.
5. **Rate limits** — no numbers, no headers.
6. **Which endpoints return 201** — the OpenAPI shows 200 on every inspected create,
   though 201 is documented as in use.
7. **Whether credit-history accepts date-only values.** Padding to midnight rather
   than relying on it.
8. **Artwork upload body size** under base64 inflation — measure in v0.2.

## Review corrections (r1 → r2)

An adversarial review checked r1 against the live docs prose and OpenAPI JSON. What
changed:

- **Removed the false claim that the n8n node "settled empirically"** which webhook
  signature scheme is live. It was a docs-reading correction, not a test. `verify` is
  now dual-scheme. This also resolved r1's internal contradiction (main section said
  "not a header"; open question 3 said the header variant stands).
- **Fixed the idempotency/retry design.** r1 missed that a post-processing 5xx is
  cached and replays forever, and — worse — routed timeouts to exit 7 despite
  timeouts being the documented headline use case for idempotency keys.
- **48 operations, not 49.** Corrected.
- **Added `art update` (`POST /art/{id}`)**, silently omitted from r1's command table
  while claiming even coverage.
- **Artwork upload is JSON with base64 images, not multipart.** r1 asserted multipart
  and used it as evidence against the declarative-table alternative. Fabricated;
  removed.
- **Pagination now advances by `len(results)`**, fixing a latent record-skipping bug
  inherited from the n8n node's `offset += limit`.
- **Softened the 402 claim** — the declared schema carries only `state`.
- **Completed the order flag list** (`--template`, `--quantity`, `--ship-to-me`,
  `--requested-arrival`, `--purchase-order-number`).
- **Restored loxo-cli features r1 silently dropped**: `--base-url`/env,
  `--filter`, `CARDLY_PROFILE`, `--quiet`; and flagged that `build_payload` must be
  adapted (loxo wraps in a resource key; Cardly doesn't).
- **Extended the region/postcode ambiguity note to contacts**, which have the same
  contradiction in worse form.
- **All four credit-history operators** (`.lt`/`.lte`/`.gt`/`.gte`), and date-only
  padding.
- **`art list` uses `ownOnly`**, not `organisationOnly`.
- **Staged the build** into v0.1 core / v0.2 admin + artwork I/O.
