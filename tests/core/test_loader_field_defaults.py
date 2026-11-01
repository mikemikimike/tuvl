"""Regression tests for implicit default_factory injection in the model loader.

Bug: ``create_sqlmodel_class`` used to treat *any* default-less ``uuid`` /
``date`` / ``timestamp`` / ``timestamptz`` field as "auto-generate a value",
guarding only on nothing (uuid/date) or ``not is_pk`` (timestamptz). That
corrupted every nullable business field of those types created through ModelOp
CRUD: a nullable uuid FK got a dangling random UUID, and a ``date``/``timestamp``
became "today"/"now" instead of NULL.

The fix: generate only where it is semantically safe — a ``uuid`` primary key,
and the ``created_at``/``updated_at`` audit-column convention — plus explicit
opt-in literals ``default: uuid4 | now | today``. Everything else honours its
nullability.
"""

from __future__ import annotations

import datetime as _dt
import uuid as _uuid

from tuvl.core.models.loader import create_sqlmodel_class


def _model(name: str, fields: list[dict]) -> type:
    return create_sqlmodel_class(
        {
            "metadata": {"name": name},
            "spec": {"tablename": name.lower(), "fields": fields},
        }
    )


def test_default_less_fields_honour_null_and_only_safe_cases_generate() -> None:
    """One model exercising every branch; instantiate with omitted fields."""
    Employee = _model(
        "LoaderEmployeeFixture",
        [
            {"name": "id", "type": "uuid", "primary_key": True},
            # nullable uuid FK — must NOT auto-generate (was a dangling UUID)
            {"name": "ramadan_variant_id", "type": "uuid"},
            # business dates/timestamps — must be NULL when omitted (was now/today)
            {"name": "dob", "type": "date"},
            {"name": "exit_date", "type": "date", "input": False},
            {"name": "promised_at", "type": "timestamp"},
            {"name": "fitness_upto", "type": "timestamptz"},
            # audit columns — keep auto-populating to now
            {"name": "created_at", "type": "timestamp"},
            {"name": "updated_at", "type": "timestamptz"},
        ],
    )

    row = Employee(first_name="X")  # every typed field omitted

    # id auto-generates
    assert isinstance(row.id, _uuid.UUID)

    # the corruption cases: all NULL now
    assert row.ramadan_variant_id is None
    assert row.dob is None
    assert row.exit_date is None  # input:false field still NULL, not today
    assert row.promised_at is None
    assert row.fitness_upto is None

    # audit convention preserved
    assert isinstance(row.created_at, _dt.datetime)
    assert isinstance(row.updated_at, _dt.datetime)
    assert row.updated_at.tzinfo is not None  # timestamptz stays tz-aware


def test_explicit_generate_literals_opt_in() -> None:
    Model = _model(
        "LoaderLiteralFixture",
        [
            {"name": "id", "type": "uuid", "primary_key": True},
            {"name": "hired_on", "type": "date", "default": "today"},
            {"name": "signed_at", "type": "timestamp", "default": "now"},
            {"name": "signed_tz", "type": "timestamptz", "default": "now"},
        ],
    )

    row = Model()

    assert row.hired_on == _dt.date.today()
    assert isinstance(row.signed_at, _dt.datetime)
    assert isinstance(row.signed_tz, _dt.datetime)
    assert row.signed_tz.tzinfo is not None


def test_required_uuid_fk_is_not_auto_generated() -> None:
    """A required (non-PK) uuid must not silently receive a random value —
    it should be left unset so the DB NOT NULL constraint governs it."""
    Model = _model(
        "LoaderRequiredUuidFixture",
        [
            {"name": "id", "type": "uuid", "primary_key": True},
            {"name": "org_id", "type": "uuid", "required": True},
        ],
    )

    row = Model()
    assert row.org_id is None  # no dangling UUID; not auto-generated


def test_jsonb_accepts_any_json_value() -> None:
    """jsonb holds objects, lists and scalars alike (a research brief's sources
    list used to fail validation as 'a valid dictionary')."""
    from tuvl.core.models.schemas import generate_schemas

    fields = [
        {"name": "id", "type": "uuid", "primary_key": True},
        {"name": "data", "type": "jsonb"},
    ]
    model = _model("LoaderJsonbFixture", fields)
    assert model.model_validate({"data": [{"url": "x"}]}).data == [{"url": "x"}]
    create = generate_schemas("LoaderJsonbFixture", fields)["create"]
    assert create.model_validate({"data": [1, "a"]}).data == [1, "a"]


def test_redefining_a_model_replaces_its_stale_table() -> None:
    """A reload after a version toggle dropped the class from the registry must
    not fail on the table the old class left in the metadata."""
    from sqlmodel import SQLModel

    from tuvl.core.models.loader import create_sqlmodel_class

    doc = {
        "kind": "ModelDefinition",
        "metadata": {"name": "ReloadMe"},
        "spec": {
            "tablename": "reload_me_t",
            "fields": [{"name": "id", "type": "uuid", "primary_key": True}],
        },
    }
    first = create_sqlmodel_class(doc)
    second = create_sqlmodel_class(
        {
            **doc,
            "spec": {
                **doc["spec"],
                "fields": [*doc["spec"]["fields"], {"name": "x", "type": "integer"}],
            },
        }
    )
    assert (
        SQLModel.metadata.tables["reload_me_t"] is second.__table__
        and first.__table__ is not second.__table__
    )
    assert "x" in SQLModel.metadata.tables["reload_me_t"].columns
