# cardly-cli v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship v0.1 of `cardly-cli`, an unofficial CLI for the Cardly API v2, covering configure, echo, account, orders, contacts, lists, webhooks, ref, art list/get, and a generic `api` escape hatch.

**Architecture:** A Typer app whose root group maps domain errors to documented exit codes. `AppState` hangs off the Typer context and lazily resolves settings (flag > env > TOML profile) and builds an httpx client. The client owns four cross-cutting concerns Cardly forces on us: the `API-Key` header, the `{state, data}` envelope, per-invocation idempotency keys, and retry with cached-replay detection. Commands stay thin: build a payload, call the client, hand the result to `render()`.

**Tech Stack:** Python 3.11+, Typer, httpx, pydantic v2, rich. Tests: pytest + respx + Typer's `CliRunner`. Build: hatchling. Lint: ruff + black + mypy. Managed with `uv`.

**Spec:** `docs/superpowers/specs/2026-07-15-cardly-cli-design.md` (revision 2, commit `846f8b1`). Read it before starting. Where this plan and the spec disagree, the spec wins — report the discrepancy.

**Reference implementation:** `/Users/azweibel/Documents/code-projects/loxo-cli`. Its `client.py`, `config.py`, `errors.py`, `output.py`, `commands/_app.py`, `commands/_helpers.py` are the template. Read a file before mirroring it. **Do not copy blindly** — the Global Constraints below list every place cardly-cli deliberately diverges.

## Global Constraints

Every task's requirements implicitly include this section.

- **Python floor:** `>=3.11`. Line length 100 (ruff + black). `from __future__ import annotations` at the top of every module.
- **No 1Password coupling anywhere in the codebase.** No `op://` strings, no shelling out to `op`, not even in tests or fixtures. `config.py` supports a *generic* `api_key_cmd`; what the user points it at is their business, outside this repo.
- **Mocked tests only.** respx mocks httpx at the transport layer. No live API calls, ever. No network in CI.
- **No `put()`.** Cardly uses POST for updates throughout. Do not add a `put` method to the client — its absence is deliberate.
- **No `slug`.** Cardly's base URL is flat. `url_for()` joins base + endpoint, nothing else.
- **Auth header is `API-Key: <key>`.** Not `Authorization: Bearer`. This is the most likely thing to get wrong by muscle memory from loxo-cli.
- **Bodies are top-level/unwrapped.** loxo's `build_payload` returns `{resource_key: merged}`; ours must not. Porting it verbatim ships `{"order": {...}}` and 422s everything.
- **Contacts and orders have SEPARATE address models.** Orders use `city`; contacts use `locality` and read back `adminAreaLevel1`. Sharing one model guarantees a 422. Every address model carries a code comment saying so.
- **Idempotency keys are generated once per invocation and reused across that invocation's retries** — never regenerated per attempt.
- **Pagination advances `offset` by `len(results)`**, never by the requested `limit`.
- **Never log headers.** `--verbose` logs method, URL, and `Request-Id` only. Headers would leak the API key.
- **Base URL default:** `https://api.card.ly/v2`. Env vars: `CARDLY_API_KEY`, `CARDLY_BASE_URL`, `CARDLY_PROFILE`.
- **Commit after every task.** Conventional-commit prefixes (`feat:`, `test:`, `chore:`).

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Deps, entry point `cardly`, tool config |
| `src/cardly_cli/__init__.py` | `__version__` |
| `src/cardly_cli/errors.py` | `CardlyError`, `ConfigError`, exit-code mapping |
| `src/cardly_cli/config.py` | `CardlySettings`, profile/env/flag resolution |
| `src/cardly_cli/envelope.py` | `{state, data}` unwrap, 422 flattening |
| `src/cardly_cli/retry.py` | Backoff schedule, cached-replay detection |
| `src/cardly_cli/client.py` | httpx wrapper: auth, envelope, idempotency, retry |
| `src/cardly_cli/output.py` | `render()`, `apply_jq()` — ported from loxo |
| `src/cardly_cli/pagination.py` | offset/limit paging |
| `src/cardly_cli/signature.py` | Dual-scheme postback verification |
| `src/cardly_cli/models/*.py` | pydantic models, `extra="allow"` |
| `src/cardly_cli/commands/_app.py` | `CardlyGroup` — exit-code mapping |
| `src/cardly_cli/commands/_helpers.py` | `load_data`, `parse_fields`, `apply_filters`, `build_payload` |
| `src/cardly_cli/commands/*.py` | One module per resource |
| `src/cardly_cli/__main__.py` | App, `AppState`, global flags, registration |

**Dependency order.** Tasks 1–8 build the spine bottom-up; each has no dependency on anything later. Tasks 9–18 are resource commands that consume the spine and are largely independent of one another.

---

### Task 1: Scaffolding and errors

**Files:**
- Create: `pyproject.toml`, `src/cardly_cli/__init__.py`, `src/cardly_cli/errors.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ConfigError(message)` with `exit_code = 2`. `CardlyError(message, *, status_code: int | None = None, is_timeout: bool = False)` with `.status_code`, `.is_timeout`, `.is_4xx`, `.is_5xx`, `.exit_code`. `exit_code_for(exc: BaseException) -> int`.

**Context:** Both classes subclass `click.ClickException`, which gives them `.exit_code` and `.format_message()` while staying ordinary exceptions so `pytest.raises` works. Typer does **not** honour a raised `ClickException.exit_code` — that mapping is applied by `CardlyGroup` in Task 8. This module is the single source of the code table.

- [ ] **Step 1: Create the project skeleton**

```bash
mkdir -p src/cardly_cli/{models,commands} tests
touch src/cardly_cli/models/__init__.py src/cardly_cli/commands/__init__.py
```

`pyproject.toml`:

```toml
[project]
name = "cardly-cli"
version = "0.1.0"
description = "Unofficial command-line interface for the Cardly physical card sending API"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12",
    "click>=8",  # imported directly in errors.py (ClickException base); declare it explicitly
    "httpx>=0.27",
    "pydantic>=2",
    "rich>=13",
]

[project.scripts]
cardly = "cardly_cli.__main__:app"

[project.urls]
Homepage = "https://github.com/alphaomegateam/cardly-cli"

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-mock>=3.14",
    "respx>=0.21",
    "ruff>=0.6",
    "black>=24",
    "mypy>=1.11",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/cardly_cli"]

[tool.pytest.ini_options]
pythonpath = ["src"]
addopts = "-ra"

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.black]
line-length = 100
target-version = ["py311"]

[tool.mypy]
python_version = "3.11"
mypy_path = "src"
packages = ["cardly_cli"]
explicit_package_bases = true
ignore_missing_imports = true
```

`src/cardly_cli/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 2: Write the failing test**

`tests/test_errors.py`:

```python
import click
import pytest

from cardly_cli.errors import CardlyError, ConfigError, exit_code_for


def test_config_error_exit_code():
    assert ConfigError("no key").exit_code == 2


@pytest.mark.parametrize(
    "status_code,is_timeout,expected",
    [
        (None, True, 7),   # timeout
        (None, False, 7),  # network failure
        (401, False, 3),
        (403, False, 3),
        (404, False, 4),
        (429, False, 5),
        (500, False, 6),
        (503, False, 6),
        (402, False, 8),   # insufficient credit — its own code
        (400, False, 1),
        (422, False, 1),
    ],
)
def test_exit_code_mapping(status_code, is_timeout, expected):
    err = CardlyError("boom", status_code=status_code, is_timeout=is_timeout)
    assert err.exit_code == expected


def test_predicates():
    assert CardlyError("x", status_code=404).is_4xx
    assert not CardlyError("x", status_code=404).is_5xx
    assert CardlyError("x", status_code=500).is_5xx
    assert not CardlyError("x", status_code=None).is_4xx


def test_exit_code_for_click_exception():
    assert exit_code_for(ConfigError("x")) == 2
    assert exit_code_for(CardlyError("x", status_code=402)) == 8
    assert exit_code_for(ValueError("x")) == 1


def test_errors_are_click_exceptions():
    assert isinstance(CardlyError("x"), click.ClickException)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_errors.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardly_cli.errors'`

- [ ] **Step 4: Write the implementation**

`src/cardly_cli/errors.py`:

```python
from __future__ import annotations

import click

# Subclassing click.ClickException gives these errors an `.exit_code` and a
# `.format_message()`, and keeps them ordinary Exceptions so `pytest.raises`
# and the `.status_code`/`.is_4xx` predicates used by client.py keep working.
# NOTE: Typer's invocation path does NOT auto-honor a raised ClickException's
# exit_code (it surfaces as a generic exit 1). The exit-code mapping is applied
# by CardlyGroup.invoke in commands/_app.py (set on the root app via
# typer.Typer(cls=CardlyGroup)). `_cardly_exit_code` below remains the single
# source of the CardlyError mapping.


class ConfigError(click.ClickException):
    """Raised when credentials/profile resolution fails."""

    exit_code = 2


class CardlyError(click.ClickException):
    """Normalized error from a Cardly API call.

    status_code is None for network failures and timeouts.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        is_timeout: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.is_timeout = is_timeout
        self.exit_code = _cardly_exit_code(self)

    @property
    def is_4xx(self) -> bool:
        return self.status_code is not None and 400 <= self.status_code < 500

    @property
    def is_5xx(self) -> bool:
        return self.status_code is not None and 500 <= self.status_code < 600


def _cardly_exit_code(err: "CardlyError") -> int:
    if err.is_timeout or err.status_code is None:
        return 7
    if err.status_code in (401, 403):
        return 3
    if err.status_code == 402:
        # Insufficient credit. Its own code because it is the one failure a
        # scheduled job must treat differently: not a bug, not transient,
        # retrying will never help — top up the account.
        return 8
    if err.status_code == 404:
        return 4
    if err.status_code == 429:
        return 5
    if err.is_5xx:
        return 6
    return 1


def exit_code_for(exc: BaseException) -> int:
    if isinstance(exc, click.ClickException):
        return exc.exit_code
    return 1
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_errors.py -q`
Expected: PASS (16 passed)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/cardly_cli tests/test_errors.py
git commit -m "feat: scaffold project and add error types with exit-code mapping"
```

---

### Task 2: Config resolution

**Files:**
- Create: `src/cardly_cli/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `ConfigError` from Task 1.
- Produces: frozen dataclass `CardlySettings(api_key: str, base_url: str)`. `DEFAULT_BASE_URL = "https://api.card.ly/v2"`. `config_file_path() -> Path`. `load_settings(*, profile=None, api_key=None, base_url=None, env=None, config_path=None) -> CardlySettings`. `list_profiles(*, config_path=None) -> dict[str, dict]`. `write_profile(name, *, api_key=None, api_key_cmd=None, base_url=DEFAULT_BASE_URL, make_default=False, config_path=None) -> None`.

**Context:** Mirrors loxo's `config.py` minus `slug`. Precedence: flag > env > profile. The key is resolved lazily — only consult the profile (which may shell out via `api_key_cmd`) when no flag/env value satisfies the higher-precedence sources. `api_key_cmd` is a **generic** shell-out; the repo must never reference 1Password.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
import pytest

from cardly_cli.config import (
    DEFAULT_BASE_URL,
    CardlySettings,
    config_file_path,
    list_profiles,
    load_settings,
    write_profile,
)
from cardly_cli.errors import ConfigError

CONFIG = """\
default_profile = "prod"

[profile.prod]
api_key = "live_abc"
base_url = "https://api.card.ly/v2"

[profile.sandbox]
api_key_cmd = "printf test_xyz"
base_url = "https://api.card.ly/v2"
"""


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    return path


def test_default_base_url():
    assert DEFAULT_BASE_URL == "https://api.card.ly/v2"


