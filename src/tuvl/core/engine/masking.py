"""Pure data-masking utility for OTel span sanitisation.

``mask_secure_data`` is a pure function — it carries no global state and never
mutates its input.  ``secure_keys`` is passed explicitly so the function is
trivially unit-testable without loading any model YAML or touching the engine.

Redaction rules (applied depth-first):
  - If the current *key* is in ``secure_keys``, its value is replaced with
    ``"*****"`` wholesale — the value is NOT recursed into.
  - If the current *value* is a ``dict``, recurse into it.
  - If the current *value* is a ``list``, recurse into each element that is a
    ``dict`` or a ``list``; all other element types are copied as-is.
  - All other value types (str, int, float, bool, None, …) are copied as-is.
"""

from __future__ import annotations

_REDACTED = "*****"


def mask_secure_data(data: dict, secure_keys: set[str]) -> dict:
    """Return a deep-copy of *data* with every secure key's value replaced by ``'*****'``.

    Parameters
    ----------
    data:
        The source dictionary.  Must be a ``dict``; the function does not
        accept arbitrary types at the top level.
    secure_keys:
        Set of field names whose values must be redacted at every nesting level.

    Returns
    -------
    dict
        A new dictionary — the original *data* is never mutated.
    """
    result: dict = {}
    for key, value in data.items():
        if key in secure_keys:
            result[key] = _REDACTED
        elif isinstance(value, dict):
            result[key] = mask_secure_data(value, secure_keys)
        elif isinstance(value, list):
            result[key] = _mask_list(value, secure_keys)
        else:
            result[key] = value
    return result


def mask_secure_json(value: dict | list, secure_keys: set[str]) -> dict | list:
    """:func:`mask_secure_data` for a parsed JSON document, whose top level may be a list."""
    if isinstance(value, list):
        return _mask_list(value, secure_keys)
    return mask_secure_data(value, secure_keys)


def _mask_list(lst: list, secure_keys: set[str]) -> list:
    """Recursively process a list, masking any nested dicts or lists."""
    result: list = []
    for item in lst:
        if isinstance(item, dict):
            result.append(mask_secure_data(item, secure_keys))
        elif isinstance(item, list):
            result.append(_mask_list(item, secure_keys))
        else:
            result.append(item)
    return result


def public_safe_snapshot(context: dict, secure_keys: set[str]) -> dict:
    """Build the context snapshot shipped to external StepEvent consumers.

    Strips engine-internal keys (any ``_``-prefixed key — ``_session``, ``_db``,
    ``_last_error``, …) and then redacts every field declared ``secure: true``
    in a ``ModelDefinition``.  Use this anywhere a context snapshot leaves the
    process: SSE frames, the CLI test runner.

    A caller that needs the ``_``-prefixed diagnostic keys (a debug trace)
    should call ``mask_secure_data`` directly instead.
    """
    public = {k: v for k, v in context.items() if not k.startswith("_")}
    return mask_secure_data(public, secure_keys)
