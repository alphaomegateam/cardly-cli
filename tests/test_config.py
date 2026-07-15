import pytest

from cardly_cli.config import (
    DEFAULT_BASE_URL,
    CardlySettings,
    config_file_path,
    list_profiles,
    load_settings,
    write_profile,
)
from cardly_cli.errors import ConfigError

CONFIG = """\
default_profile = "prod"

[profile.prod]
api_key = "live_abc"
base_url = "https://api.card.ly/v2"

[profile.sandbox]
api_key_cmd = "printf test_xyz"
base_url = "https://api.card.ly/v2"
"""


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    return path


def test_default_base_url():
    assert DEFAULT_BASE_URL == "https://api.card.ly/v2"


def test_config_file_path_honors_xdg(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert config_file_path(env=env) == tmp_path / "cardly" / "config.toml"


def test_flag_beats_env_beats_profile(config_path):
    s = load_settings(api_key="flag", env={"CARDLY_API_KEY": "env"}, config_path=config_path)
    assert s.api_key == "flag"

    s = load_settings(env={"CARDLY_API_KEY": "env"}, config_path=config_path)
    assert s.api_key == "env"

    s = load_settings(env={}, config_path=config_path)
    assert s.api_key == "live_abc"  # default_profile = prod


def test_profile_selected_by_flag_and_env(config_path):
    s = load_settings(profile="sandbox", env={}, config_path=config_path)
    assert s.api_key == "test_xyz"  # resolved via api_key_cmd

    s = load_settings(env={"CARDLY_PROFILE": "sandbox"}, config_path=config_path)
    assert s.api_key == "test_xyz"


def test_api_key_cmd_shells_out(config_path):
    s = load_settings(profile="sandbox", env={}, config_path=config_path)
    assert s.api_key == "test_xyz"


def test_api_key_cmd_failure_raises_config_error(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('[profile.p]\napi_key_cmd = "false"\n')
    with pytest.raises(ConfigError, match="api_key_cmd failed"):
        load_settings(profile="p", env={}, config_path=path)


def test_base_url_precedence_and_trailing_slash(config_path):
    s = load_settings(base_url="https://x/v2/", env={}, config_path=config_path)
    assert s.base_url == "https://x/v2"

    s = load_settings(env={"CARDLY_BASE_URL": "https://y/v2"}, config_path=config_path)
    assert s.base_url == "https://y/v2"


def test_missing_key_raises_config_error(tmp_path):
    with pytest.raises(ConfigError, match="No API key found"):
        load_settings(env={}, config_path=tmp_path / "missing.toml")


def test_unknown_profile_raises_config_error(config_path):
    with pytest.raises(ConfigError, match="not found"):
        load_settings(profile="nope", env={}, config_path=config_path)


def test_settings_has_no_slug():
    # Cardly's base URL is flat — a slug field would be meaningless here.
    assert not hasattr(CardlySettings(api_key="k", base_url="u"), "slug")


def test_list_profiles(config_path):
    profiles = list_profiles(config_path=config_path)
    assert profiles["prod"]["has_key"] is True
    assert profiles["prod"]["default"] is True
    assert profiles["sandbox"]["has_key"] is True
    assert profiles["sandbox"]["default"] is False


def test_write_profile_roundtrip_and_chmod(tmp_path):
    path = tmp_path / "new.toml"
    write_profile("dev", api_key="test_1", make_default=True, config_path=path)
    assert (path.stat().st_mode & 0o777) == 0o600
    s = load_settings(env={}, config_path=path)
    assert s.api_key == "test_1"


def test_write_profile_supports_api_key_cmd(tmp_path):
    path = tmp_path / "new.toml"
    write_profile("dev", api_key_cmd="printf zzz", make_default=True, config_path=path)
    assert load_settings(env={}, config_path=path).api_key == "zzz"
