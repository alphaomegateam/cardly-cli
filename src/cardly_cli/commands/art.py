from __future__ import annotations

from typing import Any, Optional

import typer

from cardly_cli.artwork import WARN_ENCODED_BYTES, build_artwork_pages, encoded_size
from cardly_cli.commands._helpers import load_data
from cardly_cli.models.art import Art
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

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
    data: Optional[str] = typer.Option(
        None, "--data", "-d", help="JSON body: inline, @file, or -."
    ),
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
    data: Optional[str] = typer.Option(
        None, "--data", "-d", help="JSON body: inline, @file, or -."
    ),
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
