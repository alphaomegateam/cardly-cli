from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel


class User(CardlyModel):
    id: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    # Permission-keyed object, not a list. Shape is not modelled further.
    permissions: Optional[Any] = None
