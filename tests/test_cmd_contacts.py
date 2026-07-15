import json

import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app
from conftest import strip_ansi

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}
BASE = "https://api.card.ly/v2/contact-lists/L1/contacts"


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


@respx.mock
def test_create_sends_locality():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "c1", "firstName": "Ada"}))

    respx.post(BASE).mock(side_effect=handler)
    result = runner.invoke(
        app,
        [
            "contacts",
            "create",
            "L1",
            "--first-name",
            "Ada",
            "--email",
            "ada@example.com",
            "--address",
            "12 Analytical Way",
            "--locality",
            "Melbourne",
            "--country",
            "AU",
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"]["locality"] == "Melbourne"
    assert "city" not in captured["body"]


@respx.mock
def test_create_sends_custom_fields():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "c1"}))

    respx.post(BASE).mock(side_effect=handler)
    runner.invoke(
        app,
        ["contacts", "create", "L1", "--first-name", "Ada", "--field", "birthday=1815-12-10"],
        env=ENV,
    )
    assert captured["body"]["fields"] == {"birthday": "1815-12-10"}


@respx.mock
def test_sync_posts_to_sync_endpoint():
    route = respx.post(f"{BASE}/sync").mock(return_value=httpx.Response(200, json=ok({"id": "c1"})))
    result = runner.invoke(
        app, ["contacts", "sync", "L1", "--external-id", "crm-42", "--first-name", "Ada"], env=ENV
    )
    assert result.exit_code == 0
    assert route.called


@respx.mock
def test_sync_requires_a_match_key():
    # externalId or email is the upsert key; without one the call is pointless.
    route = respx.post(f"{BASE}/sync").mock(return_value=httpx.Response(200, json=ok({"id": "c1"})))
    result = runner.invoke(app, ["contacts", "sync", "L1", "--first-name", "Ada"], env=ENV)
    assert result.exit_code == 2
    stderr = strip_ansi(result.stderr)
    assert "--external-id" in stderr or "--email" in stderr
    assert route.called is False


@respx.mock
def test_sync_accepts_email_as_match_key():
    route = respx.post(f"{BASE}/sync").mock(return_value=httpx.Response(200, json=ok({"id": "c1"})))
    result = runner.invoke(app, ["contacts", "sync", "L1", "--email", "ada@example.com"], env=ENV)
    assert result.exit_code == 0
    assert route.called


@respx.mock
def test_sync_accepts_match_key_supplied_only_via_data():
    # The match-key check reads the merged body, so a key present only in
    # --data (no --email/--external-id flag) must still satisfy it.
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "c1"}))

    respx.post(f"{BASE}/sync").mock(side_effect=handler)
    result = runner.invoke(
        app,
        ["contacts", "sync", "L1", "--data", '{"email": "ada@example.com"}'],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"]["email"] == "ada@example.com"


@respx.mock
def test_create_duplicate_error_points_at_sync():
    respx.post(BASE).mock(
        return_value=httpx.Response(
            422,
            json={
                "state": {"status": "ERROR", "messages": ["Contact already exists."]},
                "data": {"email": "This contact already exists."},
            },
        )
    )
    result = runner.invoke(
        app, ["--no-retry", "contacts", "create", "L1", "--email", "ada@example.com"], env=ENV
    )
    assert result.exit_code == 1
    assert "sync" in result.stderr.lower()


@respx.mock
def test_create_unrelated_422_does_not_mention_sync():
    # Regression: a loose "exist" substring match would fire on this too and
    # wrongly steer the user toward `sync` for a problem sync can't fix.
    respx.post(BASE).mock(
        return_value=httpx.Response(
            422,
            json={
                "state": {"status": "ERROR", "messages": ["Validation failed."]},
                "data": {"listId": "The contact list does not exist."},
            },
        )
    )
    result = runner.invoke(
        app, ["--no-retry", "contacts", "create", "L1", "--email", "ada@example.com"], env=ENV
    )
    assert result.exit_code == 1
    assert "sync" not in result.stderr.lower()


@respx.mock
def test_update_uses_post_not_put():
    route = respx.post(f"{BASE}/c1").mock(return_value=httpx.Response(200, json=ok({"id": "c1"})))
    result = runner.invoke(app, ["contacts", "update", "L1", "c1", "--first-name", "Ada"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.method == "POST"


@respx.mock
def test_find_sends_query():
    route = respx.get(f"{BASE}/find").mock(return_value=httpx.Response(200, json=ok({"id": "c1"})))
    result = runner.invoke(
        app, ["--json", "contacts", "find", "L1", "--query", "ada@x.com"], env=ENV
    )
    assert result.exit_code == 0
    assert route.calls.last.request.url.params["query"] == "ada@x.com"


@respx.mock
def test_get_and_list():
    respx.get(f"{BASE}/c1").mock(return_value=httpx.Response(200, json=ok({"id": "c1"})))
    respx.get(BASE).mock(
        return_value=httpx.Response(
            200, json=ok({"meta": {"totalRecords": 1}, "results": [{"id": "c1"}]})
        )
    )
    assert (
        json.loads(runner.invoke(app, ["--json", "contacts", "get", "L1", "c1"], env=ENV).stdout)[
            "id"
        ]
        == "c1"
    )
    assert (
        json.loads(runner.invoke(app, ["--json", "contacts", "list", "L1"], env=ENV).stdout)[0][
            "id"
        ]
        == "c1"
    )


@respx.mock
def test_delete_requires_confirmation():
    route = respx.delete(f"{BASE}/c1").mock(return_value=httpx.Response(200, json=ok({})))
    runner.invoke(app, ["contacts", "delete", "L1", "c1"], input="n\n", env=ENV)
    assert route.called is False
    result = runner.invoke(app, ["contacts", "delete", "L1", "c1", "--yes"], env=ENV)
    assert result.exit_code == 0
    assert route.called is True


@respx.mock
def test_delete_all_sends_body_to_collection():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content) if request.content else None
        return httpx.Response(200, json=ok({"deleted": 2}))

    respx.delete(BASE).mock(side_effect=handler)
    result = runner.invoke(
        app,
        ["contacts", "delete-all", "L1", "--data", '{"externalIds": ["a", "b"]}', "--yes"],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"] == {"externalIds": ["a", "b"]}


@respx.mock
def test_delete_all_requires_data():
    # A bodyless bulk DELETE has unverified behaviour and could wipe the whole
    # list; require an explicit --data body before any HTTP call is made.
    route = respx.delete(BASE).mock(return_value=httpx.Response(200, json=ok({})))
    result = runner.invoke(app, ["contacts", "delete-all", "L1", "--yes"], env=ENV)
    assert result.exit_code == 2
    assert "--data" in strip_ansi(result.stderr)
    assert route.called is False


@respx.mock
def test_delete_all_requires_confirmation():
    route = respx.delete(BASE).mock(return_value=httpx.Response(200, json=ok({})))
    result = runner.invoke(
        app,
        ["contacts", "delete-all", "L1", "--data", '{"externalIds": ["a", "b"]}'],
        input="n\n",
        env=ENV,
    )
    assert result.exit_code != 0
    assert route.called is False
