"""Credential sources against fake identity services."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from tuvl.storage.creds import AwsCredentialSource, azure_token_source, gcs_token_source
from tuvl.storage.http import Http

CLEAR = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AZURE_FEDERATED_TOKEN_FILE",
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
)
FUTURE = "2999-01-01T00:00:00Z"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in CLEAR:
        monkeypatch.delenv(var, raising=False)


def http_for(handler: object) -> Http:
    return Http(2, httpx.MockTransport(handler))  # type: ignore[arg-type]


async def test_environment_keys() -> None:
    import os

    os.environ.update(AWS_ACCESS_KEY_ID="E1", AWS_SECRET_ACCESS_KEY="E2", AWS_SESSION_TOKEN="E3")
    source = AwsCredentialSource(
        static=None, region="r", http=http_for(lambda r: httpx.Response(500))
    )
    creds = await source.get()
    assert (creds.access_key, creds.secret_key, creds.token) == ("E1", "E2", "E3")


async def test_web_identity_exchanges_the_token_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = tmp_path / "token"
    token.write_text("jwt-from-k8s")
    monkeypatch.setenv("AWS_WEB_IDENTITY_TOKEN_FILE", str(token))
    seen: list[httpx.Request] = []

    def sts(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            text=(
                '<AssumeRoleWithWebIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">'
                "<AssumeRoleWithWebIdentityResult><Credentials><AccessKeyId>AK</AccessKeyId>"
                f"<SecretAccessKey>SK</SecretAccessKey><SessionToken>ST</SessionToken>"
                f"<Expiration>{FUTURE}</Expiration></Credentials></AssumeRoleWithWebIdentityResult>"
                "</AssumeRoleWithWebIdentityResponse>"
            ),
        )

    source = AwsCredentialSource(
        static=None, region="eu-west-1", role_arn="arn:aws:iam::1:role/r", http=http_for(sts)
    )
    creds = await source.get()
    assert (creds.access_key, creds.token) == ("AK", "ST")
    assert str(seen[0].url) == "https://sts.eu-west-1.amazonaws.com/"
    assert b"WebIdentityToken=jwt-from-k8s" in seen[0].content
    await source.get()
    assert len(seen) == 1


async def test_container_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "/v2/creds/abc")

    def ecs(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://169.254.170.2/v2/creds/abc"
        return httpx.Response(
            200,
            json={"AccessKeyId": "A", "SecretAccessKey": "S", "Token": "T", "Expiration": FUTURE},
        )

    source = AwsCredentialSource(
        static=None, region="r", http=http_for(ecs), metadata_http=http_for(ecs)
    )
    assert (await source.get()).token == "T"


async def test_instance_metadata_v2() -> None:
    calls: list[tuple[str, str]] = []

    def imds(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "PUT":
            return httpx.Response(200, text="TOKEN")
        assert request.headers["x-aws-ec2-metadata-token"] == "TOKEN"
        if request.url.path.endswith("security-credentials/"):
            return httpx.Response(200, text="role-name\n")
        return httpx.Response(
            200,
            json={"AccessKeyId": "A", "SecretAccessKey": "S", "Token": "T", "Expiration": FUTURE},
        )

    source = AwsCredentialSource(
        static=None, region="r", http=http_for(imds), metadata_http=http_for(imds)
    )
    assert (await source.get()).access_key == "A"
    assert calls[0] == ("PUT", "/latest/api/token")


async def test_azure_managed_identity_caches_the_token() -> None:
    hits = 0

    def imds(request: httpx.Request) -> httpx.Response:
        nonlocal hits
        hits += 1
        assert request.headers["metadata"] == "true"
        assert "resource=https%3A%2F%2Fstorage.azure.com%2F" in str(request.url)
        return httpx.Response(
            200, json={"access_token": "AZ", "expires_on": str(time.time() + 3600)}
        )

    source = azure_token_source(http_for(imds), http_for(imds))
    assert await source.get() == "AZ"
    assert await source.get() == "AZ"
    assert hits == 1


async def test_azure_workload_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = tmp_path / "t"
    file.write_text("assertion-jwt")
    monkeypatch.setenv("AZURE_FEDERATED_TOKEN_FILE", str(file))
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant1")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client1")

    def login(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/tenant1/oauth2/v2.0/token"
        assert b"client_assertion=assertion-jwt" in request.content
        return httpx.Response(200, json={"access_token": "WI", "expires_in": 3600})

    assert await azure_token_source(http_for(login)).get() == "WI"


async def test_gcs_service_account_signs_a_jwt() -> None:
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = key.public_key()
    sa = json.dumps({"client_email": "svc@proj.iam.gserviceaccount.com", "private_key": pem})

    def token(request: httpx.Request) -> httpx.Response:
        form = dict(p.split("=", 1) for p in request.content.decode().split("&"))
        claims = jwt.decode(
            form["assertion"].replace("%3D", "="),
            public,
            algorithms=["RS256"],
            audience="https://oauth2.googleapis.com/token",
        )
        assert claims["iss"] == "svc@proj.iam.gserviceaccount.com"
        assert claims["scope"].endswith("devstorage.read_write")
        return httpx.Response(200, json={"access_token": "SA", "expires_in": 3600})

    assert await gcs_token_source(http_for(token), credentials=sa).get() == "SA"


async def test_gcs_metadata_server_and_static_token() -> None:
    def meta(request: httpx.Request) -> httpx.Response:
        assert request.headers["metadata-flavor"] == "Google"
        return httpx.Response(200, json={"access_token": "GKE", "expires_in": 3600})

    assert await gcs_token_source(http_for(meta), meta=http_for(meta)).get() == "GKE"
    assert await gcs_token_source(http_for(meta), access_token="STATIC").get() == "STATIC"
