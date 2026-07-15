from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _stable_console_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make CLI output deterministic regardless of the developer's shell.

    Rich treats FORCE_COLOR as "this is a terminal" even when output is
    captured, and injects ANSI escapes that break substring assertions on
    --help text. Developer profiles commonly set it; CI usually doesn't, so
    without this the suite passes in CI and fails locally.

    Scope is deliberately narrow: strip only the force-color vars, which are
    the actual culprit. Setting NO_COLOR/TERM here instead would assert an
    opinion about what colour state every test runs under, and would silently
    mask a future test that means to verify colour IS emitted, or one
    exercising console()'s isatty branch.
    """
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
