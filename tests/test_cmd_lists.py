import json

import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


@respx.mock
def test_lists_list():
    respx.get("https://api.card.ly/v2/contact-lists").mock(
        return_value=httpx.Response(
            200, json=ok({"meta": {"totalRecords": 1}, "results": [{"id": "L1", "name": "VIPs"}]})
        )
    )
    result = runner.invoke(app, ["--json", "lists", "list"], env=ENV)
    assert json.loads(result.stdout)[0]["name"] == "VIPs"


@respx.mock
def test_lists_get():
    respx.get("https://api.card.ly/v2/contact-lists/L1").mock(
        return_value=httpx.Response(200, json=ok({"id": "L1", "name": "VIPs"}))
    )
    result = runner.invoke(app, ["--json", "lists", "get", "L1"], env=ENV)
    assert json.loads(result.stdout)["id"] == "L1"


@respx.mock
def test_lists_create_with_fields():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "L2", "name": "Leads"}))

    respx.post("https://api.card.ly/v2/contact-lists").mock(side_effect=handler)
    result = runner.invoke(
        app,
        [
            "lists",
            "create",
            "--name",
            "Leads",
            "--description",
            "From CRM",
            "--field",
            "birthday:date",
            "--field",
            "notes",
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"]["name"] == "Leads"
    assert captured["body"]["description"] == "From CRM"
    assert captured["body"]["fields"] == [
        {"name": "birthday", "type": "date"},
        {"name": "notes", "type": "text"},  # type defaults to text
    ]


def test_lists_create_rejects_bad_field_type():
    result = runner.invoke(app, ["lists", "create", "--name", "X", "--field", "a:banana"], env=ENV)
    assert result.exit_code == 2
    assert "banana" in result.stderr


@respx.mock
def test_lists_delete_requires_confirmation():
    route = respx.delete("https://api.card.ly/v2/contact-lists/L1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    runner.invoke(app, ["lists", "delete", "L1"], input="n\n", env=ENV)
    assert route.called is False
    result = runner.invoke(app, ["lists", "delete", "L1", "--yes"], env=ENV)
    assert result.exit_code == 0
    assert route.called is True


def test_no_update_command_exists():
    # Cardly has no contact-list update endpoint. A list's name/description
    # cannot be edited via the API. This absence is deliberate.
    result = runner.invoke(app, ["lists", "update", "L1", "--name", "X"], env=ENV)
    assert result.exit_code != 0
    assert "No such command" in result.stderr or "no such command" in result.stderr.lower()
