import click
import pytest

from cardly_cli.errors import CardlyError, ConfigError, exit_code_for


def test_config_error_exit_code():
    assert ConfigError("no key").exit_code == 2


@pytest.mark.parametrize(
    "status_code,is_timeout,expected",
    [
        (None, True, 7),  # timeout
        (None, False, 7),  # network failure
        (401, False, 3),
        (403, False, 3),
        (404, False, 4),
        (429, False, 5),
        (500, False, 6),
        (503, False, 6),
        (402, False, 8),  # insufficient credit — its own code
        (400, False, 1),
        (422, False, 1),
    ],
)
def test_exit_code_mapping(status_code, is_timeout, expected):
    err = CardlyError("boom", status_code=status_code, is_timeout=is_timeout)
    assert err.exit_code == expected


def test_predicates():
    assert CardlyError("x", status_code=404).is_4xx
    assert not CardlyError("x", status_code=404).is_5xx
    assert CardlyError("x", status_code=500).is_5xx
    assert not CardlyError("x", status_code=None).is_4xx


def test_exit_code_for_click_exception():
    assert exit_code_for(ConfigError("x")) == 2
    assert exit_code_for(CardlyError("x", status_code=402)) == 8
    assert exit_code_for(ValueError("x")) == 1


def test_errors_are_click_exceptions():
    assert isinstance(CardlyError("x"), click.ClickException)
