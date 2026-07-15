from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

# The worked example from Cardly's docs. Both documented schemes cite this SAME
# vector, which is exactly why it cannot discriminate between them: it pins the
# shared md5 primitive and nothing else.
GOLDEN_SECRET = "secretabc"
GOLDEN_TIMESTAMP = "1234567890"
GOLDEN_PAYLOAD = '{"test":true}'
GOLDEN_DIGEST = "6ef4f0658ff7bb880fc3ae0cf7db3b2a"

SCHEME_BODY = "body-signatures"
SCHEME_HEADER = "header-signatures"


def compute(secret: str, timestamp: str, payload: str) -> str:
    """md5(secret + "." + timestamp + "." + payload).

    MD5, not HMAC. Weak by modern standards, but it is what Cardly implements.
    """
    return hashlib.md5(f"{secret}.{timestamp}.{payload}".encode()).hexdigest()


def _compute_bytes(secret: str, timestamp: str, payload: bytes) -> str:
    return hashlib.md5(f"{secret}.{timestamp}.".encode() + payload).hexdigest()


def _skip_string(text: str, index: int) -> int:
    """Advance past a JSON string starting at text[index] == '"'.

    Escaped characters (including escaped quotes) are skipped rather than
    parsed. Returns the index just past the closing quote. Shared by every
    string-content-skipping path so the depth-scanning and value-slicing
    logic can never drift apart.
    """
    index += 1
    length = len(text)
    while index < length:
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == '"':
            return index + 1
        index += 1
    return index


def extract_raw_property(raw: bytes, name: str) -> bytes | None:
    """Return the raw byte slice of a TOP-LEVEL property's value.

    Cardly signs the payload as transmitted. Re-serializing with json.dumps
    changes key order and whitespace and silently breaks the hash, so we slice
    the original bytes instead.

    Depth-aware: a nested {"outer": {"data": ...}} must not be mistaken for the
    root "data". String contents (including braces and escaped quotes) are
    skipped rather than parsed.

    Decoding is strict UTF-8: valid JSON must be valid UTF-8, so a decode
    failure means a malformed body, and returning None here (rather than
    silently mangling the slice via errors="replace") lets callers give an
    honest diagnostic instead of a garbage hash.

    Note on duplicate top-level keys: this is invalid JSON, but if it occurs
    anyway, this raw-slice scan takes the FIRST occurrence while json.loads
    takes the last. That's a deliberate first-wins convention here, not a bug.
    """
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    depth = 0
    index = 0
    length = len(text)
    target = f'"{name}"'

    while index < length:
        char = text[index]

        if char == '"':
            start = index
            index = _skip_string(text, index)
            token = text[start:index]
            # Only a key at depth 1 (directly inside the root object) counts.
            if depth == 1 and token == target:
                while index < length and text[index] in " \t\r\n":
                    index += 1
                if index < length and text[index] == ":":
                    index += 1
                    while index < length and text[index] in " \t\r\n":
                        index += 1
                    return _slice_value(text, index)
            continue

        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        index += 1

    return None


def _slice_value(text: str, start: int) -> bytes | None:
    """Slice one JSON value beginning at `start`, preserving it byte for byte."""
    if start >= len(text):
        return None
    char = text[start]
    length = len(text)
    if char in "{[":
        depth = 0
        index = start
        while index < length:
            current = text[index]
            if current == '"':
                index = _skip_string(text, index)
                continue
            elif current in "{[":
                depth += 1
            elif current in "}]":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1].encode()
            index += 1
        return None
    # Scalar: run to the next delimiter, skipping over string content so a
    # comma/brace/bracket INSIDE a string scalar doesn't truncate the slice.
    index = start
    while index < length and text[index] not in ",}]":
        if text[index] == '"':
            index = _skip_string(text, index)
            continue
        index += 1
    return text[start:index].strip().encode()


@dataclass(frozen=True)
class VerifyResult:
    matched: bool
    scheme: str | None = None
    tried: list[str] = field(default_factory=list)
    reason: str | None = None


def _matches_any(candidates: Any, digest: str) -> bool:
    if isinstance(candidates, str):
        candidates = [candidates]
    if not isinstance(candidates, list):
        return False
    # A match against ANY entry passes. Constant-time compare.
    return any(
        isinstance(entry, str) and hmac.compare_digest(entry.strip(), digest)
        for entry in candidates
    )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    return lowered.get(name.lower())


def verify(
    raw_body: bytes, secret: str, *, headers: Mapping[str, str] | None = None
) -> VerifyResult:
    """Verify a Cardly postback signature, trying both documented schemes.

    Cardly's docs describe two mutually exclusive schemes and share one golden
    vector between them, so the vector cannot tell them apart and neither has
    been confirmed against a live postback. Rather than pick one and be wrong
    half the time, try whichever the available inputs permit and report which
    matched — that answer is the thing worth learning.

    Fails closed: any parse failure, missing input, or empty secret is a
    non-match.
    """
    tried: list[str] = []
    if not secret:
        return VerifyResult(False, None, tried, "No secret supplied.")

    # Checked up front (independent of json.loads, which would raise and be
    # swallowed below) so a decode failure gets its own honest diagnostic
    # rather than being folded into the generic "no signature material" text.
    try:
        raw_body.decode("utf-8", errors="strict")
        body_is_utf8 = True
    except UnicodeDecodeError:
        body_is_utf8 = False

    # Scheme A: timestamp + data from the BODY, matched against body.signatures.
    try:
        body = json.loads(raw_body)
    except (ValueError, TypeError):
        body = None

    if isinstance(body, dict) and "signatures" in body and "timestamp" in body:
        raw_data = extract_raw_property(raw_body, "data")
        if raw_data is not None:
            digest = _compute_bytes(secret, str(body["timestamp"]), raw_data)
            # Only recorded as "tried" once a digest has genuinely been
            # computed — a shape that merely looks eligible (e.g. missing
            # `data`) must never be reported as an attempted comparison.
            tried.append(SCHEME_BODY)
            if _matches_any(body.get("signatures"), digest):
                return VerifyResult(True, SCHEME_BODY, tried)

    # Scheme B: timestamp from the Cardly-Timestamp header, payload is the RAW
    # body, matched against the Cardly-Signatures header.
    if headers:
        timestamp = _header(headers, "Cardly-Timestamp")
        raw_signatures = _header(headers, "Cardly-Signatures")
        if timestamp and raw_signatures:
            try:
                candidates = json.loads(raw_signatures)
            except (ValueError, TypeError):
                candidates = raw_signatures
            digest = _compute_bytes(secret, timestamp, raw_body)
            tried.append(SCHEME_HEADER)
            if _matches_any(candidates, digest):
                return VerifyResult(True, SCHEME_HEADER, tried)

    if not tried:
        if not body_is_utf8:
            reason = (
                "Body is not valid UTF-8 and could not be decoded, so no signature "
                "material could be extracted from it."
            )
        else:
            reason = (
                "No signature material found. Expected either a body with "
                "`timestamp`/`data`/`signatures`, or Cardly-Timestamp and "
                "Cardly-Signatures headers."
            )
    else:
        reason = (
            f"No signature matched. Tried: {', '.join(tried)}. Cardly documents "
            f"two schemes; if the postback is genuine, the other scheme may be "
            f"live — please report which one worked."
        )
    return VerifyResult(False, None, tried, reason)
