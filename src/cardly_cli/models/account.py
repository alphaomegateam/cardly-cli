from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel


class GiftCredit(CardlyModel):
    balance: Optional[float] = None
    currency: Optional[str] = None


class Balance(CardlyModel):
    balance: Optional[float] = None
    # Gift credit is a SEPARATE currency of value from regular credit, with its
    # own history endpoint. Not interchangeable.
    giftCredit: Optional[GiftCredit] = None


class CreditEntry(CardlyModel):
    id: Optional[str] = None
    effectiveTime: Optional[str] = None
    amount: Optional[float] = None
    balance: Optional[float] = None
    description: Optional[str] = None
    order: Optional[Any] = None
