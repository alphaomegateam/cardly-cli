from __future__ import annotations

from typing import Any, Optional

from cardly_cli.models.base import CardlyModel


class Art(CardlyModel):
    id: Optional[str] = None
    # /art/{id} accepts a UUID or a slug, and orders accept the same for
    # --artwork.
    slug: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    pages: Optional[Any] = None
    createdAt: Optional[str] = None
