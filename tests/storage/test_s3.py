from __future__ import annotations

import pytest

from tuvl.storage import (
    AuthError,
    Conflict,
    NotFound,
    RateLimited,
    Store,
    StoreSpec,
    TooLarge,
    Unavailable,
)
from tuvl.storage.creds import AwsCredentialSource
from tuvl.storage.http import Http
from tuvl.storage.s3 import S3Backend
from tuvl.storage.sigv4 import AwsCreds

from .fakes import FakeS3

CREDS = AwsCreds("AKID", "SECRET")


def make(
    fake: FakeS3, *, prefix: str = "", endpoint: str = "http://localhost:9000", **kw: object
) -> Store:
    http = Http(5, fake.transport())
    backend = S3Backend(
        bucket=fake.bucket,
        region="us-east-1",
        endpoint=endpoint,
        path_style=kw.get("path_style"),  # type: ignore[arg-type]
        creds=AwsCredentialSource(static=CREDS, region="us-east-1", http=http),
        http=http,
    )
    spec = StoreSpec(provider="s3", bucket=fake.bucket, prefix=prefix)
    return Store("s3store", spec, backend)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr("tuvl.storage.store.asyncio.sleep", instant)


async def test_roundtrip_with_prefix_and_metadata() -> None:
    fake = FakeS3()
    store = make(fake, prefix="inv/")
    blob = await store.put("a b/c.txt", b"hello", content_type="text/plain", metadata={"k": "v"})
    assert blob.sha256 and blob.size == 5
    assert "inv/a b/c.txt" in fake.objects
    assert fake.objects["inv/a b/c.txt"].headers["x-amz-meta-k"] == "v"
    data, got = await store.get("a b/c.txt")
    assert data == b"hello"
    assert (got.key, got.sha256) == ("a b/c.txt", blob.sha256)
    head = await store.head("a b/c.txt")
    assert head.size == 5
    assert head.modified == "2026-10-17T10:00:00Z"


async def test_requests_are_signed_and_never_carry_secrets() -> None:
    fake = FakeS3()
    store = make(fake)
    await store.put("k", b"x")
    request = fake.requests[0]
    assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKID/")
    assert "SECRET" not in str(request.headers)
    assert request.headers["x-amz-content-sha256"]


async def test_exclusive_put_conflicts_but_same_content_is_idempotent() -> None:
    fake = FakeS3()
    store = make(fake)
    await store.put("k", b"one")
    assert (await store.put("k", b"one")).size == 3
    with pytest.raises(Conflict):
        await store.put("k", b"two")
    assert (await store.put("k", b"two", if_exists="overwrite")).size == 3


async def test_not_found_and_idempotent_delete() -> None:
    store = make(FakeS3())
    with pytest.raises(NotFound):
        await store.get("missing")
    with pytest.raises(NotFound):
        await store.head("missing")
    await store.delete("missing")


async def test_list_paginates() -> None:
    fake = FakeS3()
    store = make(fake, prefix="p/")
    for name in ("a", "b", "c"):
        await store.put(name, b"1")
    first = await store.list(limit=2)
    assert [b.key for b in first.items] == ["a", "b"]
    second = await store.list(limit=2, cursor=first.cursor)
    assert [b.key for b in second.items] == ["c"]
    assert second.cursor is None


async def test_server_side_copy() -> None:
    fake = FakeS3()
    store = make(fake)
    await store.put("src", b"data", content_type="text/plain")
    copied = await store.copy("src", "dst")
    assert copied.key == "dst"
    assert fake.objects["dst"].data == b"data"
    with pytest.raises(Conflict):
        await store.copy("src", "dst")
    with pytest.raises(NotFound):
        await store.copy("nope", "z")


async def test_throttling_is_retried_then_surfaces() -> None:
    fake = FakeS3()
    store = make(fake)
    fake.fail_next = [503, 503]
    await store.put("k", b"x")
    fake.fail_next = [503, 503, 503]
    with pytest.raises(RateLimited):
        await store.head("k")


async def test_server_errors_map_to_unavailable() -> None:
    fake = FakeS3()
    store = make(fake)
    fake.fail_next = [500, 500, 500]
    with pytest.raises(Unavailable):
        await store.head("k")


async def test_oversized_download_is_refused() -> None:
    fake = FakeS3()
    store = make(fake)
    await store.put("big", b"x" * 100)
    with pytest.raises(TooLarge):
        await store.get("big", max_bytes=10)


async def test_url_shapes() -> None:
    fake = FakeS3()
    path = make(fake, endpoint="http://localhost:9000")
    await path.put("k", b"x")
    assert str(fake.requests[-1].url) == "http://localhost:9000/b/k"
    virtual = make(fake, endpoint="", path_style=None)
    backend = virtual.backend
    assert isinstance(backend, S3Backend)
    assert backend._url("k") == "https://b.s3.amazonaws.com/k" or backend._url("k").startswith(
        "https://b.s3.us-east-1"
    )
    dotted = S3Backend(
        bucket="my.bucket",
        region="eu-west-1",
        endpoint="",
        path_style=None,
        creds=backend._creds,
        http=backend._http,
    )
    assert dotted._url("k") == "https://s3.eu-west-1.amazonaws.com/my.bucket/k"


async def test_presigned_urls_carry_a_signature_and_no_header_auth() -> None:
    store = make(FakeS3())
    signed = await store.presign("a b.txt", expires_in=60)
    assert "X-Amz-Signature=" in signed.url and "X-Amz-Expires=60" in signed.url
    assert "a%20b.txt" in signed.url
    assert "SECRET" not in signed.url
    put = await store.presign("k", "PUT", 30)
    assert "X-Amz-Expires=30" in put.url


async def test_missing_credentials_message(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    ):
        monkeypatch.delenv(var, raising=False)
    import httpx

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    http = Http(1, httpx.MockTransport(refuse))
    source = AwsCredentialSource(static=None, region="r", http=http, metadata_http=http)
    with pytest.raises(AuthError, match="no AWS credentials"):
        await source.get()
