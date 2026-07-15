from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _stable_console_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make CLI output deterministic regardless of the developer's shell.

    Rich treats FORCE_COLOR as "this is a terminal" even when output is
    captured, and injects ANSI escapes that break substring assertions on
    --help text. Developer profiles commonly set it; CI usually doesn't, so
    without this the suite passes in CI and fails locally.
    """
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
