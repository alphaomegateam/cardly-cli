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
