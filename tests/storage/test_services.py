"""One contract suite against real S3-compatible, Azure (Azurite) and GCS (fake-gcs-server) services.

Opt-in: each service is skipped when its port is closed. Start them with the commands in
``docs/storage.md`` (Testing), or run only the local suite.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

from tuvl.storage import Conflict, NotFound, Store, StoreSpec, Unsupported, build_backend

AZURITE_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
)


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


async def _create(method: str, url: str, **kwargs: object) -> None:
    async with httpx.AsyncClient() as client:
        await client.request(method, url, **kwargs)  # type: ignore[arg-type]


async def make_s3(prefix: str) -> Store:
    env = {"S3_KEY": "testkey", "S3_SECRET": "testsecret123"}
    import os

    os.environ.update(env)
    bucket = f"b{uuid.uuid4().hex[:10]}"
    spec = StoreSpec(
        provider="s3",
        bucket=bucket,
        region="us-east-1",
        endpoint="http://localhost:19000",
        access_key="${S3_KEY}",
        secret_key="${S3_SECRET}",
        prefix=prefix,
    )
    store = Store("s3", spec, build_backend("s3", spec))
    await store.backend._send("PUT", store.backend._url(""), ok=(200, 201))  # type: ignore[attr-defined]
    return store


async def make_azure(prefix: str) -> Store:
    import os

    os.environ["AZ_KEY"] = AZURITE_KEY
    container = f"c{uuid.uuid4().hex[:10]}"
    spec = StoreSpec(
        provider="azure",
        account="devstoreaccount1",
        container=container,
        endpoint="http://127.0.0.1:10000/devstoreaccount1",
        account_key="${AZ_KEY}",
        prefix=prefix,
    )
    store = Store("az", spec, build_backend("az", spec))
    backend = store.backend
    await backend._send(  # type: ignore[attr-defined]
        "PUT",
        backend._url("", "restype=container"),
        ok=(201,),  # type: ignore[attr-defined]
    )
    return store


async def make_gcs(prefix: str) -> Store:
    import os

    os.environ["GCS_TOKEN"] = "fake"
    bucket = f"b{uuid.uuid4().hex[:10]}"
    await _create("POST", "http://localhost:14443/storage/v1/b?project=p", json={"name": bucket})
    spec = StoreSpec(
        provider="gcs",
        bucket=bucket,
        endpoint="http://localhost:14443",
        access_token="${GCS_TOKEN}",
        prefix=prefix,
    )
    return Store("gcs", spec, build_backend("gcs", spec))


SERVICES = {
    "s3": (19000, make_s3),
    "azure": (10000, make_azure),
    "gcs": (14443, make_gcs),
}


@pytest.fixture(params=sorted(SERVICES))
async def store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    port, factory = SERVICES[request.param]
    if not listening(port):
        pytest.skip(f"{request.param} emulator not running on :{port}")
    created = await factory("t/")
    yield created
    await created.aclose()


async def test_roundtrip_and_metadata(store: Store) -> None:
    blob = await store.put("dir/a b.txt", b"hello", content_type="text/plain")
    assert (blob.key, blob.size) == ("dir/a b.txt", 5)
    data, got = await store.get("dir/a b.txt")
    assert data == b"hello"
    head = await store.head("dir/a b.txt")
    assert head.size == 5
    assert head.sha256 == blob.sha256 or head.sha256 == ""
    assert got.content_type.startswith("text/plain")


async def test_exclusive_put(store: Store) -> None:
    await store.put("k", b"one")
    assert (await store.put("k", b"one")).size == 3
    with pytest.raises(Conflict):
        await store.put("k", b"two")
    assert (await store.get("k"))[0] == b"one"
    await store.put("k", b"two!", if_exists="overwrite")
    assert (await store.get("k"))[0] == b"two!"


async def test_missing_and_delete(store: Store) -> None:
    with pytest.raises(NotFound):
        await store.get("nope")
    with pytest.raises(NotFound):
        await store.head("nope")
    await store.put("gone", b"x")
    await store.delete("gone")
    with pytest.raises(NotFound):
        await store.head("gone")
    await store.delete("gone")


async def test_list_paging_and_prefix(store: Store) -> None:
    for name in ("a/1", "a/2", "a/3", "b/1"):
        await store.put(name, b"x")
    first = await store.list("a/", limit=2)
    assert [b.key for b in first.items] == ["a/1", "a/2"]
    assert first.cursor
    second = await store.list("a/", limit=2, cursor=first.cursor)
    assert [b.key for b in second.items] == ["a/3"]
    assert second.cursor is None


async def test_copy(store: Store) -> None:
    await store.put("src", b"payload", content_type="text/plain")
    copied = await store.copy("src", "dst")
    assert (await store.get("dst"))[0] == b"payload"
    assert copied.key == "dst"
    with pytest.raises(Conflict):
        await store.copy("src", "dst")
    with pytest.raises(NotFound):
        await store.copy("missing", "z")


async def test_presigned_urls_work_without_credentials(store: Store) -> None:
    await store.put("p.txt", b"presigned body")
    try:
        signed = await store.presign("p.txt", expires_in=60)
    except Unsupported:
        pytest.skip("provider has no presign in this mode")
    async with httpx.AsyncClient() as client:
        response = await client.get(signed.url)
        assert response.status_code == 200
        assert response.content == b"presigned body"
        put = await store.presign("up.txt", "PUT", 60)
        headers = {"x-ms-blob-type": "BlockBlob"} if "sig=" in put.url else {}
        uploaded = await client.put(put.url, content=b"uploaded", headers=headers)
        assert uploaded.status_code in (200, 201)
    assert (await store.get("up.txt"))[0] == b"uploaded"


async def test_parallel_writes(store: Store) -> None:
    await asyncio.gather(*(store.put(f"par/{i}", f"v{i}".encode()) for i in range(10)))
    listing = await store.list("par/", limit=100)
    assert len(listing.items) == 10
