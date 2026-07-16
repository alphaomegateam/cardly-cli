from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Optional

import typer

from cardly_cli.commands._helpers import load_data, parse_fields
from cardly_cli.errors import CardlyError
from cardly_cli.models.webhook import EVENTS, WEBHOOK_LIMIT, Webhook
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate
from cardly_cli.signature import verify as verify_signature

webhooks_app = typer.Typer(help="Manage webhooks and verify postback signatures.")

LIST_COLUMNS = ["id", "status", "targetUrl", "description", "protected"]

# Matches webhook cap or test-key rejection errors. Webhook cap errors mention
# reaching a limit/max of webhooks. Test key errors mention that test keys
# cannot create webhooks or that a live key is required. A bare status_code==422
# match fires on any validation error (bad URL, oversized description, etc.),
# which would misdirect users with an irrelevant webhook-cap hint.
_WEBHOOK_CAP_OR_TEST_KEY_RE = re.compile(
    r"\b(webhook.*limit|webhook.*maximum|webhook.*active|test.*key|live.*key)",
    re.IGNORECASE,
)


def _check_events(events: list[str]) -> None:
    unknown = [event for event in events if event not in EVENTS]
    if unknown:
        raise typer.BadParameter(
            f"Unknown event(s): {', '.join(unknown)}. Valid events: {', '.join(EVENTS)}"
        )


@webhooks_app.command("list")
def list_webhooks(
    ctx: typer.Context,
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
) -> None:
    """List webhooks."""
    state = ctx.obj
    client = state.client()
    if all_pages:
        items = list(paginate(client, "webhooks", limit=limit))
    else:
        items = extract_results(client.get("webhooks", params={"limit": limit}))
    state.emit([Webhook.model_validate(i) for i in items], columns=LIST_COLUMNS)


@webhooks_app.command("get")
def get(ctx: typer.Context, webhook_id: str = typer.Argument(...)) -> None:
    """Show one webhook."""
    state = ctx.obj
    state.emit(Webhook.model_validate(state.client().get(f"webhooks/{webhook_id}")))


@webhooks_app.command("create")
def create(
    ctx: typer.Context,
    target_url: str = typer.Option(..., "--target-url", help="HTTPS endpoint with valid SSL."),
    event: list[str] = typer.Option(
        ..., "--event", help=f"Repeatable. One of: {', '.join(EVENTS)}"
    ),
    description: Optional[str] = typer.Option(None, "--description"),
    metadata: list[str] = typer.Option([], "--metadata", help="key=value (repeatable)."),
    data: Optional[str] = typer.Option(None, "--data", "-d"),
) -> None:
    """Create a webhook. The secret is returned ONCE — save it now."""
    state = ctx.obj
    _check_events(event)
    body: dict[str, Any] = dict(load_data(data))
    body["targetUrl"] = target_url
    body["events"] = event
    if description:
        body["description"] = description
    meta = parse_fields(metadata)
    if meta:
        # Reject repeated metadata keys: parse_fields merges them into a list,
        # but Cardly's metadata is a key-value object of scalars.
        for key, value in meta.items():
            if isinstance(value, list):
                raise typer.BadParameter(
                    f"--metadata key {key!r} is repeated; each key must appear at most once."
                )
        body["metadata"] = meta

    try:
        result = state.client().post("webhooks", json=body)
    except CardlyError as exc:
        # Only append the webhook cap/test-key hint for 422s that specifically
        # mention those cases. A bare status_code==422 match would fire on any
        # validation error (bad URL, oversized description, etc.) and misdirect
        # users. The server's message must come through clean if we can't
        # confidently identify it as the cap/test-key case.
        if exc.status_code == 422 and _WEBHOOK_CAP_OR_TEST_KEY_RE.search(str(exc)):
            raise CardlyError(
                f"{exc.format_message()} (Cardly allows up to {WEBHOOK_LIMIT} active or "
                f"disabled webhooks; delete one before adding another. Note that test_ "
                f"keys cannot create webhooks — a live_ key is required.)",
                status_code=exc.status_code,
            ) from exc
        raise

    secret = result.get("secret") if isinstance(result, dict) else None
    if secret:
        # Warn (stderr), not emit, so the secret is still visible when stdout is
        # piped JSON. Cardly returns it exactly once — there is no way to read it
        # back later; recovery means delete + recreate.
        state.warn(
            f"Webhook secret: {secret}\n"
            f"Save it now — Cardly returns the secret only at creation and it "
            f"cannot be retrieved later."
        )
    state.emit(Webhook.model_validate(result))


