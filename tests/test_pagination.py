import httpx
import respx

from cardly_cli.client import CardlyClient
from cardly_cli.config import CardlySettings
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate, total_records
from cardly_cli.retry import RetryPolicy

SETTINGS = CardlySettings(api_key="k", base_url="https://api.card.ly/v2")
NO_RETRY = RetryPolicy(enabled=False)


def page(results, *, total, limit=100, offset=0):
    return {
        "state": {"status": "OK", "messages": [], "version": 1},
        "data": {
            "meta": {"limit": limit, "offset": offset, "totalRecords": total},
            "results": results,
        },
    }


def test_default_limit():
    assert DEFAULT_LIMIT == 100


def test_extract_results_and_total():
    data = {"meta": {"totalRecords": 5}, "results": [{"id": 1}]}
    assert extract_results(data) == [{"id": 1}]
    assert total_records(data) == 5
    assert extract_results({}) == []
    assert total_records({}) is None
    assert extract_results([{"id": 1}]) == [{"id": 1}]  # bare list passthrough


@respx.mock
def test_single_page():
    respx.get("https://api.card.ly/v2/webhooks").mock(
        return_value=httpx.Response(200, json=page([{"id": 1}, {"id": 2}], total=2))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert list(paginate(c, "webhooks")) == [{"id": 1}, {"id": 2}]


@respx.mock
def test_walks_multiple_pages_and_sends_limit_and_offset():
    responses = [
        httpx.Response(200, json=page([{"id": 1}, {"id": 2}], total=3, limit=2, offset=0)),
        httpx.Response(200, json=page([{"id": 3}], total=3, limit=2, offset=2)),
    ]
    route = respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert list(paginate(c, "orders", limit=2)) == [{"id": 1}, {"id": 2}, {"id": 3}]
    first, second = route.calls
    assert first.request.url.params["limit"] == "2"
    assert first.request.url.params["offset"] == "0"
    assert second.request.url.params["offset"] == "2"


@respx.mock
def test_advances_by_returned_page_size_not_requested_limit():
    # THE regression guard: server clamps limit 100 -> 25. Advancing by the
    # request would skip records 26-100 silently.
    responses = [
        httpx.Response(200, json=page([{"id": i} for i in range(25)], total=30, limit=25)),
        httpx.Response(200, json=page([{"id": i} for i in range(25, 30)], total=30, limit=25)),
    ]
    route = respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        items = list(paginate(c, "orders", limit=100))
    assert len(items) == 30
    assert route.calls[1].request.url.params["offset"] == "25"  # not "100"


@respx.mock
def test_warns_when_server_clamps_limit():
    warnings = []
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(200, json=page([{"id": 1}], total=1, limit=25))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        list(paginate(c, "orders", limit=100, warn=warnings.append))
    assert any("100" in w and "25" in w for w in warnings)


@respx.mock
def test_stops_on_empty_results():
    responses = [
        httpx.Response(200, json=page([{"id": 1}], total=99, limit=1)),
        httpx.Response(200, json=page([], total=99, limit=1)),
    ]
    respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert list(paginate(c, "orders", limit=1)) == [{"id": 1}]


@respx.mock
def test_stops_when_endpoint_ignores_offset():
    # Endpoint returns the same full page forever. Without a guard this loops
    # until Cardly rate-limits us.
    route = respx.get("https://api.card.ly/v2/contact-lists").mock(
        return_value=httpx.Response(200, json=page([{"id": 1}], total=99, limit=1, offset=0))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        items = list(paginate(c, "contact-lists", limit=1))
    assert items == [{"id": 1}]
    assert len(route.calls) == 2  # detected on the repeat, then stopped


@respx.mock
def test_stalled_offset_warns_with_total():
    # Endpoint ignores `offset` and keeps returning page 1. The stall guard
    # must stop the loop AND tell the caller the result may be incomplete,
    # including the reported total when the API supplies one.
    warnings = []
    respx.get("https://api.card.ly/v2/media").mock(
        return_value=httpx.Response(200, json=page([{"id": 1}], total=250, limit=1, offset=0))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        items = list(paginate(c, "media", limit=1, warn=warnings.append))
    assert items == [{"id": 1}]
    assert any("INCOMPLETE" in w and "250" in w for w in warnings)


@respx.mock
def test_stalled_offset_warns_without_fabricating_total():
    # Same stall, but the API doesn't report totalRecords. The warning must
    # not invent a number.
    warnings = []
    respx.get("https://api.card.ly/v2/media").mock(
        return_value=httpx.Response(
            200,
            json={
                "state": {"status": "OK"},
                "data": {"meta": {"limit": 1, "offset": 0}, "results": [{"id": 1}]},
            },
        )
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        items = list(paginate(c, "media", limit=1, warn=warnings.append))
    assert items == [{"id": 1}]
    assert len(warnings) == 1
    assert "INCOMPLETE" in warnings[0]
    assert "total" not in warnings[0].lower()


@respx.mock
def test_healthy_multi_page_walk_emits_no_stall_warning():
    # Regression guard: normal pagination (offset honoured) must never trigger
    # the stall warning.
    warnings = []
    responses = [
        httpx.Response(200, json=page([{"id": 1}, {"id": 2}], total=3, limit=2, offset=0)),
        httpx.Response(200, json=page([{"id": 3}], total=3, limit=2, offset=2)),
    ]
    respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        items = list(paginate(c, "orders", limit=2, warn=warnings.append))
    assert items == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert warnings == []


@respx.mock
def test_single_page_emits_no_stall_warning():
    warnings = []
    respx.get("https://api.card.ly/v2/webhooks").mock(
        return_value=httpx.Response(200, json=page([{"id": 1}, {"id": 2}], total=2))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        items = list(paginate(c, "webhooks", warn=warnings.append))
    assert items == [{"id": 1}, {"id": 2}]
    assert warnings == []


@respx.mock
def test_false_positive_regression_different_pages_same_length_and_first_element():
    # Regression: old signature matched on (len(results), repr(results[0])) only.
    # Two genuinely different consecutive pages that share the same length and
    # identical first element (same repr) but differ in subsequent elements would
    # trigger a false stall, silently dropping the second page's records. This
    # test verifies that both pages are yielded in full.
    responses = [
        httpx.Response(200, json=page([{"id": 1}, {"id": 2}], total=4, limit=2)),
        httpx.Response(200, json=page([{"id": 1}, {"id": 3}], total=4, limit=2)),
    ]
    respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        items = list(paginate(c, "orders", limit=2))
    # Both pages must be yielded in full: 4 records total.
    assert len(items) == 4
    # Verify records from both pages are present (second page has id=3).
    ids = [item["id"] for item in items]
    assert 1 in ids and 2 in ids and 3 in ids


@respx.mock
def test_stops_at_total_records():
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(200, json=page([{"id": 1}, {"id": 2}], total=2, limit=100))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert len(list(paginate(c, "orders"))) == 2


@respx.mock
def test_missing_total_records_keeps_paging_until_empty():
    responses = [
        httpx.Response(
            200,
            json={"state": {"status": "OK"}, "data": {"meta": {}, "results": [{"id": 1}]}},
        ),
        httpx.Response(200, json={"state": {"status": "OK"}, "data": {"meta": {}, "results": []}}),
    ]
    respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert list(paginate(c, "orders", limit=1)) == [{"id": 1}]


@respx.mock
def test_extra_params_are_preserved_across_pages():
    responses = [
        httpx.Response(200, json=page([{"id": 1}], total=2, limit=1)),
        httpx.Response(200, json=page([{"id": 2}], total=2, limit=1)),
    ]
    route = respx.get("https://api.card.ly/v2/art").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        list(paginate(c, "art", params={"ownOnly": "true"}, limit=1))
    for call in route.calls:
        assert call.request.url.params["ownOnly"] == "true"
