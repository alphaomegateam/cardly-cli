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
def test_invitations_list():
    respx.get("https://api.card.ly/v2/invitations").mock(
        return_value=httpx.Response(200, json=page([{"id": "i1", "email": "a@x.com"}]))
    )
    result = runner.invoke(app, ["--json", "invitations", "list"], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["id"] == "i1"


@respx.mock
def test_invitations_list_sends_no_filters_by_default():
    route = respx.get("https://api.card.ly/v2/invitations").mock(
        return_value=httpx.Response(200, json=page([]))
    )
    runner.invoke(app, ["--json", "invitations", "list"], env=ENV)
    params = route.calls.last.request.url.params
    assert "acceptedOnly" not in params
    assert "expiredOnly" not in params
    assert "includeAccepted" not in params


@respx.mock
def test_invitations_list_filter_flags():
    route = respx.get("https://api.card.ly/v2/invitations").mock(
        return_value=httpx.Response(200, json=page([]))
    )
    runner.invoke(app, ["--json", "invitations", "list", "--include-accepted"], env=ENV)
    assert route.calls.last.request.url.params["includeAccepted"] == "true"

    runner.invoke(app, ["--json", "invitations", "list", "--accepted-only"], env=ENV)
    assert route.calls.last.request.url.params["acceptedOnly"] == "true"

    runner.invoke(app, ["--json", "invitations", "list", "--expired-only"], env=ENV)
    assert route.calls.last.request.url.params["expiredOnly"] == "true"


@respx.mock
def test_invitations_get():
    respx.get("https://api.card.ly/v2/invitations/i1").mock(
        return_value=httpx.Response(200, json=ok({"id": "i1", "status": "pending"}))
    )
    result = runner.invoke(app, ["--json", "invitations", "get", "i1"], env=ENV)
    assert json.loads(result.stdout)["status"] == "pending"


@respx.mock
def test_invitations_find_sends_email_query():
    route = respx.get("https://api.card.ly/v2/invitations/find").mock(
        return_value=httpx.Response(200, json=ok({"id": "i1"}))
    )
    result = runner.invoke(app, ["--json", "invitations", "find", "--email", "a@x.com"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.url.params["email"] == "a@x.com"


def test_permissions_enum_is_complete():
    from cardly_cli.models.invitation import PERMISSIONS

    assert set(PERMISSIONS) == {
        "administrator",
        "artwork",
        "billing",
        "campaigns",
        "developer",
        "lists",
        "moderate",
        "moderate-history",
        "orders",
        "templates",
        "users",
        "use-credits",
        "use-saved-card",
    }
