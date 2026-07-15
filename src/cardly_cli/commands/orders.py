from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import typer

from cardly_cli.commands._helpers import apply_filters, load_data, parse_fields
from cardly_cli.models.order import SHIPPING_METHODS, Order, build_line, check_shipping
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate

orders_app = typer.Typer(help="Place, preview and inspect orders.")

LIST_COLUMNS = ["id", "status", "origin"]


def _parse_message_pages(messages: list[str], message_pages: list[str]) -> list[tuple[int, str]]:
    """Positional --message, plus explicit --message-page N=text."""
    pages: list[tuple[int, str]] = [(i + 1, text) for i, text in enumerate(messages)]
    for item in message_pages:
        if "=" not in item:
            raise typer.BadParameter(f"--message-page must be N=text, got {item!r}")
        number, text = item.split("=", 1)
        if not number.strip().isdigit():
            raise typer.BadParameter(f"--message-page page must be an integer, got {number!r}")
        pages.append((int(number), text))
    return pages


def _typed_int(values: dict[str, Any], key: str) -> Any:
    raw = values.get(key)
    return int(raw) if raw is not None else None


def _upgrade_preview_urls(payload: Any) -> Any:
    """Force preview URLs to https.

    Cardly's schema examples (and responses) return http:// links for previews.
    They point at api.card.ly, not a pre-signed CDN link.
    """
    if not isinstance(payload, dict):
        return payload
    preview = payload.get("preview")
    if isinstance(preview, dict) and isinstance(preview.get("urls"), dict):
        preview["urls"] = {
            key: (value.replace("http://", "https://", 1) if isinstance(value, str) else value)
            for key, value in preview["urls"].items()
        }
    return payload


def _warn_test_mode(state: Any, payload: Any) -> None:
    if isinstance(payload, dict) and payload.get("testMode") is True:
        state.warn(
            "TEST MODE: this key validated the request but no card was sent and "
            "no credit was spent. Use a live_ key to place real orders."
        )


def _build(
    *,
    artwork,
    template,
    quantity,
    to,
    frm,
    messages,
    message_pages,
    variables,
    style,
    shipping,
    ship_to_me,
    requested_arrival,
    data,
) -> dict[str, Any]:
    check_shipping(shipping, to.get("country"))
    return build_line(
        artwork=artwork,
        template=template,
        quantity=quantity,
        recipient=to,
        sender=frm,
        messages=_parse_message_pages(messages, message_pages),
        variables=parse_fields(variables),
        style=parse_fields(style),
        shipping=shipping,
        ship_to_me=ship_to_me,
        requested_arrival=requested_arrival,
        data=data,
    )


ARTWORK = typer.Option(None, "--artwork", help="Artwork UUID or slug, e.g. happy-birthday.")
TEMPLATE = typer.Option(
    None, "--template", help="Template ID. Without it, no variable substitution."
)
QUANTITY = typer.Option(None, "--quantity", min=1, help="Copies of this card (default 1).")
SHIPPING = typer.Option(
    None,
    "--shipping",
    help="standard (all regions) | tracked (AU only) | express (AU and US only).",
)
SHIP_TO_ME = typer.Option(
    None, "--ship-to-me/--no-ship-to-me", help="Ship to sender; adds cost per card."
)
ARRIVAL = typer.Option(None, "--requested-arrival", help="Requested future arrival date.")
MESSAGE = typer.Option([], "--message", help="Message text; repeat for pages 1, 2, 3...")
MESSAGE_PAGE = typer.Option([], "--message-page", help="Explicit page: N=text (1 = front).")
VAR = typer.Option([], "--var", help="Template variable key=value (repeatable).")
STYLE = typer.Option([], "--style", help="Card style key=value: align, color, font, size...")
DATA = typer.Option(None, "--data", "-d", help="JSON body: inline, @file, or - for stdin.")


def _recipient(**kw: Any) -> dict[str, Any]:
    return kw


