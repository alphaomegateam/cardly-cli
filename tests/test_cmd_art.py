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
def test_art_list():
    respx.get("https://api.card.ly/v2/art").mock(
        return_value=httpx.Response(
            200, json=ok({"meta": {"totalRecords": 1}, "results": [{"id": "a1", "name": "Thanks"}]})
        )
    )
    result = runner.invoke(app, ["--json", "art", "list"], env=ENV)
    assert json.loads(result.stdout)[0]["id"] == "a1"


@respx.mock
def test_art_list_own_only_uses_ownOnly_param():
    # /art uses ownOnly. The ref endpoints use organisationOnly. Different names.
    route = respx.get("https://api.card.ly/v2/art").mock(
        return_value=httpx.Response(200, json=ok({"meta": {"totalRecords": 0}, "results": []}))
    )
    result = runner.invoke(app, ["--json", "art", "list", "--own-only"], env=ENV)
    assert result.exit_code == 0
    params = route.calls.last.request.url.params
    assert params["ownOnly"] == "true"
    assert "organisationOnly" not in params


@respx.mock
def test_art_get_accepts_a_slug():
    respx.get("https://api.card.ly/v2/art/happy-birthday").mock(
        return_value=httpx.Response(200, json=ok({"id": "a1", "slug": "happy-birthday"}))
    )
    result = runner.invoke(app, ["--json", "art", "get", "happy-birthday"], env=ENV)
    assert json.loads(result.stdout)["slug"] == "happy-birthday"


def test_art_upload_is_not_in_v0_1():
    # Deferred to v0.2: POST /art is application/json with base64-embedded
    # images, which needs its own task and a body-size measurement.
    result = runner.invoke(app, ["art", "upload", "x.png"], env=ENV)
    assert result.exit_code != 0
