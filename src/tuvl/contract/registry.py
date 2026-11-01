"""Registry and loader for ``version: tuvl/v2`` documents.

``config_loader.load_all_configs`` hands every 2.0 document (``Workflow``,
``Test``, ``TaskPlan``) to :func:`register_document`, which validates it
against :mod:`tuvl.contract.schema` and stores the typed model. Errors are
reported against the author's YAML (``agents[triage_refund].decide.rules``),
not Pydantic's internal locations, with hints for the YAML 1.1 pitfalls the
2.0 syntax runs into.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from tuvl.contract.schema import (
    SCHEMA_VERSION,
    TaskPlanDocument,
    TestDocument,
    WorkflowDocument,
)

WORKFLOWS: dict[str, WorkflowDocument] = {}
TESTS: dict[str, TestDocument] = {}
TASK_PLANS: dict[str, TaskPlanDocument] = {}
#: ``(kind, name)`` → file the document was loaded from.
SOURCES: dict[tuple[str, str], str] = {}

_MODELS: dict[str, type[BaseModel]] = {
    "Workflow": WorkflowDocument,
    "Test": TestDocument,
    "TaskPlan": TaskPlanDocument,
}
_STORES: dict[str, dict[str, Any]] = {"Workflow": WORKFLOWS, "Test": TESTS, "TaskPlan": TASK_PLANS}

V1_WORKFLOW_MESSAGE = (
    "is a tuvl 1.x workflow (no 'version: tuvl/v2'). tuvl 2.0 does not load 1.x "
    "workflows — rewrite it as a 2.0 workflow (typed agents, 'version: tuvl/v2'); "
    "the migration guide maps every 1.x step kind to its 2.0 engine."
)


@dataclass(frozen=True)
class DocumentError:
    """One problem with a document, located in the author's terms."""

    path: str
    message: str
    hint: str | None = None

    def __str__(self) -> str:
        where = f"{self.path}: " if self.path else ""
        return f"{where}{self.message}" + (f" (hint: {self.hint})" if self.hint else "")


class DocumentLoadError(ValueError):
    def __init__(self, kind: str, name: str, filename: str, errors: list[DocumentError]) -> None:
        self.kind = kind
        self.name = name
        self.filename = filename
        self.errors = errors
        lines = "\n".join(f"  - {e}" for e in errors)
        label = f"{kind} '{name}'" if name else kind
        super().__init__(f"{label} in '{filename}' is invalid:\n{lines}")


def is_v2(data: dict[str, Any]) -> bool:
    return data.get("version") == SCHEMA_VERSION


def clear() -> None:
    for store in _STORES.values():
        store.clear()
    SOURCES.clear()


def parse_document(data: dict[str, Any], filename: str = "<unknown>") -> BaseModel:
    """Validate one 2.0 document without registering it."""
    kind = str(data.get("kind"))
    model = _MODELS.get(kind)
    name = _name_of(data)
    if model is None:
        raise DocumentLoadError(
            kind, name, filename, [DocumentError("kind", f"'{kind}' is not a 2.0 document kind")]
        )
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise DocumentLoadError(kind, name, filename, format_validation_error(exc, data)) from exc


def register_document(data: dict[str, Any], filename: str = "<unknown>") -> None:
    """Validate and store one 2.0 document. Names are unique per kind."""
    doc = parse_document(data, filename)
    kind = str(data["kind"])
    name = doc.metadata.name  # type: ignore[attr-defined]
    if (kind, name) in SOURCES:
        raise DocumentLoadError(
            kind,
            name,
            filename,
            [
                DocumentError(
                    "metadata.name",
                    f"duplicate {kind} name — already defined in '{SOURCES[(kind, name)]}'",
                )
            ],
        )
    _STORES[kind][name] = doc
    SOURCES[(kind, name)] = filename


def reject_v1_workflow(data: dict[str, Any], filename: str) -> None:
    raise DocumentLoadError(
        "Workflow", _name_of(data), filename, [DocumentError("", V1_WORKFLOW_MESSAGE)]
    )


# ── Error presentation ───────────────────────────────────────────────────────


