"""multipart/form-data triggers: files are stored at the edge and the run receives references."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from tuvl.api.runs import router
from tuvl.api.triggers import mount_triggers, trigger_openapi
from tuvl.contract.schema import WorkflowDocument
from tuvl.core.auth.token import mint_token
from tuvl.core.config import settings
from tuvl.runtime.code import AGENT_REGISTRY
from tuvl.runtime.host import RuntimeHost, set_host
from tuvl.storage import STORE_REGISTRY, close_all, register_store_from_dict

# minted at import: must outlive a full run of the suite, which takes ~10 minutes on a loaded runner
_TTL = 24 * 3600

ALICE = {"Authorization": f"Bearer {mint_token('alice', [], [], ttl_seconds=_TTL)}"}


def _intake(**upload: Any) -> WorkflowDocument:
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "intake"},
            "spec": {
                "trigger": {
                    "http": {
                        "path": "/t/intake",
                        "public": True,
                        "upload": {
                            "store": "inbox",
                            "prefix": "in/",
                            "max_bytes": 64,
                            "max_files": 3,
                            "accept": ["text/*", "application/pdf"],
                            **upload,
                        },
                    },
                    "input": {
                        "doc": "file",
                        "extras": "list[file]?",
                        "note": "str?",
                        "qty": "int?",
                        "tags": "list[str]?",
                    },
                },
                "agents": [
                    {
                        "id": "intake",
                        "description": "report what arrived",
                        "engine": "code",
                        "code": {"run": "intake"},
                        "inputs": {
                            "doc": "file",
                            "extras": "list[file]?",
                            "note": "str?",
                            "qty": "int?",
                            "tags": "list[str]?",
                        },
                        "outputs": {"report": "json"},
                        "routes": {"default": "END", "error": "END.failed"},
                    }
                ],
                "outputs": {
                    "default": {"body": "{{ report }}"},
                    "failed": {"status": 500},
                },
            },
        }
    )


async def _intake_agent(inp: Any, ctx: Any) -> dict[str, Any]:
    body = await ctx.read_file(inp.doc)
    return {
        "report": {
            "name": inp.doc.name,
            "key": inp.doc.key,
            "size": inp.doc.size,
            "sha256": inp.doc.sha256,
            "type": inp.doc.content_type,
            "read": body.decode(),
            "extras": len(inp.extras or []),
            "note": inp.note,
            "qty": inp.qty,
            "tags": inp.tags,
        }
    }


@pytest.fixture
def blobs(tmp_path: Path) -> Iterator[Path]:
    STORE_REGISTRY.clear()
    register_store_from_dict(
        {
            "kind": "Storage",
            "metadata": {"name": "inbox"},
            "spec": {"provider": "local", "root": str(tmp_path / "blobs")},
        }
    )
    yield tmp_path / "blobs"
    STORE_REGISTRY.clear()


@pytest.fixture
async def client(
    pg_engine: AsyncEngine, blobs: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setattr(settings, "tuvl_dev_mode", False)
    monkeypatch.setitem(AGENT_REGISTRY, "intake", _intake_agent)
    workflows = {"intake": _intake()}
    runtime = RuntimeHost(pg_engine, workflows=workflows, role="api")
    set_host(runtime)
    app = FastAPI()
    app.include_router(router)
    mount_triggers(app, workflows)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    await runtime.stop()
    await close_all()
    set_host(None)


def stored(blobs: Path) -> list[Path]:
    return sorted(
        p for p in blobs.rglob("*") if p.is_file() and p.relative_to(blobs).parts[0] != ".meta"
    )


async def test_a_file_is_stored_and_the_run_receives_its_reference(
    client: httpx.AsyncClient, blobs: Path
) -> None:
    res = await client.post(
        "/t/intake",
        files={"doc": ("../../my notes.txt", b"hello", "text/plain")},
        data={"note": "hi", "qty": "3", "tags": '["a", "b"]'},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "my notes.txt" and body["size"] == 5 and body["type"] == "text/plain"
    assert body["read"] == "hello" and body["note"] == "hi"
    assert body["qty"] == 3 and body["tags"] == ["a", "b"]
    assert body["key"].startswith("in/") and body["key"].endswith("/my_notes.txt")
    [path] = stored(blobs)
    assert path.read_bytes() == b"hello" and blobs in path.parents
    assert body["sha256"] == hashlib.sha256(b"hello").hexdigest()


async def test_several_files_into_a_list_input(client: httpx.AsyncClient, blobs: Path) -> None:
    res = await client.post(
        "/t/intake",
        files=[
            ("doc", ("a.txt", b"one", "text/plain")),
            ("extras", ("b.txt", b"two", "text/plain")),
            ("extras", ("c.pdf", b"%PDF", "application/pdf")),
        ],
    )
    assert res.status_code == 200 and res.json()["extras"] == 2
    assert len(stored(blobs)) == 3


@pytest.mark.parametrize(
    ("files", "status"),
    [
        ({"doc": ("a.png", b"x", "image/png")}, 415),
        ({"doc": ("a.txt", b"x" * 65, "text/plain")}, 413),
        ({"other": ("a.txt", b"x", "text/plain")}, 422),
    ],
)
async def test_a_refused_upload_stores_nothing(
    client: httpx.AsyncClient, blobs: Path, files: dict[str, Any], status: int
) -> None:
    res = await client.post("/t/intake", files=files)
    assert res.status_code == status, res.text
    assert stored(blobs) == []


async def test_two_files_for_a_single_file_input_are_refused(
    client: httpx.AsyncClient, blobs: Path
) -> None:
    res = await client.post(
        "/t/intake",
        files=[("doc", ("a.txt", b"1", "text/plain")), ("doc", ("b.txt", b"2", "text/plain"))],
    )
    assert res.status_code == 422 and stored(blobs) == []


async def test_files_stored_for_a_run_that_does_not_start_are_deleted(
    client: httpx.AsyncClient, blobs: Path
) -> None:
    res = await client.post(
        "/t/intake",
        files={"doc": ("a.txt", b"hello", "text/plain")},
        data={"qty": "many"},
    )
    assert res.status_code == 422
    assert stored(blobs) == []


async def test_a_file_cannot_be_named_in_json_or_query(
    client: httpx.AsyncClient, blobs: Path
) -> None:
    ref = {
        "store": "inbox",
        "key": "someone/elses.txt",
        "name": "x",
        "size": 1,
        "content_type": "text/plain",
        "sha256": "0" * 64,
    }
    res = await client.post("/t/intake", json={"doc": ref})
    assert res.status_code == 422 and "multipart" in res.text
    res = await client.post("/api/workflows/intake/runs", json={"input": {"doc": ref}})
    assert res.status_code == 422 and "multipart" in res.text


async def test_the_caller_is_authenticated_before_the_body_is_stored(
    pg_engine: AsyncEngine, blobs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "tuvl_dev_mode", False)
    monkeypatch.setitem(AGENT_REGISTRY, "intake", _intake_agent)
    doc = _intake()
    assert doc.spec.trigger.http is not None
    doc.spec.trigger.http.public = False
    workflows = {"intake": doc}
    runtime = RuntimeHost(pg_engine, workflows=workflows, role="api")
    set_host(runtime)
    app = FastAPI()
    mount_triggers(app, workflows)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        files = {"doc": ("a.txt", b"hello", "text/plain")}
        assert (await c.post("/t/intake", files=files)).status_code == 401
        assert stored(blobs) == []
        ok = await c.post("/t/intake", files=files, headers=ALICE)
        assert ok.status_code == 200
    await runtime.stop()
    set_host(None)


async def test_multipart_on_a_route_without_upload_is_refused(
    pg_engine: AsyncEngine, blobs: Path
) -> None:
    doc = _intake()
    assert doc.spec.trigger.http is not None
    doc.spec.trigger.http.upload = None
    workflows = {"intake": doc}
    runtime = RuntimeHost(pg_engine, workflows=workflows, role="api")
    set_host(runtime)
    app = FastAPI()
    mount_triggers(app, workflows)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        res = await c.post("/t/intake", files={"doc": ("a.txt", b"x", "text/plain")})
        assert res.status_code == 415
    await runtime.stop()
    set_host(None)


def test_openapi_describes_the_multipart_body() -> None:
    op = trigger_openapi(_intake())
    assert list(op["requestBody"]["content"]) == ["multipart/form-data"]
    schema = op["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert schema["properties"]["doc"] == {"type": "string", "format": "binary"}
    assert schema["properties"]["extras"]["items"] == {"type": "string", "format": "binary"}
    assert schema["required"] == ["doc"]
    assert schema["properties"]["note"]["anyOf"][0] == {"type": "string"}


async def test_the_runs_endpoint_takes_the_same_multipart_body(
    client: httpx.AsyncClient, blobs: Path
) -> None:
    res = await client.post(
        "/api/workflows/intake/runs",
        files={"doc": ("a.txt", b"hello", "text/plain")},
        data={"note": "via runs"},
    )
    assert res.status_code == 200 and res.json()["note"] == "via runs"
    assert len(stored(blobs)) == 1
    bad = await client.post("/api/workflows/intake/runs", content=b"{not json")
    assert bad.status_code == 400
