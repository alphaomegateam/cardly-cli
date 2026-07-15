import hashlib
import json

import httpx
import respx
from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}


def ok(data):
    return {"state": {"status": "OK", "messages": [], "version": 1}, "data": data}


@respx.mock
def test_webhooks_list():
    respx.get("https://api.card.ly/v2/webhooks").mock(
        return_value=httpx.Response(
            200,
            json=ok({"meta": {"totalRecords": 1}, "results": [{"id": "w1", "status": "active"}]}),
        )
    )
    result = runner.invoke(app, ["--json", "webhooks", "list"], env=ENV)
    assert json.loads(result.stdout)[0]["id"] == "w1"


@respx.mock
def test_webhooks_create_sends_target_url_and_events():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "w1", "secret": "sh-abc"}))

    respx.post("https://api.card.ly/v2/webhooks").mock(side_effect=handler)
    result = runner.invoke(
        app,
        [
            "webhooks",
            "create",
            "--target-url",
            "https://x.test/hook",
            "--event",
            "contact.order.sent",
            "--event",
            "qrCode.scanned",
            "--description",
            "prod",
            "--metadata",
            "team=growth",
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    assert captured["body"]["targetUrl"] == "https://x.test/hook"
    assert captured["body"]["events"] == ["contact.order.sent", "qrCode.scanned"]
    assert captured["body"]["description"] == "prod"
    assert captured["body"]["metadata"] == {"team": "growth"}


def test_webhooks_create_rejects_unknown_event():
    result = runner.invoke(
        app, ["webhooks", "create", "--target-url", "https://x.test", "--event", "banana"], env=ENV
    )
    assert result.exit_code == 2
    assert "banana" in result.stderr


@respx.mock
def test_webhooks_create_surfaces_the_secret_prominently():
    respx.post("https://api.card.ly/v2/webhooks").mock(
        return_value=httpx.Response(200, json=ok({"id": "w1", "secret": "sh-once-only"}))
    )
    result = runner.invoke(
        app,
        [
            "--json",
            "webhooks",
            "create",
            "--target-url",
            "https://x.test",
            "--event",
            "qrCode.scanned",
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    # Returned only at creation — must be visible even when stdout is piped JSON.
    assert "sh-once-only" in result.stderr
    assert "only" in result.stderr.lower()


@respx.mock
def test_webhooks_update_uses_post_and_requires_target_url():
    route = respx.post("https://api.card.ly/v2/webhooks/w1").mock(
        return_value=httpx.Response(200, json=ok({"id": "w1"}))
    )
    # Cardly marks targetUrl required on update even when only toggling disabled.
    missing = runner.invoke(app, ["webhooks", "update", "w1", "--disabled"], env=ENV)
    assert missing.exit_code == 2
    assert "--target-url" in missing.stderr
    assert not route.called

    result = runner.invoke(
        app, ["webhooks", "update", "w1", "--target-url", "https://x.test", "--disabled"], env=ENV
    )
    assert result.exit_code == 0
    assert route.calls.last.request.method == "POST"
    assert json.loads(route.calls.last.request.content)["disabled"] is True


@respx.mock
def test_webhooks_delete_warns_on_protected():
    respx.get("https://api.card.ly/v2/webhooks/w1").mock(
        return_value=httpx.Response(200, json=ok({"id": "w1", "protected": True}))
    )
    route = respx.delete("https://api.card.ly/v2/webhooks/w1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(app, ["webhooks", "delete", "w1", "--yes"], env=ENV)
    assert "protected" in result.stderr.lower()
    assert route.called


@respx.mock
def test_webhooks_delete_requires_confirmation():
    respx.get("https://api.card.ly/v2/webhooks/w1").mock(
        return_value=httpx.Response(200, json=ok({"id": "w1"}))
    )
    route = respx.delete("https://api.card.ly/v2/webhooks/w1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    runner.invoke(app, ["webhooks", "delete", "w1"], input="n\n", env=ENV)
    assert route.called is False


def _signed_body(secret="s3cret", timestamp="1700000000"):
    data = '{"event":"contact.order.sent"}'
    digest = hashlib.md5(f"{secret}.{timestamp}.{data}".encode()).hexdigest()
    return f'{{"timestamp":"{timestamp}","data":{data},"signatures":["{digest}"]}}'


def test_verify_matches_body_scheme_and_names_it(tmp_path):
    path = tmp_path / "postback.json"
    path.write_text(_signed_body())
    result = runner.invoke(app, ["webhooks", "verify", str(path), "--secret", "s3cret"])
    assert result.exit_code == 0
    assert "body-signatures" in result.stdout


def test_verify_reads_stdin(tmp_path):
    result = runner.invoke(
        app, ["webhooks", "verify", "-", "--secret", "s3cret"], input=_signed_body()
    )
    assert result.exit_code == 0


def test_verify_fails_closed_and_reports_schemes_tried(tmp_path):
    path = tmp_path / "postback.json"
    path.write_text(_signed_body())
    result = runner.invoke(app, ["webhooks", "verify", str(path), "--secret", "wrong"])
    assert result.exit_code == 1
    assert "body-signatures" in result.stderr


def test_verify_supports_header_scheme(tmp_path):
    secret, timestamp = "s3cret", "1700000000"
    raw = '{"event":"x"}'
    digest = hashlib.md5(f"{secret}.{timestamp}.".encode() + raw.encode()).hexdigest()
    path = tmp_path / "postback.json"
    path.write_text(raw)
    result = runner.invoke(
        app,
        [
            "webhooks",
            "verify",
            str(path),
            "--secret",
            secret,
            "--header",
            f"Cardly-Timestamp={timestamp}",
            "--header",
            f'Cardly-Signatures=["{digest}"]',
        ],
    )
    assert result.exit_code == 0
    assert "header-signatures" in result.stdout


def test_verify_needs_no_api_key(tmp_path):
    # It's an offline utility; requiring credentials would be silly.
    path = tmp_path / "postback.json"
    path.write_text(_signed_body())
    result = runner.invoke(
        app, ["webhooks", "verify", str(path), "--secret", "s3cret"], env={"CARDLY_API_KEY": ""}
    )
    assert result.exit_code == 0
