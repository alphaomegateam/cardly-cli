import json

import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}

TO = [
    "--artwork",
    "thank-you-01",
    "--to-first-name",
    "Ada",
    "--to-address",
    "12 Analytical Way",
    "--to-city",
    "Melbourne",
    "--to-country",
    "AU",
]


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


@respx.mock
def test_place_wraps_body_in_lines():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "o1", "status": "queued"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    result = runner.invoke(app, ["--json", "orders", "place", *TO, "--message", "Thanks!"], env=ENV)
    assert result.exit_code == 0
    body = captured["body"]
    assert "lines" in body and isinstance(body["lines"], list)
    line = body["lines"][0]
    assert line["artwork"] == "thank-you-01"
    assert line["recipient"]["city"] == "Melbourne"
    assert line["messages"]["pages"] == [{"page": 1, "text": "Thanks!"}]


@respx.mock
def test_preview_body_is_flat_not_wrapped():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"preview": {"urls": {}}, "order": {"creditCost": 2}}))

    respx.post("https://api.card.ly/v2/orders/preview").mock(side_effect=handler)
    result = runner.invoke(app, ["--json", "orders", "preview", *TO], env=ENV)
    assert result.exit_code == 0
    body = captured["body"]
    # Same fields as place, but NOT wrapped in lines[].
    assert "lines" not in body
    assert body["artwork"] == "thank-you-01"
    assert body["recipient"]["city"] == "Melbourne"


@respx.mock
def test_place_and_preview_build_identical_lines():
    bodies = {}

    def place_handler(request):
        bodies["place"] = json.loads(request.content)["lines"][0]
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    def preview_handler(request):
        bodies["preview"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"preview": {"urls": {}}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=place_handler)
    respx.post("https://api.card.ly/v2/orders/preview").mock(side_effect=preview_handler)
    args = [*TO, "--message", "Hi", "--var", "name=Ada", "--shipping", "standard"]
    runner.invoke(app, ["--json", "orders", "place", *args], env=ENV)
    runner.invoke(app, ["--json", "orders", "preview", *args], env=ENV)
    preview = dict(bodies["preview"])
    preview.pop("purchaseOrderNumber", None)
    assert bodies["place"] == preview


@respx.mock
def test_place_sends_purchase_order_number_at_top_level():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    runner.invoke(app, ["orders", "place", *TO, "--purchase-order-number", "PO-9"], env=ENV)
    assert captured["body"]["purchaseOrderNumber"] == "PO-9"
    assert "purchaseOrderNumber" not in captured["body"]["lines"][0]


@respx.mock
def test_place_supports_all_typed_flags():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    runner.invoke(
        app,
        [
            "orders",
            "place",
            *TO,
            "--template",
            "tpl-1",
            "--quantity",
            "3",
            "--ship-to-me",
            "--requested-arrival",
            "2026-08-01",
            "--style",
            "align=center",
            "--var",
            "name=Ada",
        ],
        env=ENV,
    )
    line = captured["body"]["lines"][0]
    assert line["template"] == "tpl-1"
    assert line["quantity"] == 3
    assert line["shipToMe"] is True
    assert line["requestedArrival"] == "2026-08-01"
    assert line["style"] == {"align": "center"}
    assert line["variables"] == {"name": "Ada"}


@respx.mock
def test_message_page_flag_controls_ordering():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    runner.invoke(
        app,
        ["orders", "place", *TO, "--message-page", "3=Back", "--message-page", "1=Front"],
        env=ENV,
    )
    pages = captured["body"]["lines"][0]["messages"]["pages"]
    assert pages == [{"page": 1, "text": "Front"}, {"page": 3, "text": "Back"}]


@respx.mock
def test_partial_sender_fails_locally_without_a_request():
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    result = runner.invoke(app, ["orders", "place", *TO, "--from-first-name", "Bob"], env=ENV)
    assert result.exit_code == 2  # Typer usage error
    assert "sender" in result.stderr.lower()
    assert not route.called


