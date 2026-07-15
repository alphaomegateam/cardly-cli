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


@respx.mock
def test_app_state_is_attached_to_context():
    # AppState carries flags to commands; nothing else can resolve settings.
    # Exercise it end to end: invoke a command with distinguishing flags and
    # confirm ctx.obj really is a populated AppState carrying them through
    # to behavior (a pinned idempotency key on the POST that echo issues).
    route = respx.post("https://api.card.ly/v2/echo").mock(
        return_value=httpx.Response(200, json={"state": {"status": "OK"}, "data": {}})
    )
    result = runner.invoke(
        app,
        ["--idempotency-key", "ctx-test-123", "--base-url", "https://api.card.ly/v2", "echo"],
        env={"CARDLY_API_KEY": "k"},
    )
    assert result.exit_code == 0
    assert route.calls.last.request.headers["Idempotency-Key"] == "ctx-test-123"


def test_api_key_is_absent_from_app_state_repr():
    # Same latent leak CardlySettings already had `field(repr=False)` for.
    # Not exploitable today (nothing currently prints an AppState), but a
    # one-word fix, and a repr/log/traceback that captures ctx.obj later must
    # not carry the live key.
    from cardly_cli.__main__ import AppState

    state = AppState(
        profile=None,
        api_key="super-secret-key",
        base_url=None,
        json_out=False,
        jq=None,
        quiet=False,
        verbose=False,
        no_color=False,
        no_retry=False,
        max_retries=3,
        idempotency_key=None,
    )
    assert "super-secret-key" not in repr(state)


@respx.mock
def test_table_output_is_pipe_safe_under_force_color(monkeypatch):
    # I3: Console(no_color=True) alone still emits bold/style ANSI codes under
    # FORCE_COLOR — only the JSON path avoided this (deliberately, per a
    # comment in output.py). Set FORCE_COLOR explicitly here rather than
    # relying on the autouse conftest fixture, which strips it and would mask
    # this exact regression.
    monkeypatch.setenv("FORCE_COLOR", "3")
    respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(200, json={"state": {"status": "OK"}, "data": {"balance": 42}})
    )
    result = runner.invoke(app, ["account", "balance"], env={"CARDLY_API_KEY": "k"})
    assert result.exit_code == 0
    assert "\x1b[" not in result.stdout


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
