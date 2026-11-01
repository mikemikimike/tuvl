"""Guardrails — artifact-backed I/O validation for agent steps.

A ``type: guardrail`` artifact declares a closed set of checks::

    kind: Artifact
    metadata: { name: brief-schema-check }
    spec:
      type: guardrail
      checks:
        - check: json_schema
          schema: { type: object, required: [brief, sources] }
        - check: regex_deny
          patterns: ["(?i)api[_-]?key"]
        - check: max_chars
          limit: 20000
        - check: pii_mask                # masks secure fields, never fails

All checks are deterministic. An LLM-judged gate is a ``type: judge``
artifact listed beside guardrails (``tuvl.runtime.judges``), and fails closed.

Attached via ``agent.guardrails: {input: […], output: […], tools: […]}`` on
``llm`` and ``loop`` agents — input before the model is called, output on
the final result, tools on each tool observation. A failing check emits the
reserved signal ``guardrail_violation``.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from tuvl.core.artifacts.registry import resolve_structured

logger = structlog.get_logger(__name__)

#: Closed set of guardrail checks.
GUARDRAIL_CHECKS: frozenset[str] = frozenset({"json_schema", "regex_deny", "max_chars", "pii_mask"})


class GuardrailViolationError(Exception):
    """A guardrail check failed — routed as the reserved ``guardrail_violation``
    signal, never raised to the client."""

    def __init__(self, artifact: str, check: str, detail: str) -> None:
        super().__init__(f"guardrail '{artifact}' check '{check}' failed: {detail}")
        self.artifact = artifact
        self.check = check
        self.detail = detail


def _try_parse_json(content: str) -> Any | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None


def _check_json_schema(schema: dict[str, Any], value: Any, path: str = "$") -> str | None:
    """Minimal closed-subset JSON-Schema check (type / required / properties /
    items / enum) — deterministic and dependency-free. Returns the first
    problem, or None."""
    expected = schema.get("type")
    if expected:
        py_ok = {
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "null": lambda v: v is None,
        }.get(expected)
        if py_ok is not None and not py_ok(value):
            return f"{path}: expected {expected}, got {type(value).__name__}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: value {value!r} not in enum {schema['enum']}"
    if isinstance(value, dict):
        for req in schema.get("required") or []:
            if req not in value:
                return f"{path}: missing required key '{req}'"
        for key, sub in (schema.get("properties") or {}).items():
            if key in value:
                problem = _check_json_schema(sub, value[key], f"{path}.{key}")
                if problem:
                    return problem
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            problem = _check_json_schema(schema["items"], item, f"{path}[{i}]")
            if problem:
                return problem
    return None


async def run_guardrails(
    refs: list[str],
    content: str,
    *,
    gate: str,
    step_id: str,
) -> str:
    """Run every check of every referenced guardrail against *content*.

    Returns the (possibly transformed — ``pii_mask``) content; raises
    :class:`GuardrailViolationError` on the first failing check.
    """
    for ref in refs:
        where = f"agent:{step_id} guardrails.{gate}"
        spec = resolve_structured(ref, site="guardrails", where=where)
        name = ref.removeprefix("artifact://").split("@")[0]
        for check in spec.get("checks") or []:
            kind = str(check.get("check") or "")
            if kind == "max_chars":
                limit = int(check.get("limit") or 0)
                if limit and len(content) > limit:
                    raise GuardrailViolationError(
                        name, "max_chars", f"content is {len(content)} chars (limit {limit})"
                    )
            elif kind == "regex_deny":
                for pattern in check.get("patterns") or []:
                    if re.search(str(pattern), content):
                        raise GuardrailViolationError(
                            name, "regex_deny", f"content matches denied pattern {pattern!r}"
                        )
            elif kind == "json_schema":
                parsed = _try_parse_json(content)
                if parsed is None:
                    raise GuardrailViolationError(name, "json_schema", "content is not valid JSON")
                problem = _check_json_schema(check.get("schema") or {}, parsed)
                if problem:
                    raise GuardrailViolationError(name, "json_schema", problem)
            elif kind == "pii_mask":
                # Transform, never a failure: mask declared secure fields in
                # JSON content so PII can't cross the gate unmasked.
                parsed = _try_parse_json(content)
                if isinstance(parsed, (dict, list)):
                    from tuvl.core.engine.masking import mask_secure_json
                    from tuvl.core.models.loader import SECURE_FIELDS

                    content = json.dumps(mask_secure_json(parsed, SECURE_FIELDS), default=str)
            else:
                logger.warning("guardrail.unknown_check", artifact=name, check=kind, gate=gate)
        logger.debug("guardrail.passed", artifact=name, gate=gate, step_id=step_id)
    return content