@respx.mock
def test_tracked_shipping_outside_australia_fails_locally():
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    args = [
        "--artwork",
        "a",
        "--to-first-name",
        "A",
        "--to-address",
        "x",
        "--to-city",
        "London",
        "--to-country",
        "GB",
        "--shipping",
        "tracked",
    ]
    result = runner.invoke(app, ["orders", "place", *args], env=ENV)
    assert result.exit_code == 2
    assert "tracked" in result.stderr
    assert not route.called


@respx.mock
def test_tracked_shipping_from_data_country_fails_locally():
    """check_shipping must gate on the MERGED line, not the flag dict."""
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    body = json.dumps({"recipient": {"country": "GB"}})
    result = runner.invoke(
        app, ["orders", "place", "--shipping", "tracked", "--data", body], env=ENV
    )
    assert result.exit_code == 2
    assert "tracked" in result.stderr
    assert not route.called


@respx.mock
def test_test_mode_response_shows_banner():
    respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"testMode": True, "order": {"id": "1"}}))
    )
    result = runner.invoke(app, ["orders", "place", *TO], env=ENV)
    assert result.exit_code == 0
    assert "TEST MODE" in result.stderr
    assert "no card was sent" in result.stderr.lower()


@respx.mock
def test_live_response_shows_no_banner():
    respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    result = runner.invoke(app, ["orders", "place", *TO], env=ENV)
    assert "TEST MODE" not in result.stderr


@respx.mock
def test_place_402_exits_8():
    respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(
            402, json={"state": {"status": "ERROR", "messages": ["Need 5 credit, have 2."]}}
        )
    )
    result = runner.invoke(app, ["--no-retry", "orders", "place", *TO], env=ENV)
    assert result.exit_code == 8
    assert "Need 5 credit" in result.stderr


@respx.mock
def test_place_accepts_data_body():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    body = json.dumps({"lines": [{"artwork": "from-data", "recipient": {"firstName": "Z"}}]})
    result = runner.invoke(app, ["orders", "place", "--data", body], env=ENV)
    assert result.exit_code == 0
    assert captured["body"]["lines"][0]["artwork"] == "from-data"


@respx.mock
def test_place_data_lines_with_card_shaping_flag_raises_badparameter():
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    body = json.dumps({"lines": [{"artwork": "from-data"}]})
    result = runner.invoke(
        app, ["orders", "place", "--data", body, "--artwork", "conflict"], env=ENV
    )
    assert result.exit_code == 2
    assert "cannot be combined" in result.stderr
    assert not route.called


@respx.mock
def test_preview_data_lines_with_card_shaping_flag_raises_badparameter():
    route = respx.post("https://api.card.ly/v2/orders/preview").mock(
        return_value=httpx.Response(200, json=ok({"preview": {"urls": {}}}))
    )
    body = json.dumps({"lines": [{"artwork": "from-data"}]})
    result = runner.invoke(app, ["orders", "preview", "--data", body, "--message", "Hi"], env=ENV)
    assert result.exit_code == 2
    assert "cannot be combined" in result.stderr
    assert not route.called


@respx.mock
def test_place_data_lines_with_purchase_order_number_allowed():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    body = json.dumps({"lines": [{"artwork": "from-data"}]})
    result = runner.invoke(
        app, ["orders", "place", "--data", body, "--purchase-order-number", "PO-1"], env=ENV
    )
    assert result.exit_code == 0
    assert captured["body"]["purchaseOrderNumber"] == "PO-1"
    assert captured["body"]["lines"][0]["artwork"] == "from-data"


@respx.mock
def test_place_preserves_other_top_level_data_keys():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    body = json.dumps({"lines": [{"artwork": "from-data"}], "customField": "keep-me"})
    result = runner.invoke(app, ["orders", "place", "--data", body], env=ENV)
    assert result.exit_code == 0
    assert captured["body"]["customField"] == "keep-me"


@respx.mock
def test_place_data_empty_lines_raises_badparameter():
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    body = json.dumps({"lines": []})
    result = runner.invoke(app, ["orders", "place", "--data", body], env=ENV)
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_preview_data_lines_single_element_previews_that_card():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"preview": {"urls": {}}}))

    respx.post("https://api.card.ly/v2/orders/preview").mock(side_effect=handler)
    body = json.dumps({"lines": [{"artwork": "from-data", "recipient": {"firstName": "Z"}}]})
    result = runner.invoke(app, ["orders", "preview", "--data", body], env=ENV)
    assert result.exit_code == 0
    assert captured["body"] == {"artwork": "from-data", "recipient": {"firstName": "Z"}}


