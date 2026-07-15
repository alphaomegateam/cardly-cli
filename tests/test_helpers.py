import io

import pytest
import typer

from cardly_cli.commands._helpers import (
    apply_filters,
    compact,
    load_data,
    parse_fields,
)


def test_load_data_inline_file_and_stdin(tmp_path):
    assert load_data(None) == {}
    assert load_data('{"a": 1}') == {"a": 1}

    path = tmp_path / "b.json"
    path.write_text('{"b": 2}')
    assert load_data(f"@{path}") == {"b": 2}

    assert load_data("-", stdin=io.StringIO('{"c": 3}')) == {"c": 3}


def test_load_data_bad_json_raises_bad_parameter():
    with pytest.raises(typer.BadParameter, match="Invalid --data JSON"):
        load_data("{nope")


def test_load_data_inline_array_raises_bad_parameter():
    with pytest.raises(typer.BadParameter, match="must be a JSON object, got list"):
        load_data("[1, 2]")


def test_load_data_inline_string_raises_bad_parameter():
    with pytest.raises(typer.BadParameter, match="must be a JSON object, got str"):
        load_data('"string"')


def test_load_data_inline_number_raises_bad_parameter():
    with pytest.raises(typer.BadParameter, match="must be a JSON object, got int"):
        load_data("42")


def test_load_data_stdin_array_raises_bad_parameter():
    with pytest.raises(typer.BadParameter, match="must be a JSON object, got list"):
        load_data("-", stdin=io.StringIO("[1, 2]"))


def test_load_data_file_array_raises_bad_parameter(tmp_path):
    path = tmp_path / "array.json"
    path.write_text("[1, 2, 3]")
    with pytest.raises(typer.BadParameter, match="must be a JSON object, got list"):
        load_data(f"@{path}")


def test_load_data_missing_file_raises_bad_parameter():
    with pytest.raises(typer.BadParameter, match="Invalid --data JSON"):
        load_data("@/nonexistent/file.json")


def test_parse_fields():
    assert parse_fields(["a=1", "b=2"]) == {"a": "1", "b": "2"}
    assert parse_fields(["a=1", "a=2"]) == {"a": ["1", "2"]}
    assert parse_fields(["a[]=1"]) == {"a": ["1"]}
    assert parse_fields(["a=x=y"]) == {"a": "x=y"}  # only split on the first =


def test_parse_fields_requires_kv():
    with pytest.raises(typer.BadParameter, match="key=value"):
        parse_fields(["nope"])


def test_apply_filters():
    items = [{"id": 1, "status": "sent"}, {"id": 2, "status": "queued"}]
    assert apply_filters(items, ["status=sent"]) == [{"id": 1, "status": "sent"}]
    assert apply_filters(items, []) == items


def test_apply_filters_unwraps_named_objects():
    items = [{"id": 1, "status": {"id": 9, "name": "Active"}}]
    assert apply_filters(items, ["status=Active"]) == items


def test_compact_is_re_exported_from_models_base():
    # compact lives in models/base.py (models must not import from commands/);
    # _helpers re-exports it so command modules have one import site.
    from cardly_cli.models.base import compact as canonical

    assert compact is canonical