def _name_of(data: dict[str, Any]) -> str:
    meta = data.get("metadata")
    return str(meta.get("name", "")) if isinstance(meta, dict) else ""


def format_validation_error(exc: ValidationError, data: Any) -> list[DocumentError]:
    """Pydantic errors → author-facing paths (``spec.agents[triage].decide``).

    Union branches are collapsed: when a value can be either shape (rules
    list or artifact ref), only the branch that got furthest is reported.
    """
    rendered = []
    for err in exc.errors(include_url=False):
        path, branch_at = _render_loc(err["loc"], data)
        rendered.append((err, path, branch_at))

    deepest: dict[str, int] = {}
    for err, _path, branch_at in rendered:
        if branch_at is not None:
            deepest[branch_at] = max(deepest.get(branch_at, 0), len(err["loc"]))

    out: list[DocumentError] = []
    seen: set[tuple[str, str]] = set()
    for err, path, branch_at in rendered:
        if branch_at is not None and len(err["loc"]) < deepest[branch_at]:
            continue
        message = _clean_message(err)
        if (path, message) in seen:
            continue
        seen.add((path, message))
        out.append(DocumentError(path, message, _hint(err)))
    return out


def _render_loc(loc: tuple[Any, ...], data: Any) -> tuple[str, str | None]:
    """Render *loc* against the raw document; also return the path at which a
    union branch label was dropped (``None`` when there was none)."""
    parts: list[str] = []
    node = data
    tag_skipped_at: int | None = None
    branch_at: str | None = None
    for key in loc:
        if isinstance(key, int):
            item = node[key] if isinstance(node, list) and -len(node) <= key < len(node) else None
            label = (
                item.get("id")
                if isinstance(item, dict) and isinstance(item.get("id"), str)
                else key
            )
            parts.append(f"[{label}]")
            node = item
            continue
        if isinstance(node, dict):
            # Discriminated unions insert the tag (``decide``, ``http``) once
            # before the fields of the chosen branch.
            if tag_skipped_at != id(node) and _is_union_tag(node, key):
                tag_skipped_at = id(node)
                continue
            # Plain unions insert the branch's class name (``LongFormField``).
            if key not in node and key[:1].isupper():
                branch_at = branch_at or "".join(parts)
                continue
        elif node is not None or "[" in key or "-" in key or key[:1].isupper():
            # A label for a union branch over a non-mapping value
            # (``list[DecideRule]``, ``constrained-str``, ``str``).
            branch_at = branch_at or "".join(parts)
            continue
        parts.append(("." if parts else "") + key)
        node = node.get(key) if isinstance(node, dict) else None
    return "".join(parts), branch_at


def _is_union_tag(node: dict[str, Any], key: str) -> bool:
    return any(node.get(field) == key for field in ("engine", "use"))


def _clean_message(err: Any) -> str:
    msg = str(err["msg"])
    if msg.startswith("Value error, "):
        msg = msg[len("Value error, ") :]
    if err["type"] == "union_tag_invalid":
        ctx = err.get("ctx") or {}
        tag = ctx.get("tag")
        expected = ctx.get("expected_tags")
        msg = f"unknown value {tag!r} — expected one of {expected}"
    elif err["type"] == "extra_forbidden":
        msg = "unknown key — not part of the 2.0 schema"
    return msg


def _hint(err: Any) -> str | None:
    value = err.get("input")
    if isinstance(value, bool) and err["type"] in ("string_type", "literal_error", "invalid_key"):
        return (
            "YAML reads bare on/off/yes/no/true/false as booleans — "
            "quote the value or use the documented spelling"
        )
    return None


def yaml_error_hint(exc: Exception) -> str | None:
    """A fix-it hint for YAML parse errors the 2.0 syntax commonly triggers."""
    text = str(exc)
    if "while parsing a flow mapping" in text or "while parsing a flow sequence" in text:
        return (
            "inside { ... } a comma ends the value and '? ' is a YAML indicator — "
            'quote types like "enum[a, b]" and "str?", or write one field per line'
        )
    return None
