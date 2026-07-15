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


def extract_raw_property(raw: bytes, name: str) -> bytes | None:
    """Return the raw byte slice of a TOP-LEVEL property's value.

    Cardly signs the payload as transmitted. Re-serializing with json.dumps
    changes key order and whitespace and silently breaks the hash, so we slice
    the original bytes instead.

    Depth-aware: a nested {"outer": {"data": ...}} must not be mistaken for the
    root "data". String contents (including braces and escaped quotes) are
    skipped rather than parsed.
    """
    text = raw.decode("utf-8", errors="replace")
    depth = 0
    index = 0
    length = len(text)
    target = f'"{name}"'

    while index < length:
        char = text[index]

        if char == '"':
            start = index
            index += 1
            while index < length:
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == '"':
                    break
                index += 1
            token = text[start : index + 1]
            index += 1
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
    if char in "{[":
        depth = 0
        index = start
        while index < len(text):
            current = text[index]
            if current == '"':
                index += 1
                while index < len(text):
                    if text[index] == "\\":
                        index += 2
                        continue
                    if text[index] == '"':
                        break
                    index += 1
            elif current in "{[":
                depth += 1
            elif current in "}]":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1].encode()
            index += 1
        return None
    # Scalar: run to the next delimiter.
    index = start
    while index < len(text) and text[index] not in ",}]":
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

    # Scheme A: timestamp + data from the BODY, matched against body.signatures.
    try:
        body = json.loads(raw_body)
    except (ValueError, TypeError):
        body = None

    if isinstance(body, dict) and "signatures" in body and "timestamp" in body:
        tried.append(SCHEME_BODY)
        raw_data = extract_raw_property(raw_body, "data")
        if raw_data is not None:
            digest = _compute_bytes(secret, str(body["timestamp"]), raw_data)
            if _matches_any(body.get("signatures"), digest):
                return VerifyResult(True, SCHEME_BODY, tried)

    # Scheme B: timestamp from the Cardly-Timestamp header, payload is the RAW
    # body, matched against the Cardly-Signatures header.
    if headers:
        timestamp = _header(headers, "Cardly-Timestamp")
        raw_signatures = _header(headers, "Cardly-Signatures")
        if timestamp and raw_signatures:
            tried.append(SCHEME_HEADER)
            try:
                candidates = json.loads(raw_signatures)
            except (ValueError, TypeError):
                candidates = raw_signatures
            digest = _compute_bytes(secret, timestamp, raw_body)
            if _matches_any(candidates, digest):
                return VerifyResult(True, SCHEME_HEADER, tried)

    if not tried:
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
