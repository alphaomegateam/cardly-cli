from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel

EVENTS = (
    "contact.order.created",
    "contact.order.sent",
    "contact.order.refunded",
    "giftCard.redeemed",
    "qrCode.scanned",
    "contact.undeliverable",
    "contact.changeOfAddress",
    "consignment.undeliverable",
    "consignment.changeOfAddress",
)

# Cardly allows up to 10 active-or-disabled webhooks at a time (Zapier-created
# ones are excluded from the count).
WEBHOOK_LIMIT = 10


class Webhook(CardlyModel):
    id: Optional[str] = None
    # Returned ONLY at creation, never again. Losing it means delete+recreate.
    secret: Optional[str] = None
    status: Optional[str] = None
    # True when created by an integration (Zapier etc.) — don't clobber.
    protected: Optional[bool] = None
    targetUrl: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    events: Optional[list[str]] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
