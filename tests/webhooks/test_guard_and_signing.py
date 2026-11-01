"""The webhook URL guard and the signature scheme."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from tuvl.webhooks import guard, signing

OK = "https://hooks.example.com/notify?x=1"


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/x",  # plain http
        "ftp://hooks.example.com/x",
        "https://",
        "https://127.0.0.1/x",
        "https://10.1.2.3/x",
        "https://192.168.0.9/x",
        "https://172.16.0.1/x",
        "https://169.254.169.254/latest/meta-data",
        "https://100.64.0.1/x",
        "https://0.0.0.0/x",
        "https://[::1]/x",
        "https://[fd00::1]/x",
        "https://[fe80::1]/x",
        "https://[::ffff:127.0.0.1]/x",  # IPv4-mapped loopback
        "https://[::ffff:a9fe:a9fe]/x",  # IPv4-mapped metadata address
        "https://[64:ff9b::7f00:1]/x",  # NAT64 loopback
        "https://[2002:7f00:1::]/x",  # 6to4 loopback
        "https://2130706433/x",  # decimal 127.0.0.1
        "https://0x7f000001/x",
        "https://0x7f.1/x",
        "https://017700000001/x",  # octal 127.0.0.1
        "https://127.1/x",
        "https://localhost/x",
        "https://LOCALHOST./x",
        "https://db.internal/x",
        "https://printer.local/x",
        "https://intranet/x",  # no dot: a search-domain name
        "https://user:pass@hooks.example.com/x",
        "https://hooks.example.com:99999/x",
    ],
)
def test_internal_or_odd_targets_are_refused(url: str) -> None:
    assert guard.url_problem(url) is not None, url


def test_a_public_https_url_is_accepted() -> None:
    assert guard.url_problem(OK) is None
    assert guard.url_problem("https://93.184.216.34:8443/x") is None
    assert guard.url_problem("https://[2606:4700:4700::1111]/x") is None


def test_allow_private_permits_inside_targets_but_never_credentials() -> None:
    assert guard.url_problem("http://127.0.0.1:8080/x", allow_private=True) is None
    assert guard.url_problem("https://printer.local/x", allow_private=True) is None
    assert guard.url_problem("http://u:p@127.0.0.1/x", allow_private=True) is not None


def test_blocked_ranges() -> None:
    import ipaddress

    for blocked in (
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "::1",
        "::ffff:10.0.0.1",
    ):
        assert guard.is_blocked(ipaddress.ip_address(blocked)), blocked
    for open_ in ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"):
        assert not guard.is_blocked(ipaddress.ip_address(open_)), open_


async def test_a_name_that_resolves_to_a_mix_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(answers: list[str]) -> Any:
        async def getaddrinfo(host: str, port: int, **kw: Any) -> list[Any]:
            return [(2, 1, 6, "", (a, port)) for a in answers]

        return getaddrinfo

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake(["93.184.216.34", "10.0.0.5"]))
    with pytest.raises(guard.BlockedAddress):
        await guard.resolve("rebind.example.com", 443)
    assert await guard.resolve("rebind.example.com", 443, allow_private=True)

    monkeypatch.setattr(loop, "getaddrinfo", fake(["93.184.216.34"]))
    assert await guard.resolve("ok.example.com", 443) == ["93.184.216.34"]


async def test_a_literal_internal_address_is_refused_at_connect_time() -> None:
    with pytest.raises(guard.BlockedAddress):
        await guard.resolve("169.254.169.254", 80)


SECRET = "s" * 40
VECTOR_DIGEST = "2bf17cddc7bfd9f1ec522950790b89ab293ed9680b8580b041643e09fd8a9543"
BODY = b'{"id":"1"}'


def test_a_signed_notification_verifies_with_the_secret() -> None:
    header = signing.sign(BODY, [SECRET])
    assert signing.verify(header, BODY, [SECRET])


def test_tampering_the_wrong_secret_and_stale_timestamps_fail() -> None:
    header = signing.sign(BODY, [SECRET])
    assert not signing.verify(header, BODY + b" ", [SECRET])
    assert not signing.verify(header, BODY, ["x" * 40])
    old = signing.sign(BODY, [SECRET], now=int(time.time()) - 1000)
    assert not signing.verify(old, BODY, [SECRET])
    assert signing.verify(old, BODY, [SECRET], tolerance=2000)


def test_rotation_signs_with_both_secrets() -> None:
    new, old = "n" * 40, "o" * 40
    header = signing.sign(BODY, [new, old])
    assert header.count("v1=") == 2
    assert signing.verify(header, BODY, [new]) and signing.verify(header, BODY, [old])


@pytest.mark.parametrize(
    "header", ["", "v1=abc", "t=abc,v1=abc", f"t={int(time.time())}", "t=1,t=2,v1=x"]
)
def test_malformed_headers_never_verify(header: str) -> None:
    assert not signing.verify(header, BODY, [SECRET])


def test_the_signature_matches_the_published_test_vector() -> None:
    """The npm client checks the same vector (tuvl-npm src/webhooks.test.ts): keep them in step."""
    body = (
        b'{"agent":"greet","created_at":"2026-10-20T14:00:00+00:00",'
        b'"id":"3f2b8c1e-0000-4000-8000-000000000001","run_id":"3f2b8c1e-0000-4000-8000-000000000002",'
        b'"seq":7,"type":"agent.completed","workflow":"greet"}'
    )
    assert signing.digest("k" * 40, 1700000000, body) == VECTOR_DIGEST
