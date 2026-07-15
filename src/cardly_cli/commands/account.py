from __future__ import annotations

from typing import Any, Optional

import typer

from cardly_cli.models.account import Balance, CreditEntry
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

account_app = typer.Typer(help="Account balance and credit history.")

HISTORY_COLUMNS = ["id", "effectiveTime", "amount", "balance", "description"]


def iso_to_cardly(value: str) -> str:
    """Convert an ISO datetime to Cardly's filter format.

    Cardly wants `YYYY-MM-DD HH:MM:SS` — a space, not an ISO `T`, truncated to
    second precision. A date-only value is padded to midnight: a bare
    `2026-07-01` would otherwise go out as a 10-char string and it is
    unconfirmed whether the API accepts that.
    """
    text = value.strip().replace("T", " ")
    if len(text) == 10:
        text = f"{text} 00:00:00"
    return text[:19]


def _time_params(
    after: Optional[str],
    before: Optional[str],
    after_exclusive: Optional[str],
    before_exclusive: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if after:
        params["effectiveTime.gte"] = iso_to_cardly(after)
    if before:
        params["effectiveTime.lte"] = iso_to_cardly(before)
    if after_exclusive:
        params["effectiveTime.gt"] = iso_to_cardly(after_exclusive)
    if before_exclusive:
        params["effectiveTime.lt"] = iso_to_cardly(before_exclusive)
    return params


@account_app.command("balance")
def balance(ctx: typer.Context) -> None:
    """Show credit and gift-credit balances."""
    state = ctx.obj
    state.emit(Balance.model_validate(state.client().get("account/balance")))


def _history(ctx: typer.Context, endpoint: str, all_pages: bool, limit: int, **times: Any) -> None:
    state = ctx.obj
    params = _time_params(**times)
    client = state.client()
    if all_pages:
        items = list(paginate(client, endpoint, params=params, limit=limit, warn=state.warn))
    else:
        params["limit"] = limit
        items = extract_results(client.get(endpoint, params=params))
    state.emit([CreditEntry.model_validate(i) for i in items], columns=HISTORY_COLUMNS)


AFTER = typer.Option(None, "--after", help="Inclusive lower bound (effectiveTime.gte).")
BEFORE = typer.Option(None, "--before", help="Inclusive upper bound (effectiveTime.lte).")
AFTER_X = typer.Option(None, "--after-exclusive", help="Exclusive lower bound (effectiveTime.gt).")
BEFORE_X = typer.Option(
    None, "--before-exclusive", help="Exclusive upper bound (effectiveTime.lt)."
)


@account_app.command("credit-history")
def credit_history(
    ctx: typer.Context,
    after: Optional[str] = AFTER,
    before: Optional[str] = BEFORE,
    after_exclusive: Optional[str] = AFTER_X,
    before_exclusive: Optional[str] = BEFORE_X,
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
) -> None:
    """List regular credit transactions."""
    _history(
        ctx,
        "account/credit-history",
        all_pages,
        limit,
        after=after,
        before=before,
        after_exclusive=after_exclusive,
        before_exclusive=before_exclusive,
    )


@account_app.command("gift-credit-history")
def gift_credit_history(
    ctx: typer.Context,
    after: Optional[str] = AFTER,
    before: Optional[str] = BEFORE,
    after_exclusive: Optional[str] = AFTER_X,
    before_exclusive: Optional[str] = BEFORE_X,
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
) -> None:
    """List gift-credit transactions (a separate balance from regular credit)."""
    _history(
        ctx,
        "account/gift-credit-history",
        all_pages,
        limit,
        after=after,
        before=before,
        after_exclusive=after_exclusive,
        before_exclusive=before_exclusive,
    )
