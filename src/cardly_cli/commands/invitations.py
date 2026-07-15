from __future__ import annotations

import typer

from cardly_cli.models.invitation import Invitation
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

invitations_app = typer.Typer(help="Manage user invitations.")

LIST_COLUMNS = ["id", "email", "status", "invited", "expires"]


@invitations_app.command("list")
def list_invitations(
    ctx: typer.Context,
    include_accepted: bool = typer.Option(
        False,
        "--include-accepted",
        help="Include accepted invitations. Cardly filters them out by default.",
    ),
    accepted_only: bool = typer.Option(False, "--accepted-only", help="Only accepted invitations."),
    expired_only: bool = typer.Option(False, "--expired-only", help="Only expired invitations."),
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
) -> None:
    """List invitations.

    NOTE: Cardly filters ACCEPTED invitations out of this listing by default —
    an invite you know was accepted will not appear unless you pass
    --include-accepted (or --accepted-only).
    """
    state = ctx.obj
    params: dict[str, str] = {}
    if include_accepted:
        params["includeAccepted"] = "true"
    if accepted_only:
        params["acceptedOnly"] = "true"
    if expired_only:
        params["expiredOnly"] = "true"
    client = state.client()
    if all_pages:
        items = list(paginate(client, "invitations", params=params, limit=limit, warn=state.warn))
    else:
        items = extract_results(client.get("invitations", params={**params, "limit": limit}))
    state.emit([Invitation.model_validate(i) for i in items], columns=LIST_COLUMNS)


@invitations_app.command("get")
def get(ctx: typer.Context, invitation_id: str = typer.Argument(...)) -> None:
    """Show one invitation."""
    state = ctx.obj
    state.emit(Invitation.model_validate(state.client().get(f"invitations/{invitation_id}")))


@invitations_app.command("find")
def find(
    ctx: typer.Context,
    email: str = typer.Option(..., "--email", help="Email address to search for."),
) -> None:
    """Find an invitation by email."""
    state = ctx.obj
    result = state.client().get("invitations/find", params={"email": email})
    state.emit(Invitation.model_validate(result))
