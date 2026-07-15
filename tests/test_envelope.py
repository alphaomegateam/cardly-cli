import pytest

from cardly_cli.envelope import (
    flatten_validation,
    is_error_state,
    raise_for_state,
    state_messages,
    unwrap,
)
from cardly_cli.errors import CardlyError

OK = {"state": {"status": "OK", "messages": [], "version": 1234}, "data": {"id": "abc"}}


def test_unwrap_returns_data():
    assert unwrap(OK) == {"id": "abc"}


def test_unwrap_passes_through_unenveloped():
    assert unwrap({"id": "abc"}) == {"id": "abc"}
    assert unwrap([1, 2]) == [1, 2]
    assert unwrap(None) is None


def test_unwrap_requires_both_state_and_data():
    # A payload with a `data` key but no `state` is not an envelope.
    assert unwrap({"data": {"x": 1}}) == {"data": {"x": 1}}


def test_unwrap_preserves_falsy_data():
    assert unwrap({"state": {"status": "OK"}, "data": []}) == []


def test_state_messages():
    payload = {"state": {"status": "ERROR", "messages": ["a", "b"]}, "data": {}}
    assert state_messages(payload) == ["a", "b"]
    assert state_messages({"id": 1}) == []


def test_is_error_state():
    assert is_error_state({"state": {"status": "ERROR"}, "data": {}})
    assert not is_error_state(OK)
    assert not is_error_state({"state": {"status": "WARN"}, "data": {}})
    assert not is_error_state({"id": 1})


def test_flatten_validation():
    data = {"email": "This value should be a valid email address.", "postcode": "Required."}
    out = flatten_validation(data)
    assert "email: This value should be a valid email address." in out
    assert "postcode: Required." in out
    assert "; " in out


def test_flatten_validation_non_dict():
    assert flatten_validation(["a"]) == "['a']"
    assert flatten_validation(None) == ""


def test_raise_for_state_raises_on_error_envelope():
    payload = {"state": {"status": "ERROR", "messages": ["Nope."]}, "data": {}}
    with pytest.raises(CardlyError, match="Nope."):
        raise_for_state(payload)


def test_raise_for_state_silent_on_ok():
    raise_for_state(OK)  # must not raise


def test_raise_for_state_carries_status_code():
    payload = {"state": {"status": "ERROR", "messages": ["x"]}, "data": {}}
    with pytest.raises(CardlyError) as ei:
        raise_for_state(payload, status_code=402)
    assert ei.value.exit_code == 8
