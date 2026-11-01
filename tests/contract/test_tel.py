"""TEL — the tuvl expression language (spec §6.2)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

import pytest
from pydantic import BaseModel

from tuvl.contract.tel import (
    MAX_DEPTH,
    MAX_EXPRESSION_CHARS,
    TELEvalError,
    TELSyntaxError,
    TELTypeError,
    compile_expr,
    compile_template,
)


class Item(BaseModel):
    sku: str
    qty: int


class Order(BaseModel):
    id: int
    total: float
    status: Literal["open", "paid", "refunded"]
    discount: float | None = None
    items: list[Item] = []
    created_at: dt.datetime | None = None


def resolver(name: str, variant: str) -> type[BaseModel] | None:
    return {"Order": Order}.get(name) if variant == "read" else None


ENV = {
    "order": "Order",
    "maybe_order": "Order?",
    "reason": "enum[damaged, fraud_flag, other]",
    "amount": "int",
    "note": "str?",
    "tags": "list[str]",
    "meta": "json",
    "when": "date",
    "flag": "bool",
}

DATA = {
    "order": Order(
        id=1,
        total=900.0,
        status="paid",
        items=[Item(sku="A", qty=2), Item(sku="B", qty=1)],
        created_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    ),
    "maybe_order": None,
    "reason": "fraud_flag",
    "amount": 250,
    "note": None,
    "tags": ["vip", "eu"],
    "meta": {"score": 0.9, "nested": {"k": [1, 2]}},
    "when": dt.date(2026, 10, 8),
    "flag": True,
}


def ev(text: str, data: dict | None = None) -> object:
    return compile_expr(text).evaluate(DATA if data is None else data)


def check(text: str, **kw: object) -> str:
    return compile_expr(text).check(ENV, resolver, **kw)  # type: ignore[arg-type]


# ── Evaluation ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("order.total > 500", True),
        ('reason == "fraud_flag"', True),
        ('reason != "damaged"', True),
        ("amount > 200 and len(order.items) == 2", True),
        ("amount > 300 or flag", True),
        ("not flag", False),
        ("order.items[0].sku", "A"),
        ("order.items[-1].qty", 1),
        ("order.items[5].sku", None),
        ("maybe_order.total", None),
        ("note", None),
        ("missing_root", None),
        ('"vip" in tags', True),
        ('"us" not in tags', True),
        ('reason in ["fraud_flag", "other"]', True),
        ('"aid" in order.status', True),
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("7 / 2", 3.5),
        ("-amount + 1", -249),
        ('"a" + "b"', "ab"),
        ("2.5 * 2", 5.0),
        ("meta.nested.k[1]", 2),
        ("meta.score >= 0.9", True),
        ('upper("ab") + lower("CD")', "ABcd"),
        ('starts_with(reason, "fraud") and ends_with(reason, "flag")', True),
        ('contains(tags, "eu") and contains("hello", "ell")', True),
        ("is_empty(note) and not is_empty(tags) and is_empty([])", True),
        ('len(tags) + len("abc")', 5),
        ("days_between(order.created_at, when)", 7),
        ("now() > order.created_at", True),
        ("[1, 2.5, amount]", [1, 2.5, 250]),
        ("true == 1", False),
        ("1 == 1.0", True),
        ("null == note", True),
        ("order.discount > 0", False),  # ordering with null is false
        ("order.discount == null", True),
        ("'it\\'s' + \"\\n\"", "it's\n"),
    ],
)
def test_evaluate(text: str, expected: object) -> None:
    assert ev(text) == expected


def test_and_or_short_circuit() -> None:
    # The right side would fail at runtime (arithmetic on null) if evaluated.
    assert ev("false and note + 1 > 0") is False
    assert ev("true or note + 1 > 0") is True


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("note + 1", "arithmetic on null"),
        ("amount / 0", "division by zero"),
        ("amount and flag", "'and' needs a bool, got int"),
        ("not amount", "'not' needs a bool"),
        ('meta.score > "x"', "cannot order float and str"),
        ('-"x"', "unary '-' needs a number"),
        ("upper(amount)", "upper(): needs a str"),
        ("tags.first", "cannot read field 'first' of list"),
        ("reason[0]", "cannot index str"),
        ("tags[flag]", "list index must be int"),
        ("1 in amount", "'in' needs a list or str"),
    ],
)
def test_evaluate_errors(text: str, fragment: str) -> None:
    with pytest.raises(TELEvalError) as exc:
        ev(text)
    assert fragment in str(exc.value)


def test_evaluation_never_reaches_python_attributes() -> None:
    class Sneaky:
        secret = "leak"

    with pytest.raises(TELEvalError):
        ev("obj.secret", {"obj": Sneaky()})
    assert ev("obj.secret", {"obj": {"secret": "ok"}}) == "ok"  # mappings only


# ── Syntax ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("", "empty expression"),
        ("amount >", "expected a value, found end of expression"),
        ("amount > > 1", "expected a value"),
        ("1 < amount < 3", "comparisons cannot be chained"),
        ("(amount", "expected ')'"),
        ("tags[0", "expected ']'"),
        ("order.", "expected a field name after '.'"),
        ("order.__class__", "names starting with '_' are reserved"),
        ("_secret", "names starting with '_' are reserved"),
        ("eval(amount)", "unknown function 'eval'"),
        ("len()", "len() takes 1 argument, got 0"),
        ("now(1)", "now() takes 0 arguments, got 1"),
        ('"abc', "unterminated string"),
        ('"a\\q"', "unknown escape"),
        ("amount @ 2", "unexpected character '@'"),
        ("amount amount", "unexpected 'amount'"),
        ("x" * (MAX_EXPRESSION_CHARS + 1), "longer than"),
        ("(" * (MAX_DEPTH + 5) + "1" + ")" * (MAX_DEPTH + 5), "nests deeper"),
    ],
)
def test_syntax_errors(text: str, fragment: str) -> None:
    with pytest.raises(TELSyntaxError) as exc:
        compile_expr(text)
    assert fragment in str(exc.value)


def test_syntax_error_column() -> None:
    with pytest.raises(TELSyntaxError) as exc:
        compile_expr("amount > > 1")
    assert exc.value.pos == 9


def test_roots() -> None:
    assert compile_expr('order.total > amount and "x" in tags[0] and len(note) > 0').roots() == {
        "order",
        "amount",
        "tags",
        "note",
    }


# ── Static type checking ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "result"),
    [
        ("order.total > 500", "bool"),
        ("order.items[0].sku", "str?"),
        ("order.items", "list[Item]"),
        ("maybe_order.total", "float?"),
        ("amount + 1", "int"),
        ("amount / 2", "float"),
        ("amount + order.total", "float"),
        ('reason + "!"', "str"),
        ("meta.anything.deep", "any"),
        ("days_between(when, now())", "int"),
        ("order.status", "enum[open, paid, refunded]"),
        ("[1, 2.5]", "list[float]"),
        ('["a", 1]', "list[any]"),
        ("note == null", "bool"),
    ],
)
def test_check_result_types(text: str, result: str) -> None:
    assert check(text) == result


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("ordr.total > 1", "unknown name 'ordr' — declared inputs: amount, flag"),
        ("order.totl > 500", "Order has no field 'totl' — fields: created_at, discount, id"),
        ('reason == "fraud"', "'fraud' is not a value of enum[damaged, fraud_flag, other]"),
        ('"fraud" == reason', "'fraud' is not a value of enum"),
        ('reason in ["fraud_flag", "spam"]', "'spam' is not a value of enum"),
        ('order.status == "cancelled"', "'cancelled' is not a value of enum[open, paid, refunded]"),
        ("reason == order.status", "share no values"),
        ('amount == "250"', "cannot compare int with str"),
        ("amount > when", "cannot order int and date"),
        ('reason > "damaged"', "enum values are not ordered"),
        ("amount and flag", "'and' needs a bool, got int"),
        ("not tags", "'not' needs a bool, got list[str]"),
        ("amount.value", "int has no field 'value'"),
        ("amount[0]", "int cannot be indexed"),
        ("tags[note]", "list index must be int, got str?"),
        ("tags + 1", "cannot apply '+' to list[str] and int"),
        ("amount + null", "arithmetic on null (right of '+')"),
        ("-reason", "unary '-' needs a number"),
        ("upper(amount)", "upper() argument 1 must be enum or str, got int"),
        ("days_between(amount, when)", "days_between() argument 1 must be date or datetime"),
        ('"x" in amount', "'in' needs a list or str on the right, got int"),
        ("amount in reason", "substring test needs a str on the left, got int"),
    ],
)
def test_check_errors(text: str, fragment: str) -> None:
    with pytest.raises(TELTypeError) as exc:
        check(text)
    assert fragment in str(exc.value)


def test_check_expect_bool() -> None:
    assert check("amount > 1", expect="bool") == "bool"
    assert check("meta.flag", expect="bool") == "any"  # json is unchecked
    with pytest.raises(TELTypeError, match="condition must be a bool, got int"):
        check("amount + 1", expect="bool")


def test_check_unknown_model_and_bad_input_type() -> None:
    with pytest.raises(TELTypeError, match="unknown model 'Refund'"):
        compile_expr("r.id").check({"r": "Refund"}, resolver)
    with pytest.raises(TELTypeError, match="input 'r'"):
        compile_expr("r").check({"r": "string"}, resolver)


def test_check_uses_wire_alias_for_shadowing_fields() -> None:
    from tuvl.contract import build_model

    model = build_model("Shape", {"json": "str", "count": "int"})
    assert compile_expr("s.json").check({"s": "Shape"}, lambda n, v: model) == "str"


# ── Templates ───────────────────────────────────────────────────────────────


def test_single_placeholder_keeps_the_raw_value() -> None:
    assert compile_template("{{ order.total }}").render(DATA) == 900.0
    assert compile_template("  {{ tags }} ").render(DATA) == ["vip", "eu"]
    assert compile_template("{{ note }}").render(DATA) is None


def test_interpolation_formats_values() -> None:
    t = compile_template(
        "Refund {{ order.id }} for {{ amount }} ({{ flag }}) tags={{ tags }} note={{ note }} on {{ when }}"
    )
    assert t.render(DATA) == 'Refund 1 for 250 (true) tags=["vip", "eu"] note= on 2026-10-08'


def test_literal_template_and_roots() -> None:
    assert compile_template("plain text").render(DATA) == "plain text"
    assert compile_template("{{ order.id }}-{{ amount }}").roots() == {"order", "amount"}


def test_template_check_and_errors() -> None:
    compile_template("Hi {{ order.status }}").check(ENV, resolver)
    with pytest.raises(TELTypeError, match="no field 'nme'"):
        compile_template("Hi {{ order.nme }}").check(ENV, resolver)
    with pytest.raises(TELSyntaxError) as exc:
        compile_template("Hi {{ amount > }}")
    assert exc.value.pos == 15
    with pytest.raises(TELSyntaxError, match="unclosed"):
        compile_template("Hi {{ amount")


def test_parsing_is_cached_per_text_and_errors_are_not() -> None:
    from tuvl.contract.types import parse_type

    assert compile_expr("a.b > 1") is compile_expr("a.b > 1")
    assert compile_template("hi {{ name }}") is compile_template("hi {{ name }}")
    assert parse_type("list[int]?") is parse_type("list[int]?")
    assert compile_expr("a + 1").evaluate({"a": 1}) == 2
    assert compile_expr("a + 1").evaluate({"a": 5}) == 6
    for _ in range(2):
        with pytest.raises(TELSyntaxError):
            compile_expr("a +")
        with pytest.raises(TELSyntaxError):
            compile_expr(["not", "a", "string"])  # type: ignore[arg-type]
