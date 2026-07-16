import httpx
import respx

from cardly_cli.client import CardlyClient
from cardly_cli.config import CardlySettings
from cardly_cli.pagination import DEFAULT_LIMIT, extract_results, paginate, total_records
from cardly_cli.retry import RetryPolicy

SETTINGS = CardlySettings(api_key="k", base_url="https://api.card.ly/v2")
NO_RETRY = RetryPolicy(enabled=False)


def page(results, *, total=None, limit=DEFAULT_LIMIT, page_num=1, last_record=None):
    meta = {"limit": limit, "page": page_num}
    if total is not None:
        meta["totalRecords"] = total
    if last_record is not None:
        meta["lastRecord"] = last_record
    return {
        "state": {"status": "OK", "messages": [], "version": 1},
        "data": {
            "meta": meta,
            "results": results,
        },
    }


def test_default_limit():
    assert DEFAULT_LIMIT == 250


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
        return_value=httpx.Response(200, json=page([{"id": 1}, {"id": 2}], total=2, last_record=2))
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert list(paginate(c, "webhooks")) == [{"id": 1}, {"id": 2}]


@respx.mock
def test_walks_multiple_pages_sending_page_not_offset():
    # THE regression guard for this bug: assert the actual `page` query param
    # sent on each request (1, 2, 3) and that `offset` is never sent.
    responses = [
        httpx.Response(
            200,
            json=page([{"id": 1}, {"id": 2}], total=5, limit=2, page_num=1, last_record=2),
        ),
        httpx.Response(
            200,
            json=page([{"id": 3}, {"id": 4}], total=5, limit=2, page_num=2, last_record=4),
        ),
        httpx.Response(200, json=page([{"id": 5}], total=5, limit=2, page_num=3, last_record=5)),
    ]
    route = respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        items = list(paginate(c, "orders", limit=2))
    assert items == [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]
    first, second, third = route.calls
    assert first.request.url.params["limit"] == "2"
    assert first.request.url.params["page"] == "1"
    assert second.request.url.params["page"] == "2"
    assert third.request.url.params["page"] == "3"
    for call in route.calls:
        assert "offset" not in call.request.url.params


@respx.mock
def test_stops_at_last_record_without_extra_request():
    # Termination via lastRecord >= totalRecords must not waste an extra
    # request once the API confirms the walk is complete.
    route = respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(
            200,
            json=page([{"id": 1}, {"id": 2}], total=2, limit=100, page_num=1, last_record=2),
        )
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert len(list(paginate(c, "orders"))) == 2
    assert len(route.calls) == 1


@respx.mock
def test_stops_on_empty_results():
    responses = [
        httpx.Response(200, json=page([{"id": 1}], total=99, limit=1, page_num=1)),
        httpx.Response(200, json=page([], total=99, limit=1, page_num=2)),
    ]
    respx.get("https://api.card.ly/v2/orders").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert list(paginate(c, "orders", limit=1)) == [{"id": 1}]


@respx.mock
def test_stops_on_short_page_without_total():
    # No totalRecords/lastRecord reported at all: a page shorter than the
    # requested limit is the fallback termination signal.
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(
            200,
            json={
                "state": {"status": "OK"},
                "data": {"meta": {"limit": 5, "page": 1}, "results": [{"id": 1}]},
            },
        )
    )
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        assert list(paginate(c, "orders", limit=5)) == [{"id": 1}]


@respx.mock
def test_extra_params_are_preserved_across_pages():
    responses = [
        httpx.Response(200, json=page([{"id": 1}], total=2, limit=1, page_num=1, last_record=1)),
        httpx.Response(200, json=page([{"id": 2}], total=2, limit=1, page_num=2, last_record=2)),
    ]
    route = respx.get("https://api.card.ly/v2/art").mock(side_effect=responses)
    with CardlyClient(SETTINGS, retry=NO_RETRY) as c:
        list(paginate(c, "art", params={"ownOnly": "true"}, limit=1))
    for call in route.calls:
        assert call.request.url.params["ownOnly"] == "true"