@respx.mock
def test_preview_data_lines_multiple_elements_raises_badparameter():
    route = respx.post("https://api.card.ly/v2/orders/preview").mock(
        return_value=httpx.Response(200, json=ok({"preview": {"urls": {}}}))
    )
    body = json.dumps({"lines": [{"artwork": "a"}, {"artwork": "b"}]})
    result = runner.invoke(app, ["orders", "preview", "--data", body], env=ENV)
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_preview_data_empty_lines_raises_badparameter():
    route = respx.post("https://api.card.ly/v2/orders/preview").mock(
        return_value=httpx.Response(200, json=ok({"preview": {"urls": {}}}))
    )
    body = json.dumps({"lines": []})
    result = runner.invoke(app, ["orders", "preview", "--data", body], env=ENV)
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_data_only_produces_identical_card_from_preview_and_place():
    """The regression that started this: same --data + no flags -> same card."""
    bodies = {}

    def place_handler(request):
        bodies["place"] = json.loads(request.content)["lines"][0]
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    def preview_handler(request):
        bodies["preview"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"preview": {"urls": {}}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=place_handler)
    respx.post("https://api.card.ly/v2/orders/preview").mock(side_effect=preview_handler)
    body = json.dumps(
        {"lines": [{"artwork": "from-data", "recipient": {"firstName": "Z", "country": "AU"}}]}
    )
    place_result = runner.invoke(app, ["orders", "place", "--data", body], env=ENV)
    preview_result = runner.invoke(app, ["orders", "preview", "--data", body], env=ENV)
    assert place_result.exit_code == 0
    assert preview_result.exit_code == 0
    assert bodies["place"] == bodies["preview"]


@respx.mock
def test_preview_upgrades_http_urls_to_https():
    respx.post("https://api.card.ly/v2/orders/preview").mock(
        return_value=httpx.Response(
            200,
            json=ok(
                {
                    "preview": {
                        "urls": {"card": "http://api.card.ly/v2/preview/x/card/pdf"},
                        "expires": "2026-07-16T00:00:00",
                    }
                }
            ),
        )
    )
    result = runner.invoke(app, ["--json", "orders", "preview", *TO], env=ENV)
    payload = json.loads(result.stdout)
    assert payload["preview"]["urls"]["card"].startswith("https://")


@respx.mock
def test_preview_download_fetches_pdf_with_api_key(tmp_path):
    respx.post("https://api.card.ly/v2/orders/preview").mock(
        return_value=httpx.Response(
            200,
            json=ok({"preview": {"urls": {"card": "http://api.card.ly/v2/preview/x/card/pdf"}}}),
        )
    )
    pdf = respx.get("https://api.card.ly/v2/preview/x/card/pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4")
    )
    out = tmp_path / "proof.pdf"
    result = runner.invoke(app, ["orders", "preview", *TO, "--download", str(out)], env=ENV)
    assert result.exit_code == 0
    assert out.read_bytes() == b"%PDF-1.4"
    # Preview PDFs live on api.card.ly, not a pre-signed CDN link, so the
    # API-Key header is required on the fetch too.
    assert pdf.calls.last.request.headers["API-Key"] == "k"


@respx.mock
def test_preview_download_with_none_body_raises_clean_error(tmp_path):
    respx.post("https://api.card.ly/v2/orders/preview").mock(
        return_value=httpx.Response(200, content=b"null")
    )
    out = tmp_path / "proof.pdf"
    result = runner.invoke(app, ["orders", "preview", *TO, "--download", str(out)], env=ENV)
    assert result.exit_code == 2
    assert "no card url" in result.stderr.lower()


@respx.mock
def test_preview_download_with_null_urls_raises_clean_error(tmp_path):
    respx.post("https://api.card.ly/v2/orders/preview").mock(
        return_value=httpx.Response(200, json=ok({"preview": {"urls": None}}))
    )
    out = tmp_path / "proof.pdf"
    result = runner.invoke(app, ["orders", "preview", *TO, "--download", str(out)], env=ENV)
    assert result.exit_code == 2
    assert "no card url" in result.stderr.lower()


