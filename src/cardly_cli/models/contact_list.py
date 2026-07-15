from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel

FIELD_TYPES = ("text", "date", "number", "url")


class ListField(CardlyModel):
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None


class ContactList(CardlyModel):
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    fields: Optional[list[ListField]] = None
    contactCount: Optional[int] = None
    createdAt: Optional[Any] = None
