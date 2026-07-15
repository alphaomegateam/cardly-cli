from __future__ import annotations

from typing import Any

from cardly_cli.errors import CardlyError


def _is_envelope(payload: Any) -> bool:
    return isinstance(payload, dict) and "state" in payload and "data" in payload


def unwrap(payload: Any) -> Any:
    """Return the `data` member of Cardly's {state, data} envelope.

    Every Cardly response is enveloped. Unwrapping lives here so commands never
    parse response shapes themselves. Non-enveloped payloads pass through, which
    keeps the `api` escape hatch and error paths simple.
    """
    if _is_envelope(payload):
        return payload["data"]
    return payload


def state_messages(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    state = payload.get("state")
    if not isinstance(state, dict):
        return []
    messages = state.get("messages")
    return [str(m) for m in messages] if isinstance(messages, list) else []


def is_error_state(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    state = payload.get("state")
    return isinstance(state, dict) and state.get("status") == "ERROR"


def flatten_validation(data: Any) -> str:
    """Flatten a 422 ValidationStatus ({field: reason}) into readable text.

    Cardly returns validation failures as a flat field->reason map. Dumping raw
    JSON at the user is worse than a sentence.
    """
    if data is None:
        return ""
    if not isinstance(data, dict):
        return str(data)
    return "; ".join(f"{field}: {reason}" for field, reason in data.items())


def raise_for_state(payload: Any, *, status_code: int | None = None) -> None:
    """Raise when a 200-shaped envelope carries state.status == ERROR.

    Cardly signals failure in two places: the HTTP status, and state.status
    inside an otherwise-200 body. Checking the status code alone misses this.
    """
    if not is_error_state(payload):
        return
    messages = state_messages(payload)
    text = " ".join(messages) if messages else "Cardly returned an error state."
    raise CardlyError(text, status_code=status_code)
