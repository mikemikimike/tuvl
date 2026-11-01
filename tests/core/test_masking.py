"""Regression tests for secure-field masking on the streaming surface.

The README and ``docs/observability.md`` promise that fields marked
``secure: true`` in any ``ModelDefinition`` are masked everywhere a context
snapshot leaves the process — OTel spans, SSE frames, gRPC StepEvent stream,
and the Spectrum debug trace.

These tests pin that contract at the snapshot-construction sites so a future
refactor that adds a new yield path can't silently leak PII.
"""

from __future__ import annotations

from tuvl.core.engine.masking import (
    mask_secure_data,
    public_safe_snapshot,
)

# ── Pure-function contract ────────────────────────────────────────────────────


def test_public_safe_snapshot_strips_underscore_keys() -> None:
    ctx = {
        "_session": object(),
        "_db": object(),
        "_last_error": "boom",
        "candidate_name": "Jane",
        "score": 92,
    }
    snap = public_safe_snapshot(ctx, secure_keys=set())
    assert snap == {"candidate_name": "Jane", "score": 92}


def test_public_safe_snapshot_masks_secure_fields() -> None:
    ctx = {
        "candidate_name": "Jane",
        "ssn": "123-45-6789",
        "salary": 95000,
    }
    snap = public_safe_snapshot(ctx, secure_keys={"ssn", "salary"})
    assert snap == {
        "candidate_name": "Jane",
        "ssn": "*****",
        "salary": "*****",
    }


def test_public_safe_snapshot_masks_nested_secure_fields() -> None:
    ctx = {
        "candidate": {
            "name": "Jane",
            "ssn": "123-45-6789",
            "history": [
                {"company": "Acme", "salary": 80000},
                {"company": "Globex", "salary": 95000},
            ],
        },
    }
    snap = public_safe_snapshot(ctx, secure_keys={"ssn", "salary"})
    assert snap == {
        "candidate": {
            "name": "Jane",
            "ssn": "*****",
            "history": [
                {"company": "Acme", "salary": "*****"},
                {"company": "Globex", "salary": "*****"},
            ],
        },
    }


def test_public_safe_snapshot_does_not_mutate_input() -> None:
    ctx = {"_session": "handle", "ssn": "111-22-3333", "name": "Jane"}
    snap = public_safe_snapshot(ctx, secure_keys={"ssn"})
    assert ctx == {"_session": "handle", "ssn": "111-22-3333", "name": "Jane"}
    assert snap == {"ssn": "*****", "name": "Jane"}


# ── Spectrum keeps diagnostic underscore keys but still masks ─────────────────


def test_mask_secure_data_preserves_underscore_keys() -> None:
    """Spectrum debug trace retains _last_error / _spectrum_error etc.

    Underscore-prefixed keys are NOT engine-internals from Spectrum's
    perspective — the debugger UI needs them to show error state.  Only
    ``secure: true`` fields must be redacted.
    """
    ctx = {
        "_last_error": "step failed",
        "_spectrum_error": "boom",
        "candidate_name": "Jane",
        "ssn": "123-45-6789",
    }
    snap = mask_secure_data(ctx, secure_keys={"ssn"})
    assert snap == {
        "_last_error": "step failed",
        "_spectrum_error": "boom",
        "candidate_name": "Jane",
        "ssn": "*****",
    }


# ── Pin the runner/streaming wire-up (signature check, not full engine run) ──
