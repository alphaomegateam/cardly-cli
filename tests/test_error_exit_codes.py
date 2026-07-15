import httpx
import pytest
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


def err(messages):
    return {"state": {"status": "ERROR", "messages": messages}}


@pytest.mark.parametrize(
    "status,expected",
    [(401, 3), (403, 3), (404, 4), (402, 8), (422, 1), (400, 1), (429, 5), (500, 6), (503, 6)],
)
@respx.mock
def test_http_status_maps_to_exit_code(status, expected):
    respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(status, json=err(["nope"]))
    )
    result = runner.invoke(app, ["--no-retry", "account", "balance"], env=ENV)
    assert result.exit_code == expected


@respx.mock
def test_timeout_exits_7():
    respx.get("https://api.card.ly/v2/account/balance").mock(side_effect=httpx.ConnectTimeout("t"))
    result = runner.invoke(app, ["--no-retry", "account", "balance"], env=ENV)
    assert result.exit_code == 7


@respx.mock
def test_402_carries_its_message_and_exits_8():
    # 402 gets its own code because a scheduled job must treat it differently:
    # not transient, not a bug — top up the account.
    respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(402, json=err(["Insufficient credit: need 5, have 2."]))
    )
    result = runner.invoke(app, ["--no-retry", "account", "balance"], env=ENV)
    assert result.exit_code == 8
    assert "Insufficient credit" in result.stderr


@respx.mock
def test_error_message_goes_to_stderr_cleanly():
    respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(404, json=err(["Not found."]))
    )
    result = runner.invoke(app, ["--no-retry", "account", "balance"], env=ENV)
    assert result.stderr.startswith("Error:")
    assert "Traceback" not in result.stderr
