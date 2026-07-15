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
