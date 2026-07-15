from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel, compact

# Contacts use `locality`. Orders use `city`. See the class docstring.
CONTACT_KEYS = (
    "externalId",
    "firstName",
    "lastName",
    "email",
    "company",
    "address",
    "address2",
    "locality",
    "region",
    "country",
    "postcode",
)


class Contact(CardlyModel):
    """A contact-list contact.

    NOTE: this is deliberately NOT models/order.OrderAddress, despite looking
    like duplication. Contacts use `locality` where orders use `city`, and reads
    return `adminAreaLevel1` for region. Cardly 422s every contact write if the
    order address shape is reused. Do not "DRY these up".

    region/postcode are conditionally required by country. The OpenAPI marks
    both `required` here with no x-conditionallyRequired marker at all, which
    cannot be true for every country (UK/NZ have no region; some countries have
    no postcode). The API is the only authority — do not validate them locally.
    """

    id: Optional[str] = None
    externalId: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    address: Optional[str] = None
    address2: Optional[str] = None
    locality: Optional[str] = None
    region: Optional[str] = None
    # Reads come back as adminAreaLevel1, not region.
    adminAreaLevel1: Optional[str] = None
    country: Optional[str] = None
    postcode: Optional[str] = None
    fields: Optional[dict[str, Any]] = None


def build_contact(values: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    body = compact({key: values.get(key) for key in CONTACT_KEYS})
    if fields:
        body["fields"] = fields
    return body
