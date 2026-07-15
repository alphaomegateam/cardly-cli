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


@respx.mock
def test_invitations_create_sends_email_and_permissions():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "i1"}))

    respx.post("https://api.card.ly/v2/invitations").mock(side_effect=handler)
    result = runner.invoke(
        app,
        [
            "invitations",
            "create",
            "--email",
            "a@x.com",
            "--first-name",
            "Ada",
            "--permission",
            "orders",
            "--permission",
            "use-credits",
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"]["email"] == "a@x.com"
    assert captured["body"]["firstName"] == "Ada"
    assert captured["body"]["permissions"] == ["orders", "use-credits"]


@respx.mock
def test_invitations_create_rejects_unknown_permission_locally():
    route = respx.post("https://api.card.ly/v2/invitations").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(
        app, ["invitations", "create", "--email", "a@x.com", "--permission", "banana"], env=ENV
    )
    assert result.exit_code == 2
    assert "banana" in result.stderr
    assert not route.called


@respx.mock
def test_invitations_resend_by_id_and_by_email():
    by_id = respx.post("https://api.card.ly/v2/invitations/resend/i1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(app, ["invitations", "resend", "i1"], env=ENV)
    assert result.exit_code == 0
    assert by_id.called

    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({}))

    respx.post("https://api.card.ly/v2/invitations/resend").mock(side_effect=handler)
    result = runner.invoke(app, ["invitations", "resend", "--email", "a@x.com"], env=ENV)
    assert result.exit_code == 0
    assert captured["body"] == {"email": "a@x.com"}


@respx.mock
def test_invitations_resend_requires_exactly_one_form():
    by_id = respx.post("https://api.card.ly/v2/invitations/resend/i1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    coll = respx.post("https://api.card.ly/v2/invitations/resend").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    assert runner.invoke(app, ["invitations", "resend"], env=ENV).exit_code == 2
    assert (
        runner.invoke(app, ["invitations", "resend", "i1", "--email", "a@x.com"], env=ENV).exit_code
        == 2
    )
    assert not by_id.called
    assert not coll.called


@respx.mock
def test_invitations_delete_by_id_and_by_email():
    by_id = respx.delete("https://api.card.ly/v2/invitations/i1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    assert runner.invoke(app, ["invitations", "delete", "i1", "--yes"], env=ENV).exit_code == 0
    assert by_id.called

    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({}))

    respx.delete("https://api.card.ly/v2/invitations").mock(side_effect=handler)
    result = runner.invoke(app, ["invitations", "delete", "--email", "a@x.com", "--yes"], env=ENV)
    assert result.exit_code == 0
    assert captured["body"] == {"email": "a@x.com"}


@respx.mock
def test_invitations_delete_declining_makes_no_request():
    route = respx.delete("https://api.card.ly/v2/invitations/i1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    runner.invoke(app, ["invitations", "delete", "i1"], input="n\n", env=ENV)
    assert not route.called
