from __future__ import annotations

from typing import Optional

import typer

from cardly_cli.models.user import User
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

users_app = typer.Typer(help="Manage users.")

LIST_COLUMNS = ["id", "firstName", "lastName", "email", "status"]


@users_app.command("list")
def list_users(
    ctx: typer.Context,
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
) -> None:
    """List users."""
    state = ctx.obj
    client = state.client()
    if all_pages:
        items = list(paginate(client, "users", limit=limit))
    else:
        items = extract_results(client.get("users", params={"limit": limit}))
    state.emit([User.model_validate(i) for i in items], columns=LIST_COLUMNS)


@users_app.command("get")
def get(ctx: typer.Context, user_id: str = typer.Argument(...)) -> None:
    """Show one user."""
    state = ctx.obj
    state.emit(User.model_validate(state.client().get(f"users/{user_id}")))


@users_app.command("find")
def find(
    ctx: typer.Context,
    email: str = typer.Option(..., "--email", help="Email address to search for."),
) -> None:
    """Find a user by email."""
    state = ctx.obj
    state.emit(User.model_validate(state.client().get("users/find", params={"email": email})))


@users_app.command("delete")
def delete(
    ctx: typer.Context,
    user_id: Optional[str] = typer.Argument(None, help="User ID. Omit if using --email."),
    email: Optional[str] = typer.Option(None, "--email", help="Delete by email instead of ID."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Delete a user, by ID or by email.

    Cardly exposes two delete forms: DELETE /users/{id} and DELETE /users with an
    {"email": ...} body. Exactly one is required — passing both is ambiguous about
    which record you mean, so it is rejected rather than guessed at.
    """
    state = ctx.obj
    if bool(user_id) == bool(email):
        raise typer.BadParameter("Provide exactly one of USER_ID or --email.")
    target = user_id or email
    if not yes:
        typer.confirm(f"Delete user {target}?", abort=True)
    client = state.client()
    if user_id:
        client.delete(f"users/{user_id}")
    else:
        client.request("DELETE", "users", json={"email": email})
    state.warn(f"Deleted user {target}.")
