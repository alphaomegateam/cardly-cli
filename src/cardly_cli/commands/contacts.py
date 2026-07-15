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
            externalId=external_id,
            firstName=first_name,
            lastName=last_name,
            email=email,
            company=company,
            address=address,
            address2=address2,
            locality=locality,
            region=region,
            postcode=postcode,
            country=country,
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
            externalId=external_id,
            firstName=first_name,
            lastName=last_name,
            email=email,
            company=company,
            address=address,
            address2=address2,
            locality=locality,
            region=region,
            postcode=postcode,
            country=country,
        ),
        field,
        data,
    )
    if not body.get("externalId") and not body.get("email"):
        # The match key IS the point of sync. Without one there's nothing to
        # match on, so fail here rather than spend a round trip learning that.
        raise typer.BadParameter("sync requires --external-id or --email as the match key.")
    state.emit(
        Contact.model_validate(
            state.client().post(f"contact-lists/{list_id}/contacts/sync", json=body)
        )
    )


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
            externalId=external_id,
            firstName=first_name,
            lastName=last_name,
            email=email,
            company=company,
            address=address,
            address2=address2,
            locality=locality,
            region=region,
            postcode=postcode,
            country=country,
        ),
        field,
        data,
    )
    result = state.client().post(f"contact-lists/{list_id}/contacts/{contact_id}", json=body)
    state.emit(Contact.model_validate(result))


@contacts_app.command("get")
def get(
    ctx: typer.Context,
    list_id: str = typer.Argument(...),
    contact_id: str = typer.Argument(...),
) -> None:
    """Show one contact."""
    state = ctx.obj
    state.emit(
        Contact.model_validate(state.client().get(f"contact-lists/{list_id}/contacts/{contact_id}"))
    )


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
