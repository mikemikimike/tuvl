"""SigV4 against signatures produced by botocore for the same inputs and clock."""

from __future__ import annotations

from datetime import UTC, datetime

from tuvl.storage.sigv4 import EMPTY_SHA256, AwsCreds, presign_url, sha256_hex, sign_headers

NOW = datetime(2013, 5, 24, tzinfo=UTC)
CREDS = AwsCreds("AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")


def test_presigned_get_matches_botocore() -> None:
    url = presign_url(
        "GET",
        "https://examplebucket.s3.us-east-1.amazonaws.com/test%20file.txt",
        CREDS,
        "us-east-1",
        86400,
        now=NOW,
    )
    assert url == (
        "https://examplebucket.s3.us-east-1.amazonaws.com/test%20file.txt"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
        "&X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2Fus-east-1%2Fs3%2Faws4_request"
        "&X-Amz-Date=20130524T000000Z&X-Amz-Expires=86400&X-Amz-SignedHeaders=host"
        "&X-Amz-Signature=081b7f4e0bdc109e6d111432886b7126549d2e9093482a9efcf523ef84db46bb"
    )


def test_put_headers_match_botocore() -> None:
    out = sign_headers(
        "PUT",
        "http://localhost:9000/bucket/a/b%20c.txt",
        {"content-type": "text/plain", "x-amz-meta-sha256": "abc"},
        sha256_hex(b"hello"),
        CREDS,
        "us-east-1",
        now=NOW,
    )
    assert out["x-amz-date"] == "20130524T000000Z"
    assert out["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date;x-amz-meta-sha256, "
        "Signature=dbf495898e8911701bee00463a5d7ab8764e9486417d45b7938c8d432a10ad0d"
    )


def test_query_and_session_token_match_botocore() -> None:
    creds = AwsCreds(CREDS.access_key, CREDS.secret_key, "TOKEN123")
    out = sign_headers(
        "GET",
        "http://localhost:9000/bucket?list-type=2&max-keys=10&prefix=a%2Fb",
        {},
        EMPTY_SHA256,
        creds,
        "eu-west-1",
        now=NOW,
    )
    assert out["authorization"].endswith(
        "SignedHeaders=host;x-amz-content-sha256;x-amz-date;x-amz-security-token, "
        "Signature=8451cdfa6e4b6283cc01440238608034d886110525f47c2b9f040eb101f1991d"
    )
