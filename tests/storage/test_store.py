"""Store rules over the local backend: prefix, keys, conflicts, size, read-only."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tuvl.storage import (
    Conflict,
    Forbidden,
    InvalidKey,
    NotFound,
    Store,
    StoreSpec,
    TooLarge,
    Unsupported,
)
from tuvl.storage.local import LocalBackend


async def test_put_get_head_roundtrip(local_store: Store) -> None:
    blob = await local_store.put("a/b.txt", b"hello", content_type="text/plain")
    assert blob.key == "a/b.txt"
    assert blob.size == 5
    assert blob.sha256 == hashlib.sha256(b"hello").hexdigest()
    data, got = await local_store.get("a/b.txt")
    assert data == b"hello"
    assert got.content_type == "text/plain"
    assert (await local_store.head("a/b.txt")).etag == blob.etag


async def test_keys_live_under_the_prefix(local_store: Store, tmp_path: Path) -> None:
    await local_store.put("x.txt", b"1")
    assert (tmp_path / "root" / "inv" / "x.txt").read_bytes() == b"1"
    listing = await local_store.list()
    assert [b.key for b in listing.items] == ["x.txt"]


@pytest.mark.parametrize("key", ["../x", "a/../x", "/abs", "a//b", "a/./b", "", "a\\b", "a\x00b"])
async def test_unsafe_keys_are_rejected(local_store: Store, key: str) -> None:
    with pytest.raises(InvalidKey):
        await local_store.put(key, b"x")


async def test_symlink_cannot_escape_the_root(local_store: Store, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    (tmp_path / "root" / "inv").mkdir(parents=True, exist_ok=True)
    (tmp_path / "root" / "inv" / "link").symlink_to(outside)
    with pytest.raises(InvalidKey):
        await local_store.get("link/secret.txt")


async def test_second_put_conflicts_but_identical_content_is_idempotent(local_store: Store) -> None:
    first = await local_store.put("k", b"one")
    again = await local_store.put("k", b"one")
    assert again.sha256 == first.sha256
    with pytest.raises(Conflict):
        await local_store.put("k", b"two")
    over = await local_store.put("k", b"two", if_exists="overwrite")
    assert over.size == 3


async def test_missing_object_is_not_found(local_store: Store) -> None:
    with pytest.raises(NotFound):
        await local_store.get("nope")
    with pytest.raises(NotFound):
        await local_store.head("nope")
    await local_store.delete("nope")


async def test_size_limits(tmp_path: Path) -> None:
    spec = StoreSpec(provider="local", root=str(tmp_path), max_object_bytes=10)
    store = Store("s", spec, LocalBackend(tmp_path))
    with pytest.raises(TooLarge):
        await store.put("big", b"x" * 11)
    await store.put("ok", b"x" * 10)
    with pytest.raises(TooLarge):
        await store.get("ok", max_bytes=5)


async def test_readonly_store_refuses_writes(tmp_path: Path) -> None:
    spec = StoreSpec(provider="local", root=str(tmp_path), readonly=True)
    store = Store("ro", spec, LocalBackend(tmp_path))
    with pytest.raises(Forbidden):
        await store.put("k", b"x")
    with pytest.raises(Forbidden):
        await store.delete("k")
    with pytest.raises(Forbidden):
        await store.copy("a", "b")


async def test_list_pages_in_key_order(local_store: Store) -> None:
    for name in ("c", "a", "b", "d/e"):
        await local_store.put(name, b"1")
    first = await local_store.list(limit=2)
    assert [b.key for b in first.items] == ["a", "b"]
    second = await local_store.list(limit=2, cursor=first.cursor)
    assert [b.key for b in second.items] == ["c", "d/e"]
    assert second.cursor is None
    assert [b.key for b in (await local_store.list("d/")).items] == ["d/e"]


async def test_copy_within_and_across_stores(local_store: Store, tmp_path: Path) -> None:
    await local_store.put("src", b"data", content_type="text/plain")
    copied = await local_store.copy("src", "dst")
    assert copied.key == "dst"
    assert copied.content_type == "text/plain"
    other_spec = StoreSpec(provider="local", root=str(tmp_path / "other"))
    other = Store("other", other_spec, LocalBackend(tmp_path / "other"))
    moved = await local_store.copy("src", "x", to_store=other)
    assert moved.store == "other"
    assert (await other.get("x"))[0] == b"data"
    with pytest.raises(NotFound):
        await local_store.copy("missing", "y")


async def test_presign_is_not_available_locally(local_store: Store) -> None:
    with pytest.raises(Unsupported):
        await local_store.presign("k")


async def test_presign_lifetime_is_bounded(tmp_path: Path) -> None:
    spec = StoreSpec(provider="local", root=str(tmp_path), presign_max_seconds=60)
    store = Store("s", spec, LocalBackend(tmp_path))
    with pytest.raises(InvalidKey):
        await store.presign("k", expires_in=61)


async def test_concurrent_exclusive_puts_have_one_winner(local_store: Store) -> None:
    import asyncio

    results = await asyncio.gather(
        *(local_store.put("race", f"v{i}".encode()) for i in range(8)), return_exceptions=True
    )
    assert sum(1 for r in results if not isinstance(r, Exception)) == 1
    assert all(isinstance(r, Conflict) for r in results if isinstance(r, Exception))


def test_httpx_logs_redact_sas_tokens_and_signatures(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from tuvl.storage.http import Http

    Http()
    with caplog.at_level(logging.INFO, logger="httpx"):
        logging.getLogger("httpx").info(
            'HTTP Request: GET https://a.blob.core.windows.net/c/k?sv=2021&sig=SECRETSIG%3D&se=2026 "200 OK"'
        )
        logging.getLogger("httpx").info("HTTP Request: GET https://h/k?X-Amz-Signature=abc123&x=1")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "SECRETSIG" not in text and "abc123" not in text
    assert "sig=[redacted]" in text and "se=2026" in text


async def test_list_and_head_read_the_stored_digest_instead_of_rehashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from tuvl.storage import local

    backend = LocalBackend(tmp_path)
    store = Store("s", StoreSpec(provider="local", root=str(tmp_path)), backend)
    blob = await store.put("a/b.txt", b"hello")
    meta = json.loads((tmp_path / ".meta" / "a/b.txt.json").read_text())
    assert meta["sha256"] == blob.sha256 == hashlib.sha256(b"hello").hexdigest()

    def no_rehash(*_: object) -> None:
        raise AssertionError("rehashed a file whose digest is stored")

    monkeypatch.setattr(local.hashlib, "sha256", no_rehash)
    assert [b.sha256 for b in (await store.list()).items] == [blob.sha256]
    assert (await store.head("a/b.txt")).sha256 == blob.sha256


async def test_a_file_without_a_stored_digest_or_changed_on_disk_is_hashed(
    tmp_path: Path,
) -> None:
    import json
    import os

    backend = LocalBackend(tmp_path)
    store = Store("s", StoreSpec(provider="local", root=str(tmp_path)), backend)
    await store.put("old", b"one")
    meta_file = tmp_path / ".meta" / "old.json"
    meta = json.loads(meta_file.read_text())
    meta_file.write_text(json.dumps({"content_type": meta["content_type"]}))  # an older version's
    assert (await store.head("old")).sha256 == hashlib.sha256(b"one").hexdigest()

    await store.put("edited", b"before")
    (tmp_path / "edited").write_bytes(b"after!")
    os.utime(tmp_path / "edited", ns=(1, 1))
    assert (await store.head("edited")).sha256 == hashlib.sha256(b"after!").hexdigest()
