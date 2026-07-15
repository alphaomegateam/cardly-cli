from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class CardlyModel(BaseModel):
    # extra="allow" is deliberate. Cardly's Order nests four levels deep
    # (order.items[].delivery.tracking) and ships new fields with builds. Model
    # the levels people actually read; carry the rest verbatim rather than
    # chasing the schema.
    model_config = ConfigDict(extra="allow")


def compact(mapping: dict[str, Any]) -> dict[str, Any]:
    """Drop None and empty string/list/dict values.

    Cardly validates presence, not emptiness: sending `"region": ""` for an
    omitted flag reads as "region is blank", not "region wasn't given". False
    and 0 are real values and survive.

    Lives here rather than in commands/_helpers.py because the request builders
    in models/ need it, and models must not import from commands/.
    """
    return {
        key: value
        for key, value in mapping.items()
        if value is not None and value != "" and value != [] and value != {}
    }