@orders_app.command("place")
def place(
    ctx: typer.Context,
    artwork: Optional[str] = ARTWORK,
    template: Optional[str] = TEMPLATE,
    quantity: Optional[int] = QUANTITY,
    to_first_name: Optional[str] = typer.Option(None, "--to-first-name"),
    to_last_name: Optional[str] = typer.Option(None, "--to-last-name"),
    to_company: Optional[str] = typer.Option(None, "--to-company"),
    to_address: Optional[str] = typer.Option(None, "--to-address"),
    to_address2: Optional[str] = typer.Option(None, "--to-address2"),
    to_city: Optional[str] = typer.Option(None, "--to-city"),
    to_region: Optional[str] = typer.Option(
        None, "--to-region", help="Conditionally required by country."
    ),
    to_postcode: Optional[str] = typer.Option(
        None, "--to-postcode", help="Conditionally required by country."
    ),
    to_country: Optional[str] = typer.Option(None, "--to-country", help="2-char ISO country code."),
    from_first_name: Optional[str] = typer.Option(None, "--from-first-name"),
    from_last_name: Optional[str] = typer.Option(None, "--from-last-name"),
    from_company: Optional[str] = typer.Option(None, "--from-company"),
    from_address: Optional[str] = typer.Option(None, "--from-address"),
    from_address2: Optional[str] = typer.Option(None, "--from-address2"),
    from_city: Optional[str] = typer.Option(None, "--from-city"),
    from_region: Optional[str] = typer.Option(None, "--from-region"),
    from_postcode: Optional[str] = typer.Option(None, "--from-postcode"),
    from_country: Optional[str] = typer.Option(None, "--from-country"),
    message: list[str] = MESSAGE,
    message_page: list[str] = MESSAGE_PAGE,
    var: list[str] = VAR,
    style: list[str] = STYLE,
    shipping: Optional[str] = SHIPPING,
    ship_to_me: Optional[bool] = SHIP_TO_ME,
    requested_arrival: Optional[str] = ARRIVAL,
    purchase_order_number: Optional[str] = typer.Option(None, "--purchase-order-number"),
    data: Optional[str] = DATA,
) -> None:
    """Place an order (POST /orders/place). Spends credit unless the key is test_."""
    state = ctx.obj
    if shipping and shipping not in SHIPPING_METHODS:
        raise typer.BadParameter(f"--shipping must be one of {', '.join(SHIPPING_METHODS)}")
    raw = load_data(data)
    # --data may carry a full {"lines": [...]} body; honour it as the base.
    lines = raw.pop("lines", None)
    if lines:
        body: dict[str, Any] = {"lines": lines}
    else:
        line = _build(
            artwork=artwork,
            template=template,
            quantity=quantity,
            to=_recipient(
                firstName=to_first_name,
                lastName=to_last_name,
                company=to_company,
                address=to_address,
                address2=to_address2,
                city=to_city,
                region=to_region,
                postcode=to_postcode,
                country=to_country,
            ),
            frm=_recipient(
                firstName=from_first_name,
                lastName=from_last_name,
                company=from_company,
                address=from_address,
                address2=from_address2,
                city=from_city,
                region=from_region,
                postcode=from_postcode,
                country=from_country,
            ),
            messages=message,
            message_pages=message_page,
            variables=var,
            style=style,
            shipping=shipping,
            ship_to_me=ship_to_me,
            requested_arrival=requested_arrival,
            data=raw,
        )
        # `place` wraps the line; `preview` does not. This is the ONLY shape
        # difference between the two endpoints.
        body = {"lines": [line]}
    if purchase_order_number:
        body["purchaseOrderNumber"] = purchase_order_number
    result = state.client().post("orders/place", json=body)
    _warn_test_mode(state, result)
    state.emit(result)


