"""TEL — the tuvl expression language (spec §6.2).

Used by ``decide.rules[].when``, tool ``approval.when``, test ``assertions``
and ``{{ }}`` templates. Deliberately small and closed:

* paths ``order.total``, ``items[0].sku`` — null-safe: a missing key, a
  null intermediate or an out-of-range index yields ``null``;
* literals: strings, ints, floats, ``true``/``false``/``null``, lists;
* operators ``== != < <= > >= in, not in, and, or, not, + - * /``;
* functions: ``len lower upper contains starts_with ends_with is_empty now
  days_between``.

Evaluation only walks mappings and sequences — there is no attribute access,
no calls outside the closed set and no way to reach Python objects. Every
expression is type-checked statically against the declared input types
(:meth:`Expression.check`), so a typo'd field or an enum value that cannot
occur is caught by ``tuvl lint project``, not at runtime.

Runtime semantics worth knowing: ordering comparisons with a ``null`` operand
are ``false``; arithmetic on ``null`` is an error; ``and``/``or``/``not``
require real booleans (no truthiness); ``bool`` never equals a number.
"""

from __future__ import annotations

import datetime as _dt
import functools
import json
import re
import types as _types
import typing
import uuid as _uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel

from tuvl.contract.files import FileRef
from tuvl.contract.types import (
    FieldSpec,
    ModelResolver,
    TypeParseError,
    TypeRef,
    parse_field,
    registry_resolver,
)

MAX_EXPRESSION_CHARS = 2000
#: Parsed expressions and templates kept per process; their texts come from loaded documents.
_CACHE_SIZE = 4096
MAX_DEPTH = 64


class TELError(ValueError):
    """Base class for expression-language errors."""

    def __init__(self, message: str, text: str = "", pos: int | None = None) -> None:
        self.message = message
        self.text = text
        self.pos = pos
        where = f" at column {pos + 1} in {text!r}" if text and pos is not None else ""
        super().__init__(f"{message}{where}")


class TELSyntaxError(TELError):
    """The expression text is not valid TEL."""


class TELTypeError(TELError):
    """The expression is well-formed but does not type-check against its inputs."""


class TELEvalError(TELError):
    """Evaluation failed at runtime (wrong runtime type, division by zero, …)."""


# ── Lexer ────────────────────────────────────────────────────────────────────

