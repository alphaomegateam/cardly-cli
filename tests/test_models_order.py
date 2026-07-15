import pytest
import typer

from cardly_cli.models.order import (
    SHIPPING_METHODS,
    build_address,
    build_line,
    build_messages,
    check_shipping,
    validate_sender,
)

FULL_RECIPIENT = {
    "firstName": "Ada",
    "lastName": "Lovelace",
    "address": "12 Analytical Way",
    "city": "Melbourne",
    "country": "AU",
}


def test_build_address_uses_city_not_locality():
    # Orders use `city`. Contacts use `locality`. Sharing a model 422s.
    out = build_address(FULL_RECIPIENT)
    assert out["city"] == "Melbourne"
    assert "locality" not in out


def test_build_address_compacts_empty_values():
    out = build_address({**FULL_RECIPIENT, "company": "", "address2": None, "region": "VIC"})
    assert "company" not in out
    assert "address2" not in out
    assert out["region"] == "VIC"


def test_build_address_does_not_require_region_or_postcode():
    # Conditionally required by country; the OpenAPI contradicts itself and the
    # API is the only authority. Guessing would reject valid addresses.
    out = build_address(FULL_RECIPIENT)
    assert "region" not in out and "postcode" not in out


def test_validate_sender_returns_none_when_entirely_blank():
    # Omit the key entirely so Cardly's org return details apply.
    assert validate_sender({"firstName": None, "address": "", "city": None}) is None
    assert validate_sender({}) is None


def test_validate_sender_accepts_complete_sender():
    out = validate_sender({**FULL_RECIPIENT})
    assert out is not None and out["firstName"] == "Ada"


def test_validate_sender_rejects_partial_sender():
    # "If any sender element is specified, all must be specified."
    with pytest.raises(typer.BadParameter, match="sender"):
        validate_sender({"firstName": "Ada"})


@pytest.mark.parametrize("missing", ["firstName", "address", "city", "country"])
def test_validate_sender_names_the_missing_field(missing):
    values = dict(FULL_RECIPIENT)
    values.pop(missing)
    with pytest.raises(typer.BadParameter, match=missing):
        validate_sender(values)


def test_build_messages_uses_page_key_not_name():
    # Cardly's own OpenAPI example ships {"name": 2} here. The field is `page`.
    out = build_messages([(1, "Front"), (2, "Inside")])
    assert out == {"pages": [{"page": 1, "text": "Front"}, {"page": 2, "text": "Inside"}]}
    assert "name" not in out["pages"][0]


def test_build_messages_empty_returns_none():
    assert build_messages([]) is None


def test_shipping_methods_enum():
    assert set(SHIPPING_METHODS) == {"standard", "tracked", "express"}


def test_check_shipping_standard_allowed_everywhere():
    check_shipping("standard", "GB")
    check_shipping(None, "GB")


def test_check_shipping_tracked_is_australia_only():
    check_shipping("tracked", "AU")
    check_shipping("tracked", "au")  # case-insensitive
    with pytest.raises(typer.BadParameter, match="tracked"):
        check_shipping("tracked", "US")


def test_check_shipping_express_is_au_and_us_only():
    check_shipping("express", "AU")
    check_shipping("express", "US")
    with pytest.raises(typer.BadParameter, match="express"):
        check_shipping("express", "GB")


def test_check_shipping_skips_when_country_unknown():
    # --data may carry the country; don't block on a flag we can't see.
    check_shipping("tracked", None)


def test_build_line_assembles_full_body():
    line = build_line(
        artwork="thank-you-01",
        template="tpl-1",
        quantity=2,
        recipient=FULL_RECIPIENT,
        sender=None,
        messages=[(1, "Hi")],
        variables={"name": "Ada"},
        style={"align": "center"},
        shipping="standard",
        ship_to_me=False,
        requested_arrival="2026-08-01",
        data={},
    )
    assert line["artwork"] == "thank-you-01"
    assert line["template"] == "tpl-1"
    assert line["quantity"] == 2
    assert line["recipient"]["city"] == "Melbourne"
    assert line["messages"]["pages"][0]["page"] == 1
    assert line["variables"] == {"name": "Ada"}
    assert line["style"] == {"align": "center"}
    assert line["shippingMethod"] == "standard"
    assert line["requestedArrival"] == "2026-08-01"
    assert "sender" not in line  # omitted, not null


def test_build_line_keeps_ship_to_me_false():
    line = build_line(
        artwork="a",
        recipient=FULL_RECIPIENT,
        ship_to_me=False,
        data={},
        template=None,
        quantity=None,
        sender=None,
        messages=[],
        variables={},
        style={},
        shipping=None,
        requested_arrival=None,
    )
    # False is a real value; compact() must not strip it.
    assert line["shipToMe"] is False


def test_build_line_merges_data_under_typed_flags():
    line = build_line(
        artwork="flag-wins",
        recipient=FULL_RECIPIENT,
        data={"artwork": "body", "quantity": 9},
        template=None,
        quantity=None,
        sender=None,
        messages=[],
        variables={},
        style={},
        shipping=None,
        ship_to_me=None,
        requested_arrival=None,
    )
    assert line["artwork"] == "flag-wins"
    assert line["quantity"] == 9  # from --data, no typed override given