@respx.mock
def test_preview_emits_result_before_failed_download(tmp_path):
    """A failed download must not swallow creditCost and the preview URLs."""
    respx.post("https://api.card.ly/v2/orders/preview").mock(
        return_value=httpx.Response(200, json=ok({"preview": {"urls": None}, "creditCost": 2}))
    )
    out = tmp_path / "proof.pdf"
    result = runner.invoke(
        app, ["--json", "orders", "preview", *TO, "--download", str(out)], env=ENV
    )
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["creditCost"] == 2


@respx.mock
def test_data_nested_recipient_field_survives_typed_flag_merge():
    """I1: --data recipient fields the typed flags don't cover must survive.

    A shallow `line.update(typed)` replaced the whole `recipient` object,
    silently discarding --data's company even though the request stayed
    structurally valid and shipped.
    """
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"order": {"id": "1"}}))

    respx.post("https://api.card.ly/v2/orders/place").mock(side_effect=handler)
    body = json.dumps({"recipient": {"company": "Acme Corp"}})
    result = runner.invoke(
        app,
        [
            "orders",
            "place",
            "--data",
            body,
            "--to-first-name",
            "Ada",
            "--to-address",
            "1 Main St",
            "--to-city",
            "Sydney",
            "--to-country",
            "AU",
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    recipient = captured["body"]["lines"][0]["recipient"]
    assert recipient["company"] == "Acme Corp"
    assert recipient["firstName"] == "Ada"
    assert recipient["city"] == "Sydney"


@respx.mock
def test_region_guard_fires_when_country_comes_only_from_data_alongside_to_flag():
    """I1: the region guard must not be defeated by the shallow-merge bug.

    Country lives only in --data; --to-first-name (a typed flag lacking a
    country) must not clobber it out of the merged recipient.
    """
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    body = json.dumps({"recipient": {"country": "GB"}})
    result = runner.invoke(
        app,
        ["orders", "place", "--data", body, "--to-first-name", "Ada", "--shipping", "tracked"],
        env=ENV,
    )
    assert result.exit_code == 2
    assert "tracked" in result.stderr
    assert not route.called


@respx.mock
def test_place_data_lines_null_raises_badparameter():
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    body = json.dumps({"lines": None})
    result = runner.invoke(app, ["orders", "place", "--data", body], env=ENV)
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_place_data_lines_non_list_object_raises_badparameter():
    route = respx.post("https://api.card.ly/v2/orders/place").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "1"}}))
    )
    body = json.dumps({"lines": {"artwork": "x"}})
    result = runner.invoke(app, ["orders", "place", "--data", body], env=ENV)
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_preview_data_lines_null_raises_badparameter():
    route = respx.post("https://api.card.ly/v2/orders/preview").mock(
        return_value=httpx.Response(200, json=ok({"preview": {"urls": {}}}))
    )
    body = json.dumps({"lines": None})
    result = runner.invoke(app, ["orders", "preview", "--data", body], env=ENV)
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_preview_data_lines_non_list_object_raises_badparameter():
    route = respx.post("https://api.card.ly/v2/orders/preview").mock(
        return_value=httpx.Response(200, json=ok({"preview": {"urls": {}}}))
    )
    body = json.dumps({"lines": {"artwork": "x"}})
    result = runner.invoke(app, ["orders", "preview", "--data", body], env=ENV)
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_orders_list_extracts_results():
    respx.get("https://api.card.ly/v2/orders").mock(
        return_value=httpx.Response(
            200,
            json=ok({"meta": {"totalRecords": 1}, "results": [{"id": "o1", "status": "sent"}]}),
        )
    )
    result = runner.invoke(app, ["--json", "orders", "list"], env=ENV)
    assert json.loads(result.stdout)[0]["id"] == "o1"


@respx.mock
def test_orders_get():
    respx.get("https://api.card.ly/v2/orders/o1").mock(
        return_value=httpx.Response(200, json=ok({"order": {"id": "o1", "status": "sent"}}))
    )
    result = runner.invoke(app, ["--json", "orders", "get", "o1"], env=ENV)
    assert json.loads(result.stdout)["id"] == "o1"
