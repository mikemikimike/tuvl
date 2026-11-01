"""The tuvl 2.0 type language (spec §6.1).

One small grammar describes every typed slot in a workflow — agent
``inputs``/``outputs``, trigger input, human-form fields, test expectations::

    type   := base "?"?
    base   := scalar
            | "enum[" value ("," value)* "]"
            | "list[" type "]"
            | Model ("." variant)?
    scalar := str | int | float | bool | date | datetime | uuid | json | file

A field may also use the long form ``{type, description, default}``.

Types parse to an immutable :class:`TypeRef`; :func:`build_model` compiles a
mapping of field names to types into a Pydantic model, which is the single
artefact request validation, codegen, OpenAPI and MCP schemas all derive from.
Model names must start with an uppercase letter so a typo'd scalar
(``string``) fails at parse time instead of becoming an unknown model.
"""

from __future__ import annotations

import datetime as _dt
import functools
import re
import uuid as _uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    create_model,
)

from tuvl.contract.files import FileRef

SCALARS: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "date": _dt.date,
    "datetime": _dt.datetime,
    "uuid": _uuid.UUID,
    "json": JsonValue,
    "file": FileRef,
}

#: Model variants, in the order ``SCHEMA_REGISTRY`` builds them. A bare model
#: name means ``read``.
MODEL_VARIANTS: tuple[str, ...] = ("read", "create", "update", "expanded")

# 1.x ModelDefinition type names → the 2.0 spelling, for a pointed error.
_LEGACY_NAMES = {
    "string": "str",
    "text": "str",
    "varchar": "str",
    "integer": "int",
    "bigint": "int",
    "smallint": "int",
    "numeric": "float",
    "boolean": "bool",
    "timestamp": "datetime",
    "timestamptz": "datetime",
    "jsonb": "json",
    "dict": "json",
    "any": "json",
}

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ENUM_BARE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*")
_FIELD_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
_LONG_FORM_KEYS = frozenset({"type", "description", "default"})


class TypeParseError(ValueError):
    """A type expression or field spec is malformed."""

    def __init__(self, message: str, text: str = "", pos: int | None = None) -> None:
        self.message = message
        self.text = text
        self.pos = pos
        where = f" at column {pos + 1} in {text!r}" if text and pos is not None else ""
        super().__init__(f"{message}{where}")


class TypeResolutionError(ValueError):
    """A well-formed type cannot be turned into a Python type (unknown model,
    missing variant, default that does not match its type, bad field name)."""


@dataclass(frozen=True)
class TypeRef:
    kind: Literal["scalar", "enum", "list", "model"]
    name: str = ""
    variant: str = "read"
    values: tuple[str, ...] = ()
    item: TypeRef | None = None
    optional: bool = False

    def model_refs(self) -> set[tuple[str, str]]:
        """Every ``(model, variant)`` this type references, including nested."""
        if self.kind == "model":
            return {(self.name, self.variant)}
        if self.kind == "list" and self.item is not None:
            return self.item.model_refs()
        return set()

    def __str__(self) -> str:
        return format_type(self)


_NO_DEFAULT: Any = object()


