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
