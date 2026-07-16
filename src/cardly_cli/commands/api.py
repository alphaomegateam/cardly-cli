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
    method: str = typer.Argument(
        ...,
        help="HTTP method: GET/POST/DELETE. Cardly has no PUT, but this escape hatch does "
        "not police verbs — anything else is passed through as-is.",
    ),
    path: str = typer.Argument(..., help="Endpoint path, e.g. account/balance or orders/123."),
    param: list[str] = typer.Option(
        [], "--param", "-p", help="Query param key=value (repeatable)."
    ),
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

    if all_pages:
        if method.upper() != "GET":
            raise typer.BadParameter("--all only supports GET (pagination is GET-only).")
        client = state.client()
        state.emit(list(paginate(client, path, params=params, limit=limit)))
        return

    client = state.client()
    state.emit(client.request(method.upper(), path, params=params, json=body))
