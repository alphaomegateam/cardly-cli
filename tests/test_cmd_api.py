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
def test_api_get_unwraps_envelope():
    respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(200, json=ok({"balance": 7}))
    )
    result = runner.invoke(app, ["--json", "api", "GET", "account/balance"], env=ENV)
    assert json.loads(result.stdout) == {"balance": 7}


@respx.mock
def test_api_reaches_endpoints_with_no_dedicated_command():
    # users/ is deferred to v0.2; the escape hatch reaches it today.
    respx.get("https://api.card.ly/v2/users").mock(
        return_value=httpx.Response(200, json=ok({"meta": {"totalRecords": 0}, "results": []}))
    )
    result = runner.invoke(app, ["--json", "api", "GET", "users"], env=ENV)
    assert result.exit_code == 0


@respx.mock
def test_api_sends_params_and_body():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=ok({"ok": True}))

    respx.post("https://api.card.ly/v2/orders/preview").mock(side_effect=handler)
    result = runner.invoke(
        app,
        ["api", "POST", "orders/preview", "-p", "x=1", "-d", '{"artwork": "a"}'],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"] == {"artwork": "a"}
    assert captured["params"] == {"x": "1"}


@respx.mock
def test_api_post_carries_idempotency_key():
    route = respx.post("https://api.card.ly/v2/echo").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    runner.invoke(app, ["api", "POST", "echo"], env=ENV)
    assert "Idempotency-Key" in route.calls.last.request.headers


@respx.mock
def test_api_all_paginates():
    responses = [
        httpx.Response(
            200,
            json=ok(
                {
                    "meta": {"totalRecords": 2, "limit": 1, "page": 1, "lastRecord": 1},
                    "results": [{"id": 1}],
                }
            ),
        ),
        httpx.Response(
            200,
            json=ok(
                {
                    "meta": {"totalRecords": 2, "limit": 1, "page": 2, "lastRecord": 2},
                    "results": [{"id": 2}],
                }
            ),
        ),
    ]
    respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    result = runner.invoke(
        app, ["--json", "api", "GET", "orders", "--all", "--limit", "1"], env=ENV
    )
    assert json.loads(result.stdout) == [{"id": 1}, {"id": 2}]


@respx.mock
def test_api_all_rejects_non_get():
    # I4: no @respx.mock previously meant this test would happily hit the real
    # API if the local guard ever broke — the exact shape fixed twice
    # elsewhere. Register the route and assert it's never called.
    route = respx.post("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(app, ["api", "POST", "orders", "--all"], env=ENV)
    assert result.exit_code == 2
    assert "GET" in result.stderr
    assert not route.called