def test_config_file_path_honors_xdg(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert config_file_path(env=env) == tmp_path / "cardly" / "config.toml"


def test_flag_beats_env_beats_profile(config_path):
    s = load_settings(api_key="flag", env={"CARDLY_API_KEY": "env"}, config_path=config_path)
    assert s.api_key == "flag"

    s = load_settings(env={"CARDLY_API_KEY": "env"}, config_path=config_path)
    assert s.api_key == "env"

    s = load_settings(env={}, config_path=config_path)
    assert s.api_key == "live_abc"  # default_profile = prod


def test_profile_selected_by_flag_and_env(config_path):
    s = load_settings(profile="sandbox", env={}, config_path=config_path)
    assert s.api_key == "test_xyz"  # resolved via api_key_cmd

    s = load_settings(env={"CARDLY_PROFILE": "sandbox"}, config_path=config_path)
    assert s.api_key == "test_xyz"


def test_api_key_cmd_shells_out(config_path):
    s = load_settings(profile="sandbox", env={}, config_path=config_path)
    assert s.api_key == "test_xyz"


def test_api_key_cmd_failure_raises_config_error(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('[profile.p]\napi_key_cmd = "false"\n')
    with pytest.raises(ConfigError, match="api_key_cmd failed"):
        load_settings(profile="p", env={}, config_path=path)


def test_base_url_precedence_and_trailing_slash(config_path):
    s = load_settings(base_url="https://x/v2/", env={}, config_path=config_path)
    assert s.base_url == "https://x/v2"

    s = load_settings(env={"CARDLY_BASE_URL": "https://y/v2"}, config_path=config_path)
    assert s.base_url == "https://y/v2"


def test_missing_key_raises_config_error(tmp_path):
    with pytest.raises(ConfigError, match="No API key found"):
        load_settings(env={}, config_path=tmp_path / "missing.toml")


def test_unknown_profile_raises_config_error(config_path):
    with pytest.raises(ConfigError, match="not found"):
        load_settings(profile="nope", env={}, config_path=config_path)


def test_settings_has_no_slug():
    # Cardly's base URL is flat — a slug field would be meaningless here.
    assert not hasattr(CardlySettings(api_key="k", base_url="u"), "slug")


def test_list_profiles(config_path):
    profiles = list_profiles(config_path=config_path)
    assert profiles["prod"]["has_key"] is True
    assert profiles["prod"]["default"] is True
    assert profiles["sandbox"]["has_key"] is True
    assert profiles["sandbox"]["default"] is False


def test_write_profile_roundtrip_and_chmod(tmp_path):
    path = tmp_path / "new.toml"
    write_profile("dev", api_key="test_1", make_default=True, config_path=path)
    assert (path.stat().st_mode & 0o777) == 0o600
    s = load_settings(env={}, config_path=path)
    assert s.api_key == "test_1"


def test_write_profile_supports_api_key_cmd(tmp_path):
    path = tmp_path / "new.toml"
    write_profile("dev", api_key_cmd="printf zzz", make_default=True, config_path=path)
    assert load_settings(env={}, config_path=path).api_key == "zzz"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardly_cli.config'`

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/config.py`:

```python
from __future__ import annotations

import os
import shlex
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cardly_cli.errors import ConfigError

DEFAULT_BASE_URL = "https://api.card.ly/v2"


@dataclass(frozen=True)
class CardlySettings:
    api_key: str
    base_url: str


def config_file_path(*, env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "cardly" / "config.toml"


def _read_config(config_path: Path | None) -> dict[str, Any]:
    path = config_path or config_file_path()
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _resolve_key(profile_data: Mapping[str, Any]) -> str | None:
    if profile_data.get("api_key"):
        return str(profile_data["api_key"])
    cmd = profile_data.get("api_key_cmd")
    if cmd:
        # Deliberately generic: any shell command that prints a key on stdout.
        # This repo must never reference a specific secrets manager.
        try:
            out = subprocess.run(shlex.split(str(cmd)), capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            raise ConfigError(f"api_key_cmd failed (exit {exc.returncode}).") from exc
        return out.stdout.strip()
    return None


def load_settings(
    *,
    profile: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    env: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> CardlySettings:
    env = os.environ if env is None else env
    config = _read_config(config_path)
    profile_name = profile or env.get("CARDLY_PROFILE") or config.get("default_profile")

    profile_data: dict[str, Any] = {}
    if profile_name:
        profiles = config.get("profile", {})
        if profile_name not in profiles:
            raise ConfigError(f"Profile '{profile_name}' not found in config.")
        profile_data = profiles[profile_name]

    # Resolve the key lazily: only consult the profile (which may shell out via
    # api_key_cmd) when no flag/env value satisfies the higher-precedence sources.
    resolved_key = api_key or env.get("CARDLY_API_KEY") or _resolve_key(profile_data)
    resolved_base = (
        base_url or env.get("CARDLY_BASE_URL") or profile_data.get("base_url") or DEFAULT_BASE_URL
    )

    if not resolved_key:
        raise ConfigError(
            "No API key found. Set --api-key, CARDLY_API_KEY, or run `cardly configure`."
        )
    return CardlySettings(api_key=str(resolved_key), base_url=str(resolved_base).rstrip("/"))


def list_profiles(*, config_path: Path | None = None) -> dict[str, dict]:
    config = _read_config(config_path)
    result: dict[str, dict] = {}
    for name, data in config.get("profile", {}).items():
        result[name] = {
            "base_url": data.get("base_url", DEFAULT_BASE_URL),
            "has_key": bool(data.get("api_key") or data.get("api_key_cmd")),
            "default": config.get("default_profile") == name,
        }
    return result


def _dump_toml(config: dict[str, Any]) -> str:
    lines: list[str] = []
    if config.get("default_profile"):
        lines.append(f'default_profile = "{config["default_profile"]}"')
        lines.append("")
    for name, data in config.get("profile", {}).items():
        lines.append(f"[profile.{name}]")
        for key, value in data.items():
            lines.append(f'{key} = "{value}"')
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_profile(
    name: str,
    *,
    api_key: str | None = None,
    api_key_cmd: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    make_default: bool = False,
    config_path: Path | None = None,
) -> None:
    path = config_path or config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config = _read_config(config_path)
    profiles = config.setdefault("profile", {})
    entry: dict[str, Any] = {"base_url": base_url}
    if api_key:
        entry["api_key"] = api_key
    if api_key_cmd:
        entry["api_key_cmd"] = api_key_cmd
    profiles[name] = entry
    if make_default or not config.get("default_profile"):
        config["default_profile"] = name
    path.write_text(_dump_toml(config))
    path.chmod(0o600)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/config.py tests/test_config.py
git commit -m "feat: add config resolution with profiles and generic api_key_cmd"
```

---

### Task 3: Envelope unwrapping

**Files:**
- Create: `src/cardly_cli/envelope.py`
- Test: `tests/test_envelope.py`

**Interfaces:**
- Consumes: `CardlyError` from Task 1.
- Produces: `unwrap(payload: Any) -> Any` — returns `data` when the `{state, data}` envelope is present, else the payload unchanged. `flatten_validation(data: Any) -> str` — turns a 422's `{field: reason}` map into `"field: reason; field: reason"`. `state_messages(payload: Any) -> list[str]`. `is_error_state(payload: Any) -> bool`. `raise_for_state(payload: Any, *, status_code: int | None = None) -> None`.

**Context:** Every Cardly response is `{"state": {"status": "OK"|"WARN"|"ERROR", "messages": [...], "version": int}, "data": {...}}`. Cardly can signal failure *inside a 200-shaped envelope* via `state.status == "ERROR"`, so HTTP status alone is not sufficient. Unwrapping lives here so commands never parse response shapes. Test-mode responses carry `testMode: true`.

- [ ] **Step 1: Write the failing test**

`tests/test_envelope.py`:

```python
import pytest

from cardly_cli.envelope import (
    flatten_validation,
    is_error_state,
    raise_for_state,
    state_messages,
    unwrap,
)
from cardly_cli.errors import CardlyError

OK = {"state": {"status": "OK", "messages": [], "version": 1234}, "data": {"id": "abc"}}


def test_unwrap_returns_data():
    assert unwrap(OK) == {"id": "abc"}


def test_unwrap_passes_through_unenveloped():
    assert unwrap({"id": "abc"}) == {"id": "abc"}
    assert unwrap([1, 2]) == [1, 2]
    assert unwrap(None) is None


def test_unwrap_requires_both_state_and_data():
    # A payload with a `data` key but no `state` is not an envelope.
    assert unwrap({"data": {"x": 1}}) == {"data": {"x": 1}}


def test_unwrap_preserves_falsy_data():
    assert unwrap({"state": {"status": "OK"}, "data": []}) == []


def test_state_messages():
    payload = {"state": {"status": "ERROR", "messages": ["a", "b"]}, "data": {}}
    assert state_messages(payload) == ["a", "b"]
    assert state_messages({"id": 1}) == []


def test_is_error_state():
    assert is_error_state({"state": {"status": "ERROR"}, "data": {}})
    assert not is_error_state(OK)
    assert not is_error_state({"state": {"status": "WARN"}, "data": {}})
    assert not is_error_state({"id": 1})


def test_flatten_validation():
    data = {"email": "This value should be a valid email address.", "postcode": "Required."}
    out = flatten_validation(data)
    assert "email: This value should be a valid email address." in out
    assert "postcode: Required." in out
    assert "; " in out


def test_flatten_validation_non_dict():
    assert flatten_validation(["a"]) == "['a']"
    assert flatten_validation(None) == ""


def test_raise_for_state_raises_on_error_envelope():
    payload = {"state": {"status": "ERROR", "messages": ["Nope."]}, "data": {}}
    with pytest.raises(CardlyError, match="Nope."):
        raise_for_state(payload)


def test_raise_for_state_silent_on_ok():
    raise_for_state(OK)  # must not raise


def test_raise_for_state_carries_status_code():
    payload = {"state": {"status": "ERROR", "messages": ["x"]}, "data": {}}
    with pytest.raises(CardlyError) as ei:
        raise_for_state(payload, status_code=402)
    assert ei.value.exit_code == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_envelope.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardly_cli.envelope'`

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/envelope.py`:

```python
from __future__ import annotations

from typing import Any

from cardly_cli.errors import CardlyError


def _is_envelope(payload: Any) -> bool:
    return isinstance(payload, dict) and "state" in payload and "data" in payload


def unwrap(payload: Any) -> Any:
    """Return the `data` member of Cardly's {state, data} envelope.

    Every Cardly response is enveloped. Unwrapping lives here so commands never
    parse response shapes themselves. Non-enveloped payloads pass through, which
    keeps the `api` escape hatch and error paths simple.
    """
    if _is_envelope(payload):
        return payload["data"]
    return payload


def state_messages(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    state = payload.get("state")
    if not isinstance(state, dict):
        return []
    messages = state.get("messages")
    return [str(m) for m in messages] if isinstance(messages, list) else []


def is_error_state(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    state = payload.get("state")
    return isinstance(state, dict) and state.get("status") == "ERROR"


def flatten_validation(data: Any) -> str:
    """Flatten a 422 ValidationStatus ({field: reason}) into readable text.

    Cardly returns validation failures as a flat field->reason map. Dumping raw
    JSON at the user is worse than a sentence.
    """
    if data is None:
        return ""
    if not isinstance(data, dict):
        return str(data)
    return "; ".join(f"{field}: {reason}" for field, reason in data.items())


def raise_for_state(payload: Any, *, status_code: int | None = None) -> None:
    """Raise when a 200-shaped envelope carries state.status == ERROR.

    Cardly signals failure in two places: the HTTP status, and state.status
    inside an otherwise-200 body. Checking the status code alone misses this.
    """
    if not is_error_state(payload):
        return
    messages = state_messages(payload)
    text = " ".join(messages) if messages else "Cardly returned an error state."
    raise CardlyError(text, status_code=status_code)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_envelope.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/envelope.py tests/test_envelope.py
git commit -m "feat: add envelope unwrapping and validation flattening"
```

---

### Task 4: Retry policy

**Files:**
- Create: `src/cardly_cli/retry.py`
- Test: `tests/test_retry.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RetryPolicy(max_retries: int = 3, base_delay: float = 0.5, max_delay: float = 8.0, enabled: bool = True)` with `.should_retry(*, status_code: int | None, is_timeout: bool, method: str) -> bool` and `.delay_for(attempt: int, *, rand: Callable[[], float] = random.random) -> float`. `is_cached_replay(previous: Response | None, current: Response, elapsed: float) -> bool` where `Response` is the local `AttemptResult` dataclass.

**Context:** Three rules from the spec, each with a reason:

1. **Retry 429 and 5xx.** Cardly documents no rate-limit numbers and no `RateLimit-*` headers, so back off adaptively rather than budget against a ceiling.
2. **Retry POST timeouts.** This is the documented headline use case for idempotency keys: *"if a request to Place Order does not result in a response, or the response times out, you can retry the exact same request and receive the response you would have otherwise missed."* Safe only because the key is stable across retries (Task 5).
3. **Detect cached replays.** Cardly stores the response against an idempotency key *regardless of success*, once processing starts. A post-processing 5xx is cached; retrying replays it forever. Such a retry is duplicate-safe but futile — bail rather than burn the budget.

Timeouts on non-POST verbs are **not** retried: without a key they carry no replay protection.

- [ ] **Step 1: Write the failing test**

`tests/test_retry.py`:

```python
from cardly_cli.retry import AttemptResult, RetryPolicy, is_cached_replay


def test_retries_429_and_5xx():
    p = RetryPolicy()
    assert p.should_retry(status_code=429, is_timeout=False, method="GET")
    assert p.should_retry(status_code=500, is_timeout=False, method="GET")
    assert p.should_retry(status_code=503, is_timeout=False, method="POST")


def test_does_not_retry_4xx_or_success():
    p = RetryPolicy()
    assert not p.should_retry(status_code=200, is_timeout=False, method="GET")
    assert not p.should_retry(status_code=404, is_timeout=False, method="GET")
    assert not p.should_retry(status_code=422, is_timeout=False, method="POST")
    # 402 is terminal: retrying will never conjure credit.
    assert not p.should_retry(status_code=402, is_timeout=False, method="POST")


def test_retries_post_timeouts_but_not_get_timeouts():
    p = RetryPolicy()
    # POST timeouts are the canonical idempotency-key use case: the order may
    # have landed and only the response was lost.
    assert p.should_retry(status_code=None, is_timeout=True, method="POST")
    # Without a key there is no replay protection, so don't retry blind.
    assert not p.should_retry(status_code=None, is_timeout=True, method="GET")


def test_disabled_policy_never_retries():
    p = RetryPolicy(enabled=False)
    assert not p.should_retry(status_code=429, is_timeout=False, method="GET")
    assert not p.should_retry(status_code=None, is_timeout=True, method="POST")


def test_zero_max_retries_never_retries():
    p = RetryPolicy(max_retries=0)
    assert not p.should_retry(status_code=429, is_timeout=False, method="GET")


def test_delay_grows_exponentially_and_clamps():
    p = RetryPolicy(base_delay=1.0, max_delay=8.0)
    fixed = lambda: 0.0  # noqa: E731 — no jitter, test the schedule itself
    assert p.delay_for(0, rand=fixed) == 1.0
    assert p.delay_for(1, rand=fixed) == 2.0
    assert p.delay_for(2, rand=fixed) == 4.0
    assert p.delay_for(3, rand=fixed) == 8.0
    assert p.delay_for(9, rand=fixed) == 8.0  # clamped


def test_delay_applies_jitter_within_bounds():
    p = RetryPolicy(base_delay=1.0, max_delay=8.0)
    full = p.delay_for(1, rand=lambda: 1.0)
    none = p.delay_for(1, rand=lambda: 0.0)
    assert none == 2.0
    assert 2.0 < full <= 3.0  # jitter adds up to 50%


def test_cached_replay_detected_on_identical_fast_response():
    prev = AttemptResult(status_code=500, body=b'{"state":{"status":"ERROR"}}')
    curr = AttemptResult(status_code=500, body=b'{"state":{"status":"ERROR"}}')
    # Returned instantly and byte-identical -> served from the idempotency
    # layer, not reprocessed. Retrying again is futile.
    assert is_cached_replay(prev, curr, elapsed=0.01)


def test_cached_replay_not_flagged_when_slow():
    prev = AttemptResult(status_code=500, body=b"x")
    curr = AttemptResult(status_code=500, body=b"x")
    assert not is_cached_replay(prev, curr, elapsed=2.0)


def test_cached_replay_not_flagged_when_body_differs():
    prev = AttemptResult(status_code=500, body=b"x")
    curr = AttemptResult(status_code=500, body=b"y")
    assert not is_cached_replay(prev, curr, elapsed=0.01)


def test_cached_replay_needs_a_previous_attempt():
    curr = AttemptResult(status_code=500, body=b"x")
    assert not is_cached_replay(None, curr, elapsed=0.01)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_retry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardly_cli.retry'`

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/retry.py`:

```python
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

# Below this wall-clock time, an identical repeat response is assumed to have
# come from Cardly's idempotency store rather than a fresh round trip through
# the processing layer.
CACHED_REPLAY_SECONDS = 0.25


@dataclass(frozen=True)
class AttemptResult:
    """Just enough of a response to compare two attempts."""

    status_code: int | None
    body: bytes


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    enabled: bool = True

    def should_retry(self, *, status_code: int | None, is_timeout: bool, method: str) -> bool:
        if not self.enabled or self.max_retries <= 0:
            return False
        if is_timeout:
            # POST timeouts are the documented headline use case for
            # idempotency keys: the request may have been processed and only
            # the response lost. Replaying with the same key returns the stored
            # result instead of placing a second order. Other verbs carry no
            # key, so a blind replay has no such protection.
            return method.upper() == "POST"
        if status_code is None:
            return False
        if status_code == 429:
            return True
        # 402 (insufficient credit) is deliberately excluded: it is terminal.
        return 500 <= status_code < 600

    def delay_for(self, attempt: int, *, rand: Callable[[], float] = random.random) -> float:
        """Exponential backoff with up to 50% additive jitter."""
        raw = self.base_delay * (2**attempt)
        capped = min(raw, self.max_delay)
        return capped + (capped * 0.5 * rand())


def is_cached_replay(
    previous: AttemptResult | None, current: AttemptResult, elapsed: float
) -> bool:
    """True when a retry looks like it was served from the idempotency store.

    Cardly saves the status code and body against an idempotency key
    "regardless of success" once a request starts processing, and subsequent
    requests with that key return the stored result "without hitting the
    processing layer". So a 5xx that lands after processing began is cached:
    every retry replays it, forever. Duplicate-safe, but futile — bail out
    instead of burning the whole backoff budget re-fetching a fixed answer.

    Heuristic: byte-identical response returned faster than a real round trip.
    """
    if previous is None:
        return False
    if elapsed >= CACHED_REPLAY_SECONDS:
        return False
    return previous.status_code == current.status_code and previous.body == current.body
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_retry.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/retry.py tests/test_retry.py
git commit -m "feat: add retry policy with POST-timeout retry and cached-replay detection"
```

---

### Task 5: HTTP client

**Files:**
- Create: `src/cardly_cli/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `CardlySettings` (Task 2), `CardlyError` (Task 1), `unwrap`/`raise_for_state`/`flatten_validation`/`state_messages` (Task 3), `RetryPolicy`/`AttemptResult`/`is_cached_replay` (Task 4).
- Produces: `url_for(settings, endpoint) -> str`. `CardlyClient(settings, *, verbose=False, retry=None, idempotency_key=None, sleep=time.sleep)` as a context manager with `.get(endpoint, **kw)`, `.post(endpoint, **kw)`, `.delete(endpoint, **kw)`, `.request(method, endpoint, *, params=None, json=None, raw=False)`, `.last_request_id: str | None`. `build_client(settings, *, verbose=False, retry=None, idempotency_key=None) -> CardlyClient`. `TIMEOUT = 30.0`.

**Context:** This is the most load-bearing module in the CLI. It owns four things:

1. **`API-Key` header** — not `Authorization: Bearer`. The single easiest thing to get wrong by muscle memory.
2. **Envelope handling** — unwrap `{state, data}` on success; raise on `state.status == "ERROR"` even inside a 200.
3. **Idempotency** — one v4 UUID **per client instance** (i.e. per CLI invocation), sent on POST only, reused across retries. Regenerating per attempt silently destroys duplicate protection; replaying a key with a *changed body* is a hard error, which is why the key is bound to the invocation, not the attempt.
4. **Retry** — delegates the decision to `RetryPolicy`, aborts on a detected cached replay.

Error messages must never contain the API key. `--verbose` logs method, URL, and `Request-Id` — **never headers**.

`raw=True` returns the `httpx.Response` itself, for the preview-PDF download (Task 12), which needs bytes and the `API-Key` header rather than JSON.

- [ ] **Step 1: Write the failing test**

`tests/test_client.py`:

```python
import httpx
import pytest
import respx

from cardly_cli.client import TIMEOUT, CardlyClient, url_for
from cardly_cli.config import CardlySettings
from cardly_cli.errors import CardlyError
from cardly_cli.retry import RetryPolicy

SETTINGS = CardlySettings(api_key="test_key", base_url="https://api.card.ly/v2")
NO_RETRY = RetryPolicy(enabled=False)


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


def test_url_for_joins_parts():
    assert url_for(SETTINGS, "orders") == "https://api.card.ly/v2/orders"
    assert url_for(SETTINGS, "/orders/1") == "https://api.card.ly/v2/orders/1"


def test_timeout_default():
    assert TIMEOUT == 30.0


@respx.mock
def test_sends_api_key_header_not_bearer():
    route = respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(200, json=ok({"balance": 100}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert c.get("account/balance") == {"balance": 100}
    headers = route.calls.last.request.headers
    assert headers["API-Key"] == "test_key"
    assert "Authorization" not in headers


@respx.mock
def test_unwraps_envelope():
    respx.get("https://api.card.ly/v2/orders/9").mock(
        return_value=httpx.Response(200, json=ok({"id": "9"}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert c.get("orders/9") == {"id": "9"}


@respx.mock
def test_raises_on_error_state_inside_200():
    # Cardly can signal failure inside a 200-shaped envelope.
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(
            200, json={"state": {"status": "ERROR", "messages": ["Nope."]}, "data": {}}
        )
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        with pytest.raises(CardlyError, match="Nope."):
            c.get("orders")


@respx.mock
def test_402_maps_to_exit_code_8_and_includes_messages():
    respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(
            402,
            json={"state": {"status": "ERROR", "messages": ["Insufficient credit: need 5, have 2."]}},
        )
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        with pytest.raises(CardlyError) as ei:
            c.post("orders/place", json={"lines": []})
    assert ei.value.exit_code == 8
    assert "Insufficient credit" in str(ei.value)


@respx.mock
def test_422_flattens_validation_map():
    respx.post("https://api.card.ly/v2/contact-lists/1/contacts").mock(
        return_value=httpx.Response(
            422,
            json={
                "state": {"status": "ERROR", "messages": ["Validation failed."]},
                "data": {"email": "This value should be a valid email address."},
            },
        )
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        with pytest.raises(CardlyError) as ei:
            c.post("contact-lists/1/contacts", json={})
    msg = str(ei.value)
    assert "email: This value should be a valid email address." in msg
    assert ei.value.status_code == 422


@respx.mock
def test_404_raises_with_status():
    respx.get("https://api.card.ly/v2/orders/nope").mock(
        return_value=httpx.Response(404, json={"state": {"status": "ERROR", "messages": ["Gone."]}})
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        with pytest.raises(CardlyError) as ei:
            c.get("orders/nope")
    assert ei.value.exit_code == 4


@respx.mock
def test_error_message_never_contains_api_key():
    respx.get("https://api.card.ly/v2/orders").mock(return_value=httpx.Response(500, text="boom"))
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        with pytest.raises(CardlyError) as ei:
            c.get("orders")
    assert "test_key" not in str(ei.value)


@respx.mock
def test_post_sends_idempotency_key_get_does_not():
    post = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    get = respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(200, json=ok({"results": []}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        c.post("orders/place", json={"lines": []})
        c.get("orders")
    assert "Idempotency-Key" in post.calls.last.request.headers
    assert "Idempotency-Key" not in get.calls.last.request.headers


@respx.mock
def test_idempotency_key_is_stable_across_posts_in_one_invocation():
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        c.post("orders/place", json={"lines": []})
        c.post("orders/place", json={"lines": []})
    keys = [call.request.headers["Idempotency-Key"] for call in route.calls]
    assert keys[0] == keys[1]


@respx.mock
def test_idempotency_key_override_is_used():
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY, idempotency_key="pinned-123") as c:
        c.post("orders/place", json={"lines": []})
    assert route.calls.last.request.headers["Idempotency-Key"] == "pinned-123"


@respx.mock
def test_generated_idempotency_key_is_a_uuid4():
    import uuid

    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        c.post("orders/place", json={})
    key = route.calls.last.request.headers["Idempotency-Key"]
    assert uuid.UUID(key).version == 4
    assert len(key) <= 64  # Cardly's documented maximum


@respx.mock
def test_retry_reuses_the_same_idempotency_key():
    # THE critical test: a retry that mints a fresh key would place a second
    # order instead of replaying the first.
    responses = [
        httpx.Response(503, json={"state": {"status": "ERROR", "messages": ["busy"]}}),
        httpx.Response(200, json=ok({"order": {"id": "1"}})),
    ]
    route = respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=responses)
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=2, base_delay=0), sleep=lambda _: None
    ) as c:
        c.post("orders/place", json={"lines": []})
    assert len(route.calls) == 2
    keys = {call.request.headers["Idempotency-Key"] for call in route.calls}
    assert len(keys) == 1


@respx.mock
def test_retries_429_then_succeeds():
    responses = [
        httpx.Response(429, json={"state": {"status": "ERROR", "messages": ["slow down"]}}),
        httpx.Response(200, json=ok({"results": []})),
    ]
    respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=2, base_delay=0), sleep=lambda _: None
    ) as c:
        assert c.get("orders") == {"results": []}


@respx.mock
def test_exhausted_retries_raise_with_final_status():
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(429, json={"state": {"status": "ERROR", "messages": ["no"]}})
    )
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=2, base_delay=0), sleep=lambda _: None
    ) as c:
        with pytest.raises(CardlyError) as ei:
            c.get("orders")
    assert ei.value.exit_code == 5


@respx.mock
def test_post_timeout_is_retried_and_can_succeed():
    responses = [httpx.ConnectTimeout("timed out"), httpx.Response(200, json=ok({"id": "1"}))]
    route = respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=responses)
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=2, base_delay=0), sleep=lambda _: None
    ) as c:
        assert c.post("orders/place", json={"lines": []}) == {"id": "1"}
    assert len(route.calls) == 2


@respx.mock
def test_get_timeout_is_not_retried():
    route = respx.get("https://api.card.ly/v2/orders").mock(
        side_effect=httpx.ConnectTimeout("timed out")
    )
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=3, base_delay=0), sleep=lambda _: None
    ) as c:
        with pytest.raises(CardlyError) as ei:
            c.get("orders")
    assert ei.value.is_timeout
    assert ei.value.exit_code == 7
    assert len(route.calls) == 1


@respx.mock
def test_cached_replay_aborts_the_retry_loop_early():
    # An identical 5xx returned instantly means Cardly served it from the
    # idempotency store; further retries can never succeed.
    body = {"state": {"status": "ERROR", "messages": ["stored failure"]}}
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(500, json=body)
    )
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=5, base_delay=0), sleep=lambda _: None
    ) as c:
        with pytest.raises(CardlyError) as ei:
            c.post("orders/place", json={"lines": []})
    # First attempt + one retry that revealed the replay. Not all 5.
    assert len(route.calls) == 2
    assert "idempotency" in str(ei.value).lower()


@respx.mock
def test_captures_request_id():
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(200, json=ok({}), headers={"Request-Id": "req_42"})
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        c.get("orders")
        assert c.last_request_id == "req_42"


@respx.mock
def test_verbose_logs_method_url_and_request_id_but_never_headers(capsys):
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(200, json=ok({}), headers={"Request-Id": "req_7"})
    )
    with CardlyClient(SETTINGS, verbose=True, retry=NO_RETRY) as c:
        c.get("orders")
    err = capsys.readouterr().err
    assert "GET https://api.card.ly/v2/orders" in err
    assert "req_7" in err
    assert "test_key" not in err  # never log headers


@respx.mock
def test_raw_returns_response_object():
    respx.get("https://api.card.ly/v2/preview/x/card/pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4")
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        resp = c.request("GET", "preview/x/card/pdf", raw=True)
    assert resp.content == b"%PDF-1.4"


@respx.mock
def test_empty_body_returns_none():
    respx.delete("https://api.card.ly/v2/webhooks/1").mock(return_value=httpx.Response(204))
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert c.delete("webhooks/1") is None


def test_client_has_no_put_method():
    # Cardly uses POST for updates throughout. A put() would only invite bugs.
    assert not hasattr(CardlyClient(SETTINGS), "put")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardly_cli.client'`

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/client.py`:

```python
from __future__ import annotations

import sys
import time
import uuid
from typing import Any, Callable, Mapping

import httpx

from cardly_cli.config import CardlySettings
from cardly_cli.envelope import flatten_validation, raise_for_state, state_messages, unwrap
from cardly_cli.errors import CardlyError
from cardly_cli.retry import AttemptResult, RetryPolicy, is_cached_replay

TIMEOUT = 30.0


def url_for(settings: CardlySettings, endpoint: str) -> str:
    # Flat join: Cardly has no per-tenant path segment (loxo's `slug`).
    return f"{settings.base_url}/{endpoint.lstrip('/')}"


class CardlyClient:
    """httpx wrapper owning auth, the response envelope, idempotency, and retry.

    Deliberately has no `put()`: Cardly uses POST for updates throughout, and
    exposing PUT would only invite mistakes.
    """

    def __init__(
        self,
        settings: CardlySettings,
        *,
        verbose: bool = False,
        retry: RetryPolicy | None = None,
        idempotency_key: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._verbose = verbose
        self._retry = retry if retry is not None else RetryPolicy()
        self._sleep = sleep
        # ONE key per client instance == one per CLI invocation, reused across
        # every retry of every POST in that invocation. Regenerating per attempt
        # would destroy duplicate protection: Cardly only replays a stored
        # response when the key matches. (Replaying a key with a *changed* body
        # is a hard error, so the key is bound to the invocation, not reused
        # across different bodies in a way we'd have to reason about — each
        # command issues one logical write.)
        self._idempotency_key = idempotency_key or str(uuid.uuid4())
        self.last_request_id: str | None = None
        self._http = httpx.Client(
            headers={
                # NOT `Authorization: Bearer`. Cardly uses a bare API-Key header.
                "API-Key": settings.api_key,
                "Accept": "application/json",
            },
            follow_redirects=True,
            timeout=TIMEOUT,
        )

    def __enter__(self) -> "CardlyClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _headers_for(self, method: str, json: Any | None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if json is not None:
            # The docs' prose says `text/json`; the OpenAPI declares
            # application/json, and that is what actually works.
            headers["Content-Type"] = "application/json"
        if method.upper() == "POST":
            # POST only — Cardly ignores the header on other verbs.
            headers["Idempotency-Key"] = self._idempotency_key
        return headers

    def _error_from_response(self, response: httpx.Response, method: str, endpoint: str) -> CardlyError:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        messages = state_messages(payload)
        detail = " ".join(messages) if messages else response.text[:500]
        if response.status_code == 422 and isinstance(payload, dict):
            flattened = flatten_validation(payload.get("data"))
            if flattened:
                detail = f"{detail} ({flattened})" if messages else flattened
        return CardlyError(
            f"Cardly {method.upper()} {endpoint} returned {response.status_code}: {detail}",
            status_code=response.status_code,
        )

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        raw: bool = False,
    ) -> Any:
        target = url_for(self._settings, endpoint)
        headers = self._headers_for(method, json)
        previous: AttemptResult | None = None
        attempt = 0

        while True:
            started = time.monotonic()
            try:
                response = self._http.request(
                    method, target, params=params, json=json, headers=headers or None
                )
            except httpx.TimeoutException as exc:
                if self._retry.should_retry(status_code=None, is_timeout=True, method=method) and (
                    attempt < self._retry.max_retries
                ):
                    self._log(method, target, note="timeout, retrying")
                    self._sleep(self._retry.delay_for(attempt))
                    attempt += 1
                    continue
                raise CardlyError(
                    f"Cardly {method.upper()} {endpoint} timed out",
                    status_code=None,
                    is_timeout=True,
                ) from exc
            except httpx.HTTPError as exc:
                raise CardlyError(
                    f"Cardly {method.upper()} {endpoint} request failed: {exc}", status_code=None
                ) from exc

            elapsed = time.monotonic() - started
            self.last_request_id = response.headers.get("Request-Id")
            self._log(method, target, request_id=self.last_request_id)

            if response.is_success:
                if raw:
                    return response
                if not response.content:
                    return None
                payload = response.json()
                raise_for_state(payload, status_code=response.status_code)
                return unwrap(payload)

            current = AttemptResult(status_code=response.status_code, body=response.content)
            if is_cached_replay(previous, current, elapsed):
                # Cardly stored this failure against our idempotency key and is
                # replaying it without reprocessing. More retries cannot help.
                raise CardlyError(
                    f"Cardly {method.upper()} {endpoint} returned {response.status_code} "
                    f"replayed from the idempotency store; retrying cannot change it. "
                    f"Use a new --idempotency-key to force reprocessing.",
                    status_code=response.status_code,
                )

            retryable = self._retry.should_retry(
                status_code=response.status_code, is_timeout=False, method=method
            )
            if retryable and attempt < self._retry.max_retries:
                previous = current
                self._sleep(self._retry.delay_for(attempt))
                attempt += 1
                continue

            raise self._error_from_response(response, method, endpoint)

    def _log(
        self, method: str, target: str, *, request_id: str | None = None, note: str | None = None
    ) -> None:
        if not self._verbose:
            return
        # Method + URL + Request-Id only. NEVER headers: that would leak the
        # API key into logs and bug reports.
        line = f"{method.upper()} {target}"
        if request_id:
            line += f" (Request-Id: {request_id})"
        if note:
            line += f" [{note}]"
        print(line, file=sys.stderr)

    def get(self, endpoint: str, **kw: Any) -> Any:
        return self.request("GET", endpoint, **kw)

    def post(self, endpoint: str, **kw: Any) -> Any:
        return self.request("POST", endpoint, **kw)

    def delete(self, endpoint: str, **kw: Any) -> Any:
        return self.request("DELETE", endpoint, **kw)


def build_client(
    settings: CardlySettings,
    *,
    verbose: bool = False,
    retry: RetryPolicy | None = None,
    idempotency_key: str | None = None,
) -> CardlyClient:
    return CardlyClient(
        settings, verbose=verbose, retry=retry, idempotency_key=idempotency_key
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -q`
Expected: PASS (23 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/client.py tests/test_client.py
git commit -m "feat: add HTTP client with API-Key auth, envelope handling, idempotency and retry"
```

---

### Task 6: Output rendering

**Files:**
- Create: `src/cardly_cli/output.py`
- Test: `tests/test_output.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `to_jsonable(obj) -> Any`, `apply_jq(data, expr) -> Any`, `render(data, *, as_json, jq=None, columns=None, console=None) -> None`.

**Context:** Port loxo's `output.py` nearly verbatim — read `/Users/azweibel/Documents/code-projects/loxo-cli/src/loxo_cli/output.py` first. Two loxo behaviours are load-bearing and must survive the port:

1. **JSON output bypasses Rich's colorizer.** Rich reports `is_terminal=True` whenever `FORCE_COLOR` is set — a common dev-env default — even when stdout is a pipe. Routing JSON through `console.print` wraps it in ANSI escapes and breaks `json.loads` and `--jq` consumers.
2. **`_fmt` renders `{"id":…, "name":…}` objects as their `name`** in tables.

One Cardly-specific change: loxo's `_fmt` name-unwrapping still applies, but Cardly list payloads are `{"meta":…, "results":[…]}` — extracting `results` is `pagination.py`'s job (Task 7), not this module's.

- [ ] **Step 1: Write the failing test**

`tests/test_output.py`:

```python
import json

import pytest
from rich.console import Console

from cardly_cli.output import apply_jq, render, to_jsonable


def cap():
    import io

    buf = io.StringIO()
    return buf, Console(file=buf, no_color=True, width=200)


def test_to_jsonable_handles_models_and_nesting():
    from pydantic import BaseModel

    class M(BaseModel):
        a: int

    assert to_jsonable(M(a=1)) == {"a": 1}
    assert to_jsonable([M(a=1)]) == [{"a": 1}]
    assert to_jsonable({"k": M(a=1)}) == {"k": {"a": 1}}
    assert to_jsonable("x") == "x"


@pytest.mark.parametrize(
    "expr,expected",
    [
        (".", {"results": [{"id": 1}]}),
        ("", {"results": [{"id": 1}]}),
        (".results", [{"id": 1}]),
        ("results", [{"id": 1}]),  # leading dot optional
        (".results.0.id", 1),
        (".results[].id", [1]),
        (".missing", None),
        (".results.0.missing.deeper", None),  # jq yields null past a scalar
    ],
)
def test_apply_jq(expr, expected):
    data = {"results": [{"id": 1}]}
    assert apply_jq(data, expr) == expected


def test_apply_jq_rejects_list_op_on_non_list():
    import click

    with pytest.raises(click.ClickException):
        apply_jq({"a": 1}, ".a[]")


def test_render_json_is_plain_and_parseable():
    buf, console = cap()
    render({"id": "abc"}, as_json=True, console=console)
    assert json.loads(buf.getvalue()) == {"id": "abc"}
    assert "\x1b[" not in buf.getvalue()  # no ANSI escapes


def test_render_jq_implies_json():
    buf, console = cap()
    render({"results": [{"id": 1}]}, as_json=False, jq=".results", console=console)
    assert json.loads(buf.getvalue()) == [{"id": 1}]


def test_render_table_for_list_of_dicts():
    buf, console = cap()
    render([{"id": "1", "status": "sent"}], as_json=False, columns=["id", "status"], console=console)
    out = buf.getvalue()
    assert "id" in out and "status" in out and "sent" in out


def test_render_table_for_dict():
    buf, console = cap()
    render({"balance": 42}, as_json=False, console=console)
    assert "balance" in buf.getvalue()


def test_fmt_unwraps_named_objects():
    buf, console = cap()
    render([{"status": {"id": 3, "name": "Active"}}], as_json=False, console=console)
    assert "Active" in buf.getvalue()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_output.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardly_cli.output'`

- [ ] **Step 3: Port the implementation**

Copy `/Users/azweibel/Documents/code-projects/loxo-cli/src/loxo_cli/output.py` to `src/cardly_cli/output.py` verbatim, then make exactly these changes:

1. No import changes are needed (the module imports only `click`, `pydantic`, `rich`).
2. Update the `_fmt` docstring comment: replace the `Loxo returns many fields...` sentence with:

```python
        # Cardly returns several fields as {"id": ..., "name": ...} objects.
        # Show the human-readable name in tables instead of dumping raw JSON.
```

3. Update `apply_jq`'s docstring example from `'.results.0.title'` to `'.results.0.id'`.

Everything else — `to_jsonable`, `_tokenize`, `_is_index`, the `console.file.write(json.dumps(...))` bypass and its comment, the table-building branches — ports unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_output.py -q`
Expected: PASS (17 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/output.py tests/test_output.py
git commit -m "feat: port output rendering with --json/--jq support"
```

---

### Task 7: Pagination

**Files:**
- Create: `src/cardly_cli/pagination.py`
- Test: `tests/test_pagination.py`

**Interfaces:**
- Consumes: `CardlyClient` (Task 5).
- Produces: `DEFAULT_LIMIT = 100`. `extract_results(data) -> list`. `total_records(data) -> int | None`. `paginate(client, endpoint, *, params=None, limit=DEFAULT_LIMIT, warn=None) -> Iterator[Any]`.

**Context:** One scheme only: offset/limit. Cardly's list envelope (post-unwrap) is `{"meta": {...}, "results": [...]}`.

Three rules, each guarding a real failure:

1. **Advance `offset` by `len(results)`, never by the requested `limit`.** The n8n node does `offset += limit` (`GenericFunctions.ts:96`). `limit`/`offset` are documented in prose but **undeclared in the OpenAPI**, and unverified on `/contact-lists`, `/contact-lists/{id}/contacts` and `/webhooks`. If a server clamps `limit` below what we asked, advancing by the request silently skips records: ask 100, get 25, jump 100, lose 26–100.
2. **Cross-check `meta.limit` against the requested limit** and warn — clamping should be visible, not silent.
3. **Terminate on empty results OR `totalRecords` reached.** If an endpoint ignores `offset` and returns page 1 forever, we stop instead of looping and hammering the API into a 429. Same instinct as loxo's `after_id` cursor-stall guard.

- [ ] **Step 1: Write the failing test**

`tests/test_pagination.py`:

```python
import httpx
import respx

from cardly_cli.client import CardlyClient
from cardly_cli.config import CardlySettings
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate, total_records
from cardly_cli.retry import RetryPolicy

SETTINGS = CardlySettings(api_key="k", base_url="https://api.card.ly/v2")
NO_RETRY = RetryPolicy(enabled=False)


def page(results, *, total, limit=100, offset=0):
    return {
        "state": {"status": "OK", "messages": [], "version": 1},
        "data": {
            "meta": {"limit": limit, "offset": offset, "totalRecords": total},
            "results": results,
        },
    }


def test_default_limit():
    assert DEFAULT_LIMIT == 100


def test_extract_results_and_total():
    data = {"meta": {"totalRecords": 5}, "results": [{"id": 1}]}
    assert extract_results(data) == [{"id": 1}]
    assert total_records(data) == 5
    assert extract_results({}) == []
    assert total_records({}) is None
    assert extract_results([{"id": 1}]) == [{"id": 1}]  # bare list passthrough


@respx.mock
def test_single_page():
    respx.get("https://api.card.ly/v2/webhooks").mock(
        return_value=httpx.Response(200, json=page([{"id": 1}, {"id": 2}], total=2))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert list(paginate(c, "webhooks")) == [{"id": 1}, {"id": 2}]


@respx.mock
def test_walks_multiple_pages_and_sends_limit_and_offset():
    responses = [
        httpx.Response(200, json=page([{"id": 1}, {"id": 2}], total=3, limit=2, offset=0)),
        httpx.Response(200, json=page([{"id": 3}], total=3, limit=2, offset=2)),
    ]
    route = respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert list(paginate(c, "orders", limit=2)) == [{"id": 1}, {"id": 2}, {"id": 3}]
    first, second = route.calls
    assert first.request.url.params["limit"] == "2"
    assert first.request.url.params["offset"] == "0"
    assert second.request.url.params["offset"] == "2"


@respx.mock
def test_advances_by_returned_page_size_not_requested_limit():
    # THE regression guard: server clamps limit 100 -> 25. Advancing by the
    # request would skip records 26-100 silently.
    responses = [
        httpx.Response(200, json=page([{"id": i} for i in range(25)], total=30, limit=25)),
        httpx.Response(200, json=page([{"id": i} for i in range(25, 30)], total=30, limit=25)),
    ]
    route = respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        items = list(paginate(c, "orders", limit=100))
    assert len(items) == 30
    assert route.calls[1].request.url.params["offset"] == "25"  # not "100"


@respx.mock
def test_warns_when_server_clamps_limit():
    warnings = []
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(200, json=page([{"id": 1}], total=1, limit=25))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        list(paginate(c, "orders", limit=100, warn=warnings.append))
    assert any("100" in w and "25" in w for w in warnings)


@respx.mock
def test_stops_on_empty_results():
    responses = [
        httpx.Response(200, json=page([{"id": 1}], total=99, limit=1)),
        httpx.Response(200, json=page([], total=99, limit=1)),
    ]
    respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert list(paginate(c, "orders", limit=1)) == [{"id": 1}]


@respx.mock
def test_stops_when_endpoint_ignores_offset():
    # Endpoint returns the same full page forever. Without a guard this loops
    # until Cardly rate-limits us.
    route = respx.get("https://api.card.ly/v2/contact-lists").mock(
        return_value=httpx.Response(200, json=page([{"id": 1}], total=99, limit=1, offset=0))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        items = list(paginate(c, "contact-lists", limit=1))
    assert items == [{"id": 1}]
    assert len(route.calls) == 2  # detected on the repeat, then stopped


@respx.mock
def test_stops_at_total_records():
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(200, json=page([{"id": 1}, {"id": 2}], total=2, limit=100))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert len(list(paginate(c, "orders"))) == 2


@respx.mock
def test_missing_total_records_keeps_paging_until_empty():
    responses = [
        httpx.Response(
            200,
            json={"state": {"status": "OK"}, "data": {"meta": {}, "results": [{"id": 1}]}},
        ),
        httpx.Response(200, json={"state": {"status": "OK"}, "data": {"meta": {}, "results": []}}),
    ]
    respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert list(paginate(c, "orders", limit=1)) == [{"id": 1}]


@respx.mock
def test_extra_params_are_preserved_across_pages():
    responses = [
        httpx.Response(200, json=page([{"id": 1}], total=2, limit=1)),
        httpx.Response(200, json=page([{"id": 2}], total=2, limit=1)),
    ]
    route = respx.get("https://api.card.ly/v2/art").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        list(paginate(c, "art", params={"ownOnly": "true"}, limit=1))
    for call in route.calls:
        assert call.request.url.params["ownOnly"] == "true"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pagination.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardly_cli.pagination'`

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/pagination.py`:

```python
from __future__ import annotations

from typing import Any, Callable, Iterator

from cardly_cli.client import CardlyClient

# The documented default is 25; we ask for more to cut round trips. See the
# clamp cross-check below for why asking is not the same as receiving.
DEFAULT_LIMIT = 100


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

    NOTE: `limit`/`offset` are documented in the API's prose but are NOT
    declared as parameters on any list endpoint in the OpenAPI spec, and remain
    unverified against /contact-lists, /contact-lists/{id}/contacts and
    /webhooks. Everything defensive below follows from that uncertainty.
    """
    base_params = dict(params or {})
    offset = 0
    seen_signature: tuple | None = None

    while True:
        page_params = dict(base_params)
        page_params["limit"] = limit
        page_params["offset"] = offset
        data = client.get(endpoint, params=page_params)
        results = extract_results(data)

        if not results:
            return

        # Guard: an endpoint that ignores `offset` returns page 1 forever.
        # Without this we loop until Cardly rate-limits us (429).
        signature = (offset, len(results), repr(results[0]))
        if seen_signature is not None and signature[1:] == seen_signature[1:]:
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

        # Advance by what we RECEIVED, never by what we asked for. If the
        # server clamps `limit`, advancing by the request skips the difference
        # silently (ask 100, get 25, jump 100 -> records 26-100 vanish).
        offset += len(results)

        total = total_records(data)
        if total is not None and offset >= total:
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pagination.py -q`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/pagination.py tests/test_pagination.py
git commit -m "feat: add offset/limit pagination that advances by returned page size"
```

---

### Task 8: App spine — models base, error group, AppState

**Files:**
- Create: `src/cardly_cli/models/base.py`, `src/cardly_cli/commands/_app.py`, `src/cardly_cli/__main__.py`
- Test: `tests/test_app_state.py`

**This task must end with the full suite GREEN.** Tests that need a real command to
exercise (credential resolution, `--base-url` routing, the exit-code contract) land in
Task 11, which provides the `echo`/`account` commands they drive. At this task the app
has a spine and a stub `echo` group only.

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: `CardlyModel(BaseModel)` with `model_config = ConfigDict(extra="allow")`. `compact(mapping: dict) -> dict`. `CardlyGroup(TyperGroup)`. `AppState` dataclass with `.settings()`, `.client()`, `.console()`, `.emit(data, *, columns=None)`, `.warn(msg)`, and fields `profile, api_key, base_url, json_out, jq, quiet, verbose, no_color, no_retry, max_retries, idempotency_key, config_path`. Module-level `app: typer.Typer`.

**Context:** `CardlyGroup.invoke` is how exit codes actually reach the shell. Typer does **not** honour a raised `ClickException.exit_code` — it surfaces as a generic exit 1 with no message. Setting `typer.Typer(cls=CardlyGroup)` on the **root** app wraps the entire command tree, so nested sub-app commands and root-level commands alike get their `CardlyError`/`ConfigError` converted to `typer.Exit` with the mapped code and a clean stderr message. Command modules stay plain `typer.Typer`.

`AppState.client()` builds a client carrying the invocation's `RetryPolicy` and `--idempotency-key`. Because one `AppState` exists per invocation and `client()` is called once per command, the generated key is stable for that invocation.

At this task the app registers **no** sub-commands yet — later tasks add their own registration line. Keep the imports-at-bottom pattern from loxo's `__main__.py` (it avoids circular imports; the `# noqa: E402` markers are intentional).

- [ ] **Step 1: Write the failing tests**

`tests/test_app_state.py`:

```python
from typer.testing import CliRunner

from cardly_cli import __version__
from cardly_cli.__main__ import app
from cardly_cli.models.base import CardlyModel, compact

runner = CliRunner()


def test_cardly_model_allows_extra_fields():
    # Cardly ships new fields with builds; carry them rather than drop them.
    model = CardlyModel.model_validate({"known": 1, "surprise": "kept"})
    assert model.model_dump()["surprise"] == "kept"


def test_compact_strips_empties_but_keeps_false_and_zero():
    assert compact({"a": 1, "b": None, "c": "", "d": [], "e": {}}) == {"a": 1}
    # False and 0 are meaningful (shipToMe=false), not absence.
    assert compact({"f": False, "g": 0}) == {"f": False, "g": 0}


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert "cardly" in result.stdout.lower()


def test_root_help_lists_global_flags():
    result = runner.invoke(app, ["--help"])
    for flag in ("--profile", "--api-key", "--base-url", "--json", "--jq",
                 "--quiet", "--verbose", "--no-color", "--no-retry",
                 "--max-retries", "--idempotency-key"):
        assert flag in result.stdout, f"missing global flag: {flag}"


def test_app_state_is_attached_to_context():
    # AppState carries flags to commands; nothing else can resolve settings.
    from cardly_cli.__main__ import AppState

    assert AppState.__dataclass_fields__["idempotency_key"]
    assert AppState.__dataclass_fields__["base_url"]
```

> **Deliberately NOT here:** credential-resolution, `--base-url` routing, and the
> exit-code contract all need a real command to drive. They land in Task 11 with the
> `echo`/`account` commands. This task ends green.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_app_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardly_cli.__main__'`

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/models/base.py`:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class CardlyModel(BaseModel):
    # extra="allow" is deliberate. Cardly's Order nests four levels deep
    # (order.items[].delivery.tracking) and ships new fields with builds. Model
    # the levels people actually read; carry the rest verbatim rather than
    # chasing the schema.
    model_config = ConfigDict(extra="allow")


def compact(mapping: dict[str, Any]) -> dict[str, Any]:
    """Drop None and empty string/list/dict values.

    Cardly validates presence, not emptiness: sending `"region": ""` for an
    omitted flag reads as "region is blank", not "region wasn't given". False
    and 0 are real values and survive.

    Lives here rather than in commands/_helpers.py because the request builders
    in models/ need it, and models must not import from commands/.
    """
    return {
        key: value
        for key, value in mapping.items()
        if value is not None and value != "" and value != [] and value != {}
    }
```

`src/cardly_cli/commands/_app.py`:

```python
from __future__ import annotations

from typing import Any

import typer
from typer.core import TyperGroup

from cardly_cli.errors import CardlyError, ConfigError


class CardlyGroup(TyperGroup):
    """Root command group mapping cardly's domain errors to documented exit codes.

    Typer's invocation path does NOT honor a raised ``ClickException``'s
    ``exit_code`` (it surfaces as a generic exit 1 with no message). Set this as
    the root app's group class via the supported ``typer.Typer(cls=CardlyGroup)``
    hook: its ``invoke`` wraps the entire command tree, so every command — nested
    sub-app commands and root-level commands alike — gets its ``CardlyError`` /
    ``ConfigError`` converted into ``typer.Exit`` with the mapped code, with a
    clean message on stderr. Command files stay plain ``typer.Typer``.
    """

    def invoke(self, ctx) -> Any:  # ctx is typer's vendored-click Context
        try:
            return super().invoke(ctx)
        except (CardlyError, ConfigError) as exc:
            typer.echo(f"Error: {exc.format_message()}", err=True)
            raise typer.Exit(code=exc.exit_code) from exc
```

`src/cardly_cli/__main__.py`:

```python
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console

from cardly_cli import __version__
from cardly_cli.client import CardlyClient, build_client
from cardly_cli.commands._app import CardlyGroup
from cardly_cli.config import CardlySettings, load_settings
from cardly_cli.output import render
from cardly_cli.retry import RetryPolicy

HELP_EPILOG = "Unofficial — not affiliated with Cardly."

app = typer.Typer(
    cls=CardlyGroup,
    help="cardly — command-line interface for the Cardly card-sending API.",
    epilog=HELP_EPILOG,
    no_args_is_help=True,
)


@dataclass
class AppState:
    profile: Optional[str]
    api_key: Optional[str]
    base_url: Optional[str]
    json_out: bool
    jq: Optional[str]
    quiet: bool
    verbose: bool
    no_color: bool
    no_retry: bool
    max_retries: int
    idempotency_key: Optional[str]
    config_path: Optional[Path] = None
    _settings: Optional[CardlySettings] = field(default=None, repr=False)

    def settings(self) -> CardlySettings:
        if self._settings is None:
            self._settings = load_settings(
                profile=self.profile,
                api_key=self.api_key,
                base_url=self.base_url,
                config_path=self.config_path,
            )
        return self._settings

    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(max_retries=self.max_retries, enabled=not self.no_retry)

    def client(self) -> CardlyClient:
        # One client per invocation => one idempotency key per invocation,
        # reused across that invocation's retries.
        return build_client(
            self.settings(),
            verbose=self.verbose,
            retry=self.retry_policy(),
            idempotency_key=self.idempotency_key,
        )

    def console(self) -> Console:
        # Disable color when the user asked (--no-color), when the NO_COLOR
        # convention is set (https://no-color.org/), or when stdout is not a
        # TTY (piped/redirected). The explicit isatty check is needed because
        # Rich forces color on when FORCE_COLOR is set even into a pipe.
        no_color = self.no_color or bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()
        return Console(no_color=no_color)

    def warn(self, message: str) -> None:
        if not self.quiet:
            typer.echo(message, err=True)

    def emit(self, data: Any, *, columns: list[str] | None = None) -> None:
        if self.quiet and not (self.json_out or self.jq):
            return
        render(
            data,
            as_json=self.json_out,
            jq=self.jq,
            columns=columns,
            console=self.console(),
        )


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Config profile."),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="Cardly API key."),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="API base URL."),
    config_path: Optional[Path] = typer.Option(None, "--config-path", help="Config file path."),
    json_out: bool = typer.Option(False, "--json", help="Force JSON output."),
    jq: Optional[str] = typer.Option(
        None,
        "--jq",
        help="Select part of the output by path, e.g. '.results' or "
        "'.results.0.id'. The leading '.' is optional ('results' works too).",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress non-error output."),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Log requests to stderr."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable color."),
    no_retry: bool = typer.Option(False, "--no-retry", help="Disable retry on 429/5xx/timeout."),
    max_retries: int = typer.Option(3, "--max-retries", help="Max retry attempts."),
    idempotency_key: Optional[str] = typer.Option(
        None,
        "--idempotency-key",
        help="Pin the Idempotency-Key sent on POSTs (default: a fresh UUID per invocation).",
    ),
) -> None:
    """cardly CLI. Unofficial — not affiliated with Cardly."""
    ctx.obj = AppState(
        profile=profile,
        api_key=api_key,
        base_url=base_url,
        config_path=config_path,
        json_out=json_out,
        jq=jq,
        quiet=quiet,
        verbose=verbose,
        no_color=no_color,
        no_retry=no_retry,
        max_retries=max_retries,
        idempotency_key=idempotency_key,
    )


# Sub-app registration is appended by later tasks. Imports live at the bottom to
# avoid circular imports; the E402 markers are intentional.
from cardly_cli.commands.echo import echo_app  # noqa: E402

app.add_typer(echo_app, name="echo")


def run() -> None:
    # Exit-code mapping happens in CardlyGroup.invoke (commands/_app.py, set via
    # typer.Typer(cls=CardlyGroup)): Typer does NOT honor a raised
    # ClickException's exit_code, so domain errors become typer.Exit with the
    # mapped code.
    app()


if __name__ == "__main__":
    run()
```

> The `echo` import above forward-references Task 10. Create a stub now so the module imports:
> ```bash
> printf 'from __future__ import annotations\n\nimport typer\n\necho_app = typer.Typer(help="Connectivity check.")\n' > src/cardly_cli/commands/echo.py
> ```
> Task 10 replaces it with the real implementation.

- [ ] **Step 4: Run the FULL suite to verify it is green**

Run: `uv run pytest -q`
Expected: PASS — every test, including Tasks 1–7's. This task must not leave a red test behind.

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/models/base.py src/cardly_cli/commands/_app.py \
        src/cardly_cli/commands/echo.py src/cardly_cli/__main__.py \
        tests/test_app_state.py
git commit -m "feat: add app spine with AppState, global flags and exit-code group"
```

---

### Task 9: Payload helpers

**Files:**
- Create: `src/cardly_cli/commands/_helpers.py`
- Test: `tests/test_helpers.py`

**Interfaces:**
- Consumes: `compact` from `models/base.py` (Task 8).
- Produces: `load_data(raw: str | None, *, stdin=None) -> dict`. `parse_fields(fields: list[str]) -> dict[str, Any]`. `apply_filters(items: list, filters: list[str]) -> list`. `build_payload(typed: dict, data: dict, fields: dict | None = None) -> dict`. Re-exports `compact` for command-side use.

**Context:** Read loxo's `_helpers.py` first. `load_data`, `parse_fields` and `apply_filters` port nearly verbatim.

**`build_payload` is the one that must NOT port verbatim.** loxo's signature is `build_payload(resource_key, typed, data, fields)` and it returns `{resource_key: merged}`. Cardly's bodies are **top-level** — there is no resource key. Shipping `{"order": {...}}` 422s everything. Ours drops the parameter entirely and returns the merged dict.

`compact()` is defined in `models/base.py` (Task 8) and re-exported here for command-side use. It lives there, not here, because the request builders in `models/` need it and **models must not import from `commands/`** — that inversion works (no cycle) but reads backwards and invites one later. Cardly's builders strip empty/None values so omitted flags don't send `null` and trip validation; the n8n node does the same (`orderBuilder.ts`).

- [ ] **Step 1: Write the failing test**

`tests/test_helpers.py`:

```python
import io

import pytest
import typer

from cardly_cli.commands._helpers import (
    apply_filters,
    build_payload,
    compact,
    load_data,
    parse_fields,
)


def test_load_data_inline_file_and_stdin(tmp_path):
    assert load_data(None) == {}
    assert load_data('{"a": 1}') == {"a": 1}

    path = tmp_path / "b.json"
    path.write_text('{"b": 2}')
    assert load_data(f"@{path}") == {"b": 2}

    assert load_data("-", stdin=io.StringIO('{"c": 3}')) == {"c": 3}


def test_load_data_bad_json_raises_bad_parameter():
    with pytest.raises(typer.BadParameter, match="Invalid --data JSON"):
        load_data("{nope")


def test_parse_fields():
    assert parse_fields(["a=1", "b=2"]) == {"a": "1", "b": "2"}
    assert parse_fields(["a=1", "a=2"]) == {"a": ["1", "2"]}
    assert parse_fields(["a[]=1"]) == {"a": ["1"]}
    assert parse_fields(["a=x=y"]) == {"a": "x=y"}  # only split on the first =


def test_parse_fields_requires_kv():
    with pytest.raises(typer.BadParameter, match="key=value"):
        parse_fields(["nope"])


def test_apply_filters():
    items = [{"id": 1, "status": "sent"}, {"id": 2, "status": "queued"}]
    assert apply_filters(items, ["status=sent"]) == [{"id": 1, "status": "sent"}]
    assert apply_filters(items, []) == items


def test_apply_filters_unwraps_named_objects():
    items = [{"id": 1, "status": {"id": 9, "name": "Active"}}]
    assert apply_filters(items, ["status=Active"]) == items


def test_compact_is_re_exported_from_models_base():
    # compact lives in models/base.py (models must not import from commands/);
    # _helpers re-exports it so command modules have one import site.
    from cardly_cli.models.base import compact as canonical

    assert compact is canonical


def test_build_payload_returns_unwrapped_body():
    # Cardly bodies are top-level. loxo wraps in a resource key; we must not.
    out = build_payload({"artwork": "slug"}, {}, {})
    assert out == {"artwork": "slug"}
    assert "order" not in out


def test_build_payload_precedence_typed_over_data():
    out = build_payload({"artwork": "flag"}, {"artwork": "body", "quantity": 2}, {})
    assert out == {"artwork": "flag", "quantity": 2}


def test_build_payload_ignores_none_typed_values():
    out = build_payload({"artwork": None, "quantity": 3}, {"artwork": "body"}, {})
    assert out == {"artwork": "body", "quantity": 3}


def test_build_payload_fields_win():
    out = build_payload({"a": "typed"}, {"a": "data"}, {"a": "field"})
    assert out == {"a": "field"}


def test_build_payload_fields_optional():
    assert build_payload({"a": 1}, {}) == {"a": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_helpers.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardly_cli.commands._helpers'`

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/commands/_helpers.py`:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

import typer

from cardly_cli.models.base import compact

__all__ = ["apply_filters", "build_payload", "compact", "load_data", "parse_fields"]


def load_data(raw: str | None, *, stdin: TextIO | None = None) -> dict:
    if raw is None:
        return {}
    try:
        if raw == "-":
            source = stdin or sys.stdin
            return json.load(source)
        if raw.startswith("@"):
            return json.loads(Path(raw[1:]).read_text())
        return json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        raise typer.BadParameter(f"Invalid --data JSON: {exc}") from exc


def parse_fields(fields: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in fields:
        if "=" not in item:
            raise typer.BadParameter(f"--field must be key=value, got {item!r}")
        key, value = item.split("=", 1)
        force_list = key.endswith("[]")
        if force_list:
            key = key[:-2]
        if key in result:
            existing = result[key]
            result[key] = existing + [value] if isinstance(existing, list) else [existing, value]
        elif force_list:
            result[key] = [value]
        else:
            result[key] = value
    return result


def apply_filters(items: list[Any], filters: list[str]) -> list[Any]:
    """Post-filter API records by exact field match, client-side.

    Each filter is ``key=value``. For object-valued fields the value is matched
    against the object's ``name`` (then ``id``).
    """
    if not filters:
        return items
    pairs: list[tuple[str, str]] = []
    for item in filters:
        if "=" not in item:
            raise typer.BadParameter(f"--filter must be key=value, got {item!r}")
        key, value = item.split("=", 1)
        pairs.append((key, value))

    def matches(record: Any) -> bool:
        if not isinstance(record, dict):
            return False
        for key, value in pairs:
            actual = record.get(key)
            if isinstance(actual, dict):
                actual = actual.get("name", actual.get("id"))
            if actual is None or str(actual) != value:
                return False
        return True

    return [item for item in items if matches(item)]


def build_payload(typed: dict, data: dict, fields: dict | None = None) -> dict:
    """Merge typed flags over a --data body. Precedence: fields > typed > data.

    NOTE: unlike loxo-cli's build_payload, this returns an UNWRAPPED body.
    Cardly's request bodies are top-level; there is no {"order": {...}}
    resource-key envelope. Wrapping 422s every write.
    """
    merged: dict[str, Any] = dict(data)
    merged.update({k: v for k, v in typed.items() if v is not None})
    merged.update(fields or {})
    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_helpers.py -q`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/commands/_helpers.py tests/test_helpers.py
git commit -m "feat: add payload helpers with unwrapped build_payload"
```

---

### Task 10: `configure`

**Files:**
- Create: `src/cardly_cli/commands/configure.py`
- Modify: `src/cardly_cli/__main__.py` (add registration)
- Test: `tests/test_cmd_configure.py`

**Interfaces:**
- Consumes: `write_profile`, `list_profiles`, `config_file_path`, `DEFAULT_BASE_URL` (Task 2); `AppState` (Task 8).
- Produces: `configure_app: typer.Typer` with `set` and `list` commands.

**Context:** `configure set` writes a profile; `configure list` shows them. **Never print a stored key** — show only whether one is present. `--api-key-cmd` stores a generic shell command; this repo must not mention any specific secrets manager, though the help text may note that any command printing a key on stdout works.

- [ ] **Step 1: Write the failing test**

`tests/test_cmd_configure.py`:

```python
import json

from typer.testing import CliRunner

from cardly_cli.__main__ import app
from cardly_cli.config import load_settings

runner = CliRunner()


def test_configure_set_writes_profile(tmp_path):
    path = tmp_path / "config.toml"
    result = runner.invoke(
        app,
        ["--config-path", str(path), "configure", "set", "prod", "--api-key", "live_abc"],
    )
    assert result.exit_code == 0
    assert load_settings(env={}, config_path=path).api_key == "live_abc"


def test_configure_set_supports_api_key_cmd(tmp_path):
    path = tmp_path / "config.toml"
    result = runner.invoke(
        app,
        [
            "--config-path", str(path), "configure", "set", "sandbox",
            "--api-key-cmd", "printf test_xyz",
        ],
    )
    assert result.exit_code == 0
    assert load_settings(env={}, config_path=path).api_key == "test_xyz"


def test_configure_set_requires_a_key_source(tmp_path):
    path = tmp_path / "config.toml"
    result = runner.invoke(app, ["--config-path", str(path), "configure", "set", "p"])
    assert result.exit_code != 0
    assert "--api-key" in result.stderr or "--api-key" in result.stdout


def test_configure_set_rejects_both_key_sources(tmp_path):
    path = tmp_path / "config.toml"
    result = runner.invoke(
        app,
        [
            "--config-path", str(path), "configure", "set", "p",
            "--api-key", "k", "--api-key-cmd", "printf k",
        ],
    )
    assert result.exit_code != 0


def test_configure_list_never_prints_the_key(tmp_path):
    path = tmp_path / "config.toml"
    runner.invoke(
        app, ["--config-path", str(path), "configure", "set", "prod", "--api-key", "live_SECRET"]
    )
    result = runner.invoke(app, ["--config-path", str(path), "--json", "configure", "list"])
    assert result.exit_code == 0
    assert "live_SECRET" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["prod"]["has_key"] is True


def test_configure_set_make_default(tmp_path):
    path = tmp_path / "config.toml"
    runner.invoke(app, ["--config-path", str(path), "configure", "set", "a", "--api-key", "1"])
    runner.invoke(
        app, ["--config-path", str(path), "configure", "set", "b", "--api-key", "2", "--default"]
    )
    assert load_settings(env={}, config_path=path).api_key == "2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cmd_configure.py -q`
Expected: FAIL — no `configure` command

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/commands/configure.py`:

```python
from __future__ import annotations

from typing import Optional

import typer

from cardly_cli.config import DEFAULT_BASE_URL, config_file_path, list_profiles, write_profile

configure_app = typer.Typer(help="Manage config profiles. Unofficial — not affiliated with Cardly.")

KEY_CMD_HELP = (
    "Shell command that prints the API key on stdout. Any command works; "
    "the key is never stored in the config file."
)


@configure_app.command("set")
def set_profile(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Profile name, e.g. prod or sandbox."),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="API key to store."),
    api_key_cmd: Optional[str] = typer.Option(None, "--api-key-cmd", help=KEY_CMD_HELP),
    base_url: str = typer.Option(DEFAULT_BASE_URL, "--base-url", help="API base URL."),
    make_default: bool = typer.Option(False, "--default", help="Make this the default profile."),
) -> None:
    """Write a profile to the config file."""
    state = ctx.obj
    if bool(api_key) == bool(api_key_cmd):
        raise typer.BadParameter("Provide exactly one of --api-key or --api-key-cmd.")
    write_profile(
        name,
        api_key=api_key,
        api_key_cmd=api_key_cmd,
        base_url=base_url,
        make_default=make_default,
        config_path=state.config_path,
    )
    path = state.config_path or config_file_path()
    state.warn(f"Wrote profile '{name}' to {path}")


@configure_app.command("list")
def list_cmd(ctx: typer.Context) -> None:
    """List configured profiles. Never prints stored keys."""
    state = ctx.obj
    state.emit(list_profiles(config_path=state.config_path))
```

In `src/cardly_cli/__main__.py`, add to the bottom import block:

```python
from cardly_cli.commands.configure import configure_app  # noqa: E402

app.add_typer(configure_app, name="configure")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cmd_configure.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/commands/configure.py src/cardly_cli/__main__.py tests/test_cmd_configure.py
git commit -m "feat: add configure command for profile management"
```

---

### Task 11: `echo` and `account`

**Files:**
- Create: `src/cardly_cli/models/account.py`, `src/cardly_cli/commands/account.py`
- Modify: `src/cardly_cli/commands/echo.py` (replace the Task 8 stub), `src/cardly_cli/__main__.py`
- Test: `tests/test_cmd_echo.py`, `tests/test_cmd_account.py`, `tests/test_error_exit_codes.py` (new), `tests/test_app_state.py` (append)

**This task also lands the deferred spine tests.** Task 8 built `AppState` and the
exit-code group but could not exercise them: credential resolution, `--base-url`
routing, and the exit-code contract all need a real command to drive. `echo` and
`account balance` are those commands, so those tests belong here.

**Interfaces:**
- Consumes: `CardlyModel` (Task 8), `AppState`, `CardlyClient`.
- Produces: `echo_app: typer.Typer` (one default command). `account_app: typer.Typer` with `balance`, `credit-history`, `gift-credit-history`. `Balance(CardlyModel)`, `CreditEntry(CardlyModel)`. `iso_to_cardly(value: str) -> str`.

**Context:** `echo` calls `POST /echo` — a free connectivity/auth smoke check.

`account balance` returns credit plus a `giftCredit` `{balance, currency}` sub-object: **two separate currencies of value**.

The credit-history date filters are the fiddly part. Cardly uses **dotted comparison operators** with a **space-separated, second-precision** datetime — `YYYY-MM-DD HH:MM:SS`, *not* ISO-T. All four operators are declared (`.lt`, `.lte`, `.gt`, `.gte`) and all four are exposed. **Date-only input must be padded to midnight**: a bare `2026-07-01` would otherwise pass through as a 10-char string, and it is unconfirmed whether the API accepts that (spec open question 7). Pad rather than find out in production.

- [ ] **Step 1: Write the failing tests**

`tests/test_cmd_echo.py`:

```python
import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


@respx.mock
def test_echo_posts_and_reports():
    route = respx.post("https://api.card.ly/v2/echo").mock(
        return_value=httpx.Response(200, json={"state": {"status": "OK"}, "data": {"ok": True}})
    )
    result = runner.invoke(app, ["--json", "echo"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.headers["API-Key"] == "k"


@respx.mock
def test_echo_passes_test_param():
    route = respx.post("https://api.card.ly/v2/echo").mock(
        return_value=httpx.Response(200, json={"state": {"status": "OK"}, "data": {"test": "hi"}})
    )
    result = runner.invoke(app, ["--json", "echo", "--test", "hi"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.url.params["test"] == "hi"


@respx.mock
def test_echo_401_exits_3():
    respx.post("https://api.card.ly/v2/echo").mock(
        return_value=httpx.Response(401, json={"state": {"status": "ERROR", "messages": ["bad key"]}})
    )
    result = runner.invoke(app, ["--no-retry", "echo"], env=ENV)
    assert result.exit_code == 3
```

Append to `tests/test_app_state.py` (the spine tests Task 8 deferred — they need a
real command to drive). Add `import httpx` and `import respx` to that file's imports:

```python
def test_missing_key_exits_2(tmp_path):
    result = runner.invoke(
        app,
        ["--config-path", str(tmp_path / "none.toml"), "echo"],
        env={"CARDLY_API_KEY": "", "CARDLY_PROFILE": ""},
    )
    assert result.exit_code == 2
    assert "No API key found" in result.stderr


@respx.mock
def test_base_url_flag_redirects_requests():
    route = respx.post("https://mock.test/v2/echo").mock(
        return_value=httpx.Response(200, json={"state": {"status": "OK"}, "data": {"ok": True}})
    )
    result = runner.invoke(
        app, ["--base-url", "https://mock.test/v2", "--json", "echo"], env={"CARDLY_API_KEY": "k"}
    )
    assert result.exit_code == 0
    assert route.called


@respx.mock
def test_verbose_logs_request_id_but_never_the_key():
    respx.post("https://api.card.ly/v2/echo").mock(
        return_value=httpx.Response(
            200, json={"state": {"status": "OK"}, "data": {}}, headers={"Request-Id": "req_9"}
        )
    )
    result = runner.invoke(app, ["-v", "echo"], env={"CARDLY_API_KEY": "sekrit"})
    assert "req_9" in result.stderr
    assert "sekrit" not in result.stderr
```

`tests/test_cmd_account.py`:

```python
import json

import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app
from cardly_cli.commands.account import iso_to_cardly

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


@respx.mock
def test_balance_shows_credit_and_gift_credit():
    respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(
            200, json=ok({"balance": 120, "giftCredit": {"balance": 50, "currency": "AUD"}})
        )
    )
    result = runner.invoke(app, ["--json", "account", "balance"], env=ENV)
    payload = json.loads(result.stdout)
    assert payload["balance"] == 120
    assert payload["giftCredit"]["currency"] == "AUD"


def test_iso_to_cardly_converts_and_pads():
    # Space-separated, second precision, NOT ISO-T.
    assert iso_to_cardly("2026-07-01T10:30:00") == "2026-07-01 10:30:00"
    assert iso_to_cardly("2026-07-01 10:30:00") == "2026-07-01 10:30:00"
    # Date-only pads to midnight rather than sending a bare 10-char string.
    assert iso_to_cardly("2026-07-01") == "2026-07-01 00:00:00"
    # Sub-second precision is truncated to 19 chars.
    assert iso_to_cardly("2026-07-01T10:30:00.123456") == "2026-07-01 10:30:00"


@respx.mock
def test_credit_history_sends_all_four_dotted_operators():
    route = respx.get("https://api.card.ly/v2/account/credit-history").mock(
        return_value=httpx.Response(200, json=ok({"meta": {"totalRecords": 0}, "results": []}))
    )
    result = runner.invoke(
        app,
        [
            "--json", "account", "credit-history",
            "--after", "2026-07-01",
            "--before", "2026-07-31T23:59:59",
            "--after-exclusive", "2026-06-01",
            "--before-exclusive", "2026-08-01",
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    params = route.calls.last.request.url.params
    assert params["effectiveTime.gte"] == "2026-07-01 00:00:00"
    assert params["effectiveTime.lte"] == "2026-07-31 23:59:59"
    assert params["effectiveTime.gt"] == "2026-06-01 00:00:00"
    assert params["effectiveTime.lt"] == "2026-08-01 00:00:00"


@respx.mock
def test_gift_credit_history_uses_its_own_endpoint():
    route = respx.get("https://api.card.ly/v2/account/gift-credit-history").mock(
        return_value=httpx.Response(200, json=ok({"meta": {"totalRecords": 0}, "results": []}))
    )
    result = runner.invoke(app, ["--json", "account", "gift-credit-history"], env=ENV)
    assert result.exit_code == 0
    assert route.called
```

`tests/test_error_exit_codes.py` — the exit-code contract, deferred from Task 8
because it needs a real command to drive:

```python
import httpx
import pytest
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


def err(messages):
    return {"state": {"status": "ERROR", "messages": messages}}


@pytest.mark.parametrize(
    "status,expected",
    [(401, 3), (403, 3), (404, 4), (402, 8), (422, 1), (400, 1), (429, 5), (500, 6), (503, 6)],
)
@respx.mock
def test_http_status_maps_to_exit_code(status, expected):
    respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(status, json=err(["nope"]))
    )
    result = runner.invoke(app, ["--no-retry", "account", "balance"], env=ENV)
    assert result.exit_code == expected


@respx.mock
def test_timeout_exits_7():
    respx.get("https://api.card.ly/v2/account/balance").mock(
        side_effect=httpx.ConnectTimeout("t")
    )
    result = runner.invoke(app, ["--no-retry", "account", "balance"], env=ENV)
    assert result.exit_code == 7


@respx.mock
def test_402_carries_its_message_and_exits_8():
    # 402 gets its own code because a scheduled job must treat it differently:
    # not transient, not a bug — top up the account.
    respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(402, json=err(["Insufficient credit: need 5, have 2."]))
    )
    result = runner.invoke(app, ["--no-retry", "account", "balance"], env=ENV)
    assert result.exit_code == 8
    assert "Insufficient credit" in result.stderr


@respx.mock
def test_error_message_goes_to_stderr_cleanly():
    respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(404, json=err(["Not found."]))
    )
    result = runner.invoke(app, ["--no-retry", "account", "balance"], env=ENV)
    assert result.stderr.startswith("Error:")
    assert "Traceback" not in result.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cmd_echo.py tests/test_cmd_account.py -q`
Expected: FAIL — no `account` command; `echo` is a stub with no commands

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/commands/echo.py` (replaces the stub):

```python
from __future__ import annotations

from typing import Optional

import typer

echo_app = typer.Typer(
    help="Connectivity and auth smoke check. Unofficial — not affiliated with Cardly.",
    invoke_without_command=True,
)


@echo_app.callback(invoke_without_command=True)
def echo(
    ctx: typer.Context,
    test: Optional[str] = typer.Option(None, "--test", help="Value to echo back."),
) -> None:
    """POST /echo — verifies the base URL and API key without spending credit."""
    if ctx.invoked_subcommand is not None:
        return
    state = ctx.obj
    params = {"test": test} if test else None
    state.emit(state.client().post("echo", params=params))
```

`src/cardly_cli/models/account.py`:

```python
from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel


class GiftCredit(CardlyModel):
    balance: Optional[float] = None
    currency: Optional[str] = None


class Balance(CardlyModel):
    balance: Optional[float] = None
    # Gift credit is a SEPARATE currency of value from regular credit, with its
    # own history endpoint. Not interchangeable.
    giftCredit: Optional[GiftCredit] = None


class CreditEntry(CardlyModel):
    id: Optional[str] = None
    effectiveTime: Optional[str] = None
    amount: Optional[float] = None
    balance: Optional[float] = None
    description: Optional[str] = None
    order: Optional[Any] = None
```

`src/cardly_cli/commands/account.py`:

```python
from __future__ import annotations

from typing import Any, Optional

import typer

from cardly_cli.models.account import Balance, CreditEntry
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

account_app = typer.Typer(help="Account balance and credit history.")

HISTORY_COLUMNS = ["id", "effectiveTime", "amount", "balance", "description"]


def iso_to_cardly(value: str) -> str:
    """Convert an ISO datetime to Cardly's filter format.

    Cardly wants `YYYY-MM-DD HH:MM:SS` — a space, not an ISO `T`, truncated to
    second precision. A date-only value is padded to midnight: a bare
    `2026-07-01` would otherwise go out as a 10-char string and it is
    unconfirmed whether the API accepts that.
    """
    text = value.strip().replace("T", " ")
    if len(text) == 10:
        text = f"{text} 00:00:00"
    return text[:19]


def _time_params(
    after: Optional[str],
    before: Optional[str],
    after_exclusive: Optional[str],
    before_exclusive: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if after:
        params["effectiveTime.gte"] = iso_to_cardly(after)
    if before:
        params["effectiveTime.lte"] = iso_to_cardly(before)
    if after_exclusive:
        params["effectiveTime.gt"] = iso_to_cardly(after_exclusive)
    if before_exclusive:
        params["effectiveTime.lt"] = iso_to_cardly(before_exclusive)
    return params


@account_app.command("balance")
def balance(ctx: typer.Context) -> None:
    """Show credit and gift-credit balances."""
    state = ctx.obj
    state.emit(Balance.model_validate(state.client().get("account/balance")))


def _history(ctx: typer.Context, endpoint: str, all_pages: bool, limit: int, **times: Any) -> None:
    state = ctx.obj
    params = _time_params(**times)
    client = state.client()
    if all_pages:
        items = list(paginate(client, endpoint, params=params, limit=limit, warn=state.warn))
    else:
        params["limit"] = limit
        items = extract_results(client.get(endpoint, params=params))
    state.emit([CreditEntry.model_validate(i) for i in items], columns=HISTORY_COLUMNS)


AFTER = typer.Option(None, "--after", help="Inclusive lower bound (effectiveTime.gte).")
BEFORE = typer.Option(None, "--before", help="Inclusive upper bound (effectiveTime.lte).")
AFTER_X = typer.Option(None, "--after-exclusive", help="Exclusive lower bound (effectiveTime.gt).")
BEFORE_X = typer.Option(None, "--before-exclusive", help="Exclusive upper bound (effectiveTime.lt).")


@account_app.command("credit-history")
def credit_history(
    ctx: typer.Context,
    after: Optional[str] = AFTER,
    before: Optional[str] = BEFORE,
    after_exclusive: Optional[str] = AFTER_X,
    before_exclusive: Optional[str] = BEFORE_X,
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
) -> None:
    """List regular credit transactions."""
    _history(
        ctx,
        "account/credit-history",
        all_pages,
        limit,
        after=after,
        before=before,
        after_exclusive=after_exclusive,
        before_exclusive=before_exclusive,
    )


@account_app.command("gift-credit-history")
def gift_credit_history(
    ctx: typer.Context,
    after: Optional[str] = AFTER,
    before: Optional[str] = BEFORE,
    after_exclusive: Optional[str] = AFTER_X,
    before_exclusive: Optional[str] = BEFORE_X,
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
) -> None:
    """List gift-credit transactions (a separate balance from regular credit)."""
    _history(
        ctx,
        "account/gift-credit-history",
        all_pages,
        limit,
        after=after,
        before=before,
        after_exclusive=after_exclusive,
        before_exclusive=before_exclusive,
    )
```

In `__main__.py`'s bottom import block:

```python
from cardly_cli.commands.account import account_app  # noqa: E402

app.add_typer(account_app, name="account")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: PASS — the full suite, including the exit-code contract and the `--base-url` / credential tests this task lands.

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/models/account.py src/cardly_cli/commands/account.py \
        src/cardly_cli/commands/echo.py src/cardly_cli/__main__.py \
        tests/test_cmd_echo.py tests/test_cmd_account.py \
        tests/test_error_exit_codes.py tests/test_app_state.py
git commit -m "feat: add echo and account commands with exit-code contract tests"
```

---

### Task 12: `orders` — models and line builder

**Files:**
- Create: `src/cardly_cli/models/order.py`
- Test: `tests/test_models_order.py`

**Interfaces:**
- Consumes: `CardlyModel`, `compact` (both Task 8, `models/base.py`).
- Produces: `OrderAddress`, `Style`, `MessagePage`, `Order`, `OrderItem`, `Preview` models. `build_address(values: dict) -> dict`. `validate_sender(values: dict) -> dict | None`. `build_messages(pages: list[tuple[int, str]]) -> dict | None`. `check_shipping(method: str | None, country: str | None) -> None` raising `typer.BadParameter`. `build_line(...) -> dict`. `SHIPPING_METHODS`, `SHIPPING_REGIONS`.

**Context:** This module holds every order-specific rule. Read the spec's "Orders" section before starting.

**Order addresses use `city`.** Contacts use `locality` (Task 14). These must never share a model — see the comment requirement in Global Constraints.

**Sender is all-or-nothing.** Cardly: "if any sender element is specified, all must be specified." So: if *any* sender value is present, require the complete set and fail locally; if *none* are, return `None` so the key is omitted entirely and Cardly's org defaults apply. Required-if-present: `firstName`, `address`, `city`, `country`.

**`region`/`postcode` are NOT validated.** The OpenAPI contradicts itself and no country table exists. Guessing rejects valid addresses. Let the API decide.

**Shipping is region-gated:** `standard` everywhere, `tracked` **AU only**, `express` **AU and US only**.

**Message pages nest at `messages.pages[]` keyed by `page`** (1-based int; 1 = front), *not* `name`. Cardly's own OpenAPI example gets this wrong — hence the test.

- [ ] **Step 1: Write the failing test**

`tests/test_models_order.py`:

```python
import pytest
import typer

from cardly_cli.models.order import (
    SHIPPING_METHODS,
    build_address,
    build_line,
    build_messages,
    check_shipping,
    validate_sender,
)

FULL_RECIPIENT = {
    "firstName": "Ada",
    "lastName": "Lovelace",
    "address": "12 Analytical Way",
    "city": "Melbourne",
    "country": "AU",
}


def test_build_address_uses_city_not_locality():
    # Orders use `city`. Contacts use `locality`. Sharing a model 422s.
    out = build_address(FULL_RECIPIENT)
    assert out["city"] == "Melbourne"
    assert "locality" not in out


def test_build_address_compacts_empty_values():
    out = build_address({**FULL_RECIPIENT, "company": "", "address2": None, "region": "VIC"})
    assert "company" not in out
    assert "address2" not in out
    assert out["region"] == "VIC"


def test_build_address_does_not_require_region_or_postcode():
    # Conditionally required by country; the OpenAPI contradicts itself and the
    # API is the only authority. Guessing would reject valid addresses.
    out = build_address(FULL_RECIPIENT)
    assert "region" not in out and "postcode" not in out


def test_validate_sender_returns_none_when_entirely_blank():
    # Omit the key entirely so Cardly's org return details apply.
    assert validate_sender({"firstName": None, "address": "", "city": None}) is None
    assert validate_sender({}) is None


def test_validate_sender_accepts_complete_sender():
    out = validate_sender({**FULL_RECIPIENT})
    assert out is not None and out["firstName"] == "Ada"


def test_validate_sender_rejects_partial_sender():
    # "If any sender element is specified, all must be specified."
    with pytest.raises(typer.BadParameter, match="sender"):
        validate_sender({"firstName": "Ada"})


@pytest.mark.parametrize("missing", ["firstName", "address", "city", "country"])
def test_validate_sender_names_the_missing_field(missing):
    values = dict(FULL_RECIPIENT)
    values.pop(missing)
    with pytest.raises(typer.BadParameter, match=missing):
        validate_sender(values)


def test_build_messages_uses_page_key_not_name():
    # Cardly's own OpenAPI example ships {"name": 2} here. The field is `page`.
    out = build_messages([(1, "Front"), (2, "Inside")])
    assert out == {"pages": [{"page": 1, "text": "Front"}, {"page": 2, "text": "Inside"}]}
    assert "name" not in out["pages"][0]


def test_build_messages_empty_returns_none():
    assert build_messages([]) is None


def test_shipping_methods_enum():
    assert set(SHIPPING_METHODS) == {"standard", "tracked", "express"}


def test_check_shipping_standard_allowed_everywhere():
    check_shipping("standard", "GB")
    check_shipping(None, "GB")


def test_check_shipping_tracked_is_australia_only():
    check_shipping("tracked", "AU")
    check_shipping("tracked", "au")  # case-insensitive
    with pytest.raises(typer.BadParameter, match="tracked"):
        check_shipping("tracked", "US")


def test_check_shipping_express_is_au_and_us_only():
    check_shipping("express", "AU")
    check_shipping("express", "US")
    with pytest.raises(typer.BadParameter, match="express"):
        check_shipping("express", "GB")


def test_check_shipping_skips_when_country_unknown():
    # --data may carry the country; don't block on a flag we can't see.
    check_shipping("tracked", None)


def test_build_line_assembles_full_body():
    line = build_line(
        artwork="thank-you-01",
        template="tpl-1",
        quantity=2,
        recipient=FULL_RECIPIENT,
        sender=None,
        messages=[(1, "Hi")],
        variables={"name": "Ada"},
        style={"align": "center"},
        shipping="standard",
        ship_to_me=False,
        requested_arrival="2026-08-01",
        data={},
    )
    assert line["artwork"] == "thank-you-01"
    assert line["template"] == "tpl-1"
    assert line["quantity"] == 2
    assert line["recipient"]["city"] == "Melbourne"
    assert line["messages"]["pages"][0]["page"] == 1
    assert line["variables"] == {"name": "Ada"}
    assert line["style"] == {"align": "center"}
    assert line["shippingMethod"] == "standard"
    assert line["requestedArrival"] == "2026-08-01"
    assert "sender" not in line  # omitted, not null


def test_build_line_keeps_ship_to_me_false():
    line = build_line(
        artwork="a", recipient=FULL_RECIPIENT, ship_to_me=False, data={},
        template=None, quantity=None, sender=None, messages=[], variables={},
        style={}, shipping=None, requested_arrival=None,
    )
    # False is a real value; compact() must not strip it.
    assert line["shipToMe"] is False


def test_build_line_merges_data_under_typed_flags():
    line = build_line(
        artwork="flag-wins", recipient=FULL_RECIPIENT, data={"artwork": "body", "quantity": 9},
        template=None, quantity=None, sender=None, messages=[], variables={},
        style={}, shipping=None, ship_to_me=None, requested_arrival=None,
    )
    assert line["artwork"] == "flag-wins"
    assert line["quantity"] == 9  # from --data, no typed override given
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models_order.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardly_cli.models.order'`

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/models/order.py`:

```python
from __future__ import annotations

from typing import Any, Optional

import typer

from cardly_cli.models.base import CardlyModel, compact

SHIPPING_METHODS = ("standard", "tracked", "express")

# Availability is region-gated. Checked client-side to preempt a 422 that costs
# a round trip to discover.
SHIPPING_REGIONS: dict[str, set[str] | None] = {
    "standard": None,  # all regions
    "tracked": {"AU"},
    "express": {"AU", "US"},
}

# Present-if-any-present. Cardly: "if any sender element is specified, all must
# be specified." region/postcode are deliberately absent — see build_address.
SENDER_REQUIRED = ("firstName", "address", "city", "country")

ADDRESS_KEYS = (
    "firstName",
    "lastName",
    "company",
    "address",
    "address2",
    "city",
    "region",
    "postcode",
    "country",
)


class OrderAddress(CardlyModel):
    """Recipient/sender address for ORDERS.

    NOTE: orders use `city`; contacts use `locality` and read back
    `adminAreaLevel1`. This looks like duplication of models/contact.py and is
    not — unifying them guarantees a 422 on contact writes. Do not "clean up".
    """

    firstName: Optional[str] = None
    lastName: Optional[str] = None
    company: Optional[str] = None
    address: Optional[str] = None
    address2: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    postcode: Optional[str] = None
    country: Optional[str] = None


class Style(CardlyModel):
    align: Optional[str] = None
    color: Optional[str] = None
    font: Optional[str] = None
    size: Optional[int] = None
    verticalAlign: Optional[str] = None
    writing: Optional[str] = None


class MessagePage(CardlyModel):
    # `page`, NOT `name`. 1-based; 1 is the front, then reading order.
    page: Optional[int] = None
    text: Optional[str] = None
    style: Optional[Style] = None


class OrderItem(CardlyModel):
    id: Optional[str] = None
    type: Optional[str] = None
    artwork: Optional[Any] = None
    template: Optional[Any] = None
    label: Optional[str] = None
    quantity: Optional[int] = None
    costs: Optional[Any] = None
    shipTo: Optional[Any] = None
    shipMethod: Optional[str] = None
    scheduledDate: Optional[str] = None
    recipient: Optional[Any] = None
    sender: Optional[Any] = None
    delivery: Optional[Any] = None
    tracking: Optional[Any] = None


class Order(CardlyModel):
    id: Optional[str] = None
    status: Optional[str] = None
    origin: Optional[str] = None
    customer: Optional[Any] = None
    costs: Optional[Any] = None
    timings: Optional[Any] = None
    items: Optional[list[OrderItem]] = None


class Preview(CardlyModel):
    urls: Optional[Any] = None
    expires: Optional[str] = None


def build_address(values: dict[str, Any]) -> dict[str, Any]:
    """Build an ORDER address (uses `city`).

    region/postcode are conditionally required by country. The OpenAPI
    contradicts itself on which are required and no country table exists, so we
    send what we're given and let the API be the authority. Guessing here would
    reject valid addresses.
    """
    return compact({key: values.get(key) for key in ADDRESS_KEYS})


def validate_sender(values: dict[str, Any]) -> dict[str, Any] | None:
    """Return a complete sender, or None when no sender was given at all.

    Cardly's rule: "if any sender element is specified, all must be specified."
    So a partial sender is a local error, and a wholly absent one means "use my
    organisation's return details" — which requires omitting the key entirely
    rather than sending nulls.
    """
    built = build_address(values)
    if not built:
        return None
    missing = [key for key in SENDER_REQUIRED if not built.get(key)]
    if missing:
        raise typer.BadParameter(
            "Incomplete sender: if any --from-* option is given, all of "
            f"{', '.join(SENDER_REQUIRED)} are required. Missing: {', '.join(missing)}."
        )
    return built


def build_messages(pages: list[tuple[int, str]]) -> dict[str, Any] | None:
    """Nest message text at messages.pages[] keyed by `page`.

    The key is `page` (1-based int), not `name` — Cardly's own OpenAPI example
    ships {"name": 2} here, which is wrong.
    """
    if not pages:
        return None
    ordered = sorted(pages, key=lambda item: item[0])
    return {"pages": [{"page": number, "text": text} for number, text in ordered]}


def check_shipping(method: str | None, country: str | None) -> None:
    """Preempt a region 422: tracked is AU-only, express is AU+US-only."""
    if not method or not country:
        return
    allowed = SHIPPING_REGIONS.get(method)
    if allowed is None:
        return
    if country.upper() not in allowed:
        raise typer.BadParameter(
            f"Shipping method '{method}' is only available for "
            f"{', '.join(sorted(allowed))} (got {country.upper()}). "
            f"Use 'standard' instead."
        )


def build_line(
    *,
    artwork: str | None,
    template: str | None,
    quantity: int | None,
    recipient: dict[str, Any],
    sender: dict[str, Any] | None,
    messages: list[tuple[int, str]],
    variables: dict[str, Any],
    style: dict[str, Any],
    shipping: str | None,
    ship_to_me: bool | None,
    requested_arrival: str | None,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Assemble one order line. Shared verbatim by `place` and `preview`.

    `place` wraps the result in {"lines": [line]}; `preview` sends it flat. That
    wrap is the ONLY difference between the two bodies.
    """
    built_recipient = build_address(recipient)
    built_sender = validate_sender(sender or {})
    line: dict[str, Any] = dict(data)
    typed = compact(
        {
            "artwork": artwork,
            "template": template,
            "quantity": quantity,
            "recipient": built_recipient,
            "messages": build_messages(messages),
            "variables": variables,
            "style": style,
            "shippingMethod": shipping,
            "requestedArrival": requested_arrival,
        }
    )
    line.update(typed)
    if built_sender:
        line["sender"] = built_sender
    if ship_to_me is not None:
        # False is meaningful, so set it outside compact().
        line["shipToMe"] = ship_to_me
    return line
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models_order.py -q`
Expected: PASS (19 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/models/order.py tests/test_models_order.py
git commit -m "feat: add order models with sender, shipping and message-page rules"
```

---

### Task 13: `orders` commands

**Files:**
- Create: `src/cardly_cli/commands/orders.py`
- Modify: `src/cardly_cli/__main__.py`
- Test: `tests/test_cmd_orders.py`

**Interfaces:**
- Consumes: everything from Task 12; `paginate`/`extract_results` (Task 7); `load_data`/`parse_fields`/`apply_filters` (Task 9).
- Produces: `orders_app: typer.Typer` with `place`, `preview`, `get`, `list`.

**Context:** `place` and `preview` share one flag set and one builder. The only difference:
- `place` → `POST /orders/place`, body `{"lines": [line], "purchaseOrderNumber": ...}`
- `preview` → `POST /orders/preview`, body is the line **flat**

**`testMode: true` must lead with a banner** so a `test_` key is never mistaken for a real send.

**Preview URLs:** returned as `http://` (force-upgrade to `https://`), they **expire**, and they live on `api.card.ly` rather than a pre-signed CDN link — so `--download` needs the `API-Key` header, which means fetching through our own client.

- [ ] **Step 1: Write the failing test**

`tests/test_cmd_orders.py`:

```python
import json

import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}

TO = [
    "--artwork", "thank-you-01",
    "--to-first-name", "Ada",
    "--to-address", "12 Analytical Way",
    "--to-city", "Melbourne",
    "--to-country", "AU",
]


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


@respx.mock
def test_place_wraps_body_in_lines():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "o1", "status": "queued"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    result = runner.invoke(app, ["--json", "orders", "place", *TO, "--message", "Thanks!"], env=ENV)
    assert result.exit_code == 0
    body = captured["body"]
    assert "lines" in body and isinstance(body["lines"], list)
    line = body["lines"][0]
    assert line["artwork"] == "thank-you-01"
    assert line["recipient"]["city"] == "Melbourne"
    assert line["messages"]["pages"] == [{"page": 1, "text": "Thanks!"}]


@respx.mock
def test_preview_body_is_flat_not_wrapped():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"preview": {"urls": {}}, "order": {"creditCost": 2}}))

    respx.post("https://api.card.ly/v2/orders/preview").mock(side_effect=handler)
    result = runner.invoke(app, ["--json", "orders", "preview", *TO], env=ENV)
    assert result.exit_code == 0
    body = captured["body"]
    # Same fields as place, but NOT wrapped in lines[].
    assert "lines" not in body
    assert body["artwork"] == "thank-you-01"
    assert body["recipient"]["city"] == "Melbourne"


@respx.mock
def test_place_and_preview_build_identical_lines():
    bodies = {}

    def place_handler(request):
        bodies["place"] = json.loads(request.content)["lines"][0]
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    def preview_handler(request):
        bodies["preview"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"preview": {"urls": {}}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=place_handler)
    respx.post("https://api.card.ly/v2/orders/preview").mock(side_effect=preview_handler)
    args = [*TO, "--message", "Hi", "--var", "name=Ada", "--shipping", "standard"]
    runner.invoke(app, ["--json", "orders", "place", *args], env=ENV)
    runner.invoke(app, ["--json", "orders", "preview", *args], env=ENV)
    preview = dict(bodies["preview"])
    preview.pop("purchaseOrderNumber", None)
    assert bodies["place"] == preview


@respx.mock
def test_place_sends_purchase_order_number_at_top_level():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    runner.invoke(app, ["orders", "place", *TO, "--purchase-order-number", "PO-9"], env=ENV)
    assert captured["body"]["purchaseOrderNumber"] == "PO-9"
    assert "purchaseOrderNumber" not in captured["body"]["lines"][0]


@respx.mock
def test_place_supports_all_typed_flags():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    runner.invoke(
        app,
        [
            "orders", "place", *TO,
            "--template", "tpl-1",
            "--quantity", "3",
            "--ship-to-me",
            "--requested-arrival", "2026-08-01",
            "--style", "align=center",
            "--var", "name=Ada",
        ],
        env=ENV,
    )
    line = captured["body"]["lines"][0]
    assert line["template"] == "tpl-1"
    assert line["quantity"] == 3
    assert line["shipToMe"] is True
    assert line["requestedArrival"] == "2026-08-01"
    assert line["style"] == {"align": "center"}
    assert line["variables"] == {"name": "Ada"}


@respx.mock
def test_message_page_flag_controls_ordering():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    runner.invoke(
        app, ["orders", "place", *TO, "--message-page", "3=Back", "--message-page", "1=Front"],
        env=ENV,
    )
    pages = captured["body"]["lines"][0]["messages"]["pages"]
    assert pages == [{"page": 1, "text": "Front"}, {"page": 3, "text": "Back"}]


def test_partial_sender_fails_locally_without_a_request():
    result = runner.invoke(app, ["orders", "place", *TO, "--from-first-name", "Bob"], env=ENV)
    assert result.exit_code == 2  # Typer usage error
    assert "sender" in result.stderr.lower()


def test_tracked_shipping_outside_australia_fails_locally():
    args = [
        "--artwork", "a", "--to-first-name", "A", "--to-address", "x",
        "--to-city", "London", "--to-country", "GB", "--shipping", "tracked",
    ]
    result = runner.invoke(app, ["orders", "place", *args], env=ENV)
    assert result.exit_code == 2
    assert "tracked" in result.stderr


@respx.mock
def test_test_mode_response_shows_banner():
    respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"testMode": True, "order": {"id": "1"}}))
    )
    result = runner.invoke(app, ["orders", "place", *TO], env=ENV)
    assert result.exit_code == 0
    assert "TEST MODE" in result.stderr
    assert "no card was sent" in result.stderr.lower()


@respx.mock
def test_live_response_shows_no_banner():
    respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    result = runner.invoke(app, ["orders", "place", *TO], env=ENV)
    assert "TEST MODE" not in result.stderr


@respx.mock
def test_place_402_exits_8():
    respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(
            402, json={"state": {"status": "ERROR", "messages": ["Need 5 credit, have 2."]}}
        )
    )
    result = runner.invoke(app, ["--no-retry", "orders", "place", *TO], env=ENV)
    assert result.exit_code == 8
    assert "Need 5 credit" in result.stderr


@respx.mock
def test_place_accepts_data_body():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    body = json.dumps({"lines": [{"artwork": "from-data", "recipient": {"firstName": "Z"}}]})
    result = runner.invoke(app, ["orders", "place", "--data", body], env=ENV)
    assert result.exit_code == 0
    assert captured["body"]["lines"][0]["artwork"] == "from-data"


@respx.mock
def test_preview_upgrades_http_urls_to_https():
    respx.post("https://api.card.ly/v2/orders/preview").mock(
        return_value=httpx.Response(
            200,
            json=ok(
                {
                    "preview": {
                        "urls": {"card": "http://api.card.ly/v2/preview/x/card/pdf"},
                        "expires": "2026-07-16T00:00:00",
                    }
                }
            ),
        )
    )
    result = runner.invoke(app, ["--json", "orders", "preview", *TO], env=ENV)
    payload = json.loads(result.stdout)
    assert payload["preview"]["urls"]["card"].startswith("https://")


@respx.mock
def test_preview_download_fetches_pdf_with_api_key(tmp_path):
    respx.post("https://api.card.ly/v2/orders/preview").mock(
        return_value=httpx.Response(
            200,
            json=ok({"preview": {"urls": {"card": "http://api.card.ly/v2/preview/x/card/pdf"}}}),
        )
    )
    pdf = respx.get("https://api.card.ly/v2/preview/x/card/pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4")
    )
    out = tmp_path / "proof.pdf"
    result = runner.invoke(
        app, ["orders", "preview", *TO, "--download", str(out)], env=ENV
    )
    assert result.exit_code == 0
    assert out.read_bytes() == b"%PDF-1.4"
    # Preview PDFs live on api.card.ly, not a pre-signed CDN link, so the
    # API-Key header is required on the fetch too.
    assert pdf.calls.last.request.headers["API-Key"] == "k"


@respx.mock
def test_orders_list_extracts_results():
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(
            200,
            json=ok({"meta": {"totalRecords": 1}, "results": [{"id": "o1", "status": "sent"}]}),
        )
    )
    result = runner.invoke(app, ["--json", "orders", "list"], env=ENV)
    assert json.loads(result.stdout)[0]["id"] == "o1"


@respx.mock
def test_orders_get():
    respx.get("https://api.card.ly/v2/orders/o1").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "o1", "status": "sent"}}))
    )
    result = runner.invoke(app, ["--json", "orders", "get", "o1"], env=ENV)
    assert json.loads(result.stdout)["id"] == "o1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cmd_orders.py -q`
Expected: FAIL — no `orders` command

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/commands/orders.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import typer

from cardly_cli.commands._helpers import apply_filters, load_data, parse_fields
from cardly_cli.models.order import SHIPPING_METHODS, Order, build_line, check_shipping
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

orders_app = typer.Typer(help="Place, preview and inspect orders.")

LIST_COLUMNS = ["id", "status", "origin"]


def _parse_message_pages(messages: list[str], message_pages: list[str]) -> list[tuple[int, str]]:
    """Positional --message, plus explicit --message-page N=text."""
    pages: list[tuple[int, str]] = [(i + 1, text) for i, text in enumerate(messages)]
    for item in message_pages:
        if "=" not in item:
            raise typer.BadParameter(f"--message-page must be N=text, got {item!r}")
        number, text = item.split("=", 1)
        if not number.strip().isdigit():
            raise typer.BadParameter(f"--message-page page must be an integer, got {number!r}")
        pages.append((int(number), text))
    return pages


def _typed_int(values: dict[str, Any], key: str) -> Any:
    raw = values.get(key)
    return int(raw) if raw is not None else None


def _upgrade_preview_urls(payload: Any) -> Any:
    """Force preview URLs to https.

    Cardly's schema examples (and responses) return http:// links for previews.
    They point at api.card.ly, not a pre-signed CDN link.
    """
    if not isinstance(payload, dict):
        return payload
    preview = payload.get("preview")
    if isinstance(preview, dict) and isinstance(preview.get("urls"), dict):
        preview["urls"] = {
            key: (value.replace("http://", "https://", 1) if isinstance(value, str) else value)
            for key, value in preview["urls"].items()
        }
    return payload


def _warn_test_mode(state: Any, payload: Any) -> None:
    if isinstance(payload, dict) and payload.get("testMode") is True:
        state.warn(
            "TEST MODE: this key validated the request but no card was sent and "
            "no credit was spent. Use a live_ key to place real orders."
        )


def _build(
    *,
    artwork,
    template,
    quantity,
    to,
    frm,
    messages,
    message_pages,
    variables,
    style,
    shipping,
    ship_to_me,
    requested_arrival,
    data,
) -> dict[str, Any]:
    check_shipping(shipping, to.get("country"))
    return build_line(
        artwork=artwork,
        template=template,
        quantity=quantity,
        recipient=to,
        sender=frm,
        messages=_parse_message_pages(messages, message_pages),
        variables=parse_fields(variables),
        style=parse_fields(style),
        shipping=shipping,
        ship_to_me=ship_to_me,
        requested_arrival=requested_arrival,
        data=data,
    )


ARTWORK = typer.Option(None, "--artwork", help="Artwork UUID or slug, e.g. happy-birthday.")
TEMPLATE = typer.Option(None, "--template", help="Template ID. Without it, no variable substitution.")
QUANTITY = typer.Option(None, "--quantity", min=1, help="Copies of this card (default 1).")
SHIPPING = typer.Option(
    None,
    "--shipping",
    help="standard (all regions) | tracked (AU only) | express (AU and US only).",
)
SHIP_TO_ME = typer.Option(
    None, "--ship-to-me/--no-ship-to-me", help="Ship to sender; adds cost per card."
)
ARRIVAL = typer.Option(None, "--requested-arrival", help="Requested future arrival date.")
MESSAGE = typer.Option([], "--message", help="Message text; repeat for pages 1, 2, 3...")
MESSAGE_PAGE = typer.Option([], "--message-page", help="Explicit page: N=text (1 = front).")
VAR = typer.Option([], "--var", help="Template variable key=value (repeatable).")
STYLE = typer.Option([], "--style", help="Card style key=value: align, color, font, size...")
DATA = typer.Option(None, "--data", "-d", help="JSON body: inline, @file, or - for stdin.")


def _recipient(**kw: Any) -> dict[str, Any]:
    return kw


@orders_app.command("place")
def place(
    ctx: typer.Context,
    artwork: Optional[str] = ARTWORK,
    template: Optional[str] = TEMPLATE,
    quantity: Optional[int] = QUANTITY,
    to_first_name: Optional[str] = typer.Option(None, "--to-first-name"),
    to_last_name: Optional[str] = typer.Option(None, "--to-last-name"),
    to_company: Optional[str] = typer.Option(None, "--to-company"),
    to_address: Optional[str] = typer.Option(None, "--to-address"),
    to_address2: Optional[str] = typer.Option(None, "--to-address2"),
    to_city: Optional[str] = typer.Option(None, "--to-city"),
    to_region: Optional[str] = typer.Option(None, "--to-region", help="Conditionally required by country."),
    to_postcode: Optional[str] = typer.Option(None, "--to-postcode", help="Conditionally required by country."),
    to_country: Optional[str] = typer.Option(None, "--to-country", help="2-char ISO country code."),
    from_first_name: Optional[str] = typer.Option(None, "--from-first-name"),
    from_last_name: Optional[str] = typer.Option(None, "--from-last-name"),
    from_company: Optional[str] = typer.Option(None, "--from-company"),
    from_address: Optional[str] = typer.Option(None, "--from-address"),
    from_address2: Optional[str] = typer.Option(None, "--from-address2"),
    from_city: Optional[str] = typer.Option(None, "--from-city"),
    from_region: Optional[str] = typer.Option(None, "--from-region"),
    from_postcode: Optional[str] = typer.Option(None, "--from-postcode"),
    from_country: Optional[str] = typer.Option(None, "--from-country"),
    message: list[str] = MESSAGE,
    message_page: list[str] = MESSAGE_PAGE,
    var: list[str] = VAR,
    style: list[str] = STYLE,
    shipping: Optional[str] = SHIPPING,
    ship_to_me: Optional[bool] = SHIP_TO_ME,
    requested_arrival: Optional[str] = ARRIVAL,
    purchase_order_number: Optional[str] = typer.Option(None, "--purchase-order-number"),
    data: Optional[str] = DATA,
) -> None:
    """Place an order (POST /orders/place). Spends credit unless the key is test_."""
    state = ctx.obj
    if shipping and shipping not in SHIPPING_METHODS:
        raise typer.BadParameter(f"--shipping must be one of {', '.join(SHIPPING_METHODS)}")
    raw = load_data(data)
    # --data may carry a full {"lines": [...]} body; honour it as the base.
    lines = raw.pop("lines", None)
    if lines:
        body: dict[str, Any] = {"lines": lines}
    else:
        line = _build(
            artwork=artwork,
            template=template,
            quantity=quantity,
            to=_recipient(
                firstName=to_first_name, lastName=to_last_name, company=to_company,
                address=to_address, address2=to_address2, city=to_city,
                region=to_region, postcode=to_postcode, country=to_country,
            ),
            frm=_recipient(
                firstName=from_first_name, lastName=from_last_name, company=from_company,
                address=from_address, address2=from_address2, city=from_city,
                region=from_region, postcode=from_postcode, country=from_country,
            ),
            messages=message,
            message_pages=message_page,
            variables=var,
            style=style,
            shipping=shipping,
            ship_to_me=ship_to_me,
            requested_arrival=requested_arrival,
            data=raw,
        )
        # `place` wraps the line; `preview` does not. This is the ONLY shape
        # difference between the two endpoints.
        body = {"lines": [line]}
    if purchase_order_number:
        body["purchaseOrderNumber"] = purchase_order_number
    result = state.client().post("orders/place", json=body)
    _warn_test_mode(state, result)
    state.emit(result)


@orders_app.command("preview")
def preview(
    ctx: typer.Context,
    artwork: Optional[str] = ARTWORK,
    template: Optional[str] = TEMPLATE,
    quantity: Optional[int] = QUANTITY,
    to_first_name: Optional[str] = typer.Option(None, "--to-first-name"),
    to_last_name: Optional[str] = typer.Option(None, "--to-last-name"),
    to_company: Optional[str] = typer.Option(None, "--to-company"),
    to_address: Optional[str] = typer.Option(None, "--to-address"),
    to_address2: Optional[str] = typer.Option(None, "--to-address2"),
    to_city: Optional[str] = typer.Option(None, "--to-city"),
    to_region: Optional[str] = typer.Option(None, "--to-region"),
    to_postcode: Optional[str] = typer.Option(None, "--to-postcode"),
    to_country: Optional[str] = typer.Option(None, "--to-country"),
    from_first_name: Optional[str] = typer.Option(None, "--from-first-name"),
    from_last_name: Optional[str] = typer.Option(None, "--from-last-name"),
    from_company: Optional[str] = typer.Option(None, "--from-company"),
    from_address: Optional[str] = typer.Option(None, "--from-address"),
    from_address2: Optional[str] = typer.Option(None, "--from-address2"),
    from_city: Optional[str] = typer.Option(None, "--from-city"),
    from_region: Optional[str] = typer.Option(None, "--from-region"),
    from_postcode: Optional[str] = typer.Option(None, "--from-postcode"),
    from_country: Optional[str] = typer.Option(None, "--from-country"),
    message: list[str] = MESSAGE,
    message_page: list[str] = MESSAGE_PAGE,
    var: list[str] = VAR,
    style: list[str] = STYLE,
    shipping: Optional[str] = SHIPPING,
    ship_to_me: Optional[bool] = SHIP_TO_ME,
    requested_arrival: Optional[str] = ARRIVAL,
    download: Optional[Path] = typer.Option(
        None, "--download", help="Save the proof PDF to this path."
    ),
    data: Optional[str] = DATA,
) -> None:
    """Preview an order (POST /orders/preview) — watermarked proof, no credit spent."""
    state = ctx.obj
    if shipping and shipping not in SHIPPING_METHODS:
        raise typer.BadParameter(f"--shipping must be one of {', '.join(SHIPPING_METHODS)}")
    raw = load_data(data)
    raw.pop("lines", None)  # preview takes ONE card, flat — never a lines[] wrap
    body = _build(
        artwork=artwork,
        template=template,
        quantity=quantity,
        to=_recipient(
            firstName=to_first_name, lastName=to_last_name, company=to_company,
            address=to_address, address2=to_address2, city=to_city,
            region=to_region, postcode=to_postcode, country=to_country,
        ),
        frm=_recipient(
            firstName=from_first_name, lastName=from_last_name, company=from_company,
            address=from_address, address2=from_address2, city=from_city,
            region=from_region, postcode=from_postcode, country=from_country,
        ),
        messages=message,
        message_pages=message_page,
        variables=var,
        style=style,
        shipping=shipping,
        ship_to_me=ship_to_me,
        requested_arrival=requested_arrival,
        data=raw,
    )
    client = state.client()
    result = _upgrade_preview_urls(client.post("orders/preview", json=body))
    _warn_test_mode(state, result)

    if download:
        url = (result.get("preview") or {}).get("urls", {}).get("card")
        if not url:
            raise typer.BadParameter("Preview response carried no card URL to download.")
        # Preview URLs expire (preview.expires) and are NOT pre-signed CDN
        # links — they sit on api.card.ly, so the fetch needs our API-Key
        # header. Fetch now; never cache the URL across runs.
        response = client.request("GET", url, raw=True)
        download.write_bytes(response.content)
        state.warn(f"Wrote proof PDF to {download}")

    state.emit(result)


@orders_app.command("get")
def get_order(ctx: typer.Context, order_id: str = typer.Argument(...)) -> None:
    """Show one order."""
    state = ctx.obj
    data = state.client().get(f"orders/{order_id}")
    inner = data.get("order", data) if isinstance(data, dict) else data
    state.emit(Order.model_validate(inner))


@orders_app.command("list")
def list_orders(
    ctx: typer.Context,
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
    filter_: list[str] = typer.Option([], "--filter", help="Client-side key=value match."),
) -> None:
    """List orders."""
    state = ctx.obj
    client = state.client()
    if all_pages:
        items = list(paginate(client, "orders", limit=limit, warn=state.warn))
    else:
        items = extract_results(client.get("orders", params={"limit": limit}))
    rows = [Order.model_validate(i) for i in apply_filters(items, filter_)]
    state.emit(rows, columns=LIST_COLUMNS)
```

> **Note on `client.request("GET", url, raw=True)`:** `url_for` prefixes the base URL, so an absolute preview URL must be passed through unchanged. Add this guard to `url_for` in `client.py` and a test for it:
> ```python
> def url_for(settings: CardlySettings, endpoint: str) -> str:
>     if endpoint.startswith(("http://", "https://")):
>         return endpoint
>     return f"{settings.base_url}/{endpoint.lstrip('/')}"
> ```
> ```python
> def test_url_for_passes_absolute_urls_through():
>     assert url_for(SETTINGS, "https://api.card.ly/v2/preview/x/card/pdf") == (
>         "https://api.card.ly/v2/preview/x/card/pdf"
>     )
> ```

In `__main__.py`'s bottom import block:

```python
from cardly_cli.commands.orders import orders_app  # noqa: E402

app.add_typer(orders_app, name="orders")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cmd_orders.py tests/test_client.py -q`
Expected: PASS (16 + 24 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/commands/orders.py src/cardly_cli/client.py \
        src/cardly_cli/__main__.py tests/test_cmd_orders.py tests/test_client.py
git commit -m "feat: add orders place/preview/get/list with shared line builder"
```

---

### Task 14: `contacts`

**Files:**
- Create: `src/cardly_cli/models/contact.py`, `src/cardly_cli/commands/contacts.py`
- Modify: `src/cardly_cli/__main__.py`
- Test: `tests/test_models_contact.py`, `tests/test_cmd_contacts.py`

**Interfaces:**
- Consumes: `CardlyModel`, `compact` (Task 8); `parse_fields`, `load_data`, `apply_filters` (Task 9); pagination (Task 7).
- Produces: `Contact(CardlyModel)`, `CONTACT_KEYS`, `build_contact(values, fields) -> dict`. `contacts_app: typer.Typer` with `create`, `sync`, `get`, `list`, `find`, `update`, `delete`, `delete-all`.

**Context — the address vocabulary split is the whole point of this task.**

Contacts use **`locality`** where orders use `city`, and reads return **`adminAreaLevel1`** for region. The n8n design spec: *"The request builders must not share a single address shape or contact creation will 422."* `models/contact.py` must carry a comment saying so — this looks like duplication of `models/order.py` and is not.

Other rules:
- **`sync` requires at least one of `--external-id`/`--email`** — it's the upsert match key. Enforce locally; no point spending a round trip.
- **`create` rejects duplicates** server-side on those fields. On a 422 mentioning a duplicate, the error should point at `sync`.
- **`update` is a POST** to the contact path, not PUT/PATCH.
- `--field k=v` fills `fields`, a map keyed by Cardly field code.
- `region`/`postcode` are **not** validated (see Task 12's rationale; contacts have the same OpenAPI contradiction in worse form).

- [ ] **Step 1: Write the failing tests**

`tests/test_models_contact.py`:

```python
from cardly_cli.models.contact import Contact, build_contact


def test_build_contact_uses_locality_not_city():
    # THE test. Orders serialize `city`; contacts serialize `locality`.
    # Sharing one address model 422s every contact write.
    out = build_contact({"firstName": "Ada", "address": "x", "locality": "Melbourne",
                         "country": "AU"}, {})
    assert out["locality"] == "Melbourne"
    assert "city" not in out


def test_build_contact_compacts_empties():
    out = build_contact({"firstName": "Ada", "lastName": "", "email": None}, {})
    assert out == {"firstName": "Ada"}


def test_build_contact_includes_fields_map():
    out = build_contact({"firstName": "Ada"}, {"birthday": "1815-12-10"})
    assert out["fields"] == {"birthday": "1815-12-10"}


def test_build_contact_omits_empty_fields_map():
    assert "fields" not in build_contact({"firstName": "Ada"}, {})


def test_contact_model_reads_admin_area_level_1():
    # Reads come back with adminAreaLevel1, not `region`.
    c = Contact.model_validate({"id": "1", "firstName": "Ada", "adminAreaLevel1": "VIC"})
    assert c.adminAreaLevel1 == "VIC"
```

`tests/test_cmd_contacts.py`:

```python
import json

import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}
BASE = "https://api.card.ly/v2/contact-lists/L1/contacts"


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


@respx.mock
def test_create_sends_locality():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "c1", "firstName": "Ada"}))

    respx.post(BASE).mock(side_effect=handler)
    result = runner.invoke(
        app,
        [
            "contacts", "create", "L1",
            "--first-name", "Ada", "--email", "ada@example.com",
            "--address", "12 Analytical Way", "--locality", "Melbourne", "--country", "AU",
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"]["locality"] == "Melbourne"
    assert "city" not in captured["body"]


@respx.mock
def test_create_sends_custom_fields():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "c1"}))

    respx.post(BASE).mock(side_effect=handler)
    runner.invoke(
        app,
        ["contacts", "create", "L1", "--first-name", "Ada", "--field", "birthday=1815-12-10"],
        env=ENV,
    )
    assert captured["body"]["fields"] == {"birthday": "1815-12-10"}


@respx.mock
def test_sync_posts_to_sync_endpoint():
    route = respx.post(f"{BASE}/sync").mock(return_value=httpx.Response(200, json=ok({"id": "c1"})))
    result = runner.invoke(
        app, ["contacts", "sync", "L1", "--external-id", "crm-42", "--first-name", "Ada"], env=ENV
    )
    assert result.exit_code == 0
    assert route.called


def test_sync_requires_a_match_key():
    # externalId or email is the upsert key; without one the call is pointless.
    result = runner.invoke(app, ["contacts", "sync", "L1", "--first-name", "Ada"], env=ENV)
    assert result.exit_code == 2
    assert "--external-id" in result.stderr or "--email" in result.stderr


@respx.mock
def test_sync_accepts_email_as_match_key():
    route = respx.post(f"{BASE}/sync").mock(return_value=httpx.Response(200, json=ok({"id": "c1"})))
    result = runner.invoke(
        app, ["contacts", "sync", "L1", "--email", "ada@example.com"], env=ENV
    )
    assert result.exit_code == 0
    assert route.called


@respx.mock
def test_create_duplicate_error_points_at_sync():
    respx.post(BASE).mock(
        return_value=httpx.Response(
            422,
            json={
                "state": {"status": "ERROR", "messages": ["Contact already exists."]},
                "data": {"email": "This contact already exists."},
            },
        )
    )
    result = runner.invoke(
        app, ["--no-retry", "contacts", "create", "L1", "--email", "ada@example.com"], env=ENV
    )
    assert result.exit_code == 1
    assert "sync" in result.stderr.lower()


@respx.mock
def test_update_uses_post_not_put():
    route = respx.post(f"{BASE}/c1").mock(return_value=httpx.Response(200, json=ok({"id": "c1"})))
    result = runner.invoke(app, ["contacts", "update", "L1", "c1", "--first-name", "Ada"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.method == "POST"


@respx.mock
def test_find_sends_query():
    route = respx.get(f"{BASE}/find").mock(return_value=httpx.Response(200, json=ok({"id": "c1"})))
    result = runner.invoke(app, ["--json", "contacts", "find", "L1", "--query", "ada@x.com"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.url.params["query"] == "ada@x.com"


@respx.mock
def test_get_and_list():
    respx.get(f"{BASE}/c1").mock(return_value=httpx.Response(200, json=ok({"id": "c1"})))
    respx.get(BASE).mock(
        return_value=httpx.Response(200, json=ok({"meta": {"totalRecords": 1}, "results": [{"id": "c1"}]}))
    )
    assert json.loads(runner.invoke(app, ["--json", "contacts", "get", "L1", "c1"], env=ENV).stdout)["id"] == "c1"
    assert json.loads(runner.invoke(app, ["--json", "contacts", "list", "L1"], env=ENV).stdout)[0]["id"] == "c1"


@respx.mock
def test_delete_requires_confirmation():
    route = respx.delete(f"{BASE}/c1").mock(return_value=httpx.Response(200, json=ok({})))
    runner.invoke(app, ["contacts", "delete", "L1", "c1"], input="n\n", env=ENV)
    assert route.called is False
    result = runner.invoke(app, ["contacts", "delete", "L1", "c1", "--yes"], env=ENV)
    assert result.exit_code == 0
    assert route.called is True


@respx.mock
def test_delete_all_sends_body_to_collection():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content) if request.content else None
        return httpx.Response(200, json=ok({"deleted": 2}))

    respx.delete(BASE).mock(side_effect=handler)
    result = runner.invoke(
        app, ["contacts", "delete-all", "L1", "--data", '{"externalIds": ["a", "b"]}', "--yes"],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"] == {"externalIds": ["a", "b"]}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models_contact.py tests/test_cmd_contacts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardly_cli.models.contact'`

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/models/contact.py`:

```python
from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel, compact

# Contacts use `locality`. Orders use `city`. See the class docstring.
CONTACT_KEYS = (
    "externalId",
    "firstName",
    "lastName",
    "email",
    "company",
    "address",
    "address2",
    "locality",
    "region",
    "country",
    "postcode",
)


class Contact(CardlyModel):
    """A contact-list contact.

    NOTE: this is deliberately NOT models/order.OrderAddress, despite looking
    like duplication. Contacts use `locality` where orders use `city`, and reads
    return `adminAreaLevel1` for region. Cardly 422s every contact write if the
    order address shape is reused. Do not "DRY these up".

    region/postcode are conditionally required by country. The OpenAPI marks
    both `required` here with no x-conditionallyRequired marker at all, which
    cannot be true for every country (UK/NZ have no region; some countries have
    no postcode). The API is the only authority — do not validate them locally.
    """

    id: Optional[str] = None
    externalId: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    address: Optional[str] = None
    address2: Optional[str] = None
    locality: Optional[str] = None
    region: Optional[str] = None
    # Reads come back as adminAreaLevel1, not region.
    adminAreaLevel1: Optional[str] = None
    country: Optional[str] = None
    postcode: Optional[str] = None
    fields: Optional[dict[str, Any]] = None


def build_contact(values: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    body = compact({key: values.get(key) for key in CONTACT_KEYS})
    if fields:
        body["fields"] = fields
    return body
```

`src/cardly_cli/commands/contacts.py`:

```python
from __future__ import annotations

from typing import Any, Optional

import typer

from cardly_cli.commands._helpers import apply_filters, load_data, parse_fields
from cardly_cli.errors import CardlyError
from cardly_cli.models.contact import Contact, build_contact
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

contacts_app = typer.Typer(help="Manage contacts within a contact list.")

LIST_COLUMNS = ["id", "externalId", "firstName", "lastName", "email", "locality"]

FIRST = typer.Option(None, "--first-name")
LAST = typer.Option(None, "--last-name")
EMAIL = typer.Option(None, "--email")
EXTERNAL = typer.Option(None, "--external-id", help="Your system's ID; the sync match key.")
COMPANY = typer.Option(None, "--company")
ADDRESS = typer.Option(None, "--address")
ADDRESS2 = typer.Option(None, "--address2")
LOCALITY = typer.Option(None, "--locality", help="City/suburb. (Contacts use `locality`.)")
REGION = typer.Option(None, "--region", help="Conditionally required by country.")
POSTCODE = typer.Option(None, "--postcode", help="Conditionally required by country.")
COUNTRY = typer.Option(None, "--country", help="2-char ISO country code.")
FIELD = typer.Option([], "--field", help="Custom field key=value, keyed by Cardly field code.")
DATA = typer.Option(None, "--data", "-d", help="JSON body: inline, @file, or -.")


def _values(**kw: Any) -> dict[str, Any]:
    return kw


def _body(kw: dict[str, Any], field: list[str], data: Optional[str]) -> dict[str, Any]:
    raw = load_data(data)
    body = dict(raw)
    body.update(build_contact(kw, parse_fields(field)))
    return body


@contacts_app.command("create")
def create(
    ctx: typer.Context,
    list_id: str = typer.Argument(..., help="Contact list ID."),
    external_id: Optional[str] = EXTERNAL,
    first_name: Optional[str] = FIRST,
    last_name: Optional[str] = LAST,
    email: Optional[str] = EMAIL,
    company: Optional[str] = COMPANY,
    address: Optional[str] = ADDRESS,
    address2: Optional[str] = ADDRESS2,
    locality: Optional[str] = LOCALITY,
    region: Optional[str] = REGION,
    postcode: Optional[str] = POSTCODE,
    country: Optional[str] = COUNTRY,
    field: list[str] = FIELD,
    data: Optional[str] = DATA,
) -> None:
    """Create a contact. Rejects duplicates on externalId/email — use `sync` to upsert."""
    state = ctx.obj
    body = _body(
        _values(
            externalId=external_id, firstName=first_name, lastName=last_name, email=email,
            company=company, address=address, address2=address2, locality=locality,
            region=region, postcode=postcode, country=country,
        ),
        field,
        data,
    )
    try:
        result = state.client().post(f"contact-lists/{list_id}/contacts", json=body)
    except CardlyError as exc:
        if exc.status_code == 422 and "exist" in str(exc).lower():
            raise CardlyError(
                f"{exc.format_message()} "
                f"(Cardly rejects duplicates on externalId/email; use "
                f"`cardly contacts sync {list_id} ...` to upsert instead.)",
                status_code=exc.status_code,
            ) from exc
        raise
    state.emit(Contact.model_validate(result))


@contacts_app.command("sync")
def sync(
    ctx: typer.Context,
    list_id: str = typer.Argument(...),
    external_id: Optional[str] = EXTERNAL,
    first_name: Optional[str] = FIRST,
    last_name: Optional[str] = LAST,
    email: Optional[str] = EMAIL,
    company: Optional[str] = COMPANY,
    address: Optional[str] = ADDRESS,
    address2: Optional[str] = ADDRESS2,
    locality: Optional[str] = LOCALITY,
    region: Optional[str] = REGION,
    postcode: Optional[str] = POSTCODE,
    country: Optional[str] = COUNTRY,
    field: list[str] = FIELD,
    data: Optional[str] = DATA,
) -> None:
    """Upsert a contact by externalId or email."""
    state = ctx.obj
    body = _body(
        _values(
            externalId=external_id, firstName=first_name, lastName=last_name, email=email,
            company=company, address=address, address2=address2, locality=locality,
            region=region, postcode=postcode, country=country,
        ),
        field,
        data,
    )
    if not body.get("externalId") and not body.get("email"):
        # The match key IS the point of sync. Without one there's nothing to
        # match on, so fail here rather than spend a round trip learning that.
        raise typer.BadParameter("sync requires --external-id or --email as the match key.")
    state.emit(Contact.model_validate(state.client().post(f"contact-lists/{list_id}/contacts/sync", json=body)))


@contacts_app.command("update")
def update(
    ctx: typer.Context,
    list_id: str = typer.Argument(...),
    contact_id: str = typer.Argument(...),
    external_id: Optional[str] = EXTERNAL,
    first_name: Optional[str] = FIRST,
    last_name: Optional[str] = LAST,
    email: Optional[str] = EMAIL,
    company: Optional[str] = COMPANY,
    address: Optional[str] = ADDRESS,
    address2: Optional[str] = ADDRESS2,
    locality: Optional[str] = LOCALITY,
    region: Optional[str] = REGION,
    postcode: Optional[str] = POSTCODE,
    country: Optional[str] = COUNTRY,
    field: list[str] = FIELD,
    data: Optional[str] = DATA,
) -> None:
    """Update a contact. NOTE: Cardly uses POST here, not PUT/PATCH."""
    state = ctx.obj
    body = _body(
        _values(
            externalId=external_id, firstName=first_name, lastName=last_name, email=email,
            company=company, address=address, address2=address2, locality=locality,
            region=region, postcode=postcode, country=country,
        ),
        field,
        data,
    )
    result = state.client().post(f"contact-lists/{list_id}/contacts/{contact_id}", json=body)
    state.emit(Contact.model_validate(result))


@contacts_app.command("get")
def get(ctx: typer.Context, list_id: str = typer.Argument(...), contact_id: str = typer.Argument(...)) -> None:
    """Show one contact."""
    state = ctx.obj
    state.emit(Contact.model_validate(state.client().get(f"contact-lists/{list_id}/contacts/{contact_id}")))


@contacts_app.command("find")
def find(
    ctx: typer.Context,
    list_id: str = typer.Argument(...),
    query: str = typer.Option(..., "--query", "-q", help="Email or externalId."),
) -> None:
    """Find a contact by email or externalId."""
    state = ctx.obj
    result = state.client().get(f"contact-lists/{list_id}/contacts/find", params={"query": query})
    state.emit(Contact.model_validate(result))


@contacts_app.command("list")
def list_contacts(
    ctx: typer.Context,
    list_id: str = typer.Argument(...),
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
    filter_: list[str] = typer.Option([], "--filter", help="Client-side key=value match."),
) -> None:
    """List contacts in a list."""
    state = ctx.obj
    endpoint = f"contact-lists/{list_id}/contacts"
    client = state.client()
    if all_pages:
        items = list(paginate(client, endpoint, limit=limit, warn=state.warn))
    else:
        items = extract_results(client.get(endpoint, params={"limit": limit}))
    rows = [Contact.model_validate(i) for i in apply_filters(items, filter_)]
    state.emit(rows, columns=LIST_COLUMNS)


@contacts_app.command("delete")
def delete(
    ctx: typer.Context,
    list_id: str = typer.Argument(...),
    contact_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Delete one contact."""
    state = ctx.obj
    if not yes:
        typer.confirm(f"Delete contact {contact_id} from list {list_id}?", abort=True)
    state.client().delete(f"contact-lists/{list_id}/contacts/{contact_id}")
    state.warn(f"Deleted contact {contact_id}.")


@contacts_app.command("delete-all")
def delete_all(
    ctx: typer.Context,
    list_id: str = typer.Argument(...),
    data: Optional[str] = DATA,
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Bulk-delete contacts by body (DELETE on the collection)."""
    state = ctx.obj
    if not yes:
        typer.confirm(f"Bulk-delete contacts from list {list_id}?", abort=True)
    body = load_data(data) or None
    state.emit(state.client().request("DELETE", f"contact-lists/{list_id}/contacts", json=body))
```

In `__main__.py`'s bottom import block:

```python
from cardly_cli.commands.contacts import contacts_app  # noqa: E402

app.add_typer(contacts_app, name="contacts")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models_contact.py tests/test_cmd_contacts.py -q`
Expected: PASS (5 + 11 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/models/contact.py src/cardly_cli/commands/contacts.py \
        src/cardly_cli/__main__.py tests/test_models_contact.py tests/test_cmd_contacts.py
git commit -m "feat: add contacts commands with locality address vocabulary"
```

---

### Task 15: `lists`

**Files:**
- Create: `src/cardly_cli/models/contact_list.py`, `src/cardly_cli/commands/lists.py`
- Modify: `src/cardly_cli/__main__.py`
- Test: `tests/test_cmd_lists.py`

**Interfaces:**
- Consumes: `CardlyModel`, `load_data`, pagination.
- Produces: `ContactList(CardlyModel)`, `ListField(CardlyModel)`. `lists_app: typer.Typer` with `list`, `get`, `create`, `delete`.

**Context:** **There is no update endpoint.** A list's name/description cannot be edited via the API. Do not add an `update` command — its absence is a fact about Cardly, not an oversight. The test asserts this.

Create body: `{name, description?, fields: [{name, type, description?}]}` where `type` is one of `text`, `date`, `number`, `url`.

- [ ] **Step 1: Write the failing test**

`tests/test_cmd_lists.py`:

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


@respx.mock
def test_lists_list():
    respx.get("https://api.card.ly/v2/contact-lists").mock(
        return_value=httpx.Response(
            200, json=ok({"meta": {"totalRecords": 1}, "results": [{"id": "L1", "name": "VIPs"}]})
        )
    )
    result = runner.invoke(app, ["--json", "lists", "list"], env=ENV)
    assert json.loads(result.stdout)[0]["name"] == "VIPs"


@respx.mock
def test_lists_get():
    respx.get("https://api.card.ly/v2/contact-lists/L1").mock(
        return_value=httpx.Response(200, json=ok({"id": "L1", "name": "VIPs"}))
    )
    result = runner.invoke(app, ["--json", "lists", "get", "L1"], env=ENV)
    assert json.loads(result.stdout)["id"] == "L1"


@respx.mock
def test_lists_create_with_fields():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "L2", "name": "Leads"}))

    respx.post("https://api.card.ly/v2/contact-lists").mock(side_effect=handler)
    result = runner.invoke(
        app,
        [
            "lists", "create", "--name", "Leads", "--description", "From CRM",
            "--field", "birthday:date", "--field", "notes",
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"]["name"] == "Leads"
    assert captured["body"]["description"] == "From CRM"
    assert captured["body"]["fields"] == [
        {"name": "birthday", "type": "date"},
        {"name": "notes", "type": "text"},  # type defaults to text
    ]


def test_lists_create_rejects_bad_field_type():
    result = runner.invoke(app, ["lists", "create", "--name", "X", "--field", "a:banana"], env=ENV)
    assert result.exit_code == 2
    assert "banana" in result.stderr


@respx.mock
def test_lists_delete_requires_confirmation():
    route = respx.delete("https://api.card.ly/v2/contact-lists/L1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    runner.invoke(app, ["lists", "delete", "L1"], input="n\n", env=ENV)
    assert route.called is False
    result = runner.invoke(app, ["lists", "delete", "L1", "--yes"], env=ENV)
    assert result.exit_code == 0
    assert route.called is True


def test_no_update_command_exists():
    # Cardly has no contact-list update endpoint. A list's name/description
    # cannot be edited via the API. This absence is deliberate.
    result = runner.invoke(app, ["lists", "update", "L1", "--name", "X"], env=ENV)
    assert result.exit_code != 0
    assert "No such command" in result.stderr or "no such command" in result.stderr.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cmd_lists.py -q`
Expected: FAIL — no `lists` command

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/models/contact_list.py`:

```python
from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel

FIELD_TYPES = ("text", "date", "number", "url")


class ListField(CardlyModel):
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None


class ContactList(CardlyModel):
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    fields: Optional[list[ListField]] = None
    contactCount: Optional[int] = None
    createdAt: Optional[Any] = None
```

`src/cardly_cli/commands/lists.py`:

```python
from __future__ import annotations

from typing import Any, Optional

import typer

from cardly_cli.commands._helpers import load_data
from cardly_cli.models.contact_list import FIELD_TYPES, ContactList
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

# NOTE: no `update` command. Cardly exposes GET/POST on the collection and
# GET/DELETE on the item — there is NO contact-list update endpoint, so a list's
# name and description cannot be edited via the API. The absence is deliberate.
lists_app = typer.Typer(help="Manage contact lists.")

LIST_COLUMNS = ["id", "name", "description", "contactCount"]


def _parse_list_fields(items: list[str]) -> list[dict[str, Any]]:
    """Parse `name[:type]` into Cardly's fields[] entries. type defaults to text."""
    fields: list[dict[str, Any]] = []
    for item in items:
        name, _, type_ = item.partition(":")
        type_ = type_ or "text"
        if type_ not in FIELD_TYPES:
            raise typer.BadParameter(
                f"--field type must be one of {', '.join(FIELD_TYPES)}, got {type_!r}"
            )
        fields.append({"name": name, "type": type_})
    return fields


@lists_app.command("list")
def list_lists(
    ctx: typer.Context,
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
) -> None:
    """List contact lists."""
    state = ctx.obj
    client = state.client()
    if all_pages:
        items = list(paginate(client, "contact-lists", limit=limit, warn=state.warn))
    else:
        items = extract_results(client.get("contact-lists", params={"limit": limit}))
    state.emit([ContactList.model_validate(i) for i in items], columns=LIST_COLUMNS)


@lists_app.command("get")
def get(ctx: typer.Context, list_id: str = typer.Argument(...)) -> None:
    """Show one contact list."""
    state = ctx.obj
    state.emit(ContactList.model_validate(state.client().get(f"contact-lists/{list_id}")))


@lists_app.command("create")
def create(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(None, "--name"),
    description: Optional[str] = typer.Option(None, "--description"),
    field: list[str] = typer.Option(
        [], "--field", help=f"Custom field as name[:type]; type one of {', '.join(FIELD_TYPES)}."
    ),
    data: Optional[str] = typer.Option(None, "--data", "-d", help="JSON body: inline, @file, or -."),
) -> None:
    """Create a contact list."""
    state = ctx.obj
    body: dict[str, Any] = dict(load_data(data))
    if name:
        body["name"] = name
    if description:
        body["description"] = description
    fields = _parse_list_fields(field)
    if fields:
        body["fields"] = fields
    state.emit(ContactList.model_validate(state.client().post("contact-lists", json=body)))


@lists_app.command("delete")
def delete(
    ctx: typer.Context,
    list_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Delete a contact list and its contacts."""
    state = ctx.obj
    if not yes:
        typer.confirm(f"Delete contact list {list_id} and all its contacts?", abort=True)
    state.client().delete(f"contact-lists/{list_id}")
    state.warn(f"Deleted contact list {list_id}.")
```

In `__main__.py`'s bottom import block:

```python
from cardly_cli.commands.lists import lists_app  # noqa: E402

app.add_typer(lists_app, name="lists")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cmd_lists.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/models/contact_list.py src/cardly_cli/commands/lists.py \
        src/cardly_cli/__main__.py tests/test_cmd_lists.py
git commit -m "feat: add contact list commands"
```

---

### Task 16: Postback signature verification

**Files:**
- Create: `src/cardly_cli/signature.py`
- Test: `tests/test_signature.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GOLDEN_SECRET`, `GOLDEN_TIMESTAMP`, `GOLDEN_PAYLOAD`, `GOLDEN_DIGEST` constants. `compute(secret: str, timestamp: str, payload: str) -> str`. `extract_raw_property(raw: bytes, name: str) -> bytes | None`. `VerifyResult(matched: bool, scheme: str | None, tried: list[str], reason: str | None)`. `verify(raw_body: bytes, secret: str, *, headers: Mapping[str, str] | None = None) -> VerifyResult`.

**Context — read the spec's "Signature verification" section in full before starting.**

Cardly's docs describe **two different schemes** and we do not know which is live. Both cite the *same* golden vector, so the vector cannot discriminate between them.

| | Scheme A ("Verify Postback Signatures") | Scheme B ("Secure Your Endpoint") |
|---|---|---|
| Timestamp from | body's `timestamp` property | `Cardly-Timestamp` header |
| Payload | JSON-encoded `data` object | raw request body |
| Compare against | body's `signatures` array | `Cardly-Signatures` JSON header |

Shared primitive: `md5(secret + "." + timestamp + "." + payload)`.

**Neither has been validated against a live postback.** The n8n node implements Scheme A after a docs-reading correction — *not* an empirical test. So `verify` tries both and reports **which matched**. That makes the command the instrument that finally settles the question.

**The raw byte slice matters.** Cardly signs `data` *as transmitted*. Re-`json.dumps()`-ing it changes key order and whitespace and silently breaks the hash. `extract_raw_property` must be **depth-aware** so a nested `"data"` key can't be mistaken for the root one.

MD5, not HMAC — weak, but it's what Cardly implements. Compare in constant time. Fail closed.

- [ ] **Step 1: Write the failing test**

`tests/test_signature.py`:

```python
import hashlib
import json

from cardly_cli.signature import (
    GOLDEN_DIGEST,
    GOLDEN_PAYLOAD,
    GOLDEN_SECRET,
    GOLDEN_TIMESTAMP,
    compute,
    extract_raw_property,
    verify,
)


def test_golden_vector_from_cardly_docs():
    # md5("secretabc.1234567890.{"test":true}") == 6ef4f0658ff7bb880fc3ae0cf7db3b2a
    # Both documented schemes cite this same vector, which is exactly why it
    # cannot tell them apart — it only pins the shared md5 primitive.
    assert compute(GOLDEN_SECRET, GOLDEN_TIMESTAMP, GOLDEN_PAYLOAD) == GOLDEN_DIGEST
    assert GOLDEN_DIGEST == "6ef4f0658ff7bb880fc3ae0cf7db3b2a"


def test_extract_raw_property_returns_bytes_as_transmitted():
    raw = b'{"timestamp":"1","data":{"b":2,"a":1},"signatures":["x"]}'
    # Note key order b,a preserved and no whitespace added.
    assert extract_raw_property(raw, "data") == b'{"b":2,"a":1}'


def test_extract_raw_property_preserves_whitespace_exactly():
    raw = b'{"data": { "a" : 1 } }'
    assert extract_raw_property(raw, "data") == b'{ "a" : 1 }'


def test_extract_raw_property_is_depth_aware():
    # A nested "data" key must NOT be mistaken for the root one.
    raw = b'{"outer":{"data":{"wrong":true}},"data":{"right":true}}'
    assert extract_raw_property(raw, "data") == b'{"right":true}'


def test_extract_raw_property_handles_strings_with_braces():
    raw = b'{"note":"} not a brace {","data":{"a":1}}'
    assert extract_raw_property(raw, "data") == b'{"a":1}'


def test_extract_raw_property_handles_escaped_quotes():
    raw = rb'{"note":"say \"hi\" }","data":{"a":1}}'
    assert extract_raw_property(raw, "data") == b'{"a":1}'


def test_extract_raw_property_missing_returns_none():
    assert extract_raw_property(b'{"a":1}', "data") is None


def test_extract_raw_property_non_object_value():
    assert extract_raw_property(b'{"data":[1,2]}', "data") == b"[1,2]"
    assert extract_raw_property(b'{"data":true}', "data") == b"true"


def _scheme_a_body(secret="s3cret", timestamp="1700000000", data=None):
    data = {"event": "contact.order.sent", "id": "o1"} if data is None else data
    raw_data = json.dumps(data, separators=(",", ":"))
    digest = hashlib.md5(f"{secret}.{timestamp}.{raw_data}".encode()).hexdigest()
    body = f'{{"timestamp":"{timestamp}","data":{raw_data},"signatures":["{digest}"]}}'
    return body.encode(), digest


def test_verify_scheme_a_body_signatures_array():
    raw, _ = _scheme_a_body()
    result = verify(raw, "s3cret")
    assert result.matched
    assert result.scheme == "body-signatures"


def test_verify_scheme_a_matches_any_entry_in_the_array():
    raw, digest = _scheme_a_body()
    body = json.loads(raw)
    body_raw = raw.replace(
        f'["{digest}"]'.encode(), f'["deadbeef","{digest}"]'.encode()
    )
    assert verify(body_raw, "s3cret").matched


def test_verify_scheme_b_header_signatures():
    secret, timestamp = "s3cret", "1700000000"
    raw = b'{"event":"contact.order.sent"}'
    digest = hashlib.md5(f"{secret}.{timestamp}.".encode() + raw).hexdigest()
    result = verify(
        raw,
        secret,
        headers={"Cardly-Timestamp": timestamp, "Cardly-Signatures": json.dumps([digest])},
    )
    assert result.matched
    assert result.scheme == "header-signatures"


def test_verify_header_scheme_accepts_bare_string_header():
    secret, timestamp = "s3cret", "1700000000"
    raw = b'{"a":1}'
    digest = hashlib.md5(f"{secret}.{timestamp}.".encode() + raw).hexdigest()
    result = verify(raw, secret, headers={"Cardly-Timestamp": timestamp, "Cardly-Signatures": digest})
    assert result.matched


def test_verify_headers_are_case_insensitive():
    secret, timestamp = "s3cret", "1700000000"
    raw = b'{"a":1}'
    digest = hashlib.md5(f"{secret}.{timestamp}.".encode() + raw).hexdigest()
    result = verify(
        raw, secret, headers={"cardly-timestamp": timestamp, "cardly-signatures": json.dumps([digest])}
    )
    assert result.matched


def test_verify_fails_closed_on_wrong_secret():
    raw, _ = _scheme_a_body()
    result = verify(raw, "wrong-secret")
    assert not result.matched
    assert result.scheme is None


def test_verify_reports_every_scheme_tried():
    raw, _ = _scheme_a_body()
    result = verify(raw, "wrong", headers={"Cardly-Timestamp": "1", "Cardly-Signatures": "[]"})
    assert not result.matched
    assert "body-signatures" in result.tried
    assert "header-signatures" in result.tried
    assert result.reason  # names what was tried rather than asserting "bad signature"


def test_verify_tries_only_body_scheme_without_headers():
    raw, _ = _scheme_a_body()
    result = verify(raw, "wrong")
    assert result.tried == ["body-signatures"]


def test_verify_fails_closed_on_unparseable_body():
    result = verify(b"not json", "s")
    assert not result.matched
    assert result.reason


def test_verify_fails_closed_on_empty_secret():
    raw, _ = _scheme_a_body()
    assert not verify(raw, "").matched


def test_verify_uses_raw_slice_not_reserialized_data():
    # Cardly signs `data` AS TRANSMITTED. Build a body whose data has key order
    # and spacing that json.dumps would never reproduce; only a raw slice can
    # match.
    secret, timestamp = "s3cret", "1700000000"
    weird = '{ "z":1,   "a":2 }'
    digest = hashlib.md5(f"{secret}.{timestamp}.{weird}".encode()).hexdigest()
    raw = f'{{"timestamp":"{timestamp}","data":{weird},"signatures":["{digest}"]}}'.encode()
    result = verify(raw, secret)
    assert result.matched, "re-serializing data breaks the hash; must use the raw byte slice"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_signature.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cardly_cli.signature'`

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/signature.py`:

```python
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

# The worked example from Cardly's docs. Both documented schemes cite this SAME
# vector, which is exactly why it cannot discriminate between them: it pins the
# shared md5 primitive and nothing else.
GOLDEN_SECRET = "secretabc"
GOLDEN_TIMESTAMP = "1234567890"
GOLDEN_PAYLOAD = '{"test":true}'
GOLDEN_DIGEST = "6ef4f0658ff7bb880fc3ae0cf7db3b2a"

SCHEME_BODY = "body-signatures"
SCHEME_HEADER = "header-signatures"


def compute(secret: str, timestamp: str, payload: str) -> str:
    """md5(secret + "." + timestamp + "." + payload).

    MD5, not HMAC. Weak by modern standards, but it is what Cardly implements.
    """
    return hashlib.md5(f"{secret}.{timestamp}.{payload}".encode()).hexdigest()


def _compute_bytes(secret: str, timestamp: str, payload: bytes) -> str:
    return hashlib.md5(f"{secret}.{timestamp}.".encode() + payload).hexdigest()


def extract_raw_property(raw: bytes, name: str) -> bytes | None:
    """Return the raw byte slice of a TOP-LEVEL property's value.

    Cardly signs the payload as transmitted. Re-serializing with json.dumps
    changes key order and whitespace and silently breaks the hash, so we slice
    the original bytes instead.

    Depth-aware: a nested {"outer": {"data": ...}} must not be mistaken for the
    root "data". String contents (including braces and escaped quotes) are
    skipped rather than parsed.
    """
    text = raw.decode("utf-8", errors="replace")
    depth = 0
    index = 0
    length = len(text)
    target = f'"{name}"'

    while index < length:
        char = text[index]

        if char == '"':
            start = index
            index += 1
            while index < length:
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == '"':
                    break
                index += 1
            token = text[start : index + 1]
            index += 1
            # Only a key at depth 1 (directly inside the root object) counts.
            if depth == 1 and token == target:
                while index < length and text[index] in " \t\r\n":
                    index += 1
                if index < length and text[index] == ":":
                    index += 1
                    while index < length and text[index] in " \t\r\n":
                        index += 1
                    return _slice_value(text, index)
            continue

        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        index += 1

    return None


def _slice_value(text: str, start: int) -> bytes | None:
    """Slice one JSON value beginning at `start`, preserving it byte for byte."""
    if start >= len(text):
        return None
    char = text[start]
    if char in "{[":
        depth = 0
        index = start
        while index < len(text):
            current = text[index]
            if current == '"':
                index += 1
                while index < len(text):
                    if text[index] == "\\":
                        index += 2
                        continue
                    if text[index] == '"':
                        break
                    index += 1
            elif current in "{[":
                depth += 1
            elif current in "}]":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1].encode()
            index += 1
        return None
    # Scalar: run to the next delimiter.
    index = start
    while index < len(text) and text[index] not in ",}]":
        index += 1
    return text[start:index].strip().encode()


@dataclass(frozen=True)
class VerifyResult:
    matched: bool
    scheme: str | None = None
    tried: list[str] = field(default_factory=list)
    reason: str | None = None


def _matches_any(candidates: Any, digest: str) -> bool:
    if isinstance(candidates, str):
        candidates = [candidates]
    if not isinstance(candidates, list):
        return False
    # A match against ANY entry passes. Constant-time compare.
    return any(
        isinstance(entry, str) and hmac.compare_digest(entry.strip(), digest)
        for entry in candidates
    )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    return lowered.get(name.lower())


def verify(
    raw_body: bytes, secret: str, *, headers: Mapping[str, str] | None = None
) -> VerifyResult:
    """Verify a Cardly postback signature, trying both documented schemes.

    Cardly's docs describe two mutually exclusive schemes and share one golden
    vector between them, so the vector cannot tell them apart and neither has
    been confirmed against a live postback. Rather than pick one and be wrong
    half the time, try whichever the available inputs permit and report which
    matched — that answer is the thing worth learning.

    Fails closed: any parse failure, missing input, or empty secret is a
    non-match.
    """
    tried: list[str] = []
    if not secret:
        return VerifyResult(False, None, tried, "No secret supplied.")

    # Scheme A: timestamp + data from the BODY, matched against body.signatures.
    try:
        body = json.loads(raw_body)
    except (ValueError, TypeError):
        body = None

    if isinstance(body, dict) and "signatures" in body and "timestamp" in body:
        tried.append(SCHEME_BODY)
        raw_data = extract_raw_property(raw_body, "data")
        if raw_data is not None:
            digest = _compute_bytes(secret, str(body["timestamp"]), raw_data)
            if _matches_any(body.get("signatures"), digest):
                return VerifyResult(True, SCHEME_BODY, tried)

    # Scheme B: timestamp from the Cardly-Timestamp header, payload is the RAW
    # body, matched against the Cardly-Signatures header.
    if headers:
        timestamp = _header(headers, "Cardly-Timestamp")
        raw_signatures = _header(headers, "Cardly-Signatures")
        if timestamp and raw_signatures:
            tried.append(SCHEME_HEADER)
            try:
                candidates = json.loads(raw_signatures)
            except (ValueError, TypeError):
                candidates = raw_signatures
            digest = _compute_bytes(secret, timestamp, raw_body)
            if _matches_any(candidates, digest):
                return VerifyResult(True, SCHEME_HEADER, tried)

    if not tried:
        reason = (
            "No signature material found. Expected either a body with "
            "`timestamp`/`data`/`signatures`, or Cardly-Timestamp and "
            "Cardly-Signatures headers."
        )
    else:
        reason = (
            f"No signature matched. Tried: {', '.join(tried)}. Cardly documents "
            f"two schemes; if the postback is genuine, the other scheme may be "
            f"live — please report which one worked."
        )
    return VerifyResult(False, None, tried, reason)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_signature.py -q`
Expected: PASS (19 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/signature.py tests/test_signature.py
git commit -m "feat: add dual-scheme postback signature verification"
```

---

### Task 17: `webhooks`

**Files:**
- Create: `src/cardly_cli/models/webhook.py`, `src/cardly_cli/commands/webhooks.py`
- Modify: `src/cardly_cli/__main__.py`
- Test: `tests/test_cmd_webhooks.py`

**Interfaces:**
- Consumes: `CardlyModel`, `verify`/`VerifyResult` (Task 16), `load_data`, `parse_fields`, pagination.
- Produces: `Webhook(CardlyModel)`, `EVENTS: tuple[str, ...]`, `WEBHOOK_LIMIT = 10`. `webhooks_app: typer.Typer` with `list`, `get`, `create`, `update`, `delete`, `verify`.

**Context:**
- **Nine events**, validated client-side against `EVENTS` so a typo fails locally.
- **The `secret` is returned only at creation.** Surface it prominently — the only recovery from losing it is delete + recreate. Print it to stderr as a warning even in `--json` mode, so a piped invocation still shows it.
- **Update requires `--target-url`** even when only toggling `--disabled`; the API marks it required.
- **`protected` webhooks** were created by Zapier etc. — warn before clobbering.
- **Limit of 10** active-or-disabled webhooks (Zapier-created excluded). Surface a hint on the relevant failure rather than counting client-side.
- **`verify` reads a postback body** from a file/stdin plus `--secret`, optional `--header` pairs, and reports which scheme matched. Exit 0 on match, 1 on no match.

- [ ] **Step 1: Write the failing test**

`tests/test_cmd_webhooks.py`:

```python
import hashlib
import json

import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


@respx.mock
def test_webhooks_list():
    respx.get("https://api.card.ly/v2/webhooks").mock(
        return_value=httpx.Response(
            200,
            json=ok({"meta": {"totalRecords": 1}, "results": [{"id": "w1", "status": "active"}]}),
        )
    )
    result = runner.invoke(app, ["--json", "webhooks", "list"], env=ENV)
    assert json.loads(result.stdout)[0]["id"] == "w1"


@respx.mock
def test_webhooks_create_sends_target_url_and_events():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "w1", "secret": "sh-abc"}))

    respx.post("https://api.card.ly/v2/webhooks").mock(side_effect=handler)
    result = runner.invoke(
        app,
        [
            "webhooks", "create", "--target-url", "https://x.test/hook",
            "--event", "contact.order.sent", "--event", "qrCode.scanned",
            "--description", "prod", "--metadata", "team=growth",
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"]["targetUrl"] == "https://x.test/hook"
    assert captured["body"]["events"] == ["contact.order.sent", "qrCode.scanned"]
    assert captured["body"]["description"] == "prod"
    assert captured["body"]["metadata"] == {"team": "growth"}


def test_webhooks_create_rejects_unknown_event():
    result = runner.invoke(
        app, ["webhooks", "create", "--target-url", "https://x.test", "--event", "banana"], env=ENV
    )
    assert result.exit_code == 2
    assert "banana" in result.stderr


@respx.mock
def test_webhooks_create_surfaces_the_secret_prominently():
    respx.post("https://api.card.ly/v2/webhooks").mock(
        return_value=httpx.Response(200, json=ok({"id": "w1", "secret": "sh-once-only"}))
    )
    result = runner.invoke(
        app,
        ["--json", "webhooks", "create", "--target-url", "https://x.test", "--event", "qrCode.scanned"],
        env=ENV,
    )
    assert result.exit_code == 0
    # Returned only at creation — must be visible even when stdout is piped JSON.
    assert "sh-once-only" in result.stderr
    assert "only" in result.stderr.lower()


@respx.mock
def test_webhooks_update_uses_post_and_requires_target_url():
    route = respx.post("https://api.card.ly/v2/webhooks/w1").mock(
        return_value=httpx.Response(200, json=ok({"id": "w1"}))
    )
    # Cardly marks targetUrl required on update even when only toggling disabled.
    missing = runner.invoke(app, ["webhooks", "update", "w1", "--disabled"], env=ENV)
    assert missing.exit_code == 2
    assert "--target-url" in missing.stderr

    result = runner.invoke(
        app, ["webhooks", "update", "w1", "--target-url", "https://x.test", "--disabled"], env=ENV
    )
    assert result.exit_code == 0
    assert route.calls.last.request.method == "POST"
    assert json.loads(route.calls.last.request.content)["disabled"] is True


@respx.mock
def test_webhooks_delete_warns_on_protected():
    respx.get("https://api.card.ly/v2/webhooks/w1").mock(
        return_value=httpx.Response(200, json=ok({"id": "w1", "protected": True}))
    )
    route = respx.delete("https://api.card.ly/v2/webhooks/w1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(app, ["webhooks", "delete", "w1", "--yes"], env=ENV)
    assert "protected" in result.stderr.lower()
    assert route.called


@respx.mock
def test_webhooks_delete_requires_confirmation():
    respx.get("https://api.card.ly/v2/webhooks/w1").mock(
        return_value=httpx.Response(200, json=ok({"id": "w1"}))
    )
    route = respx.delete("https://api.card.ly/v2/webhooks/w1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    runner.invoke(app, ["webhooks", "delete", "w1"], input="n\n", env=ENV)
    assert route.called is False


def _signed_body(secret="s3cret", timestamp="1700000000"):
    data = '{"event":"contact.order.sent"}'
    digest = hashlib.md5(f"{secret}.{timestamp}.{data}".encode()).hexdigest()
    return f'{{"timestamp":"{timestamp}","data":{data},"signatures":["{digest}"]}}'


def test_verify_matches_body_scheme_and_names_it(tmp_path):
    path = tmp_path / "postback.json"
    path.write_text(_signed_body())
    result = runner.invoke(app, ["webhooks", "verify", str(path), "--secret", "s3cret"])
    assert result.exit_code == 0
    assert "body-signatures" in result.stdout


def test_verify_reads_stdin(tmp_path):
    result = runner.invoke(
        app, ["webhooks", "verify", "-", "--secret", "s3cret"], input=_signed_body()
    )
    assert result.exit_code == 0


def test_verify_fails_closed_and_reports_schemes_tried(tmp_path):
    path = tmp_path / "postback.json"
    path.write_text(_signed_body())
    result = runner.invoke(app, ["webhooks", "verify", str(path), "--secret", "wrong"])
    assert result.exit_code == 1
    assert "body-signatures" in result.stderr


def test_verify_supports_header_scheme(tmp_path):
    secret, timestamp = "s3cret", "1700000000"
    raw = '{"event":"x"}'
    digest = hashlib.md5(f"{secret}.{timestamp}.".encode() + raw.encode()).hexdigest()
    path = tmp_path / "postback.json"
    path.write_text(raw)
    result = runner.invoke(
        app,
        [
            "webhooks", "verify", str(path), "--secret", secret,
            "--header", f"Cardly-Timestamp={timestamp}",
            "--header", f"Cardly-Signatures=[\"{digest}\"]",
        ],
    )
    assert result.exit_code == 0
    assert "header-signatures" in result.stdout


def test_verify_needs_no_api_key(tmp_path):
    # It's an offline utility; requiring credentials would be silly.
    path = tmp_path / "postback.json"
    path.write_text(_signed_body())
    result = runner.invoke(
        app, ["webhooks", "verify", str(path), "--secret", "s3cret"], env={"CARDLY_API_KEY": ""}
    )
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cmd_webhooks.py -q`
Expected: FAIL — no `webhooks` command

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/models/webhook.py`:

```python
from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel

EVENTS = (
    "contact.order.created",
    "contact.order.sent",
    "contact.order.refunded",
    "giftCard.redeemed",
    "qrCode.scanned",
    "contact.undeliverable",
    "contact.changeOfAddress",
    "consignment.undeliverable",
    "consignment.changeOfAddress",
)

# Cardly allows up to 10 active-or-disabled webhooks at a time (Zapier-created
# ones are excluded from the count).
WEBHOOK_LIMIT = 10


class Webhook(CardlyModel):
    id: Optional[str] = None
    # Returned ONLY at creation, never again. Losing it means delete+recreate.
    secret: Optional[str] = None
    status: Optional[str] = None
    # True when created by an integration (Zapier etc.) — don't clobber.
    protected: Optional[bool] = None
    targetUrl: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    events: Optional[list[str]] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
```

`src/cardly_cli/commands/webhooks.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

import typer

from cardly_cli.commands._helpers import load_data, parse_fields
from cardly_cli.errors import CardlyError
from cardly_cli.models.webhook import EVENTS, WEBHOOK_LIMIT, Webhook
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate
from cardly_cli.signature import verify as verify_signature

webhooks_app = typer.Typer(help="Manage webhooks and verify postback signatures.")

LIST_COLUMNS = ["id", "status", "targetUrl", "description", "protected"]


def _check_events(events: list[str]) -> None:
    unknown = [event for event in events if event not in EVENTS]
    if unknown:
        raise typer.BadParameter(
            f"Unknown event(s): {', '.join(unknown)}. Valid events: {', '.join(EVENTS)}"
        )


@webhooks_app.command("list")
def list_webhooks(
    ctx: typer.Context,
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
) -> None:
    """List webhooks."""
    state = ctx.obj
    client = state.client()
    if all_pages:
        items = list(paginate(client, "webhooks", limit=limit, warn=state.warn))
    else:
        items = extract_results(client.get("webhooks", params={"limit": limit}))
    state.emit([Webhook.model_validate(i) for i in items], columns=LIST_COLUMNS)


@webhooks_app.command("get")
def get(ctx: typer.Context, webhook_id: str = typer.Argument(...)) -> None:
    """Show one webhook."""
    state = ctx.obj
    state.emit(Webhook.model_validate(state.client().get(f"webhooks/{webhook_id}")))


@webhooks_app.command("create")
def create(
    ctx: typer.Context,
    target_url: str = typer.Option(..., "--target-url", help="HTTPS endpoint with valid SSL."),
    event: list[str] = typer.Option(..., "--event", help=f"Repeatable. One of: {', '.join(EVENTS)}"),
    description: Optional[str] = typer.Option(None, "--description"),
    metadata: list[str] = typer.Option([], "--metadata", help="key=value (repeatable)."),
    data: Optional[str] = typer.Option(None, "--data", "-d"),
) -> None:
    """Create a webhook. The secret is returned ONCE — save it now."""
    state = ctx.obj
    _check_events(event)
    body: dict[str, Any] = dict(load_data(data))
    body["targetUrl"] = target_url
    body["events"] = event
    if description:
        body["description"] = description
    meta = parse_fields(metadata)
    if meta:
        body["metadata"] = meta

    try:
        result = state.client().post("webhooks", json=body)
    except CardlyError as exc:
        if exc.status_code in (402, 422):
            raise CardlyError(
                f"{exc.format_message()} (Cardly allows up to {WEBHOOK_LIMIT} active or "
                f"disabled webhooks; delete one before adding another. Note that test_ "
                f"keys cannot create webhooks — a live_ key is required.)",
                status_code=exc.status_code,
            ) from exc
        raise

    secret = result.get("secret") if isinstance(result, dict) else None
    if secret:
        # Warn (stderr), not emit, so the secret is still visible when stdout is
        # piped JSON. Cardly returns it exactly once — there is no way to read it
        # back later; recovery means delete + recreate.
        state.warn(
            f"Webhook secret: {secret}\n"
            f"Save it now — Cardly returns the secret only at creation and it "
            f"cannot be retrieved later."
        )
    state.emit(Webhook.model_validate(result))


@webhooks_app.command("update")
def update(
    ctx: typer.Context,
    webhook_id: str = typer.Argument(...),
    target_url: Optional[str] = typer.Option(
        None, "--target-url", help="Required by the API even when only toggling --disabled."
    ),
    event: list[str] = typer.Option([], "--event"),
    description: Optional[str] = typer.Option(None, "--description"),
    metadata: list[str] = typer.Option([], "--metadata", help="key=value (repeatable)."),
    disabled: Optional[bool] = typer.Option(None, "--disabled/--enabled"),
    data: Optional[str] = typer.Option(None, "--data", "-d"),
) -> None:
    """Update a webhook. NOTE: Cardly uses POST here, not PUT/PATCH."""
    state = ctx.obj
    body: dict[str, Any] = dict(load_data(data))
    if target_url:
        body["targetUrl"] = target_url
    if not body.get("targetUrl"):
        # The API marks targetUrl required on update regardless of what else
        # changes, so catch it here rather than spend a round trip on a 422.
        raise typer.BadParameter(
            "--target-url is required on update (Cardly requires it even when only "
            "toggling --disabled)."
        )
    if event:
        _check_events(event)
        body["events"] = event
    if description:
        body["description"] = description
    meta = parse_fields(metadata)
    if meta:
        body["metadata"] = meta
    if disabled is not None:
        body["disabled"] = disabled
    state.emit(Webhook.model_validate(state.client().post(f"webhooks/{webhook_id}", json=body)))


@webhooks_app.command("delete")
def delete(
    ctx: typer.Context,
    webhook_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Delete a webhook."""
    state = ctx.obj
    client = state.client()
    existing = client.get(f"webhooks/{webhook_id}")
    if isinstance(existing, dict) and existing.get("protected"):
        state.warn(
            f"Webhook {webhook_id} is protected — it was created by an integration "
            f"(Zapier or similar). Deleting it may break that integration."
        )
    if not yes:
        typer.confirm(f"Delete webhook {webhook_id}?", abort=True)
    client.delete(f"webhooks/{webhook_id}")
    state.warn(f"Deleted webhook {webhook_id}.")


@webhooks_app.command("verify")
def verify(
    ctx: typer.Context,
    body: str = typer.Argument(..., help="Postback body: a file path, or - for stdin."),
    secret: str = typer.Option(..., "--secret", help="The webhook secret from creation."),
    header: list[str] = typer.Option(
        [], "--header", help="Request header key=value (repeatable), e.g. Cardly-Timestamp=..."
    ),
) -> None:
    """Verify a postback signature. Offline — no API key needed.

    Cardly documents two mutually exclusive signing schemes and shares one
    worked example between them, so neither can be confirmed from the docs
    alone. This tries whichever the inputs allow and reports which matched.
    """
    state = ctx.obj
    raw = sys.stdin.buffer.read() if body == "-" else Path(body).read_bytes()
    headers = parse_fields(header)
    result = verify_signature(raw, secret, headers=headers)
    if result.matched:
        typer.echo(f"Signature OK (scheme: {result.scheme})")
        return
    state.warn(f"Signature verification FAILED. {result.reason}")
    raise typer.Exit(code=1)
```

In `__main__.py`'s bottom import block:

```python
from cardly_cli.commands.webhooks import webhooks_app  # noqa: E402

app.add_typer(webhooks_app, name="webhooks")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cmd_webhooks.py -q`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/models/webhook.py src/cardly_cli/commands/webhooks.py \
        src/cardly_cli/__main__.py tests/test_cmd_webhooks.py
git commit -m "feat: add webhooks commands with dual-scheme verify"
```

---

### Task 18: `ref` and `art`

**Files:**
- Create: `src/cardly_cli/models/art.py`, `src/cardly_cli/commands/ref.py`, `src/cardly_cli/commands/art.py`
- Modify: `src/cardly_cli/__main__.py`
- Test: `tests/test_cmd_ref.py`, `tests/test_cmd_art.py`

**Interfaces:**
- Consumes: `CardlyModel`, pagination.
- Produces: `Art(CardlyModel)`. `ref_app: typer.Typer` with `fonts`, `writing-styles`, `doodles`, `templates`, `media`. `art_app: typer.Typer` with `list`, `get`.

**Context — two different "only mine" parameters, and mixing them up is the trap:**

- `ref` endpoints (`/fonts`, `/doodles`, `/media`) take **`organisationOnly`**. `/writing-styles` and `/templates` do **not** — don't expose the flag there.
- `/art` takes **`ownOnly`**. Different name, same idea.

`GET /art/{id}` accepts a **UUID or a slug**.

v0.1 is read-only for art. `upload`/`update`/`delete` are v0.2 — they need base64-embedded image payloads (`POST /art` is `application/json` with an `artwork` array of `{page, image}`, image being a base64 string), which deserves its own task and a body-size measurement.

- [ ] **Step 1: Write the failing tests**

`tests/test_cmd_ref.py`:

```python
import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


def ok(results):
    return {
        "state": {"status": "OK", "messages": [], "version": 1},
        "data": {"meta": {"totalRecords": len(results)}, "results": results},
    }


@pytest.mark.parametrize(
    "command,endpoint",
    [
        ("fonts", "fonts"),
        ("writing-styles", "writing-styles"),
        ("doodles", "doodles"),
        ("templates", "templates"),
        ("media", "media"),
    ],
)
@respx.mock
def test_ref_commands_hit_their_endpoints(command, endpoint):
    respx.get(f"https://api.card.ly/v2/{endpoint}").mock(
        return_value=httpx.Response(200, json=ok([{"id": "1", "name": "X"}]))
    )
    result = runner.invoke(app, ["--json", "ref", command], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["id"] == "1"


@pytest.mark.parametrize("command,endpoint", [("fonts", "fonts"), ("doodles", "doodles"), ("media", "media")])
@respx.mock
def test_organisation_only_supported_where_declared(command, endpoint):
    route = respx.get(f"https://api.card.ly/v2/{endpoint}").mock(
        return_value=httpx.Response(200, json=ok([]))
    )
    result = runner.invoke(app, ["--json", "ref", command, "--organisation-only"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.url.params["organisationOnly"] == "true"


@pytest.mark.parametrize("command", ["writing-styles", "templates"])
def test_organisation_only_absent_where_not_declared(command):
    # Only fonts, doodles and media declare organisationOnly.
    result = runner.invoke(app, ["ref", command, "--organisation-only"], env=ENV)
    assert result.exit_code == 2
    assert "no such option" in result.stderr.lower()
```

`tests/test_cmd_art.py`:

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


@respx.mock
def test_art_list():
    respx.get("https://api.card.ly/v2/art").mock(
        return_value=httpx.Response(
            200, json=ok({"meta": {"totalRecords": 1}, "results": [{"id": "a1", "name": "Thanks"}]})
        )
    )
    result = runner.invoke(app, ["--json", "art", "list"], env=ENV)
    assert json.loads(result.stdout)[0]["id"] == "a1"


@respx.mock
def test_art_list_own_only_uses_ownOnly_param():
    # /art uses ownOnly. The ref endpoints use organisationOnly. Different names.
    route = respx.get("https://api.card.ly/v2/art").mock(
        return_value=httpx.Response(200, json=ok({"meta": {"totalRecords": 0}, "results": []}))
    )
    result = runner.invoke(app, ["--json", "art", "list", "--own-only"], env=ENV)
    assert result.exit_code == 0
    params = route.calls.last.request.url.params
    assert params["ownOnly"] == "true"
    assert "organisationOnly" not in params


@respx.mock
def test_art_get_accepts_a_slug():
    respx.get("https://api.card.ly/v2/art/happy-birthday").mock(
        return_value=httpx.Response(200, json=ok({"id": "a1", "slug": "happy-birthday"}))
    )
    result = runner.invoke(app, ["--json", "art", "get", "happy-birthday"], env=ENV)
    assert json.loads(result.stdout)["slug"] == "happy-birthday"


def test_art_upload_is_not_in_v0_1():
    # Deferred to v0.2: POST /art is application/json with base64-embedded
    # images, which needs its own task and a body-size measurement.
    result = runner.invoke(app, ["art", "upload", "x.png"], env=ENV)
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cmd_ref.py tests/test_cmd_art.py -q`
Expected: FAIL — no `ref`/`art` commands

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/models/art.py`:

```python
from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel


class Art(CardlyModel):
    id: Optional[str] = None
    # /art/{id} accepts a UUID or a slug, and orders accept the same for
    # --artwork.
    slug: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    pages: Optional[Any] = None
    createdAt: Optional[str] = None
```

`src/cardly_cli/commands/ref.py`:

```python
from __future__ import annotations

from typing import Any

import typer

from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

ref_app = typer.Typer(help="Reference data: fonts, writing styles, doodles, templates, media.")

COLUMNS = ["id", "name", "type"]


def _fetch(ctx: typer.Context, endpoint: str, all_pages: bool, limit: int, params: dict[str, Any]) -> None:
    state = ctx.obj
    client = state.client()
    if all_pages:
        items = list(paginate(client, endpoint, params=params, limit=limit, warn=state.warn))
    else:
        items = extract_results(client.get(endpoint, params={**params, "limit": limit}))
    state.emit(items, columns=COLUMNS)


ALL = typer.Option(False, "--all", help="Fetch all pages.")
LIMIT = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size.")
# Only /fonts, /doodles and /media declare organisationOnly. /writing-styles and
# /templates do not, so the flag is deliberately absent from those two.
ORG_ONLY = typer.Option(False, "--organisation-only", help="Only your organisation's items.")


@ref_app.command("fonts")
def fonts(ctx: typer.Context, organisation_only: bool = ORG_ONLY, all_pages: bool = ALL, limit: int = LIMIT) -> None:
    """List available fonts."""
    params = {"organisationOnly": "true"} if organisation_only else {}
    _fetch(ctx, "fonts", all_pages, limit, params)


@ref_app.command("writing-styles")
def writing_styles(ctx: typer.Context, all_pages: bool = ALL, limit: int = LIMIT) -> None:
    """List handwriting styles. (No organisationOnly filter on this endpoint.)"""
    _fetch(ctx, "writing-styles", all_pages, limit, {})


@ref_app.command("doodles")
def doodles(ctx: typer.Context, organisation_only: bool = ORG_ONLY, all_pages: bool = ALL, limit: int = LIMIT) -> None:
    """List doodles."""
    params = {"organisationOnly": "true"} if organisation_only else {}
    _fetch(ctx, "doodles", all_pages, limit, params)


@ref_app.command("templates")
def templates(ctx: typer.Context, all_pages: bool = ALL, limit: int = LIMIT) -> None:
    """List templates. A template may carry a gift card (Template.giftCard)."""
    _fetch(ctx, "templates", all_pages, limit, {})


@ref_app.command("media")
def media(ctx: typer.Context, organisation_only: bool = ORG_ONLY, all_pages: bool = ALL, limit: int = LIMIT) -> None:
    """List media (card stock types)."""
    params = {"organisationOnly": "true"} if organisation_only else {}
    _fetch(ctx, "media", all_pages, limit, params)
```

`src/cardly_cli/commands/art.py`:

```python
from __future__ import annotations

import typer

from cardly_cli.models.art import Art
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

# v0.1 is read-only. upload/update/delete land in v0.2: POST /art and
# POST /art/{id} are application/json carrying an `artwork` array of
# {page, image} where image is a base64-encoded file — the only novel I/O path
# in the API, and worth its own task plus a body-size measurement.
art_app = typer.Typer(help="Browse artwork.")

LIST_COLUMNS = ["id", "slug", "name", "type"]


@art_app.command("list")
def list_art(
    ctx: typer.Context,
    own_only: bool = typer.Option(
        False, "--own-only", help="Only your own artwork. (This endpoint uses `ownOnly`.)"
    ),
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
) -> None:
    """List artwork."""
    state = ctx.obj
    # NOTE: /art uses `ownOnly`; the ref endpoints use `organisationOnly`.
    params = {"ownOnly": "true"} if own_only else {}
    client = state.client()
    if all_pages:
        items = list(paginate(client, "art", params=params, limit=limit, warn=state.warn))
    else:
        items = extract_results(client.get("art", params={**params, "limit": limit}))
    state.emit([Art.model_validate(i) for i in items], columns=LIST_COLUMNS)


@art_app.command("get")
def get(
    ctx: typer.Context,
    art_id: str = typer.Argument(..., help="Artwork UUID or slug, e.g. happy-birthday."),
) -> None:
    """Show one artwork by UUID or slug."""
    state = ctx.obj
    state.emit(Art.model_validate(state.client().get(f"art/{art_id}")))
```

In `__main__.py`'s bottom import block:

```python
from cardly_cli.commands.art import art_app  # noqa: E402
from cardly_cli.commands.ref import ref_app  # noqa: E402

app.add_typer(ref_app, name="ref")
app.add_typer(art_app, name="art")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cmd_ref.py tests/test_cmd_art.py -q`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/models/art.py src/cardly_cli/commands/ref.py \
        src/cardly_cli/commands/art.py src/cardly_cli/__main__.py \
        tests/test_cmd_ref.py tests/test_cmd_art.py
git commit -m "feat: add ref and art read commands"
```

---

### Task 19: `api` escape hatch

**Files:**
- Create: `src/cardly_cli/commands/api.py`
- Modify: `src/cardly_cli/__main__.py`
- Test: `tests/test_cmd_api.py`

**Interfaces:**
- Consumes: `load_data`, `parse_fields`, pagination.
- Produces: `register(app: typer.Typer) -> None`, `api_command(...)`.

**Context:** Mirrors loxo's `commands/api.py`, simplified: Cardly has one pagination scheme, so there's no `detect_scheme`. This is what makes v0.2's deferred endpoints (users, invitations, art writes) reachable today — `cardly api GET users` works before `cardly users list` exists.

Registered as a root-level command via `register(app)`, not `add_typer`.

- [ ] **Step 1: Write the failing test**

`tests/test_cmd_api.py`:

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


@respx.mock
def test_api_get_unwraps_envelope():
    respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(200, json=ok({"balance": 7}))
    )
    result = runner.invoke(app, ["--json", "api", "GET", "account/balance"], env=ENV)
    assert json.loads(result.stdout) == {"balance": 7}


@respx.mock
def test_api_reaches_endpoints_with_no_dedicated_command():
    # users/ is deferred to v0.2; the escape hatch reaches it today.
    respx.get("https://api.card.ly/v2/users").mock(
        return_value=httpx.Response(200, json=ok({"meta": {"totalRecords": 0}, "results": []}))
    )
    result = runner.invoke(app, ["--json", "api", "GET", "users"], env=ENV)
    assert result.exit_code == 0


@respx.mock
def test_api_sends_params_and_body():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=ok({"ok": True}))

    respx.post("https://api.card.ly/v2/orders/preview").mock(side_effect=handler)
    result = runner.invoke(
        app,
        ["api", "POST", "orders/preview", "-p", "x=1", "-d", '{"artwork": "a"}'],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"] == {"artwork": "a"}
    assert captured["params"] == {"x": "1"}


@respx.mock
def test_api_post_carries_idempotency_key():
    route = respx.post("https://api.card.ly/v2/echo").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    runner.invoke(app, ["api", "POST", "echo"], env=ENV)
    assert "Idempotency-Key" in route.calls.last.request.headers


@respx.mock
def test_api_all_paginates():
    responses = [
        httpx.Response(200, json=ok({"meta": {"totalRecords": 2, "limit": 1}, "results": [{"id": 1}]})),
        httpx.Response(200, json=ok({"meta": {"totalRecords": 2, "limit": 1}, "results": [{"id": 2}]})),
    ]
    respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    result = runner.invoke(app, ["--json", "api", "GET", "orders", "--all", "--limit", "1"], env=ENV)
    assert json.loads(result.stdout) == [{"id": 1}, {"id": 2}]


def test_api_all_rejects_non_get():
    result = runner.invoke(app, ["api", "POST", "orders", "--all"], env=ENV)
    assert result.exit_code == 2
    assert "GET" in result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cmd_api.py -q`
Expected: FAIL — no `api` command

- [ ] **Step 3: Write the implementation**

`src/cardly_cli/commands/api.py`:

```python
from __future__ import annotations

from typing import Optional

import typer

from cardly_cli.commands._helpers import load_data, parse_fields
from cardly_cli.pagination import DEFAULT_LIMIT, paginate


def register(app: typer.Typer) -> None:
    app.command(
        "api",
        help="Call any Cardly endpoint directly. Unofficial — not affiliated with Cardly.",
    )(api_command)


def api_command(
    ctx: typer.Context,
    method: str = typer.Argument(..., help="HTTP method: GET/POST/DELETE."),
    path: str = typer.Argument(..., help="Endpoint path, e.g. account/balance or orders/123."),
    param: list[str] = typer.Option([], "--param", "-p", help="Query param key=value (repeatable)."),
    data: Optional[str] = typer.Option(
        None, "--data", "-d", help="JSON body: inline, @file, or - for stdin."
    ),
    all_pages: bool = typer.Option(False, "--all", help="Auto-paginate (GET only)."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size when paginating."),
) -> None:
    """Escape hatch for endpoints without a dedicated command (e.g. users, invitations)."""
    state = ctx.obj
    params = parse_fields(param)
    body = load_data(data) or None
    client = state.client()

    if all_pages:
        if method.upper() != "GET":
            raise typer.BadParameter("--all only supports GET (pagination is GET-only).")
        state.emit(list(paginate(client, path, params=params, limit=limit, warn=state.warn)))
        return

    state.emit(client.request(method.upper(), path, params=params, json=body))
```

In `__main__.py`'s bottom import block:

```python
from cardly_cli.commands import api as _api_cmd  # noqa: E402

_api_cmd.register(app)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cmd_api.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cardly_cli/commands/api.py src/cardly_cli/__main__.py tests/test_cmd_api.py
git commit -m "feat: add generic api escape hatch"
```

---

### Task 20: Smoke test, README, LICENSE, CI

**Files:**
- Create: `tests/test_smoke.py`, `tests/conftest.py`, `README.md`, `LICENSE`, `.github/workflows/ci.yml`, `.github/workflows/publish.yml`, `CHANGELOG.md`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: the whole app.
- Produces: no new code interfaces.

**Context:** The smoke test asserts the command tree is wired and that the deliberate *absences* stay absent — those are load-bearing facts about Cardly, not oversights, and a future contributor "helpfully" adding `lists update` should get a red test.

`tests/conftest.py` stays empty (loxo's is too) — it exists so pytest roots correctly.

The README must record the **known-unverified** items honestly. Mocked tests confirm we send what we *believe*; they cannot confirm the belief. Passing CI must not imply we checked.

`CHANGELOG.md` — copy loxo-cli's format. Read it first.

- [ ] **Step 1: Write the failing test**

`tests/conftest.py`: empty file.

`tests/test_smoke.py`:

```python
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}

EXPECTED_GROUPS = [
    "account", "api", "art", "configure", "contacts", "echo",
    "lists", "orders", "ref", "webhooks",
]


def test_help_lists_every_v0_1_group():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for group in EXPECTED_GROUPS:
        assert group in result.stdout, f"missing command group: {group}"


def test_every_group_help_renders():
    for group in EXPECTED_GROUPS:
        if group == "api":
            continue  # root-level command, not a group
        result = runner.invoke(app, [group, "--help"])
        assert result.exit_code == 0, f"{group} --help failed"


def test_v0_2_groups_are_absent():
    # users/invitations are deferred to v0.2; reachable today via `cardly api`.
    result = runner.invoke(app, ["--help"])
    assert "users" not in result.stdout
    assert "invitations" not in result.stdout


def test_deliberate_absences_stay_absent():
    # Each of these reflects a fact about Cardly's API, not an oversight.
    # No contact-list update endpoint exists.
    assert runner.invoke(app, ["lists", "update", "L1"], env=ENV).exit_code != 0
    # No order cancel endpoint exists (portal-only).
    assert runner.invoke(app, ["orders", "cancel", "o1"], env=ENV).exit_code != 0


def test_unofficial_disclaimer_present():
    result = runner.invoke(app, ["--help"])
    assert "Unofficial" in result.stdout or "not affiliated" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_smoke.py -q`
Expected: PASS or FAIL depending on prior tasks; if any group is missing, fix the registration in `__main__.py`.

- [ ] **Step 3: Write README, LICENSE, CHANGELOG and CI**

`README.md`:

````markdown
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

Rather than storing the key on disk, point a profile at any command that prints it:

```bash
cardly configure set prod --api-key-cmd 'your-secret-tool read cardly/api-key'
```

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

Global flags: `--json`, `--jq`, `--quiet`, `--verbose`, `--no-color`, `--profile`,
`--base-url`, `--no-retry`, `--max-retries`, `--idempotency-key`.

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
the live API:

- **Which webhook signature scheme is live.** Both are documented; both cite the same
  worked example. `webhooks verify` tries both and reports the winner.
- **Pagination on `/contact-lists`, `/contact-lists/{id}/contacts` and `/webhooks`.**
  `limit`/`offset` are documented in prose but declared on no list endpoint in
  Cardly's OpenAPI spec. We send them anyway and page defensively — advancing by the
  returned page size, warning if the server clamps `limit`, and stopping if an
  endpoint appears to ignore `offset`.
- **Whether credit-history accepts date-only filters.** We pad to midnight rather
  than find out in production.
- **Rate limits.** A 429 exists; no numbers and no `RateLimit-*` headers are
  documented. We back off adaptively.

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
````

`LICENSE`: MIT, copyright 2026. Copy `/Users/azweibel/Documents/code-projects/loxo-cli/LICENSE` and update the year/holder if needed.

`CHANGELOG.md`: read loxo-cli's for the format, then:

```markdown
# Changelog

## 0.1.0 — 2026-07-15

Initial release. Unofficial CLI for the Cardly API v2.

- `orders` — place, preview (with `--download` proof PDF), get, list
- `contacts` — create, sync, get, list, find, update, delete, delete-all
- `lists` — list, get, create, delete
- `webhooks` — list, get, create, update, delete, and dual-scheme `verify`
- `account` — balance, credit-history, gift-credit-history
- `ref` — fonts, writing-styles, doodles, templates, media
- `art` — list, get
- `echo`, `configure`, and a generic `api` escape hatch
- Idempotency keys on every POST; retry on 429/5xx and POST timeouts
- Exit code 8 for 402 insufficient credit
```

`.github/workflows/ci.yml` — copy loxo-cli's verbatim; it needs no changes:

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v8.2.0
        with:
          python-version: ${{ matrix.python-version }}
      - run: uv sync --all-extras --dev
      - run: uv run ruff check src tests
      - run: uv run black --check src tests
      - run: uv run mypy
      - run: uv run pytest -q
```

`.github/workflows/publish.yml` — copy loxo-cli's verbatim (trusted publishing via OIDC):

```yaml
name: Publish
on:
  push:
    tags: ["v*"]
jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write   # trusted publishing (OIDC)
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v8.2.0
        with:
          python-version: "3.12"
      - run: uv build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 4: Run the full suite and all linters**

```bash
uv run pytest -q
uv run ruff check src tests
uv run black --check src tests
uv run mypy
```

Expected: all green. Fix anything that isn't before committing.

- [ ] **Step 5: Verify no 1Password coupling leaked into the repo**

```bash
! grep -ril --exclude-dir=.git -e 'op://' -e '1password' -e 'onepassword' . && echo "CLEAN"
```

Expected: `CLEAN`. Any hit is a Global Constraint violation — remove it.

- [ ] **Step 6: Commit**

```bash
git add README.md LICENSE CHANGELOG.md .github tests/test_smoke.py tests/conftest.py
git commit -m "docs: add README, changelog, license and CI"
```

---

## Definition of done (v0.1)

- [ ] `uv run pytest -q` — all green, no network access
- [ ] `uv run ruff check src tests && uv run black --check src tests && uv run mypy` — clean
- [ ] `grep -ril -e 'op://' -e '1password' .` returns nothing
- [ ] `cardly --help` lists all ten v0.1 groups
- [ ] `cardly echo` works against a real `test_` key (manual, outside the suite)
- [ ] README's "Known-unverified" section is accurate

## Spec coverage check

| Spec section | Task |
|---|---|
| Architecture / module layout | 1–9 |
| Ported loxo features (`--base-url`, `--filter`, `CARDLY_PROFILE`, `--quiet`) | 2, 8, 9 |
| `build_payload` adapted unwrapped | 9 |
| Authentication (`API-Key`, `test_`/`live_`, `testMode`) | 5, 13 |
| Orders: shared builder, `lines[]` vs flat | 12, 13 |
| Orders: complete typed flags | 13 |
| Sender all-or-nothing; shipping gates | 12 |
| region/postcode NOT validated (orders + contacts) | 12, 14 |
| Preview: https upgrade, expiry, authed PDF | 13 |
| Not built: order cancel, gift-card flag | 13, 20 |
| Contacts: `locality` vs `city` split | 14 |
| Contacts: sync match key, duplicate→sync hint, POST update | 14 |
| Lists: no update endpoint | 15 |
| Artwork: `ownOnly`; base64 upload deferred | 18 |
| Webhooks: events, write-once secret, update needs targetUrl, `protected`, limit 10 | 17 |
| Signature: dual-scheme, golden vector, raw slice, depth-aware | 16 |
| Ref: `organisationOnly` on fonts/doodles/media only | 18 |
| Account: four dotted operators, date padding | 11 |
| Pagination: advance by `len(results)`, clamp warning, stall guard | 7 |
| Errors: exit codes incl. 402→8, 422 flattening | 1, 3, 5 |
| Idempotency: per-invocation key, POST timeout retry, cached replay | 4, 5 |
| Observability: `Request-Id`, never log headers | 5 |
| Testing: mocked only, no 1P | all; verified in 20 |
| Staging v0.1 / v0.2 | 18, 19, 20 |

## Deferred to v0.2

`users` (list/get/find/delete by id and by email), `invitations` (list/get/create/find/resend/delete ×2), `art upload/update/delete` (base64-embedded images; measure body size). All reachable via `cardly api` in the meantime.