@webhooks_app.command("update")
def update(
    ctx: typer.Context,
    webhook_id: str = typer.Argument(...),
    target_url: Optional[str] = typer.Option(
        None, "--target-url", help="Required by the API even when only toggling --disabled."
    ),
    event: list[str] = typer.Option([], "--event"),
    description: Optional[str] = typer.Option(None, "--description"),
    metadata: list[str] = typer.Option([], "--metadata", help="key=value (repeatable)."),
    disabled: Optional[bool] = typer.Option(None, "--disabled/--enabled"),
    data: Optional[str] = typer.Option(None, "--data", "-d"),
) -> None:
    """Update a webhook. NOTE: Cardly uses POST here, not PUT/PATCH."""
    state = ctx.obj
    body: dict[str, Any] = dict(load_data(data))
    if target_url:
        body["targetUrl"] = target_url
    if not body.get("targetUrl"):
        # The API marks targetUrl required on update regardless of what else
        # changes, so catch it here rather than spend a round trip on a 422.
        raise typer.BadParameter(
            "--target-url is required on update (Cardly requires it even when only "
            "toggling --disabled)."
        )
    if event:
        _check_events(event)
        body["events"] = event
    if description:
        body["description"] = description
    meta = parse_fields(metadata)
    if meta:
        # Reject repeated metadata keys: parse_fields merges them into a list,
        # but Cardly's metadata is a key-value object of scalars.
        for key, value in meta.items():
            if isinstance(value, list):
                raise typer.BadParameter(
                    f"--metadata key {key!r} is repeated; each key must appear at most once."
                )
        body["metadata"] = meta
    if disabled is not None:
        body["disabled"] = disabled
    state.emit(Webhook.model_validate(state.client().post(f"webhooks/{webhook_id}", json=body)))


@webhooks_app.command("delete")
def delete(
    ctx: typer.Context,
    webhook_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation."),
) -> None:
    """Delete a webhook."""
    state = ctx.obj
    client = state.client()
    existing = client.get(f"webhooks/{webhook_id}")
    if isinstance(existing, dict) and existing.get("protected"):
        state.warn(
            f"Webhook {webhook_id} is protected — it was created by an integration "
            f"(Zapier or similar). Deleting it may break that integration."
        )
    if not yes:
        typer.confirm(f"Delete webhook {webhook_id}?", abort=True)
    client.delete(f"webhooks/{webhook_id}")
    state.warn(f"Deleted webhook {webhook_id}.")


@webhooks_app.command("verify")
def verify(
    ctx: typer.Context,
    body: str = typer.Argument(..., help="Postback body: a file path, or - for stdin."),
    secret: str = typer.Option(..., "--secret", help="The webhook secret from creation."),
    header: list[str] = typer.Option(
        [], "--header", help="Request header key=value (repeatable), e.g. Cardly-Timestamp=..."
    ),
) -> None:
    """Verify a postback signature. Offline — no API key needed.

    Cardly documents two mutually exclusive signing schemes and shares one
    worked example between them, so neither can be confirmed from the docs
    alone. This tries whichever the inputs allow and reports which matched.
    """
    state = ctx.obj
    try:
        raw = sys.stdin.buffer.read() if body == "-" else Path(body).read_bytes()
    except OSError as exc:
        raise typer.BadParameter(f"Cannot read {body!r}: {exc}") from exc
    headers = parse_fields(header)
    result = verify_signature(raw, secret, headers=headers)
    if result.matched:
        typer.echo(f"Signature OK (scheme: {result.scheme})")
        return
    state.warn(f"Signature verification FAILED. {result.reason}")
    raise typer.Exit(code=1)
