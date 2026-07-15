from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import typer

# Cardly's real request-body ceiling is UNVERIFIED — it is undocumented and
# mocked tests cannot measure it. So this is a warning threshold, not a limit:
# we tell the user the payload is large and let the API be the authority,
# rather than inventing a rule that might reject a body Cardly would accept.
WARN_ENCODED_BYTES = 10 * 1024 * 1024


def encode_image(path: Path) -> str:
    """Base64-encode an image file's contents.

    Reads the file ONCE and encodes from those bytes — no second read for a
    size check. Base64 inflates the payload by roughly a third.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise typer.BadParameter(f"Artwork file not found or unreadable: {path} ({exc})") from exc
    if not raw:
        raise typer.BadParameter(f"Artwork file is empty: {path}")
    return base64.b64encode(raw).decode("ascii")


def build_artwork_pages(specs: list[str]) -> list[dict[str, Any]]:
    """Build Cardly's `artwork` array from `PATH` or `N=PATH` specs.

    Bare paths are numbered sequentially from 1 in the order given. `N=PATH`
    sets the page explicitly. `page` is 1-based and 1 is the FRONT — the same
    convention as order message pages, where Cardly's own example wrongly shows
    a `name` key. The key here is `page`.
    """
    if not specs:
        return []
    pages: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, spec in enumerate(specs, start=1):
        number, sep, raw_path = spec.partition("=")
        if sep:
            if not number.strip().lstrip("-").isdigit():
                raise typer.BadParameter(
                    f"--artwork page must be an integer, got {number!r} in {spec!r}"
                )
            page = int(number)
            path_text = raw_path
        else:
            page = index
            path_text = spec
        if page < 1:
            raise typer.BadParameter(f"--artwork page is 1-based (1 = front), got {page}")
        if page in seen:
            raise typer.BadParameter(
                f"Duplicate --artwork page {page}; each page may be given once."
            )
        seen.add(page)
        pages.append({"page": page, "image": encode_image(Path(path_text))})
    return sorted(pages, key=lambda item: item["page"])


def encoded_size(pages: list[dict[str, Any]]) -> int:
    """Total base64 length across pages — what the size warning is measured on."""
    return sum(len(str(page.get("image", ""))) for page in pages)
