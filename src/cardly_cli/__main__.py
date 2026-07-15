from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console

from cardly_cli import __version__
from cardly_cli.client import CardlyClient, build_client
from cardly_cli.commands._app import CardlyGroup
from cardly_cli.config import CardlySettings, load_settings
from cardly_cli.output import render
from cardly_cli.retry import RetryPolicy

HELP_EPILOG = "Unofficial — not affiliated with Cardly."

app = typer.Typer(
    cls=CardlyGroup,
    help="cardly — command-line interface for the Cardly card-sending API.",
    epilog=HELP_EPILOG,
    no_args_is_help=True,
)


@dataclass
class AppState:
    profile: Optional[str]
    api_key: Optional[str]
    base_url: Optional[str]
    json_out: bool
    jq: Optional[str]
    quiet: bool
    verbose: bool
    no_color: bool
    no_retry: bool
    max_retries: int
    idempotency_key: Optional[str]
    config_path: Optional[Path] = None
    _settings: Optional[CardlySettings] = field(default=None, repr=False)

    def settings(self) -> CardlySettings:
        if self._settings is None:
            self._settings = load_settings(
                profile=self.profile,
                api_key=self.api_key,
                base_url=self.base_url,
                config_path=self.config_path,
            )
        return self._settings

    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(max_retries=self.max_retries, enabled=not self.no_retry)

    def client(self) -> CardlyClient:
        # One client per invocation => one idempotency key per invocation,
        # reused across that invocation's retries.
        return build_client(
            self.settings(),
            verbose=self.verbose,
            retry=self.retry_policy(),
            idempotency_key=self.idempotency_key,
        )

    def console(self) -> Console:
        # Disable color when the user asked (--no-color), when the NO_COLOR
        # convention is set (https://no-color.org/), or when stdout is not a
        # TTY (piped/redirected). The explicit isatty check is needed because
        # Rich forces color on when FORCE_COLOR is set even into a pipe.
        no_color = self.no_color or bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()
        return Console(no_color=no_color)

    def warn(self, message: str) -> None:
        if not self.quiet:
            typer.echo(message, err=True)

    def emit(self, data: Any, *, columns: list[str] | None = None) -> None:
        if self.quiet and not (self.json_out or self.jq):
            return
        render(
            data,
            as_json=self.json_out,
            jq=self.jq,
            columns=columns,
            console=self.console(),
        )


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Config profile."),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="Cardly API key."),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="API base URL."),
    config_path: Optional[Path] = typer.Option(None, "--config-path", help="Config file path."),
    json_out: bool = typer.Option(False, "--json", help="Force JSON output."),
    jq: Optional[str] = typer.Option(
        None,
        "--jq",
        help="Select part of the output by path, e.g. '.results' or "
        "'.results.0.id'. The leading '.' is optional ('results' works too).",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress non-error output."),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Log requests to stderr."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable color."),
    no_retry: bool = typer.Option(False, "--no-retry", help="Disable retry on 429/5xx/timeout."),
    max_retries: int = typer.Option(3, "--max-retries", help="Max retry attempts."),
    idempotency_key: Optional[str] = typer.Option(
        None,
        "--idempotency-key",
        help="Pin the Idempotency-Key sent on POSTs (default: a fresh UUID per invocation).",
    ),
) -> None:
    """cardly CLI. Unofficial — not affiliated with Cardly."""
    ctx.obj = AppState(
        profile=profile,
        api_key=api_key,
        base_url=base_url,
        config_path=config_path,
        json_out=json_out,
        jq=jq,
        quiet=quiet,
        verbose=verbose,
        no_color=no_color,
        no_retry=no_retry,
        max_retries=max_retries,
        idempotency_key=idempotency_key,
    )


# Sub-app registration is appended by later tasks. Imports live at the bottom to
# avoid circular imports; the E402 markers are intentional.
from cardly_cli.commands.echo import echo_app  # noqa: E402
from cardly_cli.commands.configure import configure_app  # noqa: E402
from cardly_cli.commands.account import account_app  # noqa: E402
from cardly_cli.commands.orders import orders_app  # noqa: E402
from cardly_cli.commands.contacts import contacts_app  # noqa: E402
from cardly_cli.commands.lists import lists_app  # noqa: E402
from cardly_cli.commands.webhooks import webhooks_app  # noqa: E402

app.add_typer(echo_app, name="echo")
app.add_typer(configure_app, name="configure")
app.add_typer(account_app, name="account")
app.add_typer(orders_app, name="orders")
app.add_typer(contacts_app, name="contacts")
app.add_typer(lists_app, name="lists")
app.add_typer(webhooks_app, name="webhooks")


def run() -> None:
    # Exit-code mapping happens in CardlyGroup.invoke (commands/_app.py, set via
    # typer.Typer(cls=CardlyGroup)): Typer does NOT honor a raised
    # ClickException's exit_code, so domain errors become typer.Exit with the
    # mapped code.
    app()


if __name__ == "__main__":
    run()
