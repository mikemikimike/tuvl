from __future__ import annotations

import pytest

from tuvl.storage import (
    STORE_REGISTRY,
    ConfigError,
    build_backend,
    get_store,
    parse_store,
    register_store_from_dict,
    required_env,
    resolved,
)
from tuvl.storage.local import LocalBackend


def doc(**spec: object) -> dict[str, object]:
    return {"kind": "Storage", "metadata": {"name": "s"}, "spec": spec}


def test_literal_secret_is_rejected() -> None:
    with pytest.raises(ConfigError, match="secret_key must be an"):
        parse_store(doc(provider="s3", bucket="b", secret_key="hunter2"))


def test_env_references_are_accepted() -> None:
    _, spec = parse_store(
        doc(provider="s3", bucket="b", access_key="${AWS_ACCESS_KEY_ID}", secret_key="${K:}")
    )
    assert required_env(spec) == ["AWS_ACCESS_KEY_ID"]


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"provider": "s3"}, "needs 'bucket'"),
        ({"provider": "azure", "account": "a"}, "needs 'container'"),
        ({"provider": "gcs"}, "needs 'bucket'"),
        ({"provider": "ftp"}, "provider"),
        ({"provider": "local", "bogus": 1}, "bogus"),
        ({"provider": "s3", "bucket": "b", "endpoint": "http://evil.example.com"}, "https"),
        ({"provider": "local", "prefix": "../x"}, "prefix"),
        ({"provider": "local", "max_object_bytes": 10**9}, "max_object_bytes"),
    ],
)
def test_invalid_stores_are_rejected(spec: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_store(doc(**spec))


@pytest.mark.parametrize(
    "endpoint", ["https://s3.example.com", "http://localhost:9000", "http://127.0.0.1:10000/acct"]
)
def test_endpoints_must_be_https_or_loopback(endpoint: str) -> None:
    _, spec = parse_store(doc(provider="s3", bucket="b", endpoint=endpoint))
    assert spec.endpoint == endpoint


def test_name_is_required() -> None:
    with pytest.raises(ConfigError, match="metadata.name"):
        parse_store({"kind": "Storage", "spec": {"provider": "local"}})


def test_env_expansion_and_missing_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    _, spec = parse_store(doc(provider="s3", bucket="${BUCKET}", region="${REGION:eu-west-1}"))
    with pytest.raises(ConfigError, match="BUCKET"):
        resolved("s", spec)
    monkeypatch.setenv("BUCKET", "acme")
    out = resolved("s", spec)
    assert (out["bucket"], out["region"]) == ("acme", "eu-west-1")


def test_get_store_opens_once_and_reloads_on_new_spec(tmp_path: object) -> None:
    STORE_REGISTRY.clear()
    register_store_from_dict(doc(provider="local", root=str(tmp_path)))
    first = get_store("s")
    assert get_store("s") is first
    register_store_from_dict(doc(provider="local", root=str(tmp_path), readonly=True))
    assert get_store("s") is not first
    with pytest.raises(ConfigError, match="unknown storage 'nope'"):
        get_store("nope")
    STORE_REGISTRY.clear()


def test_half_a_key_pair_is_an_error() -> None:
    _, spec = parse_store(doc(provider="s3", bucket="b", access_key="${A:x}"))
    with pytest.raises(ConfigError, match="go together"):
        build_backend("s", spec)


def test_local_root_is_relative_to_the_project(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tuvl.core.config import settings

    monkeypatch.setattr(type(settings), "project_dir", property(lambda self: tmp_path))
    _, spec = parse_store(doc(provider="local", root="blobs"))
    backend = build_backend("s", spec)
    assert isinstance(backend, LocalBackend)
    assert str(backend.root) == str((tmp_path / "blobs").resolve())  # type: ignore[operator]
