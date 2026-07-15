from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel

# The exact enum Cardly accepts on POST /invitations. Validated client-side so a
# typo fails locally instead of costing a round trip.
PERMISSIONS: tuple[str, ...] = (
    "administrator",
    "artwork",
    "billing",
    "campaigns",
    "developer",
    "lists",
    "moderate",
    "moderate-history",
    "orders",
    "templates",
    "users",
    "use-credits",
    "use-saved-card",
)


class Invitation(CardlyModel):
    id: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    # Permission-keyed object on reads (POST sends a list of identifiers).
    permissions: Optional[Any] = None
    invited: Optional[str] = None
    inviteSent: Optional[str] = None
    accepted: Optional[str] = None
    expires: Optional[str] = None
    links: Optional[Any] = None
