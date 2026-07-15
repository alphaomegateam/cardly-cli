import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


@respx.mock
def test_echo_posts_and_reports():
    route = respx.post("https://api.card.ly/v2/echo").mock(
        return_value=httpx.Response(200, json={"state": {"status": "OK"}, "data": {"ok": True}})
    )
    result = runner.invoke(app, ["--json", "echo"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.headers["API-Key"] == "k"


@respx.mock
def test_echo_passes_test_param():
    route = respx.post("https://api.card.ly/v2/echo").mock(
        return_value=httpx.Response(200, json={"state": {"status": "OK"}, "data": {"test": "hi"}})
    )
    result = runner.invoke(app, ["--json", "echo", "--test", "hi"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.url.params["test"] == "hi"


@respx.mock
def test_echo_401_exits_3():
    respx.post("https://api.card.ly/v2/echo").mock(
        return_value=httpx.Response(
            401, json={"state": {"status": "ERROR", "messages": ["bad key"]}}
        )
    )
    result = runner.invoke(app, ["--no-retry", "echo"], env=ENV)
    assert result.exit_code == 3
