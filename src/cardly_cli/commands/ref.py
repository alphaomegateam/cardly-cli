from __future__ import annotations

from typing import Any

import typer

from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

ref_app = typer.Typer(help="Reference data: fonts, writing styles, doodles, templates, media.")

COLUMNS = ["id", "name", "type"]


def _fetch(
    ctx: typer.Context,
    endpoint: str,
    all_pages: bool,
    limit: int,
    params: dict[str, Any],
) -> None:
    state = ctx.obj
    client = state.client()
    if all_pages:
        items = list(paginate(client, endpoint, params=params, limit=limit))
    else:
        items = extract_results(client.get(endpoint, params={**params, "limit": limit}))
    state.emit(items, columns=COLUMNS)


ALL = typer.Option(False, "--all", help="Fetch all pages.")
LIMIT = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size.")
# Only /fonts, /doodles and /media declare organisationOnly. /writing-styles and
# /templates do not, so the flag is deliberately absent from those two.
ORG_ONLY = typer.Option(False, "--organisation-only", help="Only your organisation's items.")


@ref_app.command("fonts")
def fonts(
    ctx: typer.Context,
    organisation_only: bool = ORG_ONLY,
    all_pages: bool = ALL,
    limit: int = LIMIT,
) -> None:
    """List available fonts."""
    params = {"organisationOnly": "true"} if organisation_only else {}
    _fetch(ctx, "fonts", all_pages, limit, params)


@ref_app.command("writing-styles")
def writing_styles(ctx: typer.Context, all_pages: bool = ALL, limit: int = LIMIT) -> None:
    """List handwriting styles. (No organisationOnly filter on this endpoint.)"""
    _fetch(ctx, "writing-styles", all_pages, limit, {})


@ref_app.command("doodles")
def doodles(
    ctx: typer.Context,
    organisation_only: bool = ORG_ONLY,
    all_pages: bool = ALL,
    limit: int = LIMIT,
) -> None:
    """List doodles."""
    params = {"organisationOnly": "true"} if organisation_only else {}
    _fetch(ctx, "doodles", all_pages, limit, params)


@ref_app.command("templates")
def templates(ctx: typer.Context, all_pages: bool = ALL, limit: int = LIMIT) -> None:
    """List templates. A template may carry a gift card (Template.giftCard)."""
    _fetch(ctx, "templates", all_pages, limit, {})


@ref_app.command("media")
def media(
    ctx: typer.Context,
    organisation_only: bool = ORG_ONLY,
    all_pages: bool = ALL,
    limit: int = LIMIT,
) -> None:
    """List media (card stock types)."""
    params = {"organisationOnly": "true"} if organisation_only else {}
    _fetch(ctx, "media", all_pages, limit, params)
