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
            key: (
                "https://" + value[len("http://") :]
                if isinstance(value, str) and value.startswith("http://")
                else value
            )
            for key, value in preview["urls"].items()
        }
    return payload


def _pop_lines(raw: dict[str, Any]) -> tuple[bool, Any]:
    """Pop `lines` from a --data body, validating its shape once for both commands.

    `place` used to guard only `if not lines`, never checking the type, so a
    non-list (e.g. `null` or a bare object) sailed through: `preview` crashed
    with a raw TypeError/KeyError, and `place` shipped it straight to the
    money endpoint (I2).
    """
    has_lines = "lines" in raw
    lines = raw.pop("lines", None)
    if has_lines and not isinstance(lines, list):
        raise typer.BadParameter(
            f"--data lines[] must be a JSON array, got {type(lines).__name__}."
        )
    return has_lines, lines


CARD_SHAPING_FLAGS_HELP = (
    "--data carrying lines[] cannot be combined with card-shaping flags "
    "(--artwork, --to-*, --message, ...); use one or the other."
)


def _card_shaping_flags_present(
    *,
    artwork: Any,
    template: Any,
    quantity: Any,
    to: dict[str, Any],
    frm: dict[str, Any],
    messages: list[str],
    message_pages: list[str],
    variables: list[str],
    style: list[str],
    shipping: Any,
    ship_to_me: Any,
    requested_arrival: Any,
) -> bool:
    """True if any card-shaping flag was set.

    `--purchase-order-number` is deliberately excluded — it's a top-level
    field, not part of the card, and may accompany `--data` lines[].
    """
    if any(value is not None for value in (to.values())) or any(
        value is not None for value in frm.values()
    ):
        return True
    if messages or message_pages or variables or style:
        return True
    return any(
        value is not None
        for value in (artwork, template, quantity, shipping, ship_to_me, requested_arrival)
    )


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
    line = build_line(
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
    # Gate on the MERGED line, not the flag dict — country may come from
    # --data (e.g. {"recipient": {"country": "GB"}}) rather than --to-country.
    check_shipping(shipping, (line.get("recipient") or {}).get("country"))
    return line


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
    to = _recipient(
        firstName=to_first_name,
        lastName=to_last_name,
        company=to_company,
        address=to_address,
        address2=to_address2,
        city=to_city,
        region=to_region,
        postcode=to_postcode,
        country=to_country,
    )
    frm = _recipient(
        firstName=from_first_name,
        lastName=from_last_name,
        company=from_company,
        address=from_address,
        address2=from_address2,
        city=from_city,
        region=from_region,
        postcode=from_postcode,
        country=from_country,
    )
    raw = load_data(data)
    # --data may carry a full {"lines": [...]} body; honour it as the base.
    # Detect PRESENCE not truthiness: {"lines": []} must not silently fall
    # through to a flag-built card below.
    has_lines, lines = _pop_lines(raw)
    if has_lines and _card_shaping_flags_present(
        artwork=artwork,
        template=template,
        quantity=quantity,
        to=to,
        frm=frm,
        messages=message,
        message_pages=message_page,
        variables=var,
        style=style,
        shipping=shipping,
        ship_to_me=ship_to_me,
        requested_arrival=requested_arrival,
    ):
        raise typer.BadParameter(CARD_SHAPING_FLAGS_HELP)
    if has_lines:
        if not lines:
            raise typer.BadParameter("--data lines[] must not be empty.")
        # Preserve --data's other top-level keys (e.g. purchaseOrderNumber);
        # the flag below still overrides a --data-supplied one.
        body: dict[str, Any] = {**raw, "lines": lines}
    else:
        line = _build(
            artwork=artwork,
            template=template,
            quantity=quantity,
            to=to,
            frm=frm,
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
    to = _recipient(
        firstName=to_first_name,
        lastName=to_last_name,
        company=to_company,
        address=to_address,
        address2=to_address2,
        city=to_city,
        region=to_region,
        postcode=to_postcode,
        country=to_country,
    )
    frm = _recipient(
        firstName=from_first_name,
        lastName=from_last_name,
        company=from_company,
        address=from_address,
        address2=from_address2,
        city=from_city,
        region=from_region,
        postcode=from_postcode,
        country=from_country,
    )
    raw = load_data(data)
    # preview takes ONE card, flat — never a lines[] wrap. But `--data` carrying
    # lines[] must be UNWRAPPED, not discarded (that would silently mail a
    # different card than the one just previewed).
    has_lines, lines = _pop_lines(raw)
    if has_lines and _card_shaping_flags_present(
        artwork=artwork,
        template=template,
        quantity=quantity,
        to=to,
        frm=frm,
        messages=message,
        message_pages=message_page,
        variables=var,
        style=style,
        shipping=shipping,
        ship_to_me=ship_to_me,
        requested_arrival=requested_arrival,
    ):
        raise typer.BadParameter(CARD_SHAPING_FLAGS_HELP)
    if has_lines:
        if len(lines) != 1:
            raise typer.BadParameter(
                "preview takes a single card; --data lines[] must contain exactly "
                f"one element (got {len(lines)})."
            )
        body: dict[str, Any] = lines[0]
    else:
        body = _build(
            artwork=artwork,
            template=template,
            quantity=quantity,
            to=to,
            frm=frm,
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
    # Emit BEFORE attempting the download — a failed download must not swallow
    # creditCost and the preview URLs the caller already paid to generate.
    state.emit(result)

    if download:
        preview_obj = result.get("preview") if isinstance(result, dict) else None
        url = (preview_obj.get("urls") or {}).get("card") if isinstance(preview_obj, dict) else None
        if not url:
            raise typer.BadParameter("Preview response carried no card URL to download.")
        # Preview URLs expire (preview.expires) and are NOT pre-signed CDN
        # links — they sit on api.card.ly, so the fetch needs our API-Key
        # header. Fetch now; never cache the URL across runs.
        response = client.request("GET", url, raw=True)
        download.write_bytes(response.content)
        state.warn(f"Wrote proof PDF to {download}")


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
