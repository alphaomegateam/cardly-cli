import json

import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app
from cardly_cli.commands.account import iso_to_cardly

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


@respx.mock
def test_balance_shows_credit_and_gift_credit():
    respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(
            200, json=ok({"balance": 120, "giftCredit": {"balance": 50, "currency": "AUD"}})
        )
    )
    result = runner.invoke(app, ["--json", "account", "balance"], env=ENV)
    payload = json.loads(result.stdout)
    assert payload["balance"] == 120
    assert payload["giftCredit"]["currency"] == "AUD"


def test_iso_to_cardly_converts_and_pads():
    # Space-separated, second precision, NOT ISO-T.
    assert iso_to_cardly("2026-07-01T10:30:00") == "2026-07-01 10:30:00"
    assert iso_to_cardly("2026-07-01 10:30:00") == "2026-07-01 10:30:00"
    # Date-only pads to midnight rather than sending a bare 10-char string.
    assert iso_to_cardly("2026-07-01") == "2026-07-01 00:00:00"
    # Sub-second precision is truncated to 19 chars.
    assert iso_to_cardly("2026-07-01T10:30:00.123456") == "2026-07-01 10:30:00"


@respx.mock
def test_credit_history_sends_all_four_dotted_operators():
    route = respx.get("https://api.card.ly/v2/account/credit-history").mock(
        return_value=httpx.Response(200, json=ok({"meta": {"totalRecords": 0}, "results": []}))
    )
    result = runner.invoke(
        app,
        [
            "--json",
            "account",
            "credit-history",
            "--after",
            "2026-07-01",
            "--before",
            "2026-07-31T23:59:59",
            "--after-exclusive",
            "2026-06-01",
            "--before-exclusive",
            "2026-08-01",
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    params = route.calls.last.request.url.params
    assert params["effectiveTime.gte"] == "2026-07-01 00:00:00"
    assert params["effectiveTime.lte"] == "2026-07-31 23:59:59"
    assert params["effectiveTime.gt"] == "2026-06-01 00:00:00"
    assert params["effectiveTime.lt"] == "2026-08-01 00:00:00"


@respx.mock
def test_gift_credit_history_uses_its_own_endpoint():
    route = respx.get("https://api.card.ly/v2/account/gift-credit-history").mock(
        return_value=httpx.Response(200, json=ok({"meta": {"totalRecords": 0}, "results": []}))
    )
    result = runner.invoke(app, ["--json", "account", "gift-credit-history"], env=ENV)
    assert result.exit_code == 0
    assert route.called
