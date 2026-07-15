import json

from typer.testing import CliRunner

from cardly_cli.__main__ import app
from cardly_cli.config import load_settings

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
    assert "--api-key" in result.stderr or "--api-key" in result.stdout


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
    assert payload["prod"]["has_key"] is True


def test_configure_set_make_default(tmp_path):
    path = tmp_path / "config.toml"
    runner.invoke(app, ["--config-path", str(path), "configure", "set", "a", "--api-key", "1"])
    runner.invoke(
        app, ["--config-path", str(path), "configure", "set", "b", "--api-key", "2", "--default"]
    )
    assert load_settings(env={}, config_path=path).api_key == "2"
