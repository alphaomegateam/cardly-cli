from __future__ import annotations

from typing import Optional

import typer

from cardly_cli.config import DEFAULT_BASE_URL, config_file_path, list_profiles, write_profile

configure_app = typer.Typer(help="Manage config profiles. Unofficial — not affiliated with Cardly.")

KEY_CMD_HELP = (
    "Shell command that prints the API key on stdout. Any command works; "
    "the key is never stored in the config file."
)


@configure_app.command("set")
def set_profile(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Profile name, e.g. prod or sandbox."),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="API key to store."),
    api_key_cmd: Optional[str] = typer.Option(None, "--api-key-cmd", help=KEY_CMD_HELP),
    base_url: str = typer.Option(DEFAULT_BASE_URL, "--base-url", help="API base URL."),
    make_default: bool = typer.Option(False, "--default", help="Make this the default profile."),
) -> None:
    """Write a profile to the config file."""
    state = ctx.obj
    if bool(api_key) == bool(api_key_cmd):
        raise typer.BadParameter("Provide exactly one of --api-key or --api-key-cmd.")
    write_profile(
        name,
        api_key=api_key,
        api_key_cmd=api_key_cmd,
        base_url=base_url,
        make_default=make_default,
        config_path=state.config_path,
    )
    path = state.config_path or config_file_path()
    state.warn(f"Wrote profile '{name}' to {path}")


@configure_app.command("list")
def list_cmd(ctx: typer.Context) -> None:
    """List configured profiles. Never prints stored keys."""
    state = ctx.obj
    state.emit(list_profiles(config_path=state.config_path))
