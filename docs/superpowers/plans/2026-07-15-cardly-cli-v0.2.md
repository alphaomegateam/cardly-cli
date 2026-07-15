# cardly-cli v0.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete cardly-cli's API coverage — add the `users` and `invitations` admin surface, and artwork writes (`art upload/update/delete`).

**Architecture:** v0.1's spine (config, client, errors, envelope, retry, pagination, output, `models/base`, `_app`, `_helpers`, `__main__`) is complete, reviewed, merged, and **stable — v0.2 consumes it and does not modify it.** Two new command groups follow the established module shape; `art` gains three write commands. One new pure helper (`artwork.py`) owns base64 encoding and the size guard.

**Tech Stack:** Python 3.11+, Typer, httpx, pydantic v2, rich. Tests: pytest + respx + Typer's `CliRunner`. Managed with `uv`.

**Spec:** `docs/superpowers/specs/2026-07-15-cardly-cli-design.md` (revision 2), "Scope and staging" + "Artwork" + "Users and invitations".

**Reference:** the v0.1 plan (`docs/superpowers/plans/2026-07-15-cardly-cli-v0.1.md`) shows the task shape. `src/cardly_cli/commands/contacts.py` is the closest analogue (two delete forms, a create, client-side guards); `src/cardly_cli/commands/art.py` is the group you extend.

## ⚠️ The spec is INCOMPLETE for v0.2 — these facts came from the live OpenAPI spec

The spec's "Users and invitations" section is two paragraphs and its "Artwork" section omits a required field. These were read from `https://api.card.ly/openapi/en-AU/2.2.0/json` (spec version 2.2.0) while writing this plan. **They are authoritative; the design spec is not, for these details.**

