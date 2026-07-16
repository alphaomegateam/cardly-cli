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
        if not name.strip():
            raise typer.BadParameter(f"--field name must not be empty, got {item!r}")
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
        items = list(paginate(client, "contact-lists", limit=limit))
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
    data: Optional[str] = typer.Option(
        None, "--data", "-d", help="JSON body: inline, @file, or -."
    ),
) -> None:
    """Create a contact list."""
    state = ctx.obj
    body: dict[str, Any] = dict(load_data(data))
    if name:
        body["name"] = name
    if description:
        body["description"] = description
    if not body.get("name"):
        raise typer.BadParameter("lists create requires --name (or a name in --data).")
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
