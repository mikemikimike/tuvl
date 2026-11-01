"""Boot path for ALL project YAML — ``load_all_configs``.

First coverage for the loader (previously zero tests): multi-doc files,
malformed-YAML resilience, unknown/skip kinds, excluded-directory pruning,
and the missing-project-dir no-op.
"""

from __future__ import annotations

import pytest

from tuvl.contract import registry
from tuvl.contract.registry import WORKFLOWS as WORKFLOW_REGISTRY
from tuvl.core.config_loader import load_all_configs
from tuvl.core.models.loader import MODEL_REGISTRY


@pytest.fixture(autouse=True)
def _clean_registries():
    yield
    registry.clear()
    MODEL_REGISTRY.clear()


def _wf(name: str, path: str) -> str:
    return f"""\
kind: Workflow
version: tuvl/v2
metadata:
  name: {name}
spec:
  trigger:
    http: {{path: {path}, method: POST}}
  agents:
    - id: respond
      description: placeholder
      engine: pending
      routes: {{default: END}}
"""


def test_multi_doc_file_registers_every_document(tmp_path):
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "all.yaml").write_text(
        _wf("wf_a", "/api/a") + "---\n" + _wf("wf_b", "/api/b")
    )
    load_all_configs(tmp_path)
    assert {"wf_a", "wf_b"} <= set(WORKFLOW_REGISTRY)


def test_malformed_yaml_file_is_skipped_not_fatal(tmp_path):
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "broken.yaml").write_text("kind: Workflow\n  bad_indent: [unclosed")
    (wf_dir / "good.yaml").write_text(_wf("wf_good", "/api/good"))
    load_all_configs(tmp_path)  # must not raise
    assert "wf_good" in WORKFLOW_REGISTRY


def test_malformed_doc_inside_multi_doc_kills_only_that_file(tmp_path):
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    # yaml.safe_load_all parses lazily per document, but the loader materialises
    # the full list — one bad doc discards the whole file, siblings elsewhere load.
    (wf_dir / "mixed.yaml").write_text(_wf("wf_first", "/api/first") + "---\n: : :\n")
    (wf_dir / "solo.yaml").write_text(_wf("wf_solo", "/api/solo"))
    load_all_configs(tmp_path)
    assert "wf_solo" in WORKFLOW_REGISTRY
    assert "wf_first" not in WORKFLOW_REGISTRY


def test_unknown_and_docless_kinds_are_ignored(tmp_path):
    (tmp_path / "things").mkdir()
    (tmp_path / "things" / "odd.yaml").write_text(
        "kind: Spaceship\nmetadata: {name: x}\n---\njust_a_scalar\n---\nno_kind: here\n"
    )
    load_all_configs(tmp_path)  # must not raise
    assert WORKFLOW_REGISTRY == {}


def test_excluded_and_hidden_dirs_are_pruned(tmp_path):
    hidden = tmp_path / ".venv" / "workflows"
    hidden.mkdir(parents=True)
    hidden_wf = _wf("wf_hidden", "/api/hidden")
    (hidden / "wf.yaml").write_text(hidden_wf)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "wf.yaml").write_text(_wf("wf_nm", "/api/nm"))
    load_all_configs(tmp_path)
    assert "wf_hidden" not in WORKFLOW_REGISTRY
    assert "wf_nm" not in WORKFLOW_REGISTRY


def test_missing_project_dir_is_a_noop(tmp_path):
    load_all_configs(tmp_path / "does-not-exist")  # must not raise
    assert WORKFLOW_REGISTRY == {}
