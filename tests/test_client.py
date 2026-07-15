import httpx
import pytest
import respx

from cardly_cli.client import TIMEOUT, CardlyClient, url_for
from cardly_cli.config import CardlySettings
from cardly_cli.errors import CardlyError
from cardly_cli.retry import RetryPolicy

SETTINGS = CardlySettings(api_key="test_key", base_url="https://api.card.ly/v2")
NO_RETRY = RetryPolicy(enabled=False)


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


def test_url_for_joins_parts():
    assert url_for(SETTINGS, "orders") == "https://api.card.ly/v2/orders"
    assert url_for(SETTINGS, "/orders/1") == "https://api.card.ly/v2/orders/1"


def test_url_for_passes_through_absolute_urls():
    # Task 13's preview-PDF download hits a fully-qualified URL returned by the
    # API itself; url_for must not try to prefix it with base_url.
    absolute = "https://cdn.card.ly/previews/abc123.pdf"
    assert url_for(SETTINGS, absolute) == absolute
    # http:// is upgraded to https:// so the API key never crosses the wire
    # in plaintext (Cardly returns preview URLs as http://).
    assert url_for(SETTINGS, "http://cdn.card.ly/previews/abc123.pdf") == (
        "https://cdn.card.ly/previews/abc123.pdf"
    )


def test_timeout_default():
    assert TIMEOUT == 30.0


@respx.mock
def test_sends_api_key_header_not_bearer():
    route = respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(200, json=ok({"balance": 100}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert c.get("account/balance") == {"balance": 100}
    headers = route.calls.last.request.headers
    assert headers["API-Key"] == "test_key"
    assert "Authorization" not in headers


@respx.mock
def test_unwraps_envelope():
    respx.get("https://api.card.ly/v2/orders/9").mock(
        return_value=httpx.Response(200, json=ok({"id": "9"}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert c.get("orders/9") == {"id": "9"}


@respx.mock
def test_raises_on_error_state_inside_200():
    # Cardly can signal failure inside a 200-shaped envelope.
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(
            200, json={"state": {"status": "ERROR", "messages": ["Nope."]}, "data": {}}
        )
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        with pytest.raises(CardlyError, match="Nope."):
            c.get("orders")


@respx.mock
def test_402_maps_to_exit_code_8_and_includes_messages():
    respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(
            402,
            json={
                "state": {"status": "ERROR", "messages": ["Insufficient credit: need 5, have 2."]}
            },
        )
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        with pytest.raises(CardlyError) as ei:
            c.post("orders/place", json={"lines": []})
    assert ei.value.exit_code == 8
    assert "Insufficient credit" in str(ei.value)


@respx.mock
def test_422_flattens_validation_map():
    respx.post("https://api.card.ly/v2/contact-lists/1/contacts").mock(
        return_value=httpx.Response(
            422,
            json={
                "state": {"status": "ERROR", "messages": ["Validation failed."]},
                "data": {"email": "This value should be a valid email address."},
            },
        )
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        with pytest.raises(CardlyError) as ei:
            c.post("contact-lists/1/contacts", json={})
    msg = str(ei.value)
    assert "email: This value should be a valid email address." in msg
    assert ei.value.status_code == 422


@respx.mock
def test_404_raises_with_status():
    respx.get("https://api.card.ly/v2/orders/nope").mock(
        return_value=httpx.Response(404, json={"state": {"status": "ERROR", "messages": ["Gone."]}})
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        with pytest.raises(CardlyError) as ei:
            c.get("orders/nope")
    assert ei.value.exit_code == 4


@respx.mock
def test_error_message_never_contains_api_key():
    respx.get("https://api.card.ly/v2/orders").mock(return_value=httpx.Response(500, text="boom"))
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        with pytest.raises(CardlyError) as ei:
            c.get("orders")
    assert "test_key" not in str(ei.value)


@respx.mock
def test_post_sends_idempotency_key_get_does_not():
    post = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    get = respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(200, json=ok({"results": []}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        c.post("orders/place", json={"lines": []})
        c.get("orders")
    assert "Idempotency-Key" in post.calls.last.request.headers
    assert "Idempotency-Key" not in get.calls.last.request.headers


@respx.mock
def test_idempotency_key_is_stable_across_posts_in_one_invocation():
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        c.post("orders/place", json={"lines": []})
        c.post("orders/place", json={"lines": []})
    keys = [call.request.headers["Idempotency-Key"] for call in route.calls]
    assert keys[0] == keys[1]


@respx.mock
def test_idempotency_key_override_is_used():
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY, idempotency_key="pinned-123") as c:
        c.post("orders/place", json={"lines": []})
    assert route.calls.last.request.headers["Idempotency-Key"] == "pinned-123"


@respx.mock
def test_generated_idempotency_key_is_a_uuid4():
    import uuid

    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        c.post("orders/place", json={})
    key = route.calls.last.request.headers["Idempotency-Key"]
    assert uuid.UUID(key).version == 4
    assert len(key) <= 64  # Cardly's documented maximum


@respx.mock
def test_retry_reuses_the_same_idempotency_key():
    # THE critical test: a retry that mints a fresh key would place a second
    # order instead of replaying the first.
    responses = [
        httpx.Response(503, json={"state": {"status": "ERROR", "messages": ["busy"]}}),
        httpx.Response(200, json=ok({"order": {"id": "1"}})),
    ]
    route = respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=responses)
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=2, base_delay=0), sleep=lambda _: None
    ) as c:
        c.post("orders/place", json={"lines": []})
    assert len(route.calls) == 2
    keys = {call.request.headers["Idempotency-Key"] for call in route.calls}
    assert len(keys) == 1


@respx.mock
def test_retries_429_then_succeeds():
    responses = [
        httpx.Response(429, json={"state": {"status": "ERROR", "messages": ["slow down"]}}),
        httpx.Response(200, json=ok({"results": []})),
    ]
    respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=2, base_delay=0), sleep=lambda _: None
    ) as c:
        assert c.get("orders") == {"results": []}


@respx.mock
def test_exhausted_retries_raise_with_final_status():
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(429, json={"state": {"status": "ERROR", "messages": ["no"]}})
    )
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=2, base_delay=0), sleep=lambda _: None
    ) as c:
        with pytest.raises(CardlyError) as ei:
            c.get("orders")
    assert ei.value.exit_code == 5


