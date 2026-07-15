import json

import pytest
from rich.console import Console

from cardly_cli.output import apply_jq, render, to_jsonable


def cap():
    import io

    buf = io.StringIO()
    return buf, Console(file=buf, no_color=True, width=200)


def test_to_jsonable_handles_models_and_nesting():
    from pydantic import BaseModel

    class M(BaseModel):
        a: int

    assert to_jsonable(M(a=1)) == {"a": 1}
    assert to_jsonable([M(a=1)]) == [{"a": 1}]
    assert to_jsonable({"k": M(a=1)}) == {"k": {"a": 1}}
    assert to_jsonable("x") == "x"


@pytest.mark.parametrize(
    "expr,expected",
    [
        (".", {"results": [{"id": 1}]}),
        ("", {"results": [{"id": 1}]}),
        (".results", [{"id": 1}]),
        ("results", [{"id": 1}]),  # leading dot optional
        (".results.0.id", 1),
        (".results[].id", [1]),
        (".missing", None),
        (".results.0.missing.deeper", None),  # jq yields null past a scalar
    ],
)
def test_apply_jq(expr, expected):
    data = {"results": [{"id": 1}]}
    assert apply_jq(data, expr) == expected


def test_apply_jq_rejects_list_op_on_non_list():
    import click

    with pytest.raises(click.ClickException):
        apply_jq({"a": 1}, ".a[]")


def test_render_json_is_plain_and_parseable():
    buf, console = cap()
    render({"id": "abc"}, as_json=True, console=console)
    assert json.loads(buf.getvalue()) == {"id": "abc"}
    assert "\x1b[" not in buf.getvalue()  # no ANSI escapes


def test_render_jq_implies_json():
    buf, console = cap()
    render({"results": [{"id": 1}]}, as_json=False, jq=".results", console=console)
    assert json.loads(buf.getvalue()) == [{"id": 1}]


def test_render_table_for_list_of_dicts():
    buf, console = cap()
    render(
        [{"id": "1", "status": "sent"}], as_json=False, columns=["id", "status"], console=console
    )
    out = buf.getvalue()
    assert "id" in out and "status" in out and "sent" in out


def test_render_table_for_dict():
    buf, console = cap()
    render({"balance": 42}, as_json=False, console=console)
    assert "balance" in buf.getvalue()


def test_fmt_unwraps_named_objects():
    buf, console = cap()
    render([{"status": {"id": 3, "name": "Active"}}], as_json=False, console=console)
    assert "Active" in buf.getvalue()
