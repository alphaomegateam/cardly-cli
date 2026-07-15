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
