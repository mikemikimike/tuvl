"""tuvl 2.0 type language (spec §6.1): parsing, formatting, compilation."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from pydantic import BaseModel, ValidationError

from tuvl.contract import (
    FieldSpec,
    TypeParseError,
    TypeRef,
    TypeResolutionError,
    build_model,
    format_type,
    parse_field,
    parse_type,
)


class OrderRead(BaseModel):
    id: int
    total: float


class OrderCreate(BaseModel):
    total: float


_MODELS: dict[tuple[str, str], type[BaseModel]] = {
    ("Order", "read"): OrderRead,
    ("Order", "create"): OrderCreate,
}


def resolver(name: str, variant: str) -> type[BaseModel] | None:
    return _MODELS.get((name, variant))


# ── Parsing ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("str", TypeRef("scalar", name="str")),
        ("json", TypeRef("scalar", name="json")),
        ("int?", TypeRef("scalar", name="int", optional=True)),
        ("  uuid  ?  ", TypeRef("scalar", name="uuid", optional=True)),
        ("enum[a, b,c]", TypeRef("enum", values=("a", "b", "c"))),
        ("enum[low-risk, v1.2, 3]", TypeRef("enum", values=("low-risk", "v1.2", "3"))),
        ('enum["needs review", ok]', TypeRef("enum", values=("needs review", "ok"))),
        ("list[str]", TypeRef("list", item=TypeRef("scalar", name="str"))),
        (
            "list[int?]?",
            TypeRef("list", item=TypeRef("scalar", name="int", optional=True), optional=True),
        ),
        (
            "list[list[bool]]",
            TypeRef("list", item=TypeRef("list", item=TypeRef("scalar", name="bool"))),
        ),
        ("Order", TypeRef("model", name="Order")),
        ("Order.create", TypeRef("model", name="Order", variant="create")),
        (
            "list[Order.expanded]?",
            TypeRef("list", item=TypeRef("model", name="Order", variant="expanded"), optional=True),
        ),
    ],
)
def test_parse(text: str, expected: TypeRef) -> None:
    assert parse_type(text) == expected


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("", "empty type"),
        ("string", "did you mean 'str'"),
        ("timestamp", "did you mean 'datetime'"),
        ("order", "model names start with an uppercase letter"),
        ("enum", "enum needs brackets"),
        ("list", "list needs brackets"),
        ("enum[]", "expected an enum value"),
        ("enum[a, a]", "duplicate enum value 'a'"),
        ("enum[a", "expected ']'"),
        ('enum["a]', "unterminated quoted enum value"),
        ('enum[""]', "empty enum value"),
        ("list[]", "expected a type"),
        ("list[str", "expected ']'"),
        ("Order.patch", "unknown model variant 'patch'"),
        ("str??", "unexpected '?'"),
        ("str extra", "unexpected 'e'"),
        ("1nt", "expected a type"),
    ],
)
def test_parse_errors(text: str, fragment: str) -> None:
    with pytest.raises(TypeParseError) as exc:
        parse_type(text)
    assert fragment in str(exc.value)


def test_parse_error_reports_column() -> None:
    with pytest.raises(TypeParseError) as exc:
        parse_type("list[strng]")
    assert exc.value.pos == 5
    assert "column 6" in str(exc.value)


def test_parse_rejects_non_string() -> None:
    with pytest.raises(TypeParseError, match="must be a string"):
        parse_type(42)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text",
    [
        "str",
        "int?",
        "enum[a, b]",
        'enum["needs review", ok]',
        "enum['say \"hi\"', x]",
        "list[Order.create]?",
        "list[list[uuid?]]",
        "Order",
    ],
)
def test_format_round_trips(text: str) -> None:
    ref = parse_type(text)
    assert parse_type(format_type(ref)) == ref
    assert str(ref) == format_type(ref)


def test_format_is_canonical() -> None:
    assert format_type(parse_type(" list[ Order.read ] ? ")) == "list[Order]?"


def test_model_refs_include_nested() -> None:
    assert parse_type("list[Order.create]").model_refs() == {("Order", "create")}
    assert parse_type("str").model_refs() == set()


# ── Long form ───────────────────────────────────────────────────────────────


def test_parse_field_short_and_long_form() -> None:
    assert parse_field("int") == FieldSpec(type=TypeRef("scalar", name="int"))
    long = parse_field({"type": "str?", "description": "a note", "default": "x"})
    assert long.type == TypeRef("scalar", name="str", optional=True)
    assert long.description == "a note"
    assert long.has_default and long.default == "x"
    assert not parse_field({"type": "int"}).has_default


@pytest.mark.parametrize(
    ("spec", "fragment"),
    [
        ({"description": "x"}, "needs a 'type'"),
        ({"type": "int", "required": True}, "unknown field key(s) ['required']"),
        ({"type": "int", "description": 3}, "'description' must be a string"),
        (3, "must be a type string or a mapping"),
    ],
)
def test_parse_field_errors(spec: object, fragment: str) -> None:
    with pytest.raises(TypeParseError) as exc:
        parse_field(spec)  # type: ignore[arg-type]
    assert fragment in str(exc.value)


# ── Compilation ─────────────────────────────────────────────────────────────


def test_build_model_validates_scalars_and_rejects_extra_keys() -> None:
    model = build_model(
        "Inputs",
        {
            "name": "str",
            "count": "int",
            "when": "datetime",
            "on": "date",
            "ref": "uuid",
            "payload": "json",
        },
    )
    ref = uuid.uuid4()
    m = model(
        name="a",
        count="3",
        when="2026-10-08T10:00:00",
        on="2026-10-08",
        ref=str(ref),
        payload={"k": [1]},
    )
    assert m.count == 3
    assert m.when == dt.datetime(2026, 10, 8, 10)
    assert m.on == dt.date(2026, 10, 8)
    assert m.ref == ref
    with pytest.raises(ValidationError, match="extra"):
        model(
            name="a",
            count=1,
            when="2026-10-08T10:00:00",
            on="2026-10-08",
            ref=str(ref),
            payload=1,
            other=1,
        )


def test_build_model_required_optional_and_default() -> None:
    model = build_model("M", {"a": "int", "b": "int?", "c": {"type": "int", "default": 5}})
    m = model(a=1)
    assert (m.b, m.c) == (None, 5)
    assert model(a=1, b=None).b is None
    with pytest.raises(ValidationError, match="a"):
        model()


def test_build_model_enum_and_list() -> None:
    model = build_model("M", {"verdict": "enum[strong, weak]", "tags": "list[str]"})
    assert model(verdict="weak", tags=["x"]).verdict == "weak"
    with pytest.raises(ValidationError):
        model(verdict="maybe", tags=[])
    with pytest.raises(ValidationError):
        model(verdict="strong", tags=[1])


def test_build_model_resolves_models_and_variants() -> None:
    model = build_model("M", {"order": "Order", "drafts": "list[Order.create]?"}, resolver)
    m = model(order={"id": 1, "total": 9.5}, drafts=[{"total": 2}])
    assert isinstance(m.order, OrderRead)
    assert isinstance(m.drafts[0], OrderCreate)


def test_build_model_unknown_model_or_variant() -> None:
    with pytest.raises(TypeResolutionError, match="unknown model 'Refund'"):
        build_model("M", {"r": "Refund"}, resolver)
    with pytest.raises(TypeResolutionError, match="unknown model 'Order.update'"):
        build_model("M", {"r": "Order.update?"}, resolver)


def test_build_model_uses_schema_registry_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from tuvl.core.models import schemas

    monkeypatch.setitem(schemas.SCHEMA_REGISTRY, "Order", {"read": OrderRead})
    model = build_model("M", {"order": "Order"})
    assert isinstance(model(order={"id": 1, "total": 1}).order, OrderRead)


def test_build_model_bad_default_is_rejected() -> None:
    with pytest.raises(TypeResolutionError, match="default for 'n' does not match 'int'"):
        build_model("M", {"n": {"type": "int", "default": "many"}})


@pytest.mark.parametrize("name", ["_private", "2fast", "with-dash", ""])
def test_build_model_rejects_bad_field_names(name: str) -> None:
    with pytest.raises(TypeResolutionError, match="invalid field name"):
        build_model("M", {name: "int"})


@pytest.mark.parametrize("name", ["json", "schema", "copy", "model_name"])
def test_build_model_fields_shadowing_basemodel_keep_their_wire_name(name: str) -> None:
    model = build_model("M", {name: "str"})
    m = model.model_validate({name: "v"})
    assert m.model_dump() == {name: "v"}
    assert name in model.model_json_schema()["properties"]


def test_build_model_json_schema_carries_descriptions() -> None:
    model = build_model("M", {"score": {"type": "int", "description": "0-100"}}, doc="Scores.")
    schema = model.model_json_schema()
    assert schema["properties"]["score"]["description"] == "0-100"
    assert schema["description"] == "Scores."
    assert schema["additionalProperties"] is False