@respx.mock
def test_post_timeout_is_retried_and_can_succeed():
    responses = [httpx.ConnectTimeout("timed out"), httpx.Response(200, json=ok({"id": "1"}))]
    route = respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=responses)
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=2, base_delay=0), sleep=lambda _: None
    ) as c:
        assert c.post("orders/place", json={"lines": []}) == {"id": "1"}
    assert len(route.calls) == 2


@respx.mock
def test_get_timeout_is_not_retried():
    route = respx.get("https://api.card.ly/v2/orders").mock(
        side_effect=httpx.ConnectTimeout("timed out")
    )
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=3, base_delay=0), sleep=lambda _: None
    ) as c:
        with pytest.raises(CardlyError) as ei:
            c.get("orders")
    assert ei.value.is_timeout
    assert ei.value.exit_code == 7
    assert len(route.calls) == 1


@respx.mock
def test_cached_replay_aborts_the_retry_loop_early():
    # An identical 5xx returned instantly means Cardly served it from the
    # idempotency store; further retries can never succeed.
    body = {"state": {"status": "ERROR", "messages": ["stored failure"]}}
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(500, json=body)
    )
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=5, base_delay=0), sleep=lambda _: None
    ) as c:
        with pytest.raises(CardlyError) as ei:
            c.post("orders/place", json={"lines": []})
    # First attempt + one retry that revealed the replay. Not all 5.
    assert len(route.calls) == 2
    assert "idempotency" in str(ei.value).lower()
    assert "stored failure" in str(ei.value)


