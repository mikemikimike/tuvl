"""One minimal live call per model."""

from __future__ import annotations

import asyncio
from typing import Any


async def probe(name: str, spec: dict[str, Any]) -> str | None:
    """One minimal call to the model; ``None`` when it answered, else the error."""
    import httpx

    from tuvl.core.engine.templating import expand_env

    try:
        if spec.get("type") == "decision" and spec.get("provider") in ("laya", "jev"):
            base = str(expand_env(spec.get("api_base"), source=name) or "").rstrip("/")
            async with httpx.AsyncClient(timeout=10) as client:
                (await client.get(base + "/health")).raise_for_status()
            return None
        from tuvl import llm
        from tuvl.core.models.agent_models import resolve_call_params

        model, _timeout, extra = resolve_call_params({"model": name}, name)
        if spec.get("type") == "decision" and spec.get("model"):
            model = str(spec["model"])
        await llm.acompletion(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            timeout=20,
            **extra,
        )
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"


async def probe_all(names: list[str], registry: dict[str, Any]) -> list[str | None]:
    return list(
        await asyncio.gather(*(probe(n, dict(registry.get(n) or {"model": n})) for n in names))
    )
