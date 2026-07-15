from __future__ import annotations

from typing import Any, Optional

import typer

from cardly_cli.commands._helpers import load_data
from cardly_cli.models.invitation import PERMISSIONS, Invitation
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


def _check_permissions(values: list[str]) -> None:
    unknown = [v for v in values if v not in PERMISSIONS]
    if unknown:
        raise typer.BadParameter(
            f"Unknown permission(s): {', '.join(unknown)}. "
            f"Valid permissions: {', '.join(PERMISSIONS)}"
        )


@invitations_app.command("create")
def create(
    ctx: typer.Context,
    email: str = typer.Option(..., "--email", help="Email address to invite."),
    first_name: Optional[str] = typer.Option(None, "--first-name"),
    last_name: Optional[str] = typer.Option(None, "--last-name"),
    permission: list[str] = typer.Option(
        [], "--permission", help=f"Repeatable. One of: {', '.join(PERMISSIONS)}"
    ),
    data: Optional[str] = typer.Option(
        None, "--data", "-d", help="JSON body: inline, @file, or -."
    ),
) -> None:
    """Invite a user."""
    state = ctx.obj
    _check_permissions(permission)
    body: dict[str, Any] = dict(load_data(data))
    body["email"] = email
    if first_name:
        body["firstName"] = first_name
    if last_name:
        body["lastName"] = last_name
    if permission:
        body["permissions"] = permission
    # Validate whatever ended up in body: both --permission flags and --data paths.
    if "permissions" in body:
        perms = body["permissions"]
        if not isinstance(perms, list):
            raise typer.BadParameter("permissions must be a list")
        _check_permissions(perms)
    state.emit(Invitation.model_validate(state.client().post("invitations", json=body)))


@invitations_app.command("resend")
def resend(
    ctx: typer.Context,
    invitation_id: Optional[str] = typer.Argument(
        None, help="Invitation ID. Omit if using --email."
    ),
    email: Optional[str] = typer.Option(None, "--email", help="Resend by email instead of ID."),
) -> None:
    """Resend an invitation, by ID or by email.

    Cardly exposes two forms: POST /invitations/resend/{id} and POST
    /invitations/resend with an {"email": ...} body. Exactly one is required.
    """
    state = ctx.obj
    if bool(invitation_id) == bool(email):
        raise typer.BadParameter("Provide exactly one of INVITATION_ID or --email.")
    client = state.client()
    if invitation_id:
        result = client.post(f"invitations/resend/{invitation_id}")
    else:
        result = client.post("invitations/resend", json={"email": email})
    state.warn(f"Resent invitation to {invitation_id or email}.")
    # Deliberately unvalidated: this endpoint's response shape is UNVERIFIED and may
    # be empty, so Invitation.model_validate() could raise on a successful resend.
    # The warn() above is what the human actually needs.
    state.emit(result)


@invitations_app.command("delete")
def delete(
    ctx: typer.Context,
    invitation_id: Optional[str] = typer.Argument(
        None, help="Invitation ID. Omit if using --email."
    ),
    email: Optional[str] = typer.Option(None, "--email", help="Delete by email instead of ID."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Delete an invitation, by ID or by email.

    Two forms, as with resend: DELETE /invitations/{id} and DELETE /invitations
    with an {"email": ...} body. Exactly one is required.
    """
    state = ctx.obj
    if bool(invitation_id) == bool(email):
        raise typer.BadParameter("Provide exactly one of INVITATION_ID or --email.")
    target = invitation_id or email
    if not yes:
        typer.confirm(f"Delete invitation {target}?", abort=True)
    client = state.client()
    if invitation_id:
        client.delete(f"invitations/{invitation_id}")
    else:
        client.request("DELETE", "invitations", json={"email": email})
    state.warn(f"Deleted invitation {target}.")
