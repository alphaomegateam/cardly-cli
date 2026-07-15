import base64

import pytest
import typer

from cardly_cli.artwork import (
    WARN_ENCODED_BYTES,
    build_artwork_pages,
    encode_image,
    encoded_size,
)


def test_warn_threshold_is_ten_megabytes():
    assert WARN_ENCODED_BYTES == 10 * 1024 * 1024


def test_encode_image_round_trips(tmp_path):
    img = tmp_path / "front.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n binary payload")
    encoded = encode_image(img)
    assert base64.b64decode(encoded) == b"\x89PNG\r\n\x1a\n binary payload"


def test_encode_image_missing_file_is_a_clean_error(tmp_path):
    with pytest.raises(typer.BadParameter, match="not found"):
        encode_image(tmp_path / "nope.png")


def test_encode_image_empty_file_rejected(tmp_path):
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    with pytest.raises(typer.BadParameter, match="empty"):
        encode_image(empty)


def test_build_artwork_pages_defaults_to_sequential_1_based(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"aaa")
    b.write_bytes(b"bbb")
    pages = build_artwork_pages([str(a), str(b)])
    assert [p["page"] for p in pages] == [1, 2]
    assert base64.b64decode(pages[0]["image"]) == b"aaa"


def test_build_artwork_pages_explicit_page_numbers(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"aaa")
    b.write_bytes(b"bbb")
    pages = build_artwork_pages([f"3={b}", f"1={a}"])
    assert [p["page"] for p in pages] == [1, 3]
    assert base64.b64decode(pages[0]["image"]) == b"aaa"


def test_build_artwork_pages_rejects_duplicate_page(tmp_path):
    a = tmp_path / "a.png"
    a.write_bytes(b"aaa")
    with pytest.raises(typer.BadParameter, match="[Dd]uplicate"):
        build_artwork_pages([f"1={a}", f"1={a}"])


def test_build_artwork_pages_rejects_non_integer_page(tmp_path):
    a = tmp_path / "a.png"
    a.write_bytes(b"aaa")
    with pytest.raises(typer.BadParameter, match="integer"):
        build_artwork_pages([f"front={a}"])


def test_build_artwork_pages_rejects_page_below_one(tmp_path):
    a = tmp_path / "a.png"
    a.write_bytes(b"aaa")
    with pytest.raises(typer.BadParameter, match="1-based"):
        build_artwork_pages([f"0={a}"])


def test_build_artwork_pages_empty_returns_empty():
    assert build_artwork_pages([]) == []


def test_build_artwork_pages_uses_page_key_not_name(tmp_path):
    # Cardly's own OpenAPI example ships {"name": 2} for message pages. The
    # field is `page`. Do not repeat that mistake here.
    a = tmp_path / "a.png"
    a.write_bytes(b"aaa")
    page = build_artwork_pages([str(a)])[0]
    assert set(page) == {"page", "image"}


def test_encoded_size_sums_image_bytes(tmp_path):
    a = tmp_path / "a.png"
    a.write_bytes(b"x" * 300)
    pages = build_artwork_pages([str(a)])
    assert encoded_size(pages) == len(pages[0]["image"])
