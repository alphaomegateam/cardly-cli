from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

# Below this wall-clock time, an identical repeat response is assumed to have
# come from Cardly's idempotency store rather than a fresh round trip through
# the processing layer.
CACHED_REPLAY_SECONDS = 0.25


@dataclass(frozen=True)
class AttemptResult:
    """Just enough of a response to compare two attempts."""

    status_code: int | None
    body: bytes


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    enabled: bool = True

    def should_retry(self, *, status_code: int | None, is_timeout: bool, method: str) -> bool:
        if not self.enabled or self.max_retries <= 0:
            return False
        if is_timeout:
            # POST timeouts are the documented headline use case for
            # idempotency keys: the request may have been processed and only
            # the response lost. Replaying with the same key returns the stored
            # result instead of placing a second order. Other verbs carry no
            # key, so a blind replay has no such protection.
            return method.upper() == "POST"
        if status_code is None:
            return False
        if status_code == 429:
            return True
        # 402 (insufficient credit) is deliberately excluded: it is terminal.
        return 500 <= status_code < 600

    def delay_for(self, attempt: int, *, rand: Callable[[], float] = random.random) -> float:
        """Exponential backoff with up to 50% additive jitter."""
        raw = self.base_delay * (2**attempt)
        capped = min(raw, self.max_delay)
        return capped + (capped * 0.5 * rand())


def is_cached_replay(
    previous: AttemptResult | None, current: AttemptResult, elapsed: float
) -> bool:
    """True when a retry looks like it was served from the idempotency store.

    Cardly saves the status code and body against an idempotency key
    "regardless of success" once a request starts processing, and subsequent
    requests with that key return the stored result "without hitting the
    processing layer". So a 5xx that lands after processing began is cached:
    every retry replays it, forever. Duplicate-safe, but futile — bail out
    instead of burning the whole backoff budget re-fetching a fixed answer.

    Heuristic: byte-identical response returned faster than a real round trip.
    """
    if previous is None:
        return False
    if elapsed >= CACHED_REPLAY_SECONDS:
        return False
    return previous.status_code == current.status_code and previous.body == current.body
