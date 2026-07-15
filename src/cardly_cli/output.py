from __future__ import annotations

import json
from typing import Any

import click
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, list):
        return [to_jsonable(item) for item in obj]
    if isinstance(obj, dict):
        return {key: to_jsonable(value) for key, value in obj.items()}
    return obj


def apply_jq(data: Any, expr: str) -> Any:
    """Minimal selector.

    Supports '.', '.a.b', '.[]', '.[].field', and numeric list indexes
    ('.results.0.id'). The leading '.' is optional, so bare key paths like
    'results' or 'results.0' work the same as '.results' / '.results.0'.

    Raises ``click.ClickException`` (surfaced as a clean ``Error:`` message,
    never a raw traceback) when the expression cannot be applied.
    """
    expr = expr.strip()
    if expr in ("", "."):
        return data
    # Accept both jq-style leading-dot paths ('.results') and bare key paths
    # ('results', 'results.0.id').
    rest = expr[1:] if expr.startswith(".") else expr
    current = data
    for token in _tokenize(rest):
        if token == "[]":
            if not isinstance(current, list):
                raise click.ClickException(f"--jq: '[]' applied to a non-list value in {expr!r}")
            current = list(current)
        elif isinstance(current, list):
            if _is_index(token):
                idx = int(token)
                current = current[idx] if -len(current) <= idx < len(current) else None
            else:
                current = [item.get(token) if isinstance(item, dict) else None for item in current]
        elif isinstance(current, dict):
            current = current.get(token)
        else:
            # Path continues past a scalar/None value: jq yields null here
            # rather than erroring, which is friendlier for optional fields.
            current = None
    return current


def _is_index(token: str) -> bool:
    return token.lstrip("-").isdigit()


def _tokenize(rest: str) -> list[str]:
    tokens: list[str] = []
    for part in rest.split("."):
        while "[]" in part:
            head, _, tail = part.partition("[]")
            if head:
                tokens.append(head)
            tokens.append("[]")
            part = tail
        if part:
            tokens.append(part)
    return tokens


def render(
    data: Any,
    *,
    as_json: bool,
    jq: str | None = None,
    columns: list[str] | None = None,
    console: Console | None = None,
) -> None:
    console = console or Console()
    payload = to_jsonable(data)
    if jq:
        payload = apply_jq(payload, jq)

    if as_json or jq:
        # JSON is for machine consumption: always emit plain, uncolored text.
        # We must NOT route it through the Rich colorizer, because Rich reports
        # is_terminal=True whenever FORCE_COLOR is set (a common shell/dev-env
        # default) even when stdout is a pipe, which wraps the JSON in ANSI
        # escapes and breaks json.loads / --jq consumers.
        console.file.write(json.dumps(payload, indent=2) + "\n")
        return

    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        cols = columns or list(payload[0].keys())
        table = Table(*cols)
        for row in payload:
            table.add_row(*[_fmt(row.get(c)) for c in cols])
        console.print(table)
    elif isinstance(payload, dict):
        table = Table("field", "value")
        for key, value in payload.items():
            table.add_row(key, _fmt(value))
        console.print(table)
    else:
        console.print(_fmt(payload))


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        # Cardly returns several fields as {"id": ..., "name": ...} objects.
        # Show the human-readable name in tables instead of dumping raw JSON.
        name = value.get("name")
        if isinstance(name, (str, int, float)):
            return str(name)
        return json.dumps(value)
    if isinstance(value, list):
        return json.dumps(value)
    return str(value)
