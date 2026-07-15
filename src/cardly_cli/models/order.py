from __future__ import annotations

from typing import Any, Optional

import typer

from cardly_cli.models.base import CardlyModel, compact

SHIPPING_METHODS = ("standard", "tracked", "express")

# Availability is region-gated. Checked client-side to preempt a 422 that costs
# a round trip to discover.
SHIPPING_REGIONS: dict[str, set[str] | None] = {
    "standard": None,  # all regions
    "tracked": {"AU"},
    "express": {"AU", "US"},
}

# Present-if-any-present. Cardly: "if any sender element is specified, all must
# be specified." region/postcode are deliberately absent — see build_address.
SENDER_REQUIRED = ("firstName", "address", "city", "country")

ADDRESS_KEYS = (
    "firstName",
    "lastName",
    "company",
    "address",
    "address2",
    "city",
    "region",
    "postcode",
    "country",
)


class OrderAddress(CardlyModel):
    """Recipient/sender address for ORDERS.

    NOTE: orders use `city`; contacts use `locality` and read back
    `adminAreaLevel1`. This looks like duplication of models/contact.py and is
    not — unifying them guarantees a 422 on contact writes. Do not "clean up".
    """

    firstName: Optional[str] = None
    lastName: Optional[str] = None
    company: Optional[str] = None
    address: Optional[str] = None
    address2: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    postcode: Optional[str] = None
    country: Optional[str] = None


class Style(CardlyModel):
    align: Optional[str] = None
    color: Optional[str] = None
    font: Optional[str] = None
    size: Optional[int] = None
    verticalAlign: Optional[str] = None
    writing: Optional[str] = None


class MessagePage(CardlyModel):
    # `page`, NOT `name`. 1-based; 1 is the front, then reading order.
    page: Optional[int] = None
    text: Optional[str] = None
    style: Optional[Style] = None


class OrderItem(CardlyModel):
    id: Optional[str] = None
    type: Optional[str] = None
    artwork: Optional[Any] = None
    template: Optional[Any] = None
    label: Optional[str] = None
    quantity: Optional[int] = None
    costs: Optional[Any] = None
    shipTo: Optional[Any] = None
    shipMethod: Optional[str] = None
    scheduledDate: Optional[str] = None
    recipient: Optional[OrderAddress] = None
    sender: Optional[OrderAddress] = None
    delivery: Optional[Any] = None
    tracking: Optional[Any] = None


class Order(CardlyModel):
    id: Optional[str] = None
    status: Optional[str] = None
    origin: Optional[str] = None
    customer: Optional[Any] = None
    costs: Optional[Any] = None
    timings: Optional[Any] = None
    items: Optional[list[OrderItem]] = None


def build_address(values: dict[str, Any]) -> dict[str, Any]:
    """Build an ORDER address (uses `city`).

    region/postcode are conditionally required by country. The OpenAPI
    contradicts itself on which are required and no country table exists, so we
    send what we're given and let the API be the authority. Guessing here would
    reject valid addresses.
    """
    return compact({key: values.get(key) for key in ADDRESS_KEYS})


def validate_sender(values: dict[str, Any]) -> dict[str, Any] | None:
    """Return a complete sender, or None when no sender was given at all.

    Cardly's rule: "if any sender element is specified, all must be specified."
    So a partial sender is a local error, and a wholly absent one means "use my
    organisation's return details" — which requires omitting the key entirely
    rather than sending nulls.
    """
    built = build_address(values)
    if not built:
        return None
    missing = [key for key in SENDER_REQUIRED if not built.get(key)]
    if missing:
        raise typer.BadParameter(
            "Incomplete sender: if any --from-* option is given, all of "
            f"{', '.join(SENDER_REQUIRED)} are required. Missing: {', '.join(missing)}."
        )
    return built


def build_messages(pages: list[tuple[int, str]]) -> dict[str, Any] | None:
    """Nest message text at messages.pages[] keyed by `page`.

    The key is `page` (1-based int), not `name` — Cardly's own OpenAPI example
    ships {"name": 2} here, which is wrong.
    """
    if not pages:
        return None
    # Reject duplicate page numbers to prevent ambiguous message bodies
    page_numbers = [item[0] for item in pages]
    seen = set()
    for page_num in page_numbers:
        if page_num in seen:
            raise typer.BadParameter(
                f"Duplicate --message-page for page {page_num}; each page may be given once."
            )
        seen.add(page_num)
    ordered = sorted(pages, key=lambda item: item[0])
    return {"pages": [{"page": number, "text": text} for number, text in ordered]}


def check_shipping(method: str | None, country: str | None) -> None:
    """Preempt a region 422: tracked is AU-only, express is AU+US-only."""
    if not method or not country:
        return
    allowed = SHIPPING_REGIONS.get(method)
    if allowed is None:
        return
    if country.upper() not in allowed:
        raise typer.BadParameter(
            f"Shipping method '{method}' is only available for "
            f"{', '.join(sorted(allowed))} (got {country.upper()}). "
            f"Use 'standard' instead."
        )


def _merge_nested(data_value: Any, typed_value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Deep-merge one nested address object: typed wins per-key over data's.

    `data_value` is whatever --data supplied at this key (or anything else, if
    it wasn't a dict). `typed_value` has already been through compact(), so it
    only contains keys the caller actually set — a key typed left unset can
    never clobber one --data supplied. Returns None when there is nothing to
    merge (no data dict, no typed values), so the caller can leave the key
    untouched rather than writing an empty object over nothing.
    """
    base = dict(data_value) if isinstance(data_value, dict) else {}
    merged = {**base, **(typed_value or {})}
    return merged or None


def build_line(
    *,
    artwork: str | None,
    template: str | None,
    quantity: int | None,
    recipient: dict[str, Any],
    sender: dict[str, Any] | None,
    messages: list[tuple[int, str]],
    variables: dict[str, Any],
    style: dict[str, Any],
    shipping: str | None,
    ship_to_me: bool | None,
    requested_arrival: str | None,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Assemble one order line. Shared verbatim by `place` and `preview`.

    `place` wraps the result in {"lines": [line]}; `preview` sends it flat. That
    wrap is the ONLY difference between the two bodies.
    """
    built_recipient = build_address(recipient)
    built_sender = validate_sender(sender or {})
    line: dict[str, Any] = dict(data)
    typed = compact(
        {
            "artwork": artwork,
            "template": template,
            "quantity": quantity,
            "messages": build_messages(messages),
            "variables": variables,
            "style": style,
            "shippingMethod": shipping,
            "requestedArrival": requested_arrival,
        }
    )
    line.update(typed)
    # recipient/sender are deep-merged rather than replaced wholesale (I1): a
    # plain `line.update({"recipient": built_recipient})` would silently
    # discard any --data recipient fields the typed flags don't cover (e.g.
    # recipient.company), even though the resulting body stays structurally
    # valid and ships without complaint.
    recipient_merged = _merge_nested(line.get("recipient"), built_recipient)
    if recipient_merged is not None:
        line["recipient"] = recipient_merged
    sender_merged = _merge_nested(line.get("sender"), built_sender)
    if sender_merged is not None:
        line["sender"] = sender_merged
    if ship_to_me is not None:
        # False is meaningful, so set it outside compact().
        line["shipToMe"] = ship_to_me
    return line