@dataclass(frozen=True)
class FieldSpec:
    type: TypeRef
    description: str | None = None
    default: Any = field(default=_NO_DEFAULT)

    @property
    def has_default(self) -> bool:
        return self.default is not _NO_DEFAULT


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def error(self, message: str, pos: int | None = None) -> TypeParseError:
        return TypeParseError(message, self.text, self.pos if pos is None else pos)

    def skip_ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def expect(self, ch: str) -> None:
        self.skip_ws()
        if self.peek() != ch:
            found = repr(self.peek()) if self.peek() else "end of input"
            raise self.error(f"expected {ch!r}, found {found}")
        self.pos += 1

    def parse(self) -> TypeRef:
        ref = self.type_()
        self.skip_ws()
        if self.pos != len(self.text):
            raise self.error(f"unexpected {self.peek()!r}")
        return ref

    def type_(self) -> TypeRef:
        self.skip_ws()
        start = self.pos
        m = _IDENT.match(self.text, self.pos)
        if not m:
            found = repr(self.peek()) if self.peek() else "end of input"
            raise self.error(f"expected a type, found {found}")
        word = m.group()
        self.pos = m.end()

        if word in ("enum", "list"):
            self.skip_ws()
            if self.peek() != "[":
                hint = "enum[a, b, ...]" if word == "enum" else "list[T]"
                raise self.error(f"{word} needs brackets: {hint}", start)
            self.pos += 1
            ref = self.enum_body() if word == "enum" else self.list_body()
        elif word in SCALARS:
            ref = TypeRef("scalar", name=word)
        elif word in _LEGACY_NAMES:
            raise self.error(
                f"unknown type {word!r} — did you mean {_LEGACY_NAMES[word]!r}?", start
            )
        elif not word[0].isupper():
            scalars = ", ".join(SCALARS)
            raise self.error(
                f"unknown type {word!r} — scalars are {scalars}; "
                "model names start with an uppercase letter",
                start,
            )
        else:
            ref = TypeRef("model", name=word, variant=self.variant())

        self.skip_ws()
        if self.peek() == "?":
            self.pos += 1
            ref = TypeRef(ref.kind, ref.name, ref.variant, ref.values, ref.item, optional=True)
        return ref

    def variant(self) -> str:
        if self.peek() != ".":
            return "read"
        self.pos += 1
        start = self.pos
        m = _IDENT.match(self.text, self.pos)
        if not m or m.group() not in MODEL_VARIANTS:
            got = m.group() if m else self.peek()
            raise self.error(
                f"unknown model variant {got!r} — expected one of {', '.join(MODEL_VARIANTS)}",
                start,
            )
        self.pos = m.end()
        return m.group()

    def enum_body(self) -> TypeRef:
        values: list[str] = []
        while True:
            self.skip_ws()
            start = self.pos
            value = self.enum_value()
            if value in values:
                raise self.error(f"duplicate enum value {value!r}", start)
            values.append(value)
            self.skip_ws()
            if self.peek() == ",":
                self.pos += 1
                continue
            self.expect("]")
            return TypeRef("enum", values=tuple(values))

    def enum_value(self) -> str:
        quote = self.peek()
        if quote in ("'", '"'):
            end = self.text.find(quote, self.pos + 1)
            if end == -1:
                raise self.error("unterminated quoted enum value")
            value = self.text[self.pos + 1 : end]
            if not value:
                raise self.error("empty enum value")
            self.pos = end + 1
            return value
        m = _ENUM_BARE.match(self.text, self.pos)
        if not m:
            found = repr(self.peek()) if self.peek() else "end of input"
            raise self.error(f"expected an enum value, found {found}")
        self.pos = m.end()
        return m.group()

    def list_body(self) -> TypeRef:
        item = self.type_()
        self.expect("]")
        return TypeRef("list", item=item)


def parse_type(spec: str | TypeRef) -> TypeRef:
    """Parse a type expression (``"list[Order]?"``) into a :class:`TypeRef`."""
    if isinstance(spec, TypeRef):
        return spec
    if not isinstance(spec, str):
        raise TypeParseError(f"a type must be a string, got {type(spec).__name__}")
    if not spec.strip():
        raise TypeParseError("empty type")
    return _parse_type(spec)


@functools.lru_cache(maxsize=4096)
def _parse_type(spec: str) -> TypeRef:
    return _Parser(spec).parse()


def parse_field(spec: str | Mapping[str, Any] | TypeRef | FieldSpec) -> FieldSpec:
    """Parse a field in short (``"int?"``) or long (``{type, description,
    default}``) form."""
    if isinstance(spec, FieldSpec):
        return spec
    if isinstance(spec, (str, TypeRef)):
        return FieldSpec(type=parse_type(spec))
    if isinstance(spec, Mapping):
        unknown = sorted(set(spec) - _LONG_FORM_KEYS)
        if unknown:
            raise TypeParseError(
                f"unknown field key(s) {unknown} — allowed: {sorted(_LONG_FORM_KEYS)}"
            )
        if "type" not in spec:
            raise TypeParseError("long-form field needs a 'type'")
        description = spec.get("description")
        if description is not None and not isinstance(description, str):
            raise TypeParseError("'description' must be a string")
        return FieldSpec(
            type=parse_type(spec["type"]),
            description=description,
            default=spec.get("default", _NO_DEFAULT),
        )
    raise TypeParseError(f"a field must be a type string or a mapping, got {type(spec).__name__}")


