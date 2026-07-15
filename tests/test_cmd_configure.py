import json

from typer.testing import CliRunner

from cardly_cli.__main__ import app
from cardly_cli.config import load_settings
from conftest import strip_ansi

runner = CliRunner()


def test_configure_set_writes_profile(tmp_path):
    path = tmp_path / "config.toml"
    result = runner.invoke(
        app,
        ["--config-path", str(path), "configure", "set", "prod", "--api-key", "live_abc"],
    )
    assert result.exit_code == 0
    assert load_settings(env={}, config_path=path).api_key == "live_abc"


def test_configure_set_supports_api_key_cmd(tmp_path):
    path = tmp_path / "config.toml"
    result = runner.invoke(
        app,
        [
            "--config-path",
            str(path),
            "configure",
            "set",
            "sandbox",
            "--api-key-cmd",
            "printf test_xyz",
        ],
    )
    assert result.exit_code == 0
    assert load_settings(env={}, config_path=path).api_key == "test_xyz"


def test_configure_set_requires_a_key_source(tmp_path):
    path = tmp_path / "config.toml"
    result = runner.invoke(app, ["--config-path", str(path), "configure", "set", "p"])
    assert result.exit_code != 0
    assert "--api-key" in strip_ansi(result.stderr) or "--api-key" in strip_ansi(result.stdout)


def test_configure_set_rejects_both_key_sources(tmp_path):
    path = tmp_path / "config.toml"
    result = runner.invoke(
        app,
        [
            "--config-path",
            str(path),
            "configure",
            "set",
            "p",
            "--api-key",
            "k",
            "--api-key-cmd",
            "printf k",
        ],
    )
    assert result.exit_code != 0


def test_configure_list_never_prints_the_key(tmp_path):
    path = tmp_path / "config.toml"
    runner.invoke(
        app, ["--config-path", str(path), "configure", "set", "prod", "--api-key", "live_SECRET"]
    )
    result = runner.invoke(app, ["--config-path", str(path), "--json", "configure", "list"])
    assert result.exit_code == 0
    assert "live_SECRET" not in result.stdout
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    prod_row = next((row for row in payload if row["name"] == "prod"), None)
    assert prod_row is not None
    assert prod_row["has_key"] is True


def test_configure_set_make_default(tmp_path):
    path = tmp_path / "config.toml"
    runner.invoke(app, ["--config-path", str(path), "configure", "set", "a", "--api-key", "1"])
    runner.invoke(
        app, ["--config-path", str(path), "configure", "set", "b", "--api-key", "2", "--default"]
    )
    assert load_settings(env={}, config_path=path).api_key == "2"


def test_configure_set_first_profile_implicitly_becomes_default(tmp_path):
    path = tmp_path / "config.toml"
    result = runner.invoke(
        app, ["--config-path", str(path), "configure", "set", "prod", "--api-key", "live_first"]
    )
    assert result.exit_code == 0
    assert "now the default" in result.stderr
    assert load_settings(env={}, config_path=path).api_key == "live_first"
