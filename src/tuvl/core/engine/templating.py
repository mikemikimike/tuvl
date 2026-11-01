"""Single-source string templating for the engine.

Exactly one implementation of each interpolation layer:

- :func:`render` — flat ``{{ key }}`` context interpolation. The
  ``on_missing`` parameter selects the behaviour previously spread across
  three divergent copies (engine keep/empty, agent raise).
- :func:`expand_env` — ``${VAR}`` / ``${VAR:default}`` environment expansion
  with the DataSource contract: a default wins, a missing variable with no
  default raises. Config-field concern only — never applied to prose.
"""

from __future__ import annotations

import os
import re
from typing import Any

TEMPLATE_RE = re.compile(r"\{\{([^}]+)\}\}")
ENV_RE = re.compile(r"\$\{([^}:\s]+)(?::([^}]*))?\}")

_MISSING = object()


def render(
    template: str,
    context: dict[str, Any],
    *,
    on_missing: str = "keep",
    label: str = "",
) -> str:
    """Replace flat ``{{key}}`` placeholders with values from *context*.

    Keys are stripped; no dot-path resolution (that lives in
    ``WorkflowEngine._resolve_tpl_obj``).

    ``on_missing`` selects the unresolved-key behaviour:

    - ``"keep"``  — an absent key *or* a present ``None`` leaves ``{{key}}`` intact.
    - ``"empty"`` — an absent key renders as ``""`` (a present ``None`` stringifies
      to ``"None"``, matching ``str(context.get(key, ""))``).
    - ``"raise"`` — an absent key raises ``KeyError`` naming *label* and the
      available public keys (prompt rendering wants loud failures).
    """

    def _sub(m: re.Match) -> str:
        key = m.group(1).strip()
        val = context.get(key, _MISSING)
        if on_missing == "raise":
            if val is _MISSING:
                raise KeyError(
                    f"[{label}] template references missing context key '{{{{ {key} }}}}'. "
                    f"Available keys: {[k for k in context if not k.startswith('_')]}"
                )
            return str(val)
        if on_missing == "keep":
            return str(val) if (val is not _MISSING and val is not None) else m.group(0)
        return "" if val is _MISSING else str(val)

    return TEMPLATE_RE.sub(_sub, template)


def expand_env(value: str | None, *, source: str = "config") -> str | None:
    """Expand ``${VAR}`` / ``${VAR:default}`` references from the environment.

    A declared default wins when the variable is unset; a missing variable
    with no default raises ``OSError`` naming *source* — silent pass-through
    turned unresolved secrets into confusing provider auth failures.
    """
    if not value:
        return value

    def _replace(match: re.Match) -> str:
        var_name: str = match.group(1)
        default: str | None = match.group(2)
        if default is not None:
            return os.environ.get(var_name, default)
        resolved = os.environ.get(var_name)
        if resolved is None:
            raise OSError(
                f"{source} references undefined environment variable "
                f"'${{{var_name}}}'. Set it in your .env file or environment, "
                f"or declare a default with '${{{var_name}:default}}'."
            )
        return resolved

    return ENV_RE.sub(_replace, value)
