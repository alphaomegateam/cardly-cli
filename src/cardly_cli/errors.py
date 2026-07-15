from __future__ import annotations

import click

# Subclassing click.ClickException gives these errors an `.exit_code` and a
# `.format_message()`, and keeps them ordinary Exceptions so `pytest.raises`
# and the `.status_code`/`.is_4xx` predicates used by client.py keep working.
# NOTE: Typer's invocation path does NOT auto-honor a raised ClickException's
# exit_code (it surfaces as a generic exit 1). The exit-code mapping is applied
# by CardlyGroup.invoke in commands/_app.py (set on the root app via
# typer.Typer(cls=CardlyGroup)). `_cardly_exit_code` below remains the single
# source of the CardlyError mapping.


class ConfigError(click.ClickException):
    """Raised when credentials/profile resolution fails."""

    exit_code = 2


class CardlyError(click.ClickException):
    """Normalized error from a Cardly API call.

    status_code is None for network failures and timeouts.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        is_timeout: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.is_timeout = is_timeout
        self.exit_code = _cardly_exit_code(self)  # type: ignore[misc]

    @property
    def is_4xx(self) -> bool:
        return self.status_code is not None and 400 <= self.status_code < 500

    @property
    def is_5xx(self) -> bool:
        return self.status_code is not None and 500 <= self.status_code < 600


def _cardly_exit_code(err: "CardlyError") -> int:
    if err.is_timeout or err.status_code is None:
        return 7
    if err.status_code in (401, 403):
        return 3
    if err.status_code == 402:
        # Insufficient credit. Its own code because it is the one failure a
        # scheduled job must treat differently: not a bug, not transient,
        # retrying will never help — top up the account.
        return 8
    if err.status_code == 404:
        return 4
    if err.status_code == 429:
        return 5
    if err.is_5xx:
        return 6
    return 1


def exit_code_for(exc: BaseException) -> int:
    if isinstance(exc, click.ClickException):
        return exc.exit_code
    return 1
