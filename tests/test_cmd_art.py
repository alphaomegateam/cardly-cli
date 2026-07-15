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
def test_art_list():
    respx.get("https://api.card.ly/v2/art").mock(
        return_value=httpx.Response(
            200, json=ok({"meta": {"totalRecords": 1}, "results": [{"id": "a1", "name": "Thanks"}]})
        )
    )
    result = runner.invoke(app, ["--json", "art", "list"], env=ENV)
    assert json.loads(result.stdout)[0]["id"] == "a1"


@respx.mock
def test_art_list_own_only_uses_ownOnly_param():
    # /art uses ownOnly. The ref endpoints use organisationOnly. Different names.
    route = respx.get("https://api.card.ly/v2/art").mock(
        return_value=httpx.Response(200, json=ok({"meta": {"totalRecords": 0}, "results": []}))
    )
    result = runner.invoke(app, ["--json", "art", "list", "--own-only"], env=ENV)
    assert result.exit_code == 0
    params = route.calls.last.request.url.params
    assert params["ownOnly"] == "true"
    assert "organisationOnly" not in params


@respx.mock
def test_art_get_accepts_a_slug():
    respx.get("https://api.card.ly/v2/art/happy-birthday").mock(
        return_value=httpx.Response(200, json=ok({"id": "a1", "slug": "happy-birthday"}))
    )
    result = runner.invoke(app, ["--json", "art", "get", "happy-birthday"], env=ENV)
    assert json.loads(result.stdout)["slug"] == "happy-birthday"


def test_art_upload_is_not_in_v0_1():
    # Deferred to v0.2: POST /art is application/json with base64-embedded
    # images, which needs its own task and a body-size measurement.
    result = runner.invoke(app, ["art", "upload", "x.png"], env=ENV)
    assert result.exit_code != 0


@respx.mock
def test_art_upload_sends_media_name_and_base64_pages(tmp_path):
    import base64

    front = tmp_path / "front.png"
    front.write_bytes(b"FRONTBYTES")
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "a1", "name": "Thanks"}))

    respx.post("https://api.card.ly/v2/art").mock(side_effect=handler)
    result = runner.invoke(
        app,
        [
            "art",
            "upload",
            "--media",
            "media-uuid-1",
            "--name",
            "Thanks",
            "--description",
            "A card",
            "--artwork",
            str(front),
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    body = captured["body"]
    assert body["media"] == "media-uuid-1"
    assert body["name"] == "Thanks"
    assert body["description"] == "A card"
    assert body["artwork"] == [
        {"page": 1, "image": base64.b64encode(b"FRONTBYTES").decode("ascii")}
    ]


@respx.mock
def test_art_upload_requires_media_and_says_where_to_get_it(tmp_path):
    front = tmp_path / "front.png"
    front.write_bytes(b"x")
    route = respx.post("https://api.card.ly/v2/art").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(
        app, ["art", "upload", "--name", "Thanks", "--artwork", str(front)], env=ENV
    )
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_art_upload_requires_artwork_pages(tmp_path):
    route = respx.post("https://api.card.ly/v2/art").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(app, ["art", "upload", "--media", "m1", "--name", "Thanks"], env=ENV)
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_art_upload_warns_on_a_large_payload(tmp_path, monkeypatch):
    import cardly_cli.commands.art as art_mod

    monkeypatch.setattr(art_mod, "WARN_ENCODED_BYTES", 8)
    big = tmp_path / "big.png"
    big.write_bytes(b"0123456789")
    respx.post("https://api.card.ly/v2/art").mock(
        return_value=httpx.Response(200, json=ok({"id": "a1"}))
    )
    result = runner.invoke(
        app, ["art", "upload", "--media", "m1", "--name", "Big", "--artwork", str(big)], env=ENV
    )
    assert result.exit_code == 0
    assert "large" in result.stderr.lower()


@respx.mock
def test_art_update_posts_to_the_item_path(tmp_path):
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok({"id": "a1", "name": "Renamed"}))

    route = respx.post("https://api.card.ly/v2/art/a1").mock(side_effect=handler)
    result = runner.invoke(app, ["art", "update", "a1", "--name", "Renamed"], env=ENV)
    assert result.exit_code == 0
    assert route.calls.last.request.method == "POST"
    assert captured["body"] == {"name": "Renamed"}


@respx.mock
def test_art_update_rejects_an_empty_body(tmp_path):
    route = respx.post("https://api.card.ly/v2/art/a1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    result = runner.invoke(app, ["art", "update", "a1"], env=ENV)
    assert result.exit_code == 2
    assert not route.called


@respx.mock
def test_art_delete_requires_confirmation():
    route = respx.delete("https://api.card.ly/v2/art/a1").mock(
        return_value=httpx.Response(200, json=ok({}))
    )
    runner.invoke(app, ["art", "delete", "a1"], input="n\n", env=ENV)
    assert not route.called
    result = runner.invoke(app, ["art", "delete", "a1", "--yes"], env=ENV)
    assert result.exit_code == 0
    assert route.called
