import hashlib
import json

from cardly_cli.signature import (
    GOLDEN_DIGEST,
    GOLDEN_PAYLOAD,
    GOLDEN_SECRET,
    GOLDEN_TIMESTAMP,
    compute,
    extract_raw_property,
    verify,
)


def test_golden_vector_from_cardly_docs():
    # md5("secretabc.1234567890.{"test":true}") == 6ef4f0658ff7bb880fc3ae0cf7db3b2a
    # Both documented schemes cite this same vector, which is exactly why it
    # cannot tell them apart — it only pins the shared md5 primitive.
    assert compute(GOLDEN_SECRET, GOLDEN_TIMESTAMP, GOLDEN_PAYLOAD) == GOLDEN_DIGEST
    assert GOLDEN_DIGEST == "6ef4f0658ff7bb880fc3ae0cf7db3b2a"


def test_extract_raw_property_returns_bytes_as_transmitted():
    raw = b'{"timestamp":"1","data":{"b":2,"a":1},"signatures":["x"]}'
    # Note key order b,a preserved and no whitespace added.
    assert extract_raw_property(raw, "data") == b'{"b":2,"a":1}'


def test_extract_raw_property_preserves_whitespace_exactly():
    raw = b'{"data": { "a" : 1 } }'
    assert extract_raw_property(raw, "data") == b'{ "a" : 1 }'


def test_extract_raw_property_is_depth_aware():
    # A nested "data" key must NOT be mistaken for the root one.
    raw = b'{"outer":{"data":{"wrong":true}},"data":{"right":true}}'
    assert extract_raw_property(raw, "data") == b'{"right":true}'


def test_extract_raw_property_handles_strings_with_braces():
    raw = b'{"note":"} not a brace {","data":{"a":1}}'
    assert extract_raw_property(raw, "data") == b'{"a":1}'


def test_extract_raw_property_handles_escaped_quotes():
    raw = rb'{"note":"say \"hi\" }","data":{"a":1}}'
    assert extract_raw_property(raw, "data") == b'{"a":1}'


def test_extract_raw_property_missing_returns_none():
    assert extract_raw_property(b'{"a":1}', "data") is None


def test_extract_raw_property_non_object_value():
    assert extract_raw_property(b'{"data":[1,2]}', "data") == b"[1,2]"
    assert extract_raw_property(b'{"data":true}', "data") == b"true"
    assert extract_raw_property(b'{"data":123}', "data") == b"123"


def test_extract_raw_property_scalar_string_with_comma_and_brace_not_truncated():
    # CRITICAL regression: a scalar string containing "," or "}" must not
    # truncate the slice. The old scalar branch had no string-skipping logic.
    assert extract_raw_property(b'{"data":"a,b}c"}', "data") == b'"a,b}c"'


def test_extract_raw_property_scalar_string_with_bracket_not_truncated():
    assert extract_raw_property(b'{"data":"a]b"}', "data") == b'"a]b"'


def test_extract_raw_property_scalar_string_with_escaped_quote_not_truncated():
    raw = rb'{"data":"say \"hi\", ok"}'
    assert extract_raw_property(raw, "data") == rb'"say \"hi\", ok"'


def test_extract_raw_property_invalid_utf8_returns_none():
    # Strict decoding: an undecodable body must return None rather than
    # silently mangling the slice via errors="replace".
    raw = b'{"data":{"note":"\xff\xfe bad","a":1}}'
    assert extract_raw_property(raw, "data") is None


def _scheme_a_body(secret="s3cret", timestamp="1700000000", data=None):
    data = {"event": "contact.order.sent", "id": "o1"} if data is None else data
    raw_data = json.dumps(data, separators=(",", ":"))
    digest = hashlib.md5(f"{secret}.{timestamp}.{raw_data}".encode()).hexdigest()
    body = f'{{"timestamp":"{timestamp}","data":{raw_data},"signatures":["{digest}"]}}'
    return body.encode(), digest


def test_verify_scheme_a_body_signatures_array():
    raw, _ = _scheme_a_body()
    result = verify(raw, "s3cret")
    assert result.matched
    assert result.scheme == "body-signatures"


