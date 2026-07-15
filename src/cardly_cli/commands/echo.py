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