@orders_app.command("preview")
def preview(
    ctx: typer.Context,
    artwork: Optional[str] = ARTWORK,
    template: Optional[str] = TEMPLATE,
    quantity: Optional[int] = QUANTITY,
    to_first_name: Optional[str] = typer.Option(None, "--to-first-name"),
    to_last_name: Optional[str] = typer.Option(None, "--to-last-name"),
    to_company: Optional[str] = typer.Option(None, "--to-company"),
    to_address: Optional[str] = typer.Option(None, "--to-address"),
    to_address2: Optional[str] = typer.Option(None, "--to-address2"),
    to_city: Optional[str] = typer.Option(None, "--to-city"),
    to_region: Optional[str] = typer.Option(None, "--to-region"),
    to_postcode: Optional[str] = typer.Option(None, "--to-postcode"),
    to_country: Optional[str] = typer.Option(None, "--to-country"),
    from_first_name: Optional[str] = typer.Option(None, "--from-first-name"),
    from_last_name: Optional[str] = typer.Option(None, "--from-last-name"),
    from_company: Optional[str] = typer.Option(None, "--from-company"),
    from_address: Optional[str] = typer.Option(None, "--from-address"),
    from_address2: Optional[str] = typer.Option(None, "--from-address2"),
    from_city: Optional[str] = typer.Option(None, "--from-city"),
    from_region: Optional[str] = typer.Option(None, "--from-region"),
    from_postcode: Optional[str] = typer.Option(None, "--from-postcode"),
    from_country: Optional[str] = typer.Option(None, "--from-country"),
    message: list[str] = MESSAGE,
    message_page: list[str] = MESSAGE_PAGE,
    var: list[str] = VAR,
    style: list[str] = STYLE,
    shipping: Optional[str] = SHIPPING,
    ship_to_me: Optional[bool] = SHIP_TO_ME,
    requested_arrival: Optional[str] = ARRIVAL,
    download: Optional[Path] = typer.Option(
        None, "--download", help="Save the proof PDF to this path."
    ),
    data: Optional[str] = DATA,
) -> None:
    """Preview an order (POST /orders/preview) — watermarked proof, no credit spent."""
    state = ctx.obj
    if shipping and shipping not in SHIPPING_METHODS:
        raise typer.BadParameter(f"--shipping must be one of {', '.join(SHIPPING_METHODS)}")
    raw = load_data(data)
    raw.pop("lines", None)  # preview takes ONE card, flat — never a lines[] wrap
    body = _build(
        artwork=artwork,
        template=template,
        quantity=quantity,
        to=_recipient(
            firstName=to_first_name,
            lastName=to_last_name,
            company=to_company,
            address=to_address,
            address2=to_address2,
            city=to_city,
            region=to_region,
            postcode=to_postcode,
            country=to_country,
        ),
        frm=_recipient(
            firstName=from_first_name,
            lastName=from_last_name,
            company=from_company,
            address=from_address,
            address2=from_address2,
            city=from_city,
            region=from_region,
            postcode=from_postcode,
            country=from_country,
        ),
        messages=message,
        message_pages=message_page,
        variables=var,
        style=style,
        shipping=shipping,
        ship_to_me=ship_to_me,
        requested_arrival=requested_arrival,
        data=raw,
    )
    client = state.client()
    result = _upgrade_preview_urls(client.post("orders/preview", json=body))
    _warn_test_mode(state, result)

    if download:
        url = (result.get("preview") or {}).get("urls", {}).get("card")
        if not url:
            raise typer.BadParameter("Preview response carried no card URL to download.")
        # Preview URLs expire (preview.expires) and are NOT pre-signed CDN
        # links — they sit on api.card.ly, so the fetch needs our API-Key
        # header. Fetch now; never cache the URL across runs.
        response = client.request("GET", url, raw=True)
        download.write_bytes(response.content)
        state.warn(f"Wrote proof PDF to {download}")

    state.emit(result)


@orders_app.command("get")
def get_order(ctx: typer.Context, order_id: str = typer.Argument(...)) -> None:
    """Show one order."""
    state = ctx.obj
    data = state.client().get(f"orders/{order_id}")
    inner = data.get("order", data) if isinstance(data, dict) else data
    state.emit(Order.model_validate(inner))


@orders_app.command("list")
def list_orders(
    ctx: typer.Context,
    all_pages: bool = typer.Option(False, "--all", help="Fetch all pages."),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Page size."),
    filter_: list[str] = typer.Option([], "--filter", help="Client-side key=value match."),
) -> None:
    """List orders."""
    state = ctx.obj
    client = state.client()
    if all_pages:
        items = list(paginate(client, "orders", limit=limit, warn=state.warn))
    else:
        items = extract_results(client.get("orders", params={"limit": limit}))
    rows = [Order.model_validate(i) for i in apply_filters(items, filter_)]
    state.emit(rows, columns=LIST_COLUMNS)
