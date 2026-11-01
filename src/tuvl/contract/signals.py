"""Engine-reserved signal names (spec Appendix C.1)."""

from __future__ import annotations

import re

RESERVED: frozenset[str] = frozenset(
    {
        "error",
        "parse_error",
        "timeout",
        "budget_exceeded",
        "guardrail_violation",
        "max_iterations",
        "aborted",
        "low_confidence",
        "expired",
        "not_found",
        "conflict",
        "too_large",
    }
)
HTTP_STATUS = re.compile(r"http_[1-5]\d\d")


def is_reserved(signal: str) -> bool:
    return signal in RESERVED or bool(HTTP_STATUS.fullmatch(signal))