1. **`POST /art` REQUIRES `media`, `name`, AND `artwork[]`.** `media` is a **UUID identifying the media (card stock) this artwork uses** — it is not optional, and the spec never mentions it. It comes from `GET /media`, which the CLI already exposes as `cardly ref media`. Artwork upload therefore has a **prerequisite workflow**: list media → pick a UUID → upload. The `--media` help and the error path must say so, or users will be stuck.
2. **`GET /invitations` filters out accepted invitations BY DEFAULT.** It takes `acceptedOnly`, `expiredOnly`, and `includeAccepted` (all boolean). The docs say verbatim: *"By default, accepted invitations are filtered out of listings."* A user running `cardly invitations list` and seeing nothing for an accepted invite is looking at correct-but-surprising behaviour. Expose all three flags and say so in the help.
3. **`GET /users` declares NO query parameters at all** — not even `limit`/`offset`. Same undeclared-pagination situation as `/contact-lists` and `/webhooks` in v0.1: prose documents `limit`/`offset` but no list endpoint declares them. Send them anyway and page defensively (`pagination.paginate` already does this correctly); add `/users` and `/invitations` to the README's known-unverified pagination list.
4. **`permissions` on `POST /invitations` is an enum of exactly 13 values:** `administrator`, `artwork`, `billing`, `campaigns`, `developer`, `lists`, `moderate`, `moderate-history`, `orders`, `templates`, `users`, `use-credits`, `use-saved-card`. Validate client-side so a typo fails locally.
5. **Delete-by-email sends `{"email": "..."}` as a JSON body on the collection root** (`DELETE /users`, `DELETE /invitations`), and `POST /invitations/resend` takes the same body. The by-id forms are `DELETE /users/{id}`, `DELETE /invitations/{id}`, `POST /invitations/resend/{id}`.
6. **`artwork[]` items are `{page, image}`** — `page` is a **1-based integer, 1 = front** (the same convention as order message pages, where Cardly's own example gets it wrong), `image` is a **base64-encoded string of the file contents**. `application/json`, **not multipart**.
7. **Response codes:** `POST /art` → 200/422. `POST /art/{id}` → 200/404/422. `DELETE /art/{id}` → 200/404. All users/invitations reads → 200/404. `POST /invitations` → 200/422.

## Global Constraints

Every task's requirements implicitly include this section. **All of these are lessons paid for during v0.1** — each maps to a real defect found before merge.

- **Every task ends with the FULL suite green.** Run it **plainly**: `uv run pytest -q` with the shell environment as-is (it exports `FORCE_COLOR=3`). **Never unset or override env vars to make it pass, and report THAT run's result.** A v0.1 task reported "117 passed" after sanitising its env while a plain run was red.
- **Commits must stand alone.** Before committing, `git status --porcelain` — nothing your build or tests need may be left untracked. A clean checkout of your commit must `uv sync` and pass. A v0.1 commit shipped a `pyproject.toml` referencing an untracked README and didn't build.
- **Any test asserting something "fails locally" MUST register the route and assert `not route.called`** — wherever a request is structurally reachable. Three v0.1 tests claimed this in their names and proved nothing; on a regression they would have hit the real api.card.ly while still passing. (Where no client is constructible on that path, no mock is needed — say so in the report.)
- **Eyeball real table output.** `--json` passing does not prove the human path works. `configure list` shipped a table where every row was an unreadable JSON blob because a nested field hit `_fmt`, which only unwraps dicts having a `name` key. Run your list command against a mocked response and look at it.
- **Error-hint matching must be narrow and evidence-gated.** Three v0.1 bugs came from loose matches: an `"exist"` substring that fired on "list does not exist"; a `402` catch that told users out of credit to delete a webhook; a blanket `422` that hijacked every validation error. If you cannot confidently identify the specific failure, **do not add a hint** — a clean server message beats a wrong guess.
- **No 1Password / `op` / `op://` / secrets-manager naming anywhere** — code, comments, docstrings, help text, or tests.
- **Mocked tests only (respx).** The suite must remain unable to reach the network — it currently passes with `socket.connect` monkeypatched to raise. Keep it that way.
- **Toolchain is `uv`.** Never `pip`, never bare `python`. Line length 100 (ruff + black). `from __future__ import annotations` atop every module.
- **Cardly uses POST for updates.** There is no PUT/PATCH anywhere and `CardlyClient` deliberately has no `put()`.
- **Commands must not re-handle envelopes or statuses.** `client.get/post/delete` already unwrap `{state, data}` and raise `CardlyError` (402 → exit 8). Don't re-parse response shapes.
- **Models must not import from `commands/`.** `compact` lives in `models/base.py` for exactly this reason.
- **Registration goes in `__main__.py`'s bottom import block** (`# noqa: E402` is deliberate — it avoids circular imports). Because every task touches that file, **implementers must be serialized, never parallelized.**
- **Do not modify the v0.1 spine.** If you believe a spine change is needed, stop and report it rather than making it.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/cardly_cli/models/user.py` | `User` model | 1 |
| `src/cardly_cli/commands/users.py` | `users` group (5 ops) | 1 |
| `src/cardly_cli/models/invitation.py` | `Invitation` model, `PERMISSIONS` | 2 |
| `src/cardly_cli/commands/invitations.py` | `invitations` group (8 ops) | 2, 3 |
| `src/cardly_cli/artwork.py` | base64 encoding + size guard (pure) | 4 |
| `src/cardly_cli/commands/art.py` | + `upload`, `update`, `delete` | 5 |
| `README.md`, `CHANGELOG.md`, `tests/test_smoke.py` | docs + surface assertions | 6 |

**Stage A** = Tasks 1–3 (users + invitations; mechanical, no new machinery).
**Stage B** = Tasks 4–6 (artwork I/O; the only novel path in the API).

---

### Task 1: `users`

**Files:**
- Create: `src/cardly_cli/models/user.py`, `src/cardly_cli/commands/users.py`
- Modify: `src/cardly_cli/__main__.py` (bottom import block)
- Test: `tests/test_cmd_users.py`

**Interfaces:**
- Consumes: `CardlyModel` (`models/base.py`); `AppState` via `ctx.obj` with `.client()`, `.emit(data, columns=None)`, `.warn(msg)`; `pagination.paginate(client, endpoint, *, params, limit, warn)`, `extract_results(data)`, `DEFAULT_LIMIT`.
- Produces: `User(CardlyModel)`; `users_app: typer.Typer`.

**Context:** Read `src/cardly_cli/commands/contacts.py` first — it is the closest analogue (two delete forms, client-side guards). `GET /users` declares **no** query params, but `limit`/`offset` are documented in prose; `paginate` sends them and pages defensively. `delete` has two mutually exclusive forms: by id (path) and by email (a JSON body on the collection root).

- [ ] **Step 1: Write the failing test**

`tests/test_cmd_users.py`:

```python
import json

import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


def page(results):
    return ok({"meta": {"totalRecords": len(results)}, "results": results})


@respx.mock
def test_users_list():
    respx.get("https://api.card.ly/v2/users").mock(
        return_value=httpx.Response(200, json=page([{"id": "u1", "email": "a@x.com"}]))
    )
    result = runner.invoke(app, ["--json", "users", "list"], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["id"] == "u1"


@respx.mock
def test_users_get():
    respx.get("https://api.card.ly/v2/users/u1").mock(
        return_value=httpx.Response(200, json=ok({"id": "u1", "email": "a@x.com"}))
    )
    result = runner.invoke(app, ["--json", "users", "get", "u1"], env=ENV)
    assert json.loads(result.stdout)["email"] == "a@x.com"


@respx.mock
def test_users_find_sends_email_query():
    route = respx.get("https://api.card.ly/v2/users/find").mock(
        return_value=httpx.Response(200, json=ok({"id": "u1"}))
    )
    result = runner.invoke(app, ["--json", "users", "find", "--email", "a@x.com"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.url.params["email"] == "a@x.com"


@respx.mock
def test_users_delete_by_id():
    route = respx.delete("https://api.card.ly/v2/users/u1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(app, ["users", "delete", "u1", "--yes"], env=ENV)
    assert result.exit_code == 0
    assert route.called


@respx.mock
def test_users_delete_by_email_posts_body_to_collection():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({}))

    respx.delete("https://api.card.ly/v2/users").mock(side_effect=handler)
    result = runner.invoke(app, ["users", "delete", "--email", "a@x.com", "--yes"], env=ENV)
    assert result.exit_code == 0
    assert captured["body"] == {"email": "a@x.com"}


@respx.mock
def test_users_delete_requires_exactly_one_form():
    by_id = respx.delete("https://api.card.ly/v2/users/u1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    coll = respx.delete("https://api.card.ly/v2/users").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    # Neither form given.
    neither = runner.invoke(app, ["users", "delete", "--yes"], env=ENV)
    assert neither.exit_code == 2
    # Both forms given.
    both = runner.invoke(app, ["users", "delete", "u1", "--email", "a@x.com", "--yes"], env=ENV)
    assert both.exit_code == 2
    # Neither call may have been made.
    assert not by_id.called
    assert not coll.called


@respx.mock
def test_users_delete_declining_makes_no_request():
    route = respx.delete("https://api.card.ly/v2/users/u1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    runner.invoke(app, ["users", "delete", "u1"], input="n\n", env=ENV)
    assert not route.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cmd_users.py -q`
Expected: FAIL — no `users` command.

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/models/user.py`:

```python
from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel


class User(CardlyModel):
    id: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    # Permission-keyed object, not a list. Shape is not modelled further.
    permissions: Optional[Any] = None
```

`src/cardly_cli/commands/users.py`:

```python
from __future__ import annotations

from typing import Optional

import typer

from cardly_cli.models.user import User
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

users_app = typer.Typer(help="Manage users.")

LIST_COLUMNS = ["id", "firstName", "lastName", "email", "status"]


@users_app.command("list")
def list_users(
    ctx: typer.Context,
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
) -> None:
    """List users."""
    state = ctx.obj
    client = state.client()
    if all_pages:
        items = list(paginate(client, "users", limit=limit, warn=state.warn))
    else:
        items = extract_results(client.get("users", params={"limit": limit}))
    state.emit([User.model_validate(i) for i in items], columns=LIST_COLUMNS)


@users_app.command("get")
def get(ctx: typer.Context, user_id: str = typer.Argument(...)) -> None:
    """Show one user."""
    state = ctx.obj
    state.emit(User.model_validate(state.client().get(f"users/{user_id}")))


@users_app.command("find")
def find(
    ctx: typer.Context,
    email: str = typer.Option(..., "--email", help="Email address to search for."),
) -> None:
    """Find a user by email."""
    state = ctx.obj
    state.emit(User.model_validate(state.client().get("users/find", params={"email": email})))


@users_app.command("delete")
def delete(
    ctx: typer.Context,
    user_id: Optional[str] = typer.Argument(None, help="User ID. Omit if using --email."),
    email: Optional[str] = typer.Option(None, "--email", help="Delete by email instead of ID."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Delete a user, by ID or by email.

    Cardly exposes two delete forms: DELETE /users/{id} and DELETE /users with an
    {"email": ...} body. Exactly one is required — passing both is ambiguous about
    which record you mean, so it is rejected rather than guessed at.
    """
    state = ctx.obj
    if bool(user_id) == bool(email):
        raise typer.BadParameter("Provide exactly one of USER_ID or --email.")
    target = user_id or email
    if not yes:
        typer.confirm(f"Delete user {target}?", abort=True)
    client = state.client()
    if user_id:
        client.delete(f"users/{user_id}")
    else:
        client.request("DELETE", "users", json={"email": email})
    state.warn(f"Deleted user {target}.")
```

In `src/cardly_cli/__main__.py`'s bottom import block:

```python
from cardly_cli.commands.users import users_app  # noqa: E402

app.add_typer(users_app, name="users")
```

- [ ] **Step 4: Run the FULL suite plainly**

Run: `uv run pytest -q` (shell env as-is)
Expected: PASS — 323 existing + 7 new.

- [ ] **Step 5: Eyeball the real table**

Run `users list` against a mocked response and confirm the table has real columns, not a JSON blob. Paste the output into your report. Note `permissions` is an object and is deliberately excluded from `LIST_COLUMNS`.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src tests && uv run black --check src tests && uv run mypy
git status --porcelain
git add src/cardly_cli/models/user.py src/cardly_cli/commands/users.py \
        src/cardly_cli/__main__.py tests/test_cmd_users.py
git commit -m "feat: add users commands"
```

---

### Task 2: `invitations` — model and read commands

**Files:**
- Create: `src/cardly_cli/models/invitation.py`, `src/cardly_cli/commands/invitations.py`
- Modify: `src/cardly_cli/__main__.py`
- Test: `tests/test_cmd_invitations.py`

**Interfaces:**
- Consumes: `CardlyModel`; `AppState`; pagination helpers.
- Produces: `Invitation(CardlyModel)`; `PERMISSIONS: tuple[str, ...]` (used by Task 3); `invitations_app: typer.Typer` with `list`, `get`, `find`.

**Context — the non-obvious behaviour:** `GET /invitations` **filters out accepted invitations by default.** The API docs say verbatim: *"By default, accepted invitations are filtered out of listings."* So `cardly invitations list` showing nothing for an invite you know was accepted is correct-but-surprising. Expose `--accepted-only`, `--expired-only`, `--include-accepted` and **say so in the help text** — otherwise users will think the CLI is broken.

`PERMISSIONS` is defined here (rather than in Task 3) because it belongs with the model; Task 3's `create` validates against it.

- [ ] **Step 1: Write the failing test**

`tests/test_cmd_invitations.py`:

```python
import json

import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


def page(results):
    return ok({"meta": {"totalRecords": len(results)}, "results": results})


@respx.mock
def test_invitations_list():
    respx.get("https://api.card.ly/v2/invitations").mock(
        return_value=httpx.Response(200, json=page([{"id": "i1", "email": "a@x.com"}]))
    )
    result = runner.invoke(app, ["--json", "invitations", "list"], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["id"] == "i1"


@respx.mock
def test_invitations_list_sends_no_filters_by_default():
    route = respx.get("https://api.card.ly/v2/invitations").mock(
        return_value=httpx.Response(200, json=page([]))
    )
    runner.invoke(app, ["--json", "invitations", "list"], env=ENV)
    params = route.calls.last.request.url.params
    assert "acceptedOnly" not in params
    assert "expiredOnly" not in params
    assert "includeAccepted" not in params


@respx.mock
def test_invitations_list_filter_flags():
    route = respx.get("https://api.card.ly/v2/invitations").mock(
        return_value=httpx.Response(200, json=page([]))
    )
    runner.invoke(app, ["--json", "invitations", "list", "--include-accepted"], env=ENV)
    assert route.calls.last.request.url.params["includeAccepted"] == "true"

    runner.invoke(app, ["--json", "invitations", "list", "--accepted-only"], env=ENV)
    assert route.calls.last.request.url.params["acceptedOnly"] == "true"

    runner.invoke(app, ["--json", "invitations", "list", "--expired-only"], env=ENV)
    assert route.calls.last.request.url.params["expiredOnly"] == "true"


@respx.mock
def test_invitations_get():
    respx.get("https://api.card.ly/v2/invitations/i1").mock(
        return_value=httpx.Response(200, json=ok({"id": "i1", "status": "pending"}))
    )
    result = runner.invoke(app, ["--json", "invitations", "get", "i1"], env=ENV)
    assert json.loads(result.stdout)["status"] == "pending"


@respx.mock
def test_invitations_find_sends_email_query():
    route = respx.get("https://api.card.ly/v2/invitations/find").mock(
        return_value=httpx.Response(200, json=ok({"id": "i1"}))
    )
    result = runner.invoke(app, ["--json", "invitations", "find", "--email", "a@x.com"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.url.params["email"] == "a@x.com"


def test_permissions_enum_is_complete():
    from cardly_cli.models.invitation import PERMISSIONS

    assert set(PERMISSIONS) == {
        "administrator", "artwork", "billing", "campaigns", "developer", "lists",
        "moderate", "moderate-history", "orders", "templates", "users",
        "use-credits", "use-saved-card",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cmd_invitations.py -q`
Expected: FAIL — no `cardly_cli.models.invitation`.

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/models/invitation.py`:

```python
from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel

# The exact enum Cardly accepts on POST /invitations. Validated client-side so a
# typo fails locally instead of costing a round trip.
PERMISSIONS: tuple[str, ...] = (
    "administrator",
    "artwork",
    "billing",
    "campaigns",
    "developer",
    "lists",
    "moderate",
    "moderate-history",
    "orders",
    "templates",
    "users",
    "use-credits",
    "use-saved-card",
)


class Invitation(CardlyModel):
    id: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    # Permission-keyed object on reads (POST sends a list of identifiers).
    permissions: Optional[Any] = None
    invited: Optional[str] = None
    inviteSent: Optional[str] = None
    accepted: Optional[str] = None
    expires: Optional[str] = None
    links: Optional[Any] = None
```

`src/cardly_cli/commands/invitations.py`:

```python
from __future__ import annotations

import typer

from cardly_cli.models.invitation import Invitation
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

invitations_app = typer.Typer(help="Manage user invitations.")

LIST_COLUMNS = ["id", "email", "status", "invited", "expires"]


@invitations_app.command("list")
def list_invitations(
    ctx: typer.Context,
    include_accepted: bool = typer.Option(
        False,
        "--include-accepted",
        help="Include accepted invitations. Cardly filters them out by default.",
    ),
    accepted_only: bool = typer.Option(
        False, "--accepted-only", help="Only accepted invitations."
    ),
    expired_only: bool = typer.Option(False, "--expired-only", help="Only expired invitations."),
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
) -> None:
    """List invitations.

    NOTE: Cardly filters ACCEPTED invitations out of this listing by default —
    an invite you know was accepted will not appear unless you pass
    --include-accepted (or --accepted-only).
    """
    state = ctx.obj
    params: dict[str, str] = {}
    if include_accepted:
        params["includeAccepted"] = "true"
    if accepted_only:
        params["acceptedOnly"] = "true"
    if expired_only:
        params["expiredOnly"] = "true"
    client = state.client()
    if all_pages:
        items = list(paginate(client, "invitations", params=params, limit=limit, warn=state.warn))
    else:
        items = extract_results(client.get("invitations", params={**params, "limit": limit}))
    state.emit([Invitation.model_validate(i) for i in items], columns=LIST_COLUMNS)


@invitations_app.command("get")
def get(ctx: typer.Context, invitation_id: str = typer.Argument(...)) -> None:
    """Show one invitation."""
    state = ctx.obj
    state.emit(Invitation.model_validate(state.client().get(f"invitations/{invitation_id}")))


@invitations_app.command("find")
def find(
    ctx: typer.Context,
    email: str = typer.Option(..., "--email", help="Email address to search for."),
) -> None:
    """Find an invitation by email."""
    state = ctx.obj
    result = state.client().get("invitations/find", params={"email": email})
    state.emit(Invitation.model_validate(result))
```

In `__main__.py`'s bottom import block:

```python
from cardly_cli.commands.invitations import invitations_app  # noqa: E402

app.add_typer(invitations_app, name="invitations")
```

- [ ] **Step 4: Run the FULL suite plainly**

Run: `uv run pytest -q`
Expected: PASS — 330 existing + 6 new.

- [ ] **Step 5: Eyeball the real table**

Run `invitations list` against a mocked response; confirm real columns. `permissions` and `links` are objects and are deliberately excluded from `LIST_COLUMNS`. Paste the output into your report.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src tests && uv run black --check src tests && uv run mypy
git status --porcelain
git add src/cardly_cli/models/invitation.py src/cardly_cli/commands/invitations.py \
        src/cardly_cli/__main__.py tests/test_cmd_invitations.py
git commit -m "feat: add invitations read commands"
```

---

### Task 3: `invitations` — write commands

**Files:**
- Modify: `src/cardly_cli/commands/invitations.py`, `tests/test_cmd_invitations.py`

**Interfaces:**
- Consumes: `Invitation`, `PERMISSIONS` (Task 2); `_helpers.load_data`.
- Produces: `create`, `resend`, `delete` on `invitations_app`.

**Context:** `POST /invitations` requires `email`; optional `firstName`, `lastName`, `permissions[]` (validated against `PERMISSIONS`). `resend` and `delete` each have **two forms**: by id (`resend/{id}`, `DELETE /invitations/{id}`) and by email (a `{"email": ...}` JSON body on `POST /invitations/resend` and `DELETE /invitations`). Exactly one form per invocation — mirror `users delete`'s guard from Task 1.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cmd_invitations.py`:

```python
@respx.mock
def test_invitations_create_sends_email_and_permissions():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "i1"}))

    respx.post("https://api.card.ly/v2/invitations").mock(side_effect=handler)
    result = runner.invoke(
        app,
        [
            "invitations", "create", "--email", "a@x.com",
            "--first-name", "Ada", "--permission", "orders", "--permission", "use-credits",
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"]["email"] == "a@x.com"
    assert captured["body"]["firstName"] == "Ada"
    assert captured["body"]["permissions"] == ["orders", "use-credits"]


@respx.mock
def test_invitations_create_rejects_unknown_permission_locally():
    route = respx.post("https://api.card.ly/v2/invitations").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(
        app, ["invitations", "create", "--email", "a@x.com", "--permission", "banana"], env=ENV
    )
    assert result.exit_code == 2
    assert "banana" in result.stderr
    assert not route.called


@respx.mock
def test_invitations_resend_by_id_and_by_email():
    by_id = respx.post("https://api.card.ly/v2/invitations/resend/i1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(app, ["invitations", "resend", "i1"], env=ENV)
    assert result.exit_code == 0
    assert by_id.called

    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({}))

    respx.post("https://api.card.ly/v2/invitations/resend").mock(side_effect=handler)
    result = runner.invoke(app, ["invitations", "resend", "--email", "a@x.com"], env=ENV)
    assert result.exit_code == 0
    assert captured["body"] == {"email": "a@x.com"}


@respx.mock
def test_invitations_resend_requires_exactly_one_form():
    by_id = respx.post("https://api.card.ly/v2/invitations/resend/i1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    coll = respx.post("https://api.card.ly/v2/invitations/resend").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    assert runner.invoke(app, ["invitations", "resend"], env=ENV).exit_code == 2
    assert (
        runner.invoke(app, ["invitations", "resend", "i1", "--email", "a@x.com"], env=ENV).exit_code
        == 2
    )
    assert not by_id.called
    assert not coll.called


@respx.mock
def test_invitations_delete_by_id_and_by_email():
    by_id = respx.delete("https://api.card.ly/v2/invitations/i1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    assert runner.invoke(app, ["invitations", "delete", "i1", "--yes"], env=ENV).exit_code == 0
    assert by_id.called

    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({}))

    respx.delete("https://api.card.ly/v2/invitations").mock(side_effect=handler)
    result = runner.invoke(app, ["invitations", "delete", "--email", "a@x.com", "--yes"], env=ENV)
    assert result.exit_code == 0
    assert captured["body"] == {"email": "a@x.com"}


@respx.mock
def test_invitations_delete_declining_makes_no_request():
    route = respx.delete("https://api.card.ly/v2/invitations/i1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    runner.invoke(app, ["invitations", "delete", "i1"], input="n\n", env=ENV)
    assert not route.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cmd_invitations.py -q`
Expected: FAIL — no `create`/`resend`/`delete` commands.

- [ ] **Step 3: Write the implementation**

Append to `src/cardly_cli/commands/invitations.py` (add `from typing import Any, Optional` and `from cardly_cli.commands._helpers import load_data` to the imports):

```python
def _check_permissions(values: list[str]) -> None:
    unknown = [v for v in values if v not in PERMISSIONS]
    if unknown:
        raise typer.BadParameter(
            f"Unknown permission(s): {', '.join(unknown)}. "
            f"Valid permissions: {', '.join(PERMISSIONS)}"
        )


@invitations_app.command("create")
def create(
    ctx: typer.Context,
    email: str = typer.Option(..., "--email", help="Email address to invite."),
    first_name: Optional[str] = typer.Option(None, "--first-name"),
    last_name: Optional[str] = typer.Option(None, "--last-name"),
    permission: list[str] = typer.Option(
        [], "--permission", help=f"Repeatable. One of: {', '.join(PERMISSIONS)}"
    ),
    data: Optional[str] = typer.Option(None, "--data", "-d", help="JSON body: inline, @file, or -."),
) -> None:
    """Invite a user."""
    state = ctx.obj
    _check_permissions(permission)
    body: dict[str, Any] = dict(load_data(data))
    body["email"] = email
    if first_name:
        body["firstName"] = first_name
    if last_name:
        body["lastName"] = last_name
    if permission:
        body["permissions"] = permission
    state.emit(Invitation.model_validate(state.client().post("invitations", json=body)))


@invitations_app.command("resend")
def resend(
    ctx: typer.Context,
    invitation_id: Optional[str] = typer.Argument(
        None, help="Invitation ID. Omit if using --email."
    ),
    email: Optional[str] = typer.Option(None, "--email", help="Resend by email instead of ID."),
) -> None:
    """Resend an invitation, by ID or by email.

    Cardly exposes two forms: POST /invitations/resend/{id} and POST
    /invitations/resend with an {"email": ...} body. Exactly one is required.
    """
    state = ctx.obj
    if bool(invitation_id) == bool(email):
        raise typer.BadParameter("Provide exactly one of INVITATION_ID or --email.")
    client = state.client()
    if invitation_id:
        result = client.post(f"invitations/resend/{invitation_id}")
    else:
        result = client.post("invitations/resend", json={"email": email})
    state.warn(f"Resent invitation to {invitation_id or email}.")
    state.emit(result)


@invitations_app.command("delete")
def delete(
    ctx: typer.Context,
    invitation_id: Optional[str] = typer.Argument(
        None, help="Invitation ID. Omit if using --email."
    ),
    email: Optional[str] = typer.Option(None, "--email", help="Delete by email instead of ID."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Delete an invitation, by ID or by email.

    Two forms, as with resend: DELETE /invitations/{id} and DELETE /invitations
    with an {"email": ...} body. Exactly one is required.
    """
    state = ctx.obj
    if bool(invitation_id) == bool(email):
        raise typer.BadParameter("Provide exactly one of INVITATION_ID or --email.")
    target = invitation_id or email
    if not yes:
        typer.confirm(f"Delete invitation {target}?", abort=True)
    client = state.client()
    if invitation_id:
        client.delete(f"invitations/{invitation_id}")
    else:
        client.request("DELETE", "invitations", json={"email": email})
    state.warn(f"Deleted invitation {target}.")
```

- [ ] **Step 4: Run the FULL suite plainly**

Run: `uv run pytest -q`
Expected: PASS — 336 existing + 6 new.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src tests && uv run black --check src tests && uv run mypy
git status --porcelain
git add src/cardly_cli/commands/invitations.py tests/test_cmd_invitations.py
git commit -m "feat: add invitations write commands"
```

---

### Task 4: Artwork encoding helper

**Files:**
- Create: `src/cardly_cli/artwork.py`
- Test: `tests/test_artwork.py`

**Interfaces:**
- Consumes: stdlib only (`base64`, `pathlib`). Raises `typer.BadParameter`, so it imports `typer`.
- Produces: `WARN_ENCODED_BYTES = 10 * 1024 * 1024`; `encode_image(path: Path) -> str`; `build_artwork_pages(specs: list[str]) -> list[dict[str, Any]]`; `encoded_size(pages: list[dict]) -> int`.

**Context — this is the only novel I/O path in the API.** `POST /art` sends `application/json` with an `artwork` array of `{page, image}` where `image` is base64 of the file contents. **Not multipart.**

`page` is a **1-based integer, 1 = front** — the same convention as order message pages, where Cardly's own OpenAPI example gets it wrong (`{"name": 2}`). Do not repeat that mistake.

**On size:** base64 inflates ~33%, and a multi-page card of print-resolution images is not small. **Nobody has measured Cardly's actual request-body ceiling and mocked tests cannot.** So: do not invent a hard limit. Warn above `WARN_ENCODED_BYTES` (10 MB encoded) and let the API be the authority — the same discipline v0.1 applied to `region`/`postcode` (see the spec's "Deliberately NOT validated"). The README records body size as known-unverified in Task 6.

Read the file **once** and encode from those bytes — do not `read_bytes()` for a size check and again for encoding.

- [ ] **Step 1: Write the failing test**

`tests/test_artwork.py`:

```python
import base64

import pytest
import typer

from cardly_cli.artwork import (
    WARN_ENCODED_BYTES,
    build_artwork_pages,
    encode_image,
    encoded_size,
)


def test_warn_threshold_is_ten_megabytes():
    assert WARN_ENCODED_BYTES == 10 * 1024 * 1024


def test_encode_image_round_trips(tmp_path):
    img = tmp_path / "front.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n binary payload")
    encoded = encode_image(img)
    assert base64.b64decode(encoded) == b"\x89PNG\r\n\x1a\n binary payload"


def test_encode_image_missing_file_is_a_clean_error(tmp_path):
    with pytest.raises(typer.BadParameter, match="not found"):
        encode_image(tmp_path / "nope.png")


def test_encode_image_empty_file_rejected(tmp_path):
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    with pytest.raises(typer.BadParameter, match="empty"):
        encode_image(empty)


def test_build_artwork_pages_defaults_to_sequential_1_based(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"aaa")
    b.write_bytes(b"bbb")
    pages = build_artwork_pages([str(a), str(b)])
    assert [p["page"] for p in pages] == [1, 2]
    assert base64.b64decode(pages[0]["image"]) == b"aaa"


def test_build_artwork_pages_explicit_page_numbers(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"aaa")
    b.write_bytes(b"bbb")
    pages = build_artwork_pages([f"3={b}", f"1={a}"])
    assert [p["page"] for p in pages] == [1, 3]
    assert base64.b64decode(pages[0]["image"]) == b"aaa"


def test_build_artwork_pages_rejects_duplicate_page(tmp_path):
    a = tmp_path / "a.png"
    a.write_bytes(b"aaa")
    with pytest.raises(typer.BadParameter, match="[Dd]uplicate"):
        build_artwork_pages([f"1={a}", f"1={a}"])


def test_build_artwork_pages_rejects_non_integer_page(tmp_path):
    a = tmp_path / "a.png"
    a.write_bytes(b"aaa")
    with pytest.raises(typer.BadParameter, match="integer"):
        build_artwork_pages([f"front={a}"])


def test_build_artwork_pages_rejects_page_below_one(tmp_path):
    a = tmp_path / "a.png"
    a.write_bytes(b"aaa")
    with pytest.raises(typer.BadParameter, match="1-based"):
        build_artwork_pages([f"0={a}"])


def test_build_artwork_pages_empty_returns_empty():
    assert build_artwork_pages([]) == []


def test_build_artwork_pages_uses_page_key_not_name(tmp_path):
    # Cardly's own OpenAPI example ships {"name": 2} for message pages. The
    # field is `page`. Do not repeat that mistake here.
    a = tmp_path / "a.png"
    a.write_bytes(b"aaa")
    page = build_artwork_pages([str(a)])[0]
    assert set(page) == {"page", "image"}


def test_encoded_size_sums_image_bytes(tmp_path):
    a = tmp_path / "a.png"
    a.write_bytes(b"x" * 300)
    pages = build_artwork_pages([str(a)])
    assert encoded_size(pages) == len(pages[0]["image"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_artwork.py -q`
Expected: FAIL — no module `cardly_cli.artwork`.

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/artwork.py`:

```python
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import typer

# Cardly's real request-body ceiling is UNVERIFIED — it is undocumented and
# mocked tests cannot measure it. So this is a warning threshold, not a limit:
# we tell the user the payload is large and let the API be the authority,
# rather than inventing a rule that might reject a body Cardly would accept.
WARN_ENCODED_BYTES = 10 * 1024 * 1024


def encode_image(path: Path) -> str:
    """Base64-encode an image file's contents.

    Reads the file ONCE and encodes from those bytes — no second read for a
    size check. Base64 inflates the payload by roughly a third.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise typer.BadParameter(f"Artwork file not found or unreadable: {path} ({exc})") from exc
    if not raw:
        raise typer.BadParameter(f"Artwork file is empty: {path}")
    return base64.b64encode(raw).decode("ascii")


def build_artwork_pages(specs: list[str]) -> list[dict[str, Any]]:
    """Build Cardly's `artwork` array from `PATH` or `N=PATH` specs.

    Bare paths are numbered sequentially from 1 in the order given. `N=PATH`
    sets the page explicitly. `page` is 1-based and 1 is the FRONT — the same
    convention as order message pages, where Cardly's own example wrongly shows
    a `name` key. The key here is `page`.
    """
    if not specs:
        return []
    pages: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, spec in enumerate(specs, start=1):
        number, sep, raw_path = spec.partition("=")
        if sep:
            if not number.strip().lstrip("-").isdigit():
                raise typer.BadParameter(
                    f"--artwork page must be an integer, got {number!r} in {spec!r}"
                )
            page = int(number)
            path_text = raw_path
        else:
            page = index
            path_text = spec
        if page < 1:
            raise typer.BadParameter(f"--artwork page is 1-based (1 = front), got {page}")
        if page in seen:
            raise typer.BadParameter(f"Duplicate --artwork page {page}; each page may be given once.")
        seen.add(page)
        pages.append({"page": page, "image": encode_image(Path(path_text))})
    return sorted(pages, key=lambda item: item["page"])


def encoded_size(pages: list[dict[str, Any]]) -> int:
    """Total base64 length across pages — what the size warning is measured on."""
    return sum(len(str(page.get("image", ""))) for page in pages)
```

- [ ] **Step 4: Run the FULL suite plainly**

Run: `uv run pytest -q`
Expected: PASS — 342 existing + 12 new.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src tests && uv run black --check src tests && uv run mypy
git status --porcelain
git add src/cardly_cli/artwork.py tests/test_artwork.py
git commit -m "feat: add artwork base64 encoding helper"
```

---

### Task 5: `art upload` / `update` / `delete`

**Files:**
- Modify: `src/cardly_cli/commands/art.py`, `tests/test_cmd_art.py`

**Interfaces:**
- Consumes: `artwork.build_artwork_pages`, `artwork.encoded_size`, `artwork.WARN_ENCODED_BYTES` (Task 4); `Art` model; `_helpers.load_data`; `AppState`.
- Produces: `upload`, `update`, `delete` on `art_app`.

**Context — `media` is REQUIRED and the spec never says so.**

`POST /art` requires **`media`** (a UUID), **`name`**, and **`artwork[]`**; `description` is optional. `media` identifies the card stock this artwork uses, and its UUID comes from `GET /media` — which the CLI already exposes as **`cardly ref media`**. So upload has a prerequisite workflow, and a user who doesn't know that is stuck. The `--media` help text must point at `cardly ref media`.

`POST /art/{id}` (edit) takes the same fields, **all optional** — so `update` must guard against an empty body (the same discipline `lists create` and `contacts sync` already apply: don't spend a round trip on a request that says nothing).

Remove the v0.1 "read-only" comment at the top of `art.py` — it is now false.

Responses: `POST /art` → 200/422; `POST /art/{id}` → 200/404/422; `DELETE /art/{id}` → 200/404. `client.post/delete` already map those to `CardlyError` — do not re-handle them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cmd_art.py`:

```python
@respx.mock
def test_art_upload_sends_media_name_and_base64_pages(tmp_path):
    import base64

    front = tmp_path / "front.png"
    front.write_bytes(b"FRONTBYTES")
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "a1", "name": "Thanks"}))

    respx.post("https://api.card.ly/v2/art").mock(side_effect=handler)
    result = runner.invoke(
        app,
        [
            "art", "upload", "--media", "media-uuid-1", "--name", "Thanks",
            "--description", "A card", "--artwork", str(front),
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    body = captured["body"]
    assert body["media"] == "media-uuid-1"
    assert body["name"] == "Thanks"
    assert body["description"] == "A card"
    assert body["artwork"] == [
        {"page": 1, "image": base64.b64encode(b"FRONTBYTES").decode("ascii")}
    ]


@respx.mock
def test_art_upload_requires_media_and_says_where_to_get_it(tmp_path):
    front = tmp_path / "front.png"
    front.write_bytes(b"x")
    route = respx.post("https://api.card.ly/v2/art").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(
        app, ["art", "upload", "--name", "Thanks", "--artwork", str(front)], env=ENV
    )
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_art_upload_requires_artwork_pages(tmp_path):
    route = respx.post("https://api.card.ly/v2/art").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(
        app, ["art", "upload", "--media", "m1", "--name", "Thanks"], env=ENV
    )
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_art_upload_warns_on_a_large_payload(tmp_path, monkeypatch):
    import cardly_cli.commands.art as art_mod

    monkeypatch.setattr(art_mod, "WARN_ENCODED_BYTES", 8)
    big = tmp_path / "big.png"
    big.write_bytes(b"0123456789")
    respx.post("https://api.card.ly/v2/art").mock(
        return_value=httpx.Response(200, json=ok({"id": "a1"}))
    )
    result = runner.invoke(
        app, ["art", "upload", "--media", "m1", "--name", "Big", "--artwork", str(big)], env=ENV
    )
    assert result.exit_code == 0
    assert "large" in result.stderr.lower()


@respx.mock
def test_art_update_posts_to_the_item_path(tmp_path):
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "a1", "name": "Renamed"}))

    route = respx.post("https://api.card.ly/v2/art/a1").mock(side_effect=handler)
    result = runner.invoke(app, ["art", "update", "a1", "--name", "Renamed"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.method == "POST"
    assert captured["body"] == {"name": "Renamed"}


@respx.mock
def test_art_update_rejects_an_empty_body(tmp_path):
    route = respx.post("https://api.card.ly/v2/art/a1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(app, ["art", "update", "a1"], env=ENV)
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_art_delete_requires_confirmation():
    route = respx.delete("https://api.card.ly/v2/art/a1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    runner.invoke(app, ["art", "delete", "a1"], input="n\n", env=ENV)
    assert not route.called
    result = runner.invoke(app, ["art", "delete", "a1", "--yes"], env=ENV)
    assert result.exit_code == 0
    assert route.called
```

Add `import json` to the test file's imports if it is not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cmd_art.py -q`
Expected: FAIL — no `upload`/`update`/`delete` commands.

- [ ] **Step 3: Write the implementation**

In `src/cardly_cli/commands/art.py`: **delete the v0.1 "read-only" comment** above `art_app` (it is now false), and add these imports:

```python
from typing import Any, Optional

from cardly_cli.artwork import WARN_ENCODED_BYTES, build_artwork_pages, encoded_size
from cardly_cli.commands._helpers import load_data
```

Then append:

```python
MEDIA_HELP = (
    "UUID of the media (card stock) this artwork uses. Required. "
    "List the options with `cardly ref media`."
)
ARTWORK_HELP = (
    "Image file for a page: PATH, or N=PATH to set the page explicitly. "
    "Repeatable. Bare paths number from 1; page 1 is the front."
)


def _warn_if_large(state: Any, pages: list[dict[str, Any]]) -> None:
    size = encoded_size(pages)
    if size > WARN_ENCODED_BYTES:
        state.warn(
            f"Artwork payload is large ({size / 1024 / 1024:.1f} MB base64-encoded across "
            f"{len(pages)} page(s)). Cardly's request-body limit is undocumented, so this "
            f"may be rejected or time out."
        )


@art_app.command("upload")
def upload(
    ctx: typer.Context,
    media: str = typer.Option(..., "--media", help=MEDIA_HELP),
    name: str = typer.Option(..., "--name", help="Short description for this artwork."),
    artwork: list[str] = typer.Option([], "--artwork", help=ARTWORK_HELP),
    description: Optional[str] = typer.Option(
        None, "--description", help="Longer human-readable description."
    ),
    data: Optional[str] = typer.Option(None, "--data", "-d", help="JSON body: inline, @file, or -."),
) -> None:
    """Create artwork from image files.

    Images are base64-encoded into a JSON body (Cardly does not accept multipart).
    `--media` is required and its UUID comes from `cardly ref media`.
    """
    state = ctx.obj
    body: dict[str, Any] = dict(load_data(data))
    pages = build_artwork_pages(artwork)
    if pages:
        body["artwork"] = pages
    if not body.get("artwork"):
        raise typer.BadParameter("--artwork is required: give at least one image file.")
    body["media"] = media
    body["name"] = name
    if description:
        body["description"] = description
    _warn_if_large(state, body["artwork"])
    state.emit(Art.model_validate(state.client().post("art", json=body)))


@art_app.command("update")
def update(
    ctx: typer.Context,
    art_id: str = typer.Argument(..., help="Artwork UUID or slug."),
    name: Optional[str] = typer.Option(None, "--name"),
    description: Optional[str] = typer.Option(None, "--description"),
    artwork: list[str] = typer.Option([], "--artwork", help=ARTWORK_HELP),
    data: Optional[str] = typer.Option(None, "--data", "-d", help="JSON body: inline, @file, or -."),
) -> None:
    """Edit artwork. NOTE: Cardly uses POST here, not PUT/PATCH.

    Only the fields you pass are sent. Whether Cardly merges them into the
    existing artwork or replaces the record is UNVERIFIED — if it replaces, a
    single-field edit would clear the others.
    """
    state = ctx.obj
    body: dict[str, Any] = dict(load_data(data))
    pages = build_artwork_pages(artwork)
    if pages:
        body["artwork"] = pages
    if name:
        body["name"] = name
    if description:
        body["description"] = description
    if not body:
        raise typer.BadParameter(
            "Nothing to update: pass --name, --description, --artwork, or --data."
        )
    if body.get("artwork"):
        _warn_if_large(state, body["artwork"])
    state.emit(Art.model_validate(state.client().post(f"art/{art_id}", json=body)))


@art_app.command("delete")
def delete(
    ctx: typer.Context,
    art_id: str = typer.Argument(..., help="Artwork UUID or slug."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Delete artwork."""
    state = ctx.obj
    if not yes:
        typer.confirm(f"Delete artwork {art_id}?", abort=True)
    state.client().delete(f"art/{art_id}")
    state.warn(f"Deleted artwork {art_id}.")
```

- [ ] **Step 4: Run the FULL suite plainly**

Run: `uv run pytest -q`
Expected: PASS — 354 existing + 7 new.

- [ ] **Step 5: Measure a realistic payload and report it**

The spec says to measure before assuming body size is fine. You cannot measure Cardly's ceiling, but you **can** measure ours. Generate a synthetic multi-page payload and report the encoded size, e.g.:

```bash
uv run python - <<'PY'
import tempfile, pathlib
from cardly_cli.artwork import build_artwork_pages, encoded_size
d = pathlib.Path(tempfile.mkdtemp())
# 4 pages of ~2MB each — a plausible print-resolution card.
specs = []
for i in range(1, 5):
    f = d / f"p{i}.png"
    f.write_bytes(b"\x89PNG" + b"\x00" * (2 * 1024 * 1024))
    specs.append(str(f))
pages = build_artwork_pages(specs)
raw = 4 * (2 * 1024 * 1024 + 4)
enc = encoded_size(pages)
print(f"raw {raw/1024/1024:.1f} MB -> encoded {enc/1024/1024:.1f} MB ({enc/raw:.2f}x)")
PY
```

Put the actual numbers in your report — Task 6 cites them in the README.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src tests && uv run black --check src tests && uv run mypy
git status --porcelain
git add src/cardly_cli/commands/art.py tests/test_cmd_art.py
git commit -m "feat: add art upload, update and delete"
```

---

### Task 6: Docs, changelog, smoke test

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `tests/test_smoke.py`, `src/cardly_cli/__init__.py`, `pyproject.toml`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: the full command surface.
- Produces: no new code interfaces.

**Context:** v0.1's smoke test asserts `users`/`invitations` are ABSENT and that `art upload` doesn't exist — **those assertions are now false and must be inverted.** It also asserts deliberate absences that remain true (`lists update`, `orders cancel`) — leave those alone; they are facts about Cardly and the red test is the guard against someone "helpfully" adding them.

- [ ] **Step 1: Update the smoke test**

In `tests/test_smoke.py`: add `"users"` and `"invitations"` to `EXPECTED_GROUPS`; **delete** `test_v0_2_groups_are_absent`; **delete** `test_art_upload_is_not_in_v0_1` from `tests/test_cmd_art.py`. Keep `test_deliberate_absences_stay_absent` exactly as-is.

Add:

```python
def test_v0_2_surface_is_present():
    result = runner.invoke(app, ["--help"])
    assert "users" in result.stdout
    assert "invitations" in result.stdout

    for cmd in (["art", "upload", "--help"], ["art", "update", "--help"], ["art", "delete", "--help"]):
        assert runner.invoke(app, cmd).exit_code == 0
```

- [ ] **Step 2: Run it and confirm the old assertions fail**

Run: `uv run pytest tests/test_smoke.py -q`
Expected: the deleted tests are gone; `test_v0_2_surface_is_present` passes.

- [ ] **Step 3: Update the version and docs**

`src/cardly_cli/__init__.py`: `__version__ = "0.2.0"`. `pyproject.toml`: `version = "0.2.0"`.

`README.md`:
- **Coming in v0.2 section: delete it.** Replace the command table entries so `users`, `invitations`, and `art upload/update/delete` are documented as shipped.
- **Add an artwork section** covering the prerequisite workflow — this is the part users will get stuck on:
  ````markdown
  ## Uploading artwork

  Artwork needs a **media** UUID (the card stock it prints on). List your options first:

  ```bash
  cardly ref media                       # pick the UUID you want
  cardly art upload --media <uuid> --name "Thank you" \
    --artwork front.png --artwork inside.png
  ```

  Bare `--artwork` paths are numbered from 1 in order; page 1 is the front. Use
  `--artwork 3=back.png` to set a page explicitly.

  Images are base64-encoded into a JSON body — Cardly does not accept multipart
  uploads. Base64 inflates the payload by about a third.
  ````
- **Add to "Known-unverified"** (do not remove any existing item):
  - **Cardly's request-body size limit for artwork uploads.** Undocumented. Base64 inflates ~33%, so a multi-page print-resolution card gets large fast. The CLI warns above 10 MB encoded and lets the API decide, rather than inventing a limit that might reject a body Cardly would accept. Cite the measured inflation figure from Task 5.
  - **Whether `art update` merges or replaces.** Same uncertainty as `contacts update`: only the fields you pass are sent, and if Cardly replaces the record a single-field edit would clear the rest.
  - **Pagination on `/users` and `/invitations`.** `GET /users` declares no query parameters at all, and neither endpoint declares `limit`/`offset` — the same undeclared-pagination situation as `/contact-lists` and `/webhooks`. Add them to the existing pagination bullet rather than writing a new one.
- **Add to "Deliberate omissions"** — `invitations list` hides accepted invitations by default (Cardly's behaviour, not ours); pass `--include-accepted`.

`CHANGELOG.md`, above the 0.1.0 entry:

```markdown
## 0.2.0 — 2026-07-15

Completes API coverage.

- `users` — list, get, find, delete (by ID or email)
- `invitations` — list (with accepted/expired filters), get, find, create, resend
  (by ID or email), delete (by ID or email)
- `art` — upload, update, delete. Images are base64-encoded into a JSON body;
  `--media` is required and its UUID comes from `cardly ref media`.
- `invitations list` hides accepted invitations unless `--include-accepted` is
  passed — this is Cardly's default, surfaced in the help text.
```

- [ ] **Step 4: Run the FULL suite plainly**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Repo hygiene**

```bash
uv run ruff check src tests && uv run black --check src tests && uv run mypy
grep -ril --exclude-dir=.git --exclude-dir=.superpowers --exclude-dir=docs \
  --exclude-dir=.venv --exclude-dir=.pytest_cache \
  -e 'op://' -e '1password' -e 'onepassword' . && echo "HITS — fix them" || echo CLEAN
uv run cardly --version   # must print 0.2.0
```

- [ ] **Step 6: Commit**

```bash
git status --porcelain
git add README.md CHANGELOG.md tests/test_smoke.py tests/test_cmd_art.py \
        src/cardly_cli/__init__.py pyproject.toml
git commit -m "docs: document v0.2 surface and bump to 0.2.0"
```

---

## Definition of done (v0.2)

- [ ] `uv run pytest -q` green on a **plain** run (shell exports `FORCE_COLOR=3`)
- [ ] The suite still cannot reach the network (verify with `socket.connect` monkeypatched to raise)
- [ ] `uv run ruff check src tests && uv run black --check src tests && uv run mypy` clean
- [ ] `cardly --help` lists twelve groups: account, api, art, configure, contacts, echo, invitations, lists, orders, ref, users, webhooks
- [ ] `cardly --version` prints `0.2.0`
- [ ] README documents the artwork media prerequisite and the three new known-unverified items
- [ ] Deliberate absences still absent: `lists update`, `orders cancel`

## Spec coverage check

| Spec requirement | Task |
|---|---|
| v0.2 scope: `users` | 1 |
| v0.2 scope: `invitations` | 2, 3 |
| v0.2 scope: `art upload/update/delete` | 4, 5 |
| Users/invitations: two delete forms each | 1, 3 |
| Invitations: create, resend (×2 forms), find | 2, 3 |
| Artwork: `application/json` + base64, not multipart | 4, 5 |
| Artwork: `page` 1-based, 1 = front | 4 |
| Artwork: measure body size before assuming | 4 (threshold), 5 (measurement), 6 (README) |
| `art get` accepts UUID or slug (v0.1, unchanged) | — |
| Known-unverified items recorded honestly | 6 |

## Facts this plan adds that the spec lacks

Recorded so revision 3 of the spec can absorb them:

1. `POST /art` **requires** `media` (UUID), `name`, `artwork[]` — the spec omits `media` entirely.
2. `GET /invitations` filters out accepted invitations **by default**; takes `acceptedOnly`, `expiredOnly`, `includeAccepted`.
3. `GET /users` declares **no** query parameters — pagination there is as unverified as `/contact-lists` and `/webhooks`.
4. `permissions` is a 13-value enum, listed in Task 2.
5. Delete-by-email and resend-by-email send `{"email": ...}` as a JSON body on the collection root.
