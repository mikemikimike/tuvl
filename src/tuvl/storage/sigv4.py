"""AWS Signature Version 4 for S3 and S3-compatible stores (header auth and presigned URLs)."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, urlsplit

ALGORITHM = "AWS4-HMAC-SHA256"
UNSIGNED = "UNSIGNED-PAYLOAD"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class AwsCreds:
    access_key: str
    secret_key: str
    token: str = ""
    expires_at: float | None = None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, date: str, region: str, service: str) -> bytes:
    key = _hmac(f"AWS4{secret}".encode(), date)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    return key


def _canonical_query(pairs: list[tuple[str, str]]) -> str:
    encoded = sorted((quote(k, safe="~"), quote(v, safe="~")) for k, v in pairs)
    return "&".join(f"{k}={v}" for k, v in encoded)


def host_header(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    return host if port is None or port == _DEFAULT_PORTS.get(parts.scheme) else f"{host}:{port}"


def _stamp(now: datetime) -> tuple[str, str]:
    now = now.astimezone(UTC)
    return now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")


def _signature(
    creds: AwsCreds,
    *,
    method: str,
    url: str,
    query: list[tuple[str, str]],
    headers: dict[str, str],
    signed: list[str],
    payload_hash: str,
    region: str,
    service: str,
    amz_date: str,
    date: str,
) -> str:
    canonical_headers = "".join(f"{name}:{' '.join(headers[name].split())}\n" for name in signed)
    canonical = "\n".join(
        [
            method,
            urlsplit(url).path or "/",
            _canonical_query(query),
            canonical_headers,
            ";".join(signed),
            payload_hash,
        ]
    )
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = "\n".join([ALGORITHM, amz_date, scope, sha256_hex(canonical.encode())])
    key = _signing_key(creds.secret_key, date, region, service)
    return hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()


def sign_headers(
    method: str,
    url: str,
    headers: dict[str, str],
    payload_hash: str,
    creds: AwsCreds,
    region: str,
    *,
    now: datetime | None = None,
    service: str = "s3",
) -> dict[str, str]:
    """*headers* plus the ``x-amz-*`` and ``Authorization`` headers that sign the request."""
    amz_date, date = _stamp(now or datetime.now(UTC))
    out = {k.lower(): v for k, v in headers.items()}
    out["host"] = host_header(url)
    out["x-amz-date"] = amz_date
    out["x-amz-content-sha256"] = payload_hash
    if creds.token:
        out["x-amz-security-token"] = creds.token
    signed = sorted(
        k
        for k in out
        if k == "host" or k.startswith("x-amz-") or k in ("content-type", "content-md5")
    )
    query = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    signature = _signature(
        creds,
        method=method,
        url=url,
        query=query,
        headers=out,
        signed=signed,
        payload_hash=payload_hash,
        region=region,
        service=service,
        amz_date=amz_date,
        date=date,
    )
    scope = f"{date}/{region}/{service}/aws4_request"
    out["authorization"] = (
        f"{ALGORITHM} Credential={creds.access_key}/{scope}, "
        f"SignedHeaders={';'.join(signed)}, Signature={signature}"
    )
    return out


def presign_url(
    method: str,
    url: str,
    creds: AwsCreds,
    region: str,
    expires_in: int,
    *,
    now: datetime | None = None,
    service: str = "s3",
) -> str:
    amz_date, date = _stamp(now or datetime.now(UTC))
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query += [
        ("X-Amz-Algorithm", ALGORITHM),
        ("X-Amz-Credential", f"{creds.access_key}/{date}/{region}/{service}/aws4_request"),
        ("X-Amz-Date", amz_date),
        ("X-Amz-Expires", str(expires_in)),
        ("X-Amz-SignedHeaders", "host"),
    ]
    if creds.token:
        query.append(("X-Amz-Security-Token", creds.token))
    signature = _signature(
        creds,
        method=method,
        url=url,
        query=query,
        headers={"host": host_header(url)},
        signed=["host"],
        payload_hash=UNSIGNED,
        region=region,
        service=service,
        amz_date=amz_date,
        date=date,
    )
    base = f"{parts.scheme}://{parts.netloc}{parts.path}"
    return f"{base}?{_canonical_query(query)}&X-Amz-Signature={signature}"