_KEYWORDS = frozenset({"and", "or", "not", "in", "true", "false", "null"})
_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>\d+\.\d+|\d+)
  | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>==|!=|<=|>=|[<>+\-*/().,\[\]])
    """,
    re.VERBOSE,
)
_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "'": "'"}


@dataclass(frozen=True)
class _Tok:
    kind: str  # number | string | name | kw | op | end
    value: Any
    pos: int


def _tokenize(text: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None:
            if text[pos] in "\"'":
                raise TELSyntaxError("unterminated string", text, pos)
            raise TELSyntaxError(f"unexpected character {text[pos]!r}", text, pos)
        kind = m.lastgroup or ""
        raw = m.group()
        if kind == "number":
            tokens.append(_Tok("number", float(raw) if "." in raw else int(raw), pos))
        elif kind == "string":
            tokens.append(_Tok("string", _unescape(raw[1:-1], text, pos), pos))
        elif kind == "name":
            tokens.append(_Tok("kw" if raw in _KEYWORDS else "name", raw, pos))
        elif kind == "op":
            tokens.append(_Tok("op", raw, pos))
        pos = m.end()
    tokens.append(_Tok("end", None, len(text)))
    return tokens


def _unescape(body: str, text: str, pos: int) -> str:
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            nxt = body[i + 1] if i + 1 < len(body) else ""
            if nxt not in _ESCAPES:
                raise TELSyntaxError(f"unknown escape '\\{nxt}'", text, pos + 1 + i)
            out.append(_ESCAPES[nxt])
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


# ── AST ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Node:
    pos: int


@dataclass(frozen=True)
class Lit(Node):
    value: Any


@dataclass(frozen=True)
class ListLit(Node):
    items: tuple[Node, ...]


@dataclass(frozen=True)
class Name(Node):
    name: str


@dataclass(frozen=True)
class Member(Node):
    obj: Node
    name: str


@dataclass(frozen=True)
class Index(Node):
    obj: Node
    index: Node


@dataclass(frozen=True)
class Unary(Node):
    op: str  # "not" | "-"
    operand: Node


@dataclass(frozen=True)
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class Call(Node):
    func: str
    args: tuple[Node, ...]


# ── Parser (precedence climbing) ─────────────────────────────────────────────

_COMPARISON = frozenset({"==", "!=", "<", "<=", ">", ">=", "in", "not in"})


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.toks = _tokenize(text)
        self.i = 0
        self.depth = 0

    @property
    def tok(self) -> _Tok:
        return self.toks[self.i]

    def at(self, kind: str, value: Any = None) -> bool:
        t = self.tok
        return t.kind == kind and (value is None or t.value == value)

    def advance(self) -> _Tok:
        t = self.tok
        self.i += 1
        return t

    def error(self, message: str, pos: int | None = None) -> TELSyntaxError:
        return TELSyntaxError(message, self.text, self.tok.pos if pos is None else pos)

    def describe(self, t: _Tok) -> str:
        return "end of expression" if t.kind == "end" else repr(str(t.value))

    def expect_op(self, op: str) -> _Tok:
        if not self.at("op", op):
            raise self.error(f"expected {op!r}, found {self.describe(self.tok)}")
        return self.advance()

    def parse(self) -> Node:
        node = self.or_()
        if not self.at("end"):
            raise self.error(f"unexpected {self.describe(self.tok)}")
        return node

    def nest(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise self.error(f"expression nests deeper than {MAX_DEPTH} levels")

    def or_(self) -> Node:
        node = self.and_()
        while self.at("kw", "or"):
            pos = self.advance().pos
            node = Binary(pos, "or", node, self.and_())
        return node

    def and_(self) -> Node:
        node = self.not_()
        while self.at("kw", "and"):
            pos = self.advance().pos
            node = Binary(pos, "and", node, self.not_())
        return node

    def not_(self) -> Node:
        if self.at("kw", "not"):
            pos = self.advance().pos
            self.nest()
            operand = self.not_()
            self.depth -= 1
            return Unary(pos, "not", operand)
        return self.comparison()

    def comparison(self) -> Node:
        left = self.additive()
        op = self.comparison_op()
        if op is None:
            return left
        pos, name = op
        node = Binary(pos, name, left, self.additive())
        if self.comparison_op() is not None:
            raise self.error("comparisons cannot be chained — combine them with 'and'", pos)
        return node

    def comparison_op(self) -> tuple[int, str] | None:
        t = self.tok
        if t.kind == "op" and t.value in _COMPARISON:
            self.advance()
            return t.pos, t.value
        if self.at("kw", "in"):
            self.advance()
            return t.pos, "in"
        if (
            self.at("kw", "not")
            and self.toks[self.i + 1].kind == "kw"
            and self.toks[self.i + 1].value == "in"
        ):
            self.i += 2
            return t.pos, "not in"
        return None

    def additive(self) -> Node:
        node = self.multiplicative()
        while self.at("op", "+") or self.at("op", "-"):
            t = self.advance()
            node = Binary(t.pos, t.value, node, self.multiplicative())
        return node

    def multiplicative(self) -> Node:
        node = self.unary()
        while self.at("op", "*") or self.at("op", "/"):
            t = self.advance()
            node = Binary(t.pos, t.value, node, self.unary())
        return node

    def unary(self) -> Node:
        if self.at("op", "-"):
            pos = self.advance().pos
            self.nest()
            operand = self.unary()
            self.depth -= 1
            return Unary(pos, "-", operand)
        return self.postfix()

    def postfix(self) -> Node:
        node = self.primary()
        while True:
            if self.at("op", "."):
                self.advance()
                t = self.tok
                if t.kind not in ("name", "kw"):
                    raise self.error(f"expected a field name after '.', found {self.describe(t)}")
                self.advance()
                _check_field_name(t.value, self.text, t.pos)
                node = Member(t.pos, node, t.value)
            elif self.at("op", "["):
                pos = self.advance().pos
                self.nest()
                index = self.or_()
                self.depth -= 1
                self.expect_op("]")
                node = Index(pos, node, index)
            else:
                return node

    def primary(self) -> Node:
        t = self.tok
        if t.kind in ("number", "string"):
            self.advance()
            return Lit(t.pos, t.value)
        if t.kind == "kw" and t.value in ("true", "false", "null"):
            self.advance()
            return Lit(t.pos, {"true": True, "false": False, "null": None}[t.value])
        if t.kind == "name":
            self.advance()
            if self.at("op", "("):
                return self.call(t)
            _check_field_name(t.value, self.text, t.pos)
            return Name(t.pos, t.value)
        if self.at("op", "("):
            self.advance()
            self.nest()
            node = self.or_()
            self.depth -= 1
            self.expect_op(")")
            return node
        if self.at("op", "["):
            pos = self.advance().pos
            items: list[Node] = []
            if not self.at("op", "]"):
                while True:
                    self.nest()
                    items.append(self.or_())
                    self.depth -= 1
                    if not self.at("op", ","):
                        break
                    self.advance()
            self.expect_op("]")
            return ListLit(pos, tuple(items))
        raise self.error(f"expected a value, found {self.describe(t)}")

    def call(self, name_tok: _Tok) -> Call:
        fname = name_tok.value
        if fname not in FUNCTIONS:
            known = ", ".join(sorted(FUNCTIONS))
            raise self.error(f"unknown function {fname!r} — available: {known}", name_tok.pos)
        self.advance()  # "("
        args: list[Node] = []
        if not self.at("op", ")"):
            while True:
                self.nest()
                args.append(self.or_())
                self.depth -= 1
                if not self.at("op", ","):
                    break
                self.advance()
        self.expect_op(")")
        arity = FUNCTIONS[fname][0]
        if len(args) != arity:
            raise self.error(
                f"{fname}() takes {arity} argument{'s' if arity != 1 else ''}, got {len(args)}",
                name_tok.pos,
            )
        return Call(name_tok.pos, fname, tuple(args))


def _check_field_name(name: str, text: str, pos: int) -> None:
    if name.startswith("_"):
        raise TELSyntaxError(f"{name!r}: names starting with '_' are reserved", text, pos)


# ── Static types ─────────────────────────────────────────────────────────────

_Kind = Literal[
    "any",
    "null",
    "bool",
    "int",
    "float",
    "str",
    "date",
    "datetime",
    "uuid",
    "enum",
    "list",
    "object",
]


@dataclass(frozen=True)
class _T:
    kind: _Kind
    values: tuple[str, ...] = ()
    item: _T | None = None
    cls: type[BaseModel] | None = None
    optional: bool = False

    def nullable(self) -> _T:
        return _T(self.kind, self.values, self.item, self.cls, True)

    def required(self) -> _T:
        return _T(self.kind, self.values, self.item, self.cls, False)

    def __str__(self) -> str:
        if self.kind == "enum":
            text = "enum[" + ", ".join(self.values) + "]"
        elif self.kind == "list":
            text = f"list[{self.item}]"
        elif self.kind == "object":
            text = self.cls.__name__ if self.cls else "object"
        else:
            text = self.kind
        return text + ("?" if self.optional and self.kind not in ("any", "null") else "")


_ANY = _T("any")
_NULL = _T("null")
_BOOL = _T("bool")
_INT = _T("int")
_FLOAT = _T("float")
_STR = _T("str")
_DATETIME = _T("datetime")
_NUMERIC = frozenset({"int", "float"})
_ORDERED = (_NUMERIC, frozenset({"str", "enum"}), frozenset({"date"}), frozenset({"datetime"}))


def _from_ref(ref: TypeRef, resolver: ModelResolver) -> _T:
    t: _T
    if ref.kind == "scalar":
        if ref.name == "file":
            t = _T("object", cls=FileRef)
        else:
            t = _ANY if ref.name == "json" else _T(ref.name)  # type: ignore[arg-type]
    elif ref.kind == "enum":
        t = _T("enum", values=ref.values)
    elif ref.kind == "list":
        assert ref.item is not None
        t = _T("list", item=_from_ref(ref.item, resolver))
    else:
        cls = resolver(ref.name, ref.variant)
        if cls is None:
            raise TELTypeError(f"unknown model {ref.name!r}")
        t = _T("object", cls=cls)
    return t.nullable() if ref.optional else t


_PY_SCALARS: dict[Any, _T] = {
    bool: _BOOL,
    int: _INT,
    float: _FLOAT,
    str: _STR,
    _dt.date: _T("date"),
    _dt.datetime: _DATETIME,
    _uuid.UUID: _T("uuid"),
}


def _from_annotation(ann: Any) -> _T:
    """Static type of a Pydantic field annotation (for ``model.field`` paths)."""
    origin = typing.get_origin(ann)
    args = typing.get_args(ann)
    if origin in (typing.Union, _types.UnionType):
        non_null = [a for a in args if a is not type(None)]
        inner = _from_annotation(non_null[0]) if len(non_null) == 1 else _ANY
        return inner.nullable() if len(non_null) < len(args) else inner
    if origin is Literal:
        if all(isinstance(a, str) for a in args):
            return _T("enum", values=tuple(args))
        return _ANY
    if origin in (list, Sequence, tuple):
        return _T("list", item=_from_annotation(args[0]) if args else _ANY)
    if isinstance(ann, type):
        if ann in _PY_SCALARS:
            return _PY_SCALARS[ann]
        if issubclass(ann, Enum):
            return _T("enum", values=tuple(str(m.value) for m in ann))
        if issubclass(ann, BaseModel):
            return _T("object", cls=ann)
    return _ANY


def _fields(t: _T) -> dict[str, _T]:
    assert t.cls is not None
    return {
        (info.alias or name): _from_annotation(info.annotation)
        for name, info in t.cls.model_fields.items()
    }


Env = Mapping[str, "str | Mapping[str, Any] | TypeRef | FieldSpec"]


class _Checker:
    def __init__(self, text: str, env: Mapping[str, _T], resolver: ModelResolver) -> None:
        self.text = text
        self.env = env
        self.resolver = resolver

    def error(self, message: str, node: Node) -> TELTypeError:
        return TELTypeError(message, self.text, node.pos)

    def check(self, node: Node) -> _T:
        dispatch: dict[type[Node], Callable[[Any], _T]] = {
            Lit: self.check_lit,
            ListLit: self.check_list_lit,
            Name: self.check_name,
            Member: self.check_member,
            Index: self.check_index,
            Unary: self.check_unary,
            Binary: self.check_binary,
            Call: self.check_call,
        }
        return dispatch[type(node)](node)

    def check_lit(self, node: Lit) -> _T:
        v = node.value
        if v is None:
            return _NULL
        if isinstance(v, bool):
            return _BOOL
        if isinstance(v, int):
            return _INT
        if isinstance(v, float):
            return _FLOAT
        return _STR

    def check_list_lit(self, node: ListLit) -> _T:
        items = [self.check(i) for i in node.items]
        kinds = {i.kind for i in items}
        if not items or len(kinds) != 1 and not kinds <= _NUMERIC:
            return _T("list", item=_ANY)
        return _T("list", item=_FLOAT if len(kinds) > 1 else items[0].required())

    def check_name(self, node: Name) -> _T:
        if node.name not in self.env:
            known = ", ".join(sorted(self.env)) or "none"
            raise self.error(f"unknown name {node.name!r} — declared inputs: {known}", node)
        return self.env[node.name]

    def check_member(self, node: Member) -> _T:
        obj = self.check(node.obj)
        if obj.kind == "any":
            return _ANY
        if obj.kind != "object":
            raise self.error(f"{obj} has no field {node.name!r}", node)
        fields = _fields(obj)
        if node.name not in fields:
            raise self.error(
                f"{obj.required()} has no field {node.name!r} — fields: {', '.join(sorted(fields))}",
                node,
            )
        t = fields[node.name]
        return t.nullable() if obj.optional else t

    def check_index(self, node: Index) -> _T:
        obj = self.check(node.obj)
        idx = self.check(node.index)
        if idx.kind not in ("int", "any"):
            raise self.error(f"list index must be int, got {idx}", node.index)
        if obj.kind == "any":
            return _ANY
        if obj.kind != "list":
            raise self.error(f"{obj} cannot be indexed", node)
        assert obj.item is not None
        return obj.item.nullable()  # out of range is null

    def check_unary(self, node: Unary) -> _T:
        t = self.check(node.operand)
        if node.op == "not":
            self.want_bool(t, node.operand, "'not'")
            return _BOOL
        if t.kind not in _NUMERIC and t.kind != "any":
            raise self.error(f"unary '-' needs a number, got {t}", node.operand)
        return t.required() if t.kind != "any" else _ANY

    def want_bool(self, t: _T, node: Node, what: str) -> None:
        if t.kind not in ("bool", "any"):
            raise self.error(f"{what} needs a bool, got {t}", node)

    def check_binary(self, node: Binary) -> _T:
        op = node.op
        left = self.check(node.left)
        right = self.check(node.right)
        if op in ("and", "or"):
            self.want_bool(left, node.left, f"'{op}'")
            self.want_bool(right, node.right, f"'{op}'")
            return _BOOL
        if op in ("==", "!="):
            self.comparable(left, right, node)
            return _BOOL
        if op in ("<", "<=", ">", ">="):
            if not (_ANY.kind in (left.kind, right.kind) or "null" in (left.kind, right.kind)):
                if not any(left.kind in g and right.kind in g for g in _ORDERED):
                    raise self.error(f"cannot order {left} and {right} with {op!r}", node)
                if left.kind == "enum" or right.kind == "enum":
                    raise self.error(
                        f"enum values are not ordered — use == or 'in', not {op!r}", node
                    )
            return _BOOL
        if op in ("in", "not in"):
            if right.kind == "list":
                assert right.item is not None
                if left.kind == "enum" and isinstance(node.right, ListLit):
                    for item in node.right.items:
                        self.enum_literal(left, item)
                else:
                    self.comparable(left, right.item, node)
            elif right.kind in ("str", "enum"):
                if left.kind not in ("str", "enum", "any"):
                    raise self.error(
                        f"substring test needs a str on the left, got {left}", node.left
                    )
            elif right.kind != "any":
                raise self.error(
                    f"{op!r} needs a list or str on the right, got {right}", node.right
                )
            return _BOOL
        return self.arithmetic(op, left, right, node)

    def arithmetic(self, op: str, left: _T, right: _T, node: Binary) -> _T:
        for side, t in (("left", left), ("right", right)):
            if t.kind == "null":
                raise self.error(f"arithmetic on null ({side} of {op!r})", node)
        if "any" in (left.kind, right.kind):
            return _ANY
        if op == "+" and left.kind in ("str", "enum") and right.kind in ("str", "enum"):
            return _STR
        if left.kind in _NUMERIC and right.kind in _NUMERIC:
            if op == "/" or "float" in (left.kind, right.kind):
                return _FLOAT
            return _INT
        raise self.error(f"cannot apply {op!r} to {left} and {right}", node)

    def comparable(self, a: _T, b: _T, node: Binary) -> None:
        if "any" in (a.kind, b.kind) or "null" in (a.kind, b.kind):
            return
        if a.kind == b.kind == "enum":
            if not set(a.values) & set(b.values):
                raise self.error(f"{a} and {b} share no values — this can never be equal", node)
            return
        for enum_t, other, other_node in ((a, b, node.right), (b, a, node.left)):
            if enum_t.kind == "enum" and other.kind == "str":
                self.enum_literal(enum_t, other_node)
                return
        if a.kind in _NUMERIC and b.kind in _NUMERIC:
            return
        if a.kind != b.kind:
            raise self.error(f"cannot compare {a} with {b}", node)

    def enum_literal(self, enum_t: _T, node: Node) -> None:
        if (
            isinstance(node, Lit)
            and isinstance(node.value, str)
            and node.value not in enum_t.values
        ):
            raise self.error(f"{node.value!r} is not a value of {enum_t.required()}", node)

    def check_call(self, node: Call) -> _T:
        args = [self.check(a) for a in node.args]
        accepts = FUNCTIONS[node.func][1]
        for i, (arg, allowed) in enumerate(zip(args, accepts, strict=True)):
            if arg.kind not in allowed and arg.kind != "any" and "*" not in allowed:
                raise self.error(
                    f"{node.func}() argument {i + 1} must be {' or '.join(sorted(allowed))}, got {arg}",
                    node.args[i],
                )
        return FUNCTIONS[node.func][2]


# ── Runtime ──────────────────────────────────────────────────────────────────


def _data(v: Any) -> Any:
    return v.model_dump(by_alias=True) if isinstance(v, BaseModel) else v


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, Enum):
        a = a.value
    if isinstance(b, Enum):
        b = b.value
    return bool(a == b)


class _Evaluator:
    def __init__(self, text: str) -> None:
        self.text = text

    def error(self, message: str, node: Node) -> TELEvalError:
        return TELEvalError(message, self.text, node.pos)

    def eval(self, node: Node, data: Mapping[str, Any]) -> Any:
        if isinstance(node, Lit):
            return node.value
        if isinstance(node, ListLit):
            return [self.eval(i, data) for i in node.items]
        if isinstance(node, Name):
            return _data(data.get(node.name))
        if isinstance(node, Member):
            obj = self.eval(node.obj, data)
            if obj is None:
                return None
            if not isinstance(obj, Mapping):
                raise self.error(f"cannot read field {node.name!r} of {type(obj).__name__}", node)
            return _data(obj.get(node.name))
        if isinstance(node, Index):
            obj = self.eval(node.obj, data)
            idx = self.eval(node.index, data)
            if obj is None:
                return None
            if not isinstance(obj, Sequence) or isinstance(obj, (str, bytes)):
                raise self.error(f"cannot index {type(obj).__name__}", node)
            if not isinstance(idx, int) or isinstance(idx, bool):
                raise self.error("list index must be int", node.index)
            return _data(obj[idx]) if -len(obj) <= idx < len(obj) else None
        if isinstance(node, Unary):
            v = self.eval(node.operand, data)
            if node.op == "not":
                return not self.as_bool(v, node.operand, "'not'")
            if not _is_num(v):
                raise self.error(f"unary '-' needs a number, got {_tname(v)}", node.operand)
            return -v
        if isinstance(node, Binary):
            return self.binary(node, data)
        if isinstance(node, Call):
            return self.call(node, data)
        raise AssertionError(f"unknown node {node!r}")

    def as_bool(self, v: Any, node: Node, what: str) -> bool:
        if not isinstance(v, bool):
            raise self.error(f"{what} needs a bool, got {_tname(v)}", node)
        return v

    def binary(self, node: Binary, data: Mapping[str, Any]) -> Any:
        op = node.op
        if op == "and":
            return self.as_bool(self.eval(node.left, data), node.left, "'and'") and self.as_bool(
                self.eval(node.right, data), node.right, "'and'"
            )
        if op == "or":
            return self.as_bool(self.eval(node.left, data), node.left, "'or'") or self.as_bool(
                self.eval(node.right, data), node.right, "'or'"
            )
        a = self.eval(node.left, data)
        b = self.eval(node.right, data)
        if op == "==":
            return _eq(a, b)
        if op == "!=":
            return not _eq(a, b)
        if op in ("<", "<=", ">", ">="):
            if a is None or b is None:
                return False
            try:
                return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
            except TypeError as exc:
                raise self.error(f"cannot order {_tname(a)} and {_tname(b)}", node) from exc
        if op in ("in", "not in"):
            if b is None:
                found = False
            elif isinstance(b, str):
                if not isinstance(a, str):
                    raise self.error(f"substring test needs a str, got {_tname(a)}", node.left)
                found = a in b
            elif isinstance(b, Sequence):
                found = any(_eq(a, _data(x)) for x in b)
            else:
                raise self.error(f"{op!r} needs a list or str, got {_tname(b)}", node.right)
            return found if op == "in" else not found
        return self.arithmetic(op, a, b, node)

    def arithmetic(self, op: str, a: Any, b: Any, node: Binary) -> Any:
        if a is None or b is None:
            raise self.error(f"arithmetic on null ({op!r})", node)
        if op == "+" and isinstance(a, str) and isinstance(b, str):
            return a + b
        if not (_is_num(a) and _is_num(b)):
            raise self.error(f"cannot apply {op!r} to {_tname(a)} and {_tname(b)}", node)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if b == 0:
            raise self.error("division by zero", node)
        return a / b

    def call(self, node: Call, data: Mapping[str, Any]) -> Any:
        args = [self.eval(a, data) for a in node.args]
        try:
            return FUNCTIONS[node.func][3](*args)
        except (TypeError, ValueError, AttributeError) as exc:
            raise self.error(f"{node.func}(): {exc}", node) from exc


def _tname(v: Any) -> str:
    return "null" if v is None else type(v).__name__


def _len(v: Any) -> int:
    if not isinstance(v, (str, list, tuple)):
        raise TypeError(f"needs a str or list, got {_tname(v)}")
    return len(v)


def _str_fn(name: str) -> Callable[[Any], str]:
    def fn(v: Any) -> str:
        if not isinstance(v, str):
            raise TypeError(f"needs a str, got {_tname(v)}")
        return str(getattr(v, name)())

    return fn


def _contains(haystack: Any, needle: Any) -> bool:
    if isinstance(haystack, str):
        if not isinstance(needle, str):
            raise TypeError(f"needs a str to search for, got {_tname(needle)}")
        return needle in haystack
    if isinstance(haystack, (list, tuple)):
        return any(_eq(needle, _data(x)) for x in haystack)
    if isinstance(haystack, Mapping):  # an object: is the key present?
        return needle in haystack
    if haystack is None:
        return False
    raise TypeError(f"needs a str, list or object, got {_tname(haystack)}")


def _affix(kind: Literal["start", "end"]) -> Callable[[Any, Any], bool]:
    def fn(s: Any, affix: Any) -> bool:
        if not isinstance(s, str) or not isinstance(affix, str):
            raise TypeError(f"needs two strs, got {_tname(s)} and {_tname(affix)}")
        return s.startswith(affix) if kind == "start" else s.endswith(affix)

    return fn


def _is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, (str, list, tuple, Mapping)) and len(v) == 0)


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _days_between(a: Any, b: Any) -> int:
    def as_date(v: Any) -> _dt.date:
        if isinstance(v, _dt.datetime):
            return v.date()
        if isinstance(v, _dt.date):
            return v
        raise TypeError(f"needs a date or datetime, got {_tname(v)}")

    return (as_date(b) - as_date(a)).days


_STRS = frozenset({"str", "enum"})
_DATES = frozenset({"date", "datetime"})
#: name → (arity, accepted kinds per argument, static result type, implementation)
FUNCTIONS: dict[str, tuple[int, tuple[frozenset[str], ...], _T, Callable[..., Any]]] = {
    "len": (1, (frozenset({"str", "enum", "list"}),), _INT, _len),
    "lower": (1, (_STRS,), _STR, _str_fn("lower")),
    "upper": (1, (_STRS,), _STR, _str_fn("upper")),
    "contains": (
        2,
        (frozenset({"str", "enum", "list", "model"}), frozenset({"*"})),
        _BOOL,
        _contains,
    ),
    "starts_with": (2, (_STRS, _STRS), _BOOL, _affix("start")),
    "ends_with": (2, (_STRS, _STRS), _BOOL, _affix("end")),
    "is_empty": (1, (frozenset({"*"}),), _BOOL, _is_empty),
    "now": (0, (), _DATETIME, _now),
    "days_between": (2, (_DATES, _DATES), _INT, _days_between),
}


# ── Public API ───────────────────────────────────────────────────────────────


def _env_types(env: Env, resolver: ModelResolver) -> dict[str, _T]:
    out: dict[str, _T] = {}
    for name, spec in env.items():
        try:
            out[name] = _from_ref(parse_field(spec).type, resolver)
        except TypeParseError as exc:
            raise TELTypeError(f"input {name!r}: {exc}") from exc
    return out


def _roots(node: Node) -> set[str]:
    if isinstance(node, Name):
        return {node.name}
    out: set[str] = set()
    for value in vars(node).values():
        children = value if isinstance(value, tuple) else (value,)
        for child in children:
            if isinstance(child, Node):
                out |= _roots(child)
    return out


@dataclass(frozen=True)
class Expression:
    """A parsed TEL expression."""

    text: str
    ast: Node = field(repr=False)

    def roots(self) -> set[str]:
        """Top-level names the expression reads (for input-declaration checks)."""
        return _roots(self.ast)

    def check(
        self,
        env: Env,
        resolver: ModelResolver | None = None,
        *,
        expect: Literal["bool"] | None = None,
    ) -> str:
        """Type-check against declared input types; return the result type.

        Raises :class:`TELTypeError` on any mismatch, including a non-bool
        result when ``expect="bool"`` (rule conditions, approval guards).
        """
        types = _env_types(env, resolver or registry_resolver)
        result = _Checker(self.text, types, resolver or registry_resolver).check(self.ast)
        if expect == "bool" and result.kind not in ("bool", "any"):
            raise TELTypeError(f"condition must be a bool, got {result}", self.text, self.ast.pos)
        return str(result)

    def evaluate(self, data: Mapping[str, Any]) -> Any:
        return _Evaluator(self.text).eval(self.ast, data)


def compile_expr(text: str) -> Expression:
    """Parse *text* into an :class:`Expression` (no type information needed)."""
    if not isinstance(text, str):
        raise TELSyntaxError(f"an expression must be a string, got {type(text).__name__}")
    if not text.strip():
        raise TELSyntaxError("empty expression")
    if len(text) > MAX_EXPRESSION_CHARS:
        raise TELSyntaxError(f"expression longer than {MAX_EXPRESSION_CHARS} characters")
    return _compile_expr(text)


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _compile_expr(text: str) -> Expression:
    return Expression(text, _Parser(text).parse())


# ── Templates ────────────────────────────────────────────────────────────────

_PLACEHOLDER = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)


@dataclass(frozen=True)
class Template:
    """A string with ``{{ expr }}`` placeholders.

    If the whole string is a single placeholder, :meth:`render` returns the
    raw value (so ``"{{ order.total }}"`` stays a number); otherwise values
    are interpolated as text.
    """

    text: str
    parts: tuple[str | Expression, ...] = field(repr=False)

    @property
    def is_single_value(self) -> bool:
        return len(self.parts) == 1 and isinstance(self.parts[0], Expression)

    def expressions(self) -> list[Expression]:
        return [p for p in self.parts if isinstance(p, Expression)]

    def roots(self) -> set[str]:
        out: set[str] = set()
        for expr in self.expressions():
            out |= expr.roots()
        return out

    def check(self, env: Env, resolver: ModelResolver | None = None) -> None:
        for expr in self.expressions():
            expr.check(env, resolver)

    def render(self, data: Mapping[str, Any]) -> Any:
        if self.is_single_value:
            expr = self.parts[0]
            assert isinstance(expr, Expression)
            return expr.evaluate(data)
        out: list[str] = []
        for part in self.parts:
            out.append(part if isinstance(part, str) else _to_text(part.evaluate(data)))
        return "".join(out)


def _to_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (Mapping, list, tuple)):
        return json.dumps(v, default=str)
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    return str(v)


def compile_template(text: str) -> Template:
    """Parse a template; text without ``{{ }}`` is a literal."""
    return _compile_template(text)


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _compile_template(text: str) -> Template:
    parts: list[str | Expression] = []
    pos = 0
    for m in _PLACEHOLDER.finditer(text):
        _reject_unclosed(text, pos, m.start())
        if m.start() > pos:
            parts.append(text[pos : m.start()])
        try:
            parts.append(compile_expr(m.group(1)))
        except TELSyntaxError as exc:
            raise TELSyntaxError(exc.message, text, m.start(1) + (exc.pos or 0)) from exc
        pos = m.end()
    _reject_unclosed(text, pos, len(text))
    if pos < len(text):
        parts.append(text[pos:])
    exprs = [p for p in parts if isinstance(p, Expression)]
    literal = "".join(p for p in parts if isinstance(p, str))
    if len(exprs) == 1 and not literal.strip():
        parts = [exprs[0]]
    return Template(text, tuple(parts))


def _reject_unclosed(text: str, start: int, end: int) -> None:
    i = text.find("{{", start, end)
    if i != -1:
        raise TELSyntaxError("unclosed '{{'", text, i)
