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


def test_partial_sender_fails_locally_without_a_request():
    result = runner.invoke(app, ["orders", "place", *TO, "--from-first-name", "Bob"], env=ENV)
    assert result.exit_code == 2  # Typer usage error
    assert "sender" in result.stderr.lower()


def test_tracked_shipping_outside_australia_fails_locally():
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