def format_type(ref: TypeRef) -> str:
    """Canonical text for *ref*; ``parse_type(format_type(r)) == r``."""
    if ref.kind == "scalar":
        text = ref.name
    elif ref.kind == "enum":
        text = "enum[" + ", ".join(_format_enum_value(v) for v in ref.values) + "]"
    elif ref.kind == "list":
        assert ref.item is not None
        text = f"list[{format_type(ref.item)}]"
    else:
        text = ref.name if ref.variant == "read" else f"{ref.name}.{ref.variant}"
    return text + ("?" if ref.optional else "")


def _format_enum_value(value: str) -> str:
    if _ENUM_BARE.fullmatch(value):
        return value
    quote = '"' if '"' not in value else "'"
    return f"{quote}{value}{quote}"


# ── Compilation to Pydantic ──────────────────────────────────────────────────

#: Resolves ``(model name, variant)`` to its Pydantic schema class, or None.
ModelResolver = Callable[[str, str], type[BaseModel] | None]


def registry_resolver(name: str, variant: str) -> type[BaseModel] | None:
    """Default resolver backed by the loaded ``ModelDefinition`` schemas."""
    from tuvl.core.models.schemas import SCHEMA_REGISTRY

    return SCHEMA_REGISTRY.get(name, {}).get(variant)


def annotation(ref: TypeRef, resolver: ModelResolver | None = None) -> Any:
    """The Python type annotation for *ref*."""
    resolve = resolver or registry_resolver
    base: Any
    if ref.kind == "scalar":
        base = SCALARS[ref.name]
    elif ref.kind == "enum":
        base = cast(Any, Literal).__getitem__(ref.values)
    elif ref.kind == "list":
        assert ref.item is not None
        base = list[annotation(ref.item, resolve)]  # type: ignore[misc]
    else:
        cls = resolve(ref.name, ref.variant)
        if cls is None:
            raise TypeResolutionError(f"unknown model {format_type(ref).rstrip('?')!r}")
        base = cls
    return base | None if ref.optional else base


def build_model(
    name: str,
    fields: Mapping[str, str | Mapping[str, Any] | TypeRef | FieldSpec],
    resolver: ModelResolver | None = None,
    *,
    doc: str | None = None,
) -> type[BaseModel]:
    """Compile ``{field: type}`` into a Pydantic model that rejects unknown keys.

    Optional fields (``T?``) default to ``None``; a field with a ``default``
    is not required. A field whose name collides with a ``BaseModel``
    attribute (``json``, ``schema``, ``model_*``) is stored under a suffixed
    attribute and keeps its declared name as the alias on the wire.
    """
    definitions: dict[str, Any] = {}
    for field_name, raw in fields.items():
        if not _FIELD_NAME.match(field_name):
            raise TypeResolutionError(
                f"invalid field name {field_name!r} — use letters, digits and "
                "underscores, starting with a letter"
            )
        spec = parse_field(raw)
        ann = annotation(spec.type, resolver)
        if spec.has_default:
            try:
                TypeAdapter(ann).validate_python(spec.default)
            except ValidationError as exc:
                raise TypeResolutionError(
                    f"default for {field_name!r} does not match {format_type(spec.type)!r}: "
                    f"{exc.errors()[0]['msg']}"
                ) from exc
            default = spec.default
        elif spec.type.optional:
            default = None
        else:
            default = ...

        attr = field_name
        alias: str | None = None
        if field_name.startswith("model_") or hasattr(BaseModel, field_name):
            attr, alias = f"{field_name}_", field_name
        definitions[attr] = (
            ann,
            Field(default, description=spec.description, alias=alias),
        )

    model: type[BaseModel] = create_model(
        name,
        __config__=ConfigDict(extra="forbid", validate_by_name=True, serialize_by_alias=True),
        __doc__=doc,
        **definitions,
    )
    return model
