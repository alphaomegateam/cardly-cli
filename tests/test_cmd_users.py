import json

import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


def page(results):
    return ok({"meta": {"totalRecords": len(results)}, "results": results})


@respx.mock
def test_users_list():
    respx.get("https://api.card.ly/v2/users").mock(
        return_value=httpx.Response(200, json=page([{"id": "u1", "email": "a@x.com"}]))
    )
    result = runner.invoke(app, ["--json", "users", "list"], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["id"] == "u1"


@respx.mock
def test_users_get():
    respx.get("https://api.card.ly/v2/users/u1").mock(
        return_value=httpx.Response(200, json=ok({"id": "u1", "email": "a@x.com"}))
    )
    result = runner.invoke(app, ["--json", "users", "get", "u1"], env=ENV)
    assert json.loads(result.stdout)["email"] == "a@x.com"


@respx.mock
def test_users_find_sends_email_query():
    route = respx.get("https://api.card.ly/v2/users/find").mock(
        return_value=httpx.Response(200, json=ok({"id": "u1"}))
    )
    result = runner.invoke(app, ["--json", "users", "find", "--email", "a@x.com"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.url.params["email"] == "a@x.com"


@respx.mock
def test_users_delete_by_id():
    route = respx.delete("https://api.card.ly/v2/users/u1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(app, ["users", "delete", "u1", "--yes"], env=ENV)
    assert result.exit_code == 0
    assert route.called


@respx.mock
def test_users_delete_by_email_posts_body_to_collection():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({}))

    respx.delete("https://api.card.ly/v2/users").mock(side_effect=handler)
    result = runner.invoke(app, ["users", "delete", "--email", "a@x.com", "--yes"], env=ENV)
    assert result.exit_code == 0
    assert captured["body"] == {"email": "a@x.com"}


@respx.mock
def test_users_delete_requires_exactly_one_form():
    by_id = respx.delete("https://api.card.ly/v2/users/u1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    coll = respx.delete("https://api.card.ly/v2/users").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    # Neither form given.
    neither = runner.invoke(app, ["users", "delete", "--yes"], env=ENV)
    assert neither.exit_code == 2
    # Both forms given.
    both = runner.invoke(app, ["users", "delete", "u1", "--email", "a@x.com", "--yes"], env=ENV)
    assert both.exit_code == 2
    # Neither call may have been made.
    assert not by_id.called
    assert not coll.called


@respx.mock
def test_users_delete_declining_makes_no_request():
    route = respx.delete("https://api.card.ly/v2/users/u1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    runner.invoke(app, ["users", "delete", "u1"], input="n\n", env=ENV)
    assert not route.called