def test_verify_scheme_a_matches_any_entry_in_the_array():
    raw, digest = _scheme_a_body()
    body_raw = raw.replace(f'["{digest}"]'.encode(), f'["deadbeef","{digest}"]'.encode())
    assert verify(body_raw, "s3cret").matched


def test_verify_scheme_b_header_signatures():
    secret, timestamp = "s3cret", "1700000000"
    raw = b'{"event":"contact.order.sent"}'
    digest = hashlib.md5(f"{secret}.{timestamp}.".encode() + raw).hexdigest()
    result = verify(
        raw,
        secret,
        headers={"Cardly-Timestamp": timestamp, "Cardly-Signatures": json.dumps([digest])},
    )
    assert result.matched
    assert result.scheme == "header-signatures"


def test_verify_header_scheme_accepts_bare_string_header():
    secret, timestamp = "s3cret", "1700000000"
    raw = b'{"a":1}'
    digest = hashlib.md5(f"{secret}.{timestamp}.".encode() + raw).hexdigest()
    result = verify(
        raw, secret, headers={"Cardly-Timestamp": timestamp, "Cardly-Signatures": digest}
    )
    assert result.matched


def test_verify_headers_are_case_insensitive():
    secret, timestamp = "s3cret", "1700000000"
    raw = b'{"a":1}'
    digest = hashlib.md5(f"{secret}.{timestamp}.".encode() + raw).hexdigest()
    result = verify(
        raw,
        secret,
        headers={"cardly-timestamp": timestamp, "cardly-signatures": json.dumps([digest])},
    )
    assert result.matched


def test_verify_fails_closed_on_wrong_secret():
    raw, _ = _scheme_a_body()
    result = verify(raw, "wrong-secret")
    assert not result.matched
    assert result.scheme is None


def test_verify_reports_every_scheme_tried():
    raw, _ = _scheme_a_body()
    result = verify(raw, "wrong", headers={"Cardly-Timestamp": "1", "Cardly-Signatures": "[]"})
    assert not result.matched
    assert "body-signatures" in result.tried
    assert "header-signatures" in result.tried
    assert result.reason  # names what was tried rather than asserting "bad signature"


def test_verify_tries_only_body_scheme_without_headers():
    raw, _ = _scheme_a_body()
    result = verify(raw, "wrong")
    assert result.tried == ["body-signatures"]


def test_verify_fails_closed_on_unparseable_body():
    result = verify(b"not json", "s")
    assert not result.matched
    assert result.reason


def test_verify_fails_closed_on_empty_secret():
    raw, _ = _scheme_a_body()
    assert not verify(raw, "").matched


def test_verify_tried_excludes_body_scheme_when_data_missing():
    # IMPORTANT: shape looked eligible (signatures + timestamp present) but
    # `data` is absent, so no digest was ever computed for this scheme — it
    # must not be reported as "tried".
    raw = b'{"signatures":["x"],"timestamp":"1"}'
    result = verify(raw, "secret")
    assert result.tried == []
    assert not result.matched
    assert "no signature material" in result.reason.lower()


def test_verify_tried_includes_body_scheme_when_digest_computed_wrong_secret():
    raw, _ = _scheme_a_body()
    result = verify(raw, "wrong-secret")
    assert result.tried == ["body-signatures"]
    assert not result.matched


def test_verify_fails_closed_on_invalid_utf8_body_with_clear_reason():
    raw = b'{"data":{"note":"\xff\xfe bad","a":1}}'
    result = verify(raw, "secret")
    assert result.matched is False
    assert result.reason is not None
    reason_lower = result.reason.lower()
    assert "utf-8" in reason_lower or "decode" in reason_lower


def test_verify_uses_raw_slice_not_reserialized_data():
    # Cardly signs `data` AS TRANSMITTED. Build a body whose data has key order
    # and spacing that json.dumps would never reproduce; only a raw slice can
    # match.
    secret, timestamp = "s3cret", "1700000000"
    weird = '{ "z":1,   "a":2 }'
    digest = hashlib.md5(f"{secret}.{timestamp}.{weird}".encode()).hexdigest()
    raw = f'{{"timestamp":"{timestamp}","data":{weird},"signatures":["{digest}"]}}'.encode()
    result = verify(raw, secret)
    assert result.matched, "re-serializing data breaks the hash; must use the raw byte slice"
