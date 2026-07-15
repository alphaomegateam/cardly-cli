from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

import typer

from cardly_cli.models.base import compact

__all__ = ["apply_filters", "build_payload", "compact", "load_data", "parse_fields"]


def load_data(raw: str | None, *, stdin: TextIO | None = None) -> dict:
    if raw is None:
        return {}
    try:
        if raw == "-":
            source = stdin or sys.stdin
            parsed = json.load(source)
        elif raw.startswith("@"):
            parsed = json.loads(Path(raw[1:]).read_text())
        else:
            parsed = json.loads(raw)

        if not isinstance(parsed, dict):
            raise typer.BadParameter(f"--data must be a JSON object, got {type(parsed).__name__}")
        return parsed
    except (json.JSONDecodeError, OSError) as exc:
        raise typer.BadParameter(f"Invalid --data JSON: {exc}") from exc


def parse_fields(fields: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in fields:
        if "=" not in item:
            raise typer.BadParameter(f"--field must be key=value, got {item!r}")
        key, value = item.split("=", 1)
        force_list = key.endswith("[]")
        if force_list:
            key = key[:-2]
        if key in result:
            existing = result[key]
            result[key] = existing + [value] if isinstance(existing, list) else [existing, value]
        elif force_list:
            result[key] = [value]
        else:
            result[key] = value
    return result


def apply_filters(items: list[Any], filters: list[str]) -> list[Any]:
    """Post-filter API records by exact field match, client-side.

    Each filter is ``key=value``. For object-valued fields the value is matched
    against the object's ``name`` (then ``id``).
    """
    if not filters:
        return items
    pairs: list[tuple[str, str]] = []
    for item in filters:
        if "=" not in item:
            raise typer.BadParameter(f"--filter must be key=value, got {item!r}")
        key, value = item.split("=", 1)
        pairs.append((key, value))

    def matches(record: Any) -> bool:
        if not isinstance(record, dict):
            return False
        for key, value in pairs:
            actual = record.get(key)
            if isinstance(actual, dict):
                actual = actual.get("name", actual.get("id"))
            if actual is None or str(actual) != value:
                return False
        return True

    return [item for item in items if matches(item)]


def build_payload(typed: dict, data: dict, fields: dict | None = None) -> dict:
    """Merge typed flags over a --data body. Precedence: fields > typed > data.

    NOTE: unlike loxo-cli's build_payload, this returns an UNWRAPPED body.
    Cardly's request bodies are top-level; there is no {"order": {...}}
    resource-key envelope. Wrapping 422s every write.
    """
    merged: dict[str, Any] = dict(data)
    merged.update({k: v for k, v in typed.items() if v is not None})
    merged.update(fields or {})
    return merged
