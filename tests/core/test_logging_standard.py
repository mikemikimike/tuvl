"""Regression tests pinning the structlog logging standard.

The codebase committed to a single logging contract in mid-2026:

    logger.<level>("stable.event.name", field1=value1, field2=value2, ...)

Specifically:

* No emoji literals or other decorative Unicode in the event-name string
  (these break grep, copy/paste, terminal multiplexers, and JSON consumers).
* No ``%s`` / ``%d`` / ``%r`` printf-style placeholders in the event-name
  (values become structured fields via kwargs, not embedded markers).
* No f-strings or ``.format()`` calls in the event-name (same reason —
  values must be separate fields so they're queryable in JSON output and
  correlated with OpenTelemetry spans).

Ruff's ``G`` (flake8-logging-format) catches the f-string / percent /
.format cases automatically — see ``pyproject.toml``.  Emoji literals
slip past G because they're valid string content, so we pin the
no-emoji rule here with a source scan.

If this test fires after a future edit:
  * Rewrite the offending call as a stable lowercase dotted event name
    with kwargs.  E.g.::

        # BEFORE — emoji + percent
        logger.info("✅ User %s logged in", email)

        # AFTER — structured
        logger.info("auth.login.success", email=email)

See ``docs/observability.md`` for the full contract.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ── Scope ────────────────────────────────────────────────────────────────────
SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "tuvl"

# Decorative Unicode classes we ban in logger event-name strings.  Includes
# the emoji literals that were used pre-2026, plus a handful of unicode arrows
# and check marks that crept in alongside them.  Keep this list narrow on
# purpose — we want to ban *decorative* characters, not legitimate non-ASCII
# content (e.g. a user's name in a log).
_BANNED_LITERALS = (
    # emoji
    "⚠",
    "🚨",
    "🔑",
    "🟥",
    "🟢",
    "🟡",
    "🔴",
    "🟦",
    "🔌",
    "🔒",
    "🔓",
    "📚",
    "🔢",
    "💾",
    "📦",
    "📋",
    "🔄",
    "🚀",
    "🆔",
    "🆕",
    "💡",
    "❌",
    "✅",
    "✓",
    "✗",
    "ℹ",
    "ℹ️",
    "⭐",
    "🐛",
    "🎯",
    "🎉",
    "👋",
    "⚡",
    "🏷",
    "🧹",
    "🛠",
    "📤",
    "📥",
    "⏰",
    "🔁",
    # decorative arrows / markers we don't want in event names
    "→",
    "▶",
)

_LOGGER_CALL_RE = re.compile(
    r"\blogger\.(?:debug|info|warning|warn|error|critical|exception)\s*\(",
)


def _iter_logger_calls() -> list[tuple[Path, int, str]]:
    """Yield ``(path, line_no, line)`` for every logger.<level>(...) call site."""
    out: list[tuple[Path, int, str]] = []
    for py_file in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        with py_file.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh, start=1):
                if _LOGGER_CALL_RE.search(line):
                    out.append((py_file, i, line.rstrip("\n")))
    return out


def test_no_emoji_in_logger_calls() -> None:
    """Banned decorative-Unicode literals must never appear on a logger
    call site.  Use a stable lowercase dotted event-name slug instead."""
    offenders: list[str] = []
    for path, line_no, line in _iter_logger_calls():
        for bad in _BANNED_LITERALS:
            if bad in line:
                rel = path.relative_to(SRC_ROOT.parents[1])
                offenders.append(f"{rel}:{line_no}  banned {bad!r}  →  {line.strip()}")
                break  # one violation per line is enough

    if offenders:
        msg = (
            "Found decorative Unicode in logger call sites — replace with a "
            "stable lowercase dotted event name + structured kwargs:\n\n  "
            + "\n  ".join(offenders[:30])
            + ("\n\n  …(showing 30 of more)" if len(offenders) > 30 else "")
        )
        pytest.fail(msg)


def test_logger_calls_use_str_first_arg() -> None:
    """Sanity check that the regex picks up real call sites.

    Not a contract test — just guards against the scanner silently
    matching nothing (which would make `test_no_emoji_in_logger_calls`
    vacuously pass on a future refactor).
    """
    calls = _iter_logger_calls()
    assert len(calls) > 50, (
        f"Logger-call scanner only found {len(calls)} calls in src/ — "
        "the regex probably broke.  Investigate before the emoji guard "
        "is trusted."
    )
