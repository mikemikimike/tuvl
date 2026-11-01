"""
IP-based access control shared by the dev middleware and production middleware.

TUVL_ALLOWED_HOSTS accepts a comma-separated list of IPv4/IPv6 addresses or
CIDR ranges (e.g. "192.168.1.0/24,10.0.0.5").  Localhost (127.0.0.0/8, ::1) is
always permitted regardless of this setting.
"""

import ipaddress

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from tuvl.core.config import settings

logger = structlog.get_logger(__name__)


class InvalidAllowedHostError(ValueError):
    """Raised when ``TUVL_ALLOWED_HOSTS`` contains an unparseable entry.

    Fail-loud is preferred over silently dropping bad entries: a typo like
    ``--allow-host 192.168.0.0/33`` (invalid netmask) would otherwise become
    a no-op and silently weaken the allowlist.
    """


_LOCALHOST_NETS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
]


def parse_cidr_list(
    raw: str,
    *,
    strict: bool = True,
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse a comma-separated list of IPs / CIDR ranges.

    Parameters
    ----------
    raw:
        Comma-separated string from ``TUVL_ALLOWED_HOSTS`` or ``--allow-host``.
    strict:
        When ``True`` (default), raise ``InvalidAllowedHostError`` on any
        unparseable entry so operators get a loud failure instead of a silent
        allowlist degradation.  Set to ``False`` only for diagnostic tooling
        that should never reject input.
    """
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    invalid: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError as exc:
            if strict:
                invalid.append(f"{part!r} ({exc})")
            else:
                logger.warning(
                    "Ignoring invalid host entry in non-strict mode",
                    entry=part,
                    error=str(exc),
                )

    if invalid:
        raise InvalidAllowedHostError(
            "TUVL_ALLOWED_HOSTS contains unparseable entries — refusing to "
            "build a silently-weakened allowlist. Fix or remove: " + ", ".join(invalid)
        )
    return nets


def host_is_permitted(
    host: str,
    allowlist: list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None,
) -> bool:
    """Return True if *host* is localhost or within the allowlist.

    ``allowlist`` should be a boot-time-parsed list (see
    ``AllowedHostsMiddleware.__init__``) so callers with a static allowlist
    for the process lifetime avoid re-parsing ``TUVL_ALLOWED_HOSTS`` — and
    re-validating its CIDR syntax — on every request. When omitted, the
    allowlist is parsed fresh from ``settings.tuvl_allowed_hosts`` on every
    call, which is the correct (if costlier) behaviour for callers whose
    allowed-hosts setting can change without a process restart.
    """
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False

    # Localhost is unconditionally allowed
    for net in _LOCALHOST_NETS:
        if addr in net:
            return True

    if allowlist is None:
        raw = settings.tuvl_allowed_hosts
        allowlist = parse_cidr_list(raw) if raw else []

    return any(addr in net for net in allowlist)


class AllowedHostsMiddleware(BaseHTTPMiddleware):
    """
    Production middleware — gates ALL routes to TUVL_ALLOWED_HOSTS (+ localhost).
    Only mounted when ``settings.tuvl_allowed_hosts`` is non-empty and dev mode
    is off.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        # Parsed once at boot: a malformed CIDR in TUVL_ALLOWED_HOSTS fails
        # loudly here (InvalidAllowedHostError) instead of raising a 500 on
        # the first request that reaches dispatch().
        self._allowlist = parse_cidr_list(settings.tuvl_allowed_hosts)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_host = request.client.host if request.client else ""
        if not host_is_permitted(client_host, self._allowlist):
            return JSONResponse(
                {"detail": "Your IP address is not in the allowed hosts list."},
                status_code=403,
            )
        return await call_next(request)
