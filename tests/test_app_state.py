import httpx
import respx
from typer.testing import CliRunner

from cardly_cli import __version__
from cardly_cli.__main__ import app
from cardly_cli.models.base import CardlyModel, compact

runner = CliRunner()


def test_cardly_model_allows_extra_fields():
    # Cardly ships new fields with builds; carry them rather than drop them.
    model = CardlyModel.model_validate({"known": 1, "surprise": "kept"})
    assert model.model_dump()["surprise"] == "kept"


def test_compact_strips_empties_but_keeps_false_and_zero():
    assert compact({"a": 1, "b": None, "c": "", "d": [], "e": {}}) == {"a": 1}
    # False and 0 are meaningful (shipToMe=false), not absence.
    assert compact({"f": False, "g": 0}) == {"f": False, "g": 0}


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert "cardly" in result.stdout.lower()


def test_root_help_lists_global_flags():
    result = runner.invoke(app, ["--help"])
    for flag in (
        "--profile",
        "--api-key",
        "--base-url",
        "--json",
        "--jq",
        "--quiet",
        "--verbose",
        "--no-color",
        "--no-retry",
        "--max-retries",
        "--idempotency-key",
    ):
        assert flag in result.stdout, f"missing global flag: {flag}"


def test_app_state_is_attached_to_context():
    # AppState carries flags to commands; nothing else can resolve settings.
    from cardly_cli.__main__ import AppState

    assert AppState.__dataclass_fields__["idempotency_key"]
    assert AppState.__dataclass_fields__["base_url"]


def test_missing_key_exits_2(tmp_path):
    result = runner.invoke(
        app,
        ["--config-path", str(tmp_path / "none.toml"), "echo"],
        env={"CARDLY_API_KEY": "", "CARDLY_PROFILE": ""},
    )
    assert result.exit_code == 2
    assert "No API key found" in result.stderr


@respx.mock
def test_base_url_flag_redirects_requests():
    route = respx.post("https://mock.test/v2/echo").mock(
        return_value=httpx.Response(200, json={"state": {"status": "OK"}, "data": {"ok": True}})
    )
    result = runner.invoke(
        app, ["--base-url", "https://mock.test/v2", "--json", "echo"], env={"CARDLY_API_KEY": "k"}
    )
    assert result.exit_code == 0
    assert route.called


@respx.mock
def test_verbose_logs_request_id_but_never_the_key():
    respx.post("https://api.card.ly/v2/echo").mock(
        return_value=httpx.Response(
            200, json={"state": {"status": "OK"}, "data": {}}, headers={"Request-Id": "req_9"}
        )
    )
    result = runner.invoke(app, ["-v", "echo"], env={"CARDLY_API_KEY": "sekrit"})
    assert "req_9" in result.stderr
    assert "sekrit" not in result.stderr
