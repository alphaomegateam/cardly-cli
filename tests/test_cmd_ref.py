import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


def ok(results):
    return {
        "state": {"status": "OK", "messages": [], "version": 1},
        "data": {"meta": {"totalRecords": len(results)}, "results": results},
    }


@pytest.mark.parametrize(
    "command,endpoint",
    [
        ("fonts", "fonts"),
        ("writing-styles", "writing-styles"),
        ("doodles", "doodles"),
        ("templates", "templates"),
        ("media", "media"),
    ],
)
@respx.mock
def test_ref_commands_hit_their_endpoints(command, endpoint):
    respx.get(f"https://api.card.ly/v2/{endpoint}").mock(
        return_value=httpx.Response(200, json=ok([{"id": "1", "name": "X"}]))
    )
    result = runner.invoke(app, ["--json", "ref", command], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["id"] == "1"


@pytest.mark.parametrize(
    "command,endpoint", [("fonts", "fonts"), ("doodles", "doodles"), ("media", "media")]
)
@respx.mock
def test_organisation_only_supported_where_declared(command, endpoint):
    route = respx.get(f"https://api.card.ly/v2/{endpoint}").mock(
        return_value=httpx.Response(200, json=ok([]))
    )
    result = runner.invoke(app, ["--json", "ref", command, "--organisation-only"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.url.params["organisationOnly"] == "true"


@pytest.mark.parametrize("command", ["writing-styles", "templates"])
def test_organisation_only_absent_where_not_declared(command):
    # Only fonts, doodles and media declare organisationOnly.
    result = runner.invoke(app, ["ref", command, "--organisation-only"], env=ENV)
    assert result.exit_code == 2
    assert "no such option" in result.stderr.lower()
