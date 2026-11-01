"""The artifact subsystem: file loading, the registry, ``artifact://``
resolution, precedence, the 512 KB cap, dev mtime refresh, the boot ref pass,
and validator coverage."""

from __future__ import annotations

import pytest
import yaml

from tuvl.core.artifacts.kinds import MAX_ARTIFACT_BYTES
from tuvl.core.artifacts.loader import (
    _register_artifact_from_dict,
    load_file_artifacts,
    read_prose_artifact,
)
from tuvl.core.artifacts.registry import (
    ARTIFACT_REGISTRY,
    ArtifactResolutionError,
    parse_ref,
    register_artifact,
    resolve_prose,
    resolve_structured,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    ARTIFACT_REGISTRY.clear()
    yield
    ARTIFACT_REGISTRY.clear()


def _write_md(tmp_path, fname, name, type_="prompt", version=1, body="Hello {{ who }}"):
    d = tmp_path / "artifacts"
    d.mkdir(exist_ok=True)
    front = yaml.safe_dump({"name": name, "type": type_, "version": version})
    p = d / fname
    p.write_text(f"---\n{front}---\n\n{body}")
    return p


# ── front-matter parsing + file loading ───────────────────────────────────────


def test_load_prose_artifact_from_md(tmp_path):
    _write_md(tmp_path, "triage.md", "triage-system", "prompt", 3, "You are a triager.")
    load_file_artifacts(tmp_path)
    entry = ARTIFACT_REGISTRY["triage-system"]
    assert entry.type == "prompt"
    assert entry.latest == 3
    assert entry.versions[3].content == "You are a triager."
    assert entry.versions[3].source == "file"
    assert entry.versions[3].content_hash


def test_md_without_front_matter_rejected(tmp_path):
    d = tmp_path / "artifacts"
    d.mkdir()
    (d / "bad.md").write_text("no front matter here")
    with pytest.raises(ValueError, match="front-matter"):
        read_prose_artifact(d / "bad.md")


def test_md_with_structured_type_rejected(tmp_path):
    p = _write_md(tmp_path, "g.md", "g", type_="guardrail")
    with pytest.raises(ValueError, match="must be one of"):
        read_prose_artifact(p)


def test_size_cap_enforced(tmp_path):
    _write_md(tmp_path, "big.md", "big", body="x" * (MAX_ARTIFACT_BYTES + 1))
    with pytest.raises(ValueError, match="content cap"):
        read_prose_artifact(tmp_path / "artifacts" / "big.md")


def test_multiple_versions_coexist(tmp_path):
    _write_md(tmp_path, "p_v1.md", "p", version=1, body="one")
    _write_md(tmp_path, "p_v2.md", "p", version=2, body="two")
    load_file_artifacts(tmp_path)
    entry = ARTIFACT_REGISTRY["p"]
    assert sorted(entry.versions) == [1, 2]
    assert entry.latest == 2


# ── structured (kind: Artifact) envelope ─────────────────────────────────────


def test_structured_artifact_registers():
    _register_artifact_from_dict(
        {
            "kind": "Artifact",
            "metadata": {"name": "firecrawl", "description": "MCP server"},
            "spec": {"type": "mcp", "transport": "stdio", "command": "uvx"},
        },
        "firecrawl.yaml",
    )
    entry = ARTIFACT_REGISTRY["firecrawl"]
    assert entry.type == "mcp"
    assert entry.versions[1].content == {"transport": "stdio", "command": "uvx"}


def test_structured_envelope_rejects_prose_types():
    with pytest.raises(ValueError, match="front-matter .md"):
        _register_artifact_from_dict(
            {
                "kind": "Artifact",
                "metadata": {"name": "p"},
                "spec": {"type": "prompt", "content": "x"},
            },
            "p.yaml",
        )


def test_structured_envelope_requires_spec():
    with pytest.raises(ValueError, match="no 'spec' block"):
        _register_artifact_from_dict({"kind": "Artifact", "metadata": {"name": "x"}}, "x.yaml")


# ── refs + resolution ─────────────────────────────────────────────────────────


def test_parse_ref_forms():
    assert parse_ref("artifact://name") == ("name", None)
    assert parse_ref("artifact://name@3") == ("name", 3)
    with pytest.raises(ArtifactResolutionError, match="malformed"):
        parse_ref("artifact://bad name")


def test_resolve_prose_inline_passthrough():
    assert resolve_prose("just text", site="prompt", where="t") == "just text"


def test_resolve_prose_ref_pinned_and_floating():
    register_artifact(name="p", type_="prompt", version=1, content="one", source="file")
    register_artifact(name="p", type_="prompt", version=2, content="two", source="file")
    assert resolve_prose("artifact://p@1", site="prompt", where="t") == "one"
    assert resolve_prose("artifact://p", site="prompt", where="t") == "two"  # latest


def test_resolve_floating_skips_disabled_latest():
    register_artifact(name="p", type_="prompt", version=1, content="one", source="file")
    register_artifact(
        name="p", type_="prompt", version=2, content="two", source="file", enabled=False
    )
    assert resolve_prose("artifact://p", site="prompt", where="t") == "one"
    with pytest.raises(ArtifactResolutionError, match="disabled"):
        resolve_prose("artifact://p@2", site="prompt", where="t")


def test_resolve_type_compat_enforced():
    register_artifact(name="s", type_="skill", version=1, content="skill text", source="file")
    with pytest.raises(ArtifactResolutionError, match="accepts"):
        resolve_prose("artifact://s", site="system", where="t")
    # steering accepts steering|prompt but not skill
    with pytest.raises(ArtifactResolutionError, match="accepts"):
        resolve_prose("artifact://s", site="steering", where="t")
    assert resolve_prose("artifact://s", site="skills", where="t") == "skill text"


def test_resolve_unknown_name_errors():
    with pytest.raises(ArtifactResolutionError, match="unknown artifact"):
        resolve_prose("artifact://ghost", site="prompt", where="t")


def test_resolve_structured_type_checked():
    register_artifact(
        name="fc", type_="mcp", version=1, content={"transport": "stdio"}, source="file"
    )
    assert resolve_structured("artifact://fc", site="mcp.server", where="t") == {
        "transport": "stdio"
    }
    with pytest.raises(ArtifactResolutionError, match="accepts"):
        resolve_structured("artifact://fc", site="guardrails", where="t")


# ── precedence: project file → db → external ──────────────────────────────────


def test_file_source_shadows_db_source():
    register_artifact(name="p", type_="prompt", version=1, content="file wins", source="file")
    register_artifact(name="p", type_="prompt", version=1, content="db version", source="db")
    assert resolve_prose("artifact://p", site="prompt", where="t") == "file wins"


def test_db_source_replaced_by_file_source():
    register_artifact(name="p", type_="prompt", version=1, content="db version", source="db")
    register_artifact(name="p", type_="prompt", version=1, content="file wins", source="file")
    assert resolve_prose("artifact://p", site="prompt", where="t") == "file wins"


# ── dev mtime refresh ─────────────────────────────────────────────────────────


def test_file_edit_applies_without_restart(tmp_path):
    p = _write_md(tmp_path, "p.md", "p", body="before")
    load_file_artifacts(tmp_path)
    assert resolve_prose("artifact://p", site="prompt", where="t") == "before"
    front = yaml.safe_dump({"name": "p", "type": "prompt", "version": 1})
    p.write_text(f"---\n{front}---\n\nafter")
    import os

    os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 5))
    assert resolve_prose("artifact://p", site="prompt", where="t") == "after"


# ── engine integration: agent fields resolve refs ─────────────────────────────


# ── boot ref pass ─────────────────────────────────────────────────────────────


# ── validator coverage ────────────────────────────────────────────────────────
