from cardly_cli.retry import AttemptResult, RetryPolicy, is_cached_replay


def test_retries_429_and_5xx():
    p = RetryPolicy()
    assert p.should_retry(status_code=429, is_timeout=False, method="GET")
    assert p.should_retry(status_code=500, is_timeout=False, method="GET")
    assert p.should_retry(status_code=503, is_timeout=False, method="POST")


def test_does_not_retry_4xx_or_success():
    p = RetryPolicy()
    assert not p.should_retry(status_code=200, is_timeout=False, method="GET")
    assert not p.should_retry(status_code=404, is_timeout=False, method="GET")
    assert not p.should_retry(status_code=422, is_timeout=False, method="POST")
    # 402 is terminal: retrying will never conjure credit.
    assert not p.should_retry(status_code=402, is_timeout=False, method="POST")


def test_retries_post_timeouts_but_not_get_timeouts():
    p = RetryPolicy()
    # POST timeouts are the canonical idempotency-key use case: the order may
    # have landed and only the response was lost.
    assert p.should_retry(status_code=None, is_timeout=True, method="POST")
    # Without a key there is no replay protection, so don't retry blind.
    assert not p.should_retry(status_code=None, is_timeout=True, method="GET")


def test_disabled_policy_never_retries():
    p = RetryPolicy(enabled=False)
    assert not p.should_retry(status_code=429, is_timeout=False, method="GET")
    assert not p.should_retry(status_code=None, is_timeout=True, method="POST")


def test_zero_max_retries_never_retries():
    p = RetryPolicy(max_retries=0)
    assert not p.should_retry(status_code=429, is_timeout=False, method="GET")


def test_delay_grows_exponentially_and_clamps():
    p = RetryPolicy(base_delay=1.0, max_delay=8.0)
    fixed = lambda: 0.0  # noqa: E731 — no jitter, test the schedule itself
    assert p.delay_for(0, rand=fixed) == 1.0
    assert p.delay_for(1, rand=fixed) == 2.0
    assert p.delay_for(2, rand=fixed) == 4.0
    assert p.delay_for(3, rand=fixed) == 8.0
    assert p.delay_for(9, rand=fixed) == 8.0  # clamped


def test_delay_applies_jitter_within_bounds():
    p = RetryPolicy(base_delay=1.0, max_delay=8.0)
    full = p.delay_for(1, rand=lambda: 1.0)
    none = p.delay_for(1, rand=lambda: 0.0)
    assert none == 2.0
    assert 2.0 < full <= 3.0  # jitter adds up to 50%


def test_cached_replay_detected_on_identical_fast_response():
    prev = AttemptResult(status_code=500, body=b'{"state":{"status":"ERROR"}}')
    curr = AttemptResult(status_code=500, body=b'{"state":{"status":"ERROR"}}')
    # Returned instantly and byte-identical -> served from the idempotency
    # layer, not reprocessed. Retrying again is futile.
    assert is_cached_replay(prev, curr, elapsed=0.01)


def test_cached_replay_not_flagged_when_slow():
    prev = AttemptResult(status_code=500, body=b"x")
    curr = AttemptResult(status_code=500, body=b"x")
    assert not is_cached_replay(prev, curr, elapsed=2.0)


def test_cached_replay_not_flagged_when_body_differs():
    prev = AttemptResult(status_code=500, body=b"x")
    curr = AttemptResult(status_code=500, body=b"y")
    assert not is_cached_replay(prev, curr, elapsed=0.01)


def test_cached_replay_needs_a_previous_attempt():
    curr = AttemptResult(status_code=500, body=b"x")
    assert not is_cached_replay(None, curr, elapsed=0.01)
