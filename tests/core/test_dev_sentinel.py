"""Regression tests for the dev-mode auth sentinel in tuvl.core.auth.access.

The sentinel has two layers:

  1. Hard refusal: TUVL_ENV=production + TUVL_DEV_MODE=true is never legal,
     regardless of TUVL_ALLOW_DEV_AUTH.
  2. Acknowledgement: in any other env, dev_mode requires the explicit
     TUVL_ALLOW_DEV_AUTH=true sentinel so a leaked TUVL_DEV_MODE can't
     silently activate the iam:admin bypass.

Both layers call ``sys.exit(1)`` from module-level boot code, so we verify
them via subprocess — running the import in the *current* process would
kill pytest itself.
"""

from __future__ import annotations

import subprocess
import sys


def _spawn(env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run ``python -c 'import tuvl.core.auth.access'`` with overridden envs."""
    # Strip all TUVL_* env so each test starts from a clean baseline, then
    # apply the requested overrides.
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("TUVL_")}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import tuvl.core.auth.access"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_sentinel_refuses_production_plus_dev_mode() -> None:
    """Layer 1: TUVL_ENV=production + TUVL_DEV_MODE=true must hard-fail."""
    result = _spawn(
        {
            "TUVL_ENV": "production",
            "TUVL_DEV_MODE": "true",
            "TUVL_ALLOW_DEV_AUTH": "true",  # ack flag must NOT rescue production
        }
    )
    assert result.returncode == 1, (
        f"Expected exit 1, got {result.returncode}. "
        f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "production" in combined.lower(), "Error must name the offending env"
    assert "dev_mode" in combined.lower() or "TUVL_DEV_MODE" in combined


def test_sentinel_refuses_production_even_without_ack_flag() -> None:
    """Layer 1 holds regardless of TUVL_ALLOW_DEV_AUTH."""
    result = _spawn(
        {
            "TUVL_ENV": "production",
            "TUVL_DEV_MODE": "true",
        }
    )
    assert result.returncode == 1


def test_sentinel_refuses_dev_mode_without_ack_flag() -> None:
    """Layer 2: in non-production env, dev_mode without TUVL_ALLOW_DEV_AUTH=true fails."""
    result = _spawn(
        {
            "TUVL_ENV": "development",
            "TUVL_DEV_MODE": "true",
            # TUVL_ALLOW_DEV_AUTH deliberately absent
        }
    )
    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "TUVL_ALLOW_DEV_AUTH" in combined, "Error must point at the ack flag"


def test_sentinel_passes_dev_with_ack_flag() -> None:
    """Layer 2 passes when both TUVL_ENV=development and the ack flag are set."""
    result = _spawn(
        {
            "TUVL_ENV": "development",
            "TUVL_DEV_MODE": "true",
            "TUVL_ALLOW_DEV_AUTH": "true",
        }
    )
    # Should import cleanly. (Exit 0 means the access module loaded and
    # _enforce_dev_mode_sentinel returned without sys.exit.)
    assert result.returncode == 0, (
        f"Expected dev-mode-with-ack to boot cleanly. "
        f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
    )


def test_sentinel_inert_when_dev_mode_off() -> None:
    """With TUVL_DEV_MODE unset, the sentinel is a no-op (regardless of env)."""
    # Production env, no dev mode → no shortcut to disable → boot cleanly.
    result = _spawn(
        {
            "TUVL_ENV": "production",
            "TUVL_SIGNING_KEY": "00" * 32,  # avoid the prod-key check
        }
    )
    assert result.returncode == 0, (
        f"Production-without-dev-mode should boot. "
        f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
    )