@respx.mock
def test_get_with_identical_fast_5xx_retries_full_budget():
    # GET never carries an idempotency key, so the cached-replay heuristic
    # must not fire for it: two byte-identical fast 502s from a load balancer
    # are an ordinary transient condition, not a replayed idempotent write.
    route = respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(502, text="Bad Gateway")
    )
    with CardlyClient(
        SETTINGS, retry=RetryPolicy(max_retries=3, base_delay=0), sleep=lambda _: None
    ) as c:
        with pytest.raises(CardlyError):
            c.get("orders")
    # Full budget: initial attempt + 3 retries, not aborted after 2.
    assert len(route.calls) == 4


@respx.mock
def test_sends_api_key_to_cardly_host():
    route = respx.get("https://api.card.ly/v2/account/balance").mock(
        return_value=httpx.Response(200, json=ok({"balance": 100}))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        c.get("account/balance")
    assert route.calls.last.request.headers["API-Key"] == "test_key"


@respx.mock
def test_does_not_send_api_key_to_non_cardly_host():
    respx.get("https://cdn.example/x.pdf").mock(return_value=httpx.Response(200, content=b"%PDF"))
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        resp = c.request("GET", "https://cdn.example/x.pdf", raw=True)
    assert "API-Key" not in resp.request.headers


@respx.mock
def test_redirect_off_cardly_host_does_not_leak_key():
    respx.get("https://api.card.ly/v2/some-endpoint").mock(
        return_value=httpx.Response(302, headers={"Location": "https://evil.example/steal"})
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        with pytest.raises(CardlyError):
            c.get("some-endpoint")


def test_url_for_upgrades_http_to_https():
    assert url_for(SETTINGS, "http://api.card.ly/v2/preview/x") == (
        "https://api.card.ly/v2/preview/x"
    )


@respx.mock
def test_200_with_non_json_body_raises_cardly_error():
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(200, text="<html>Access Denied</html>")
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        with pytest.raises(CardlyError) as ei:
            c.get("orders")
    assert ei.value.status_code == 200


@respx.mock
def test_captures_request_id():
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(200, json=ok({}), headers={"Request-Id": "req_42"})
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        c.get("orders")
        assert c.last_request_id == "req_42"


@respx.mock
def test_verbose_logs_method_url_and_request_id_but_never_headers(capsys):
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(200, json=ok({}), headers={"Request-Id": "req_7"})
    )
    with CardlyClient(SETTINGS, verbose=True, retry=NO_RETRY) as c:
        c.get("orders")
    err = capsys.readouterr().err
    assert "GET https://api.card.ly/v2/orders" in err
    assert "req_7" in err
    assert "test_key" not in err  # never log headers


@respx.mock
def test_raw_returns_response_object():
    respx.get("https://api.card.ly/v2/preview/x/card/pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4")
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        resp = c.request("GET", "preview/x/card/pdf", raw=True)
    assert resp.content == b"%PDF-1.4"


@respx.mock
def test_raw_returns_response_object_for_absolute_url():
    # Task 13's preview-PDF download hits an absolute URL returned by an
    # earlier API call, not a base_url-relative endpoint.
    respx.get("https://cdn.card.ly/previews/abc123.pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4")
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        resp = c.request("GET", "https://cdn.card.ly/previews/abc123.pdf", raw=True)
    assert resp.content == b"%PDF-1.4"


@respx.mock
def test_empty_body_returns_none():
    respx.delete("https://api.card.ly/v2/webhooks/1").mock(return_value=httpx.Response(204))
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert c.delete("webhooks/1") is None


def test_client_has_no_put_method():
    # Cardly uses POST for updates throughout. A put() would only invite bugs.
    assert not hasattr(CardlyClient(SETTINGS), "put")
