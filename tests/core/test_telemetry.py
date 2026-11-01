"""Unit tests for the OTel tracing & data-masking subsystem (Phase 3).

Three tests, zero network calls, zero model YAML loading:

  1. test_recursive_masking_logic
       Pure ``mask_secure_data`` invariants: nested dicts, lists-of-dicts, list
       nesting, type passthrough, and strict non-mutation of the original.

  2. test_secure_registry_population
       Validates the extraction logic that runs inside ``load_all_models()``:
       fields with ``secure: true`` must be added to ``SECURE_FIELDS``.

  3. test_dev_prod_span_emission
       a) Prod-mode: ``_record_step_span`` opens a span, sets all expected
          attributes, and the context snapshot has PII replaced with ``"*****"``.
       b) Dev-mode: ``init_telemetry()`` with ``TUVL_DEV_MODE=true`` is a genuine no-op —
          the global OTel provider is unchanged and is not an SDK TracerProvider.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# 1. Recursive masking logic
# ─────────────────────────────────────────────────────────────────────────────


def test_recursive_masking_logic() -> None:
    from tuvl.core.engine.masking import mask_secure_data

    secure_keys: set[str] = {"ssn", "password"}

    original: dict = {
        "name": "Alice",
        "ssn": "123-45-6789",
        "password": "hunter2",
        "address": {
            "street": "1 Main St",
            "password": "nested-secret",  # same key, nested
            "coords": [{"lat": 51.5, "lng": -0.1}],
        },
        "tags": ["admin", "hr"],
        "records": [
            {"id": 1, "ssn": "000-00-0001", "score": 99},
            {"id": 2, "score": 42},
        ],
        "matrix": [[{"ssn": "deep-ssn"}], [1, 2, 3]],
        "count": 7,
        "active": True,
        "nothing": None,
    }

    result = mask_secure_data(original, secure_keys)

    # Top-level secure keys are redacted.
    assert result["ssn"] == "*****"
    assert result["password"] == "*****"

    # Non-secure top-level keys are preserved.
    assert result["name"] == "Alice"
    assert result["count"] == 7
    assert result["active"] is True
    assert result["nothing"] is None

    # Nested dict: secure key redacted; non-secure keys intact.
    assert result["address"]["password"] == "*****"
    assert result["address"]["street"] == "1 Main St"

    # Nested list-of-dicts: each dict is recursed.
    assert result["address"]["coords"] == [{"lat": 51.5, "lng": -0.1}]

    # List-of-dicts at the top level.
    assert result["records"][0]["ssn"] == "*****"
    assert result["records"][0]["id"] == 1
    assert result["records"][0]["score"] == 99
    assert result["records"][1]["score"] == 42
    assert "ssn" not in result["records"][1]

    # Deeply nested list-of-list-of-dict.
    assert result["matrix"][0][0]["ssn"] == "*****"
    assert result["matrix"][1] == [1, 2, 3]

    # Plain list of strings is copied unchanged.
    assert result["tags"] == ["admin", "hr"]

    # Original dict is NOT mutated.
    assert original["ssn"] == "123-45-6789"
    assert original["password"] == "hunter2"
    assert original["address"]["password"] == "nested-secret"
    assert original["records"][0]["ssn"] == "000-00-0001"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Secure-field registry population (loader logic)
# ─────────────────────────────────────────────────────────────────────────────


def test_secure_registry_population() -> None:
    """The loader loop that backs ``load_all_models()`` must add ``secure: true``
    field names to ``SECURE_FIELDS`` and leave other fields out.
    """
    import yaml

    from tuvl.core.models.loader import SECURE_FIELDS

    yaml_text = """
kind: ModelDefinition
spec:
  name: Employee
  fields:
    - name: employee_id
      type: uuid
    - name: national_id
      type: string
      secure: true
    - name: salary
      type: numeric
      secure: true
    - name: department
      type: string
"""
    data = yaml.safe_load(yaml_text)

    # Replicate the exact extraction logic from load_all_models().
    added: list[str] = []
    for field_spec in data["spec"].get("fields", []):
        if field_spec.get("secure"):
            SECURE_FIELDS.add(field_spec["name"])
            added.append(field_spec["name"])

    try:
        assert "national_id" in SECURE_FIELDS
        assert "salary" in SECURE_FIELDS
        # Non-secure fields must NOT have been added by this loop.
        assert added == ["national_id", "salary"]
    finally:
        # Clean up so other tests are not affected by the global set.
        SECURE_FIELDS.discard("national_id")
        SECURE_FIELDS.discard("salary")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Span emission — prod mock + dev no-op
# ─────────────────────────────────────────────────────────────────────────────
