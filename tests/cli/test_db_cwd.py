"""Regression tests for TD-22: ``tuvl db`` must not chdir the process.

``tuvl db generate-rls -d <project> --out <file>`` used to
``os.chdir(project_dir)`` before resolving ``--out``, so relative output
paths silently landed inside the project directory instead of the
invoker's cwd. Fixed by setting ``TUVL_PROJECT_DIR`` (matching the pattern
already used by ``run.py`` / ``test.py``) instead of chdir'ing, and by
resolving ``--out`` against the invoker's cwd up front.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tuvl.cli.commands import db as db_mod

runner = CliRunner()


def _stub_rls(monkeypatch: pytest.MonkeyPatch) -> None:
    import tuvl.core.datasources.rls as rls_mod

    monkeypatch.setattr(rls_mod, "tenant_table_names", lambda: ["accounts"])
    monkeypatch.setattr(rls_mod, "generate_rls_sql", lambda: "-- sql --\n")


def test_generate_rls_out_resolves_against_invoker_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--out`` must be resolved against the invoker's cwd, not inside
    ``--project-dir`` (the old ``os.chdir`` made it land in the wrong
    place)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    invoker_cwd = tmp_path / "invoker"
    invoker_cwd.mkdir()

    monkeypatch.setattr(db_mod, "_ensure_project_loaded", lambda project_dir: None)
    _stub_rls(monkeypatch)
    monkeypatch.chdir(invoker_cwd)

    result = runner.invoke(
        db_mod.db_app,
        ["generate-rls", "--project-dir", str(project_dir), "--out", "rls.sql"],
    )

    assert result.exit_code == 0, result.output
    assert (invoker_cwd / "rls.sql").exists()
    assert not (project_dir / "rls.sql").exists()


def test_generate_rls_does_not_chdir_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tuvl db`` must never mutate the process cwd — every other command
    signals the project root via ``TUVL_PROJECT_DIR`` instead."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    invoker_cwd = tmp_path / "invoker"
    invoker_cwd.mkdir()

    monkeypatch.setattr(db_mod, "_ensure_project_loaded", lambda project_dir: None)
    _stub_rls(monkeypatch)
    monkeypatch.chdir(invoker_cwd)
    before = os.getcwd()

    result = runner.invoke(
        db_mod.db_app,
        ["generate-rls", "--project-dir", str(project_dir), "--out", "rls.sql"],
    )

    assert result.exit_code == 0, result.output
    assert os.getcwd() == before


def test_ensure_project_loaded_sets_env_var_not_chdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_ensure_project_loaded`` must set ``TUVL_PROJECT_DIR`` (matching
    the pattern in ``run.py`` / ``test.py``) instead of chdir'ing, and (per
    TD-42) must update the already-constructed ``settings`` singleton in
    place so ``settings.project_dir`` reflects the requested project for the
    rest of the process rather than the value captured at import time."""
    from tuvl.core.config import settings

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    monkeypatch.delenv("TUVL_PROJECT_DIR", raising=False)
    # Registers a teardown revert for ``settings.tuvl_project_dir`` so this
    # test's tmp_path project doesn't leak into later tests — the function
    # under test mutates it directly (not via monkeypatch).
    monkeypatch.setattr(settings, "tuvl_project_dir", settings.tuvl_project_dir)
    monkeypatch.setattr(db_mod.asyncio, "run", lambda coro: coro.close())
    before = os.getcwd()

    db_mod._ensure_project_loaded(project_dir)

    assert os.environ.get("TUVL_PROJECT_DIR") == str(project_dir.resolve())
    assert settings.project_dir == project_dir.resolve()
    assert os.getcwd() == before


def test_ensure_project_loaded_populates_model_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TD-42 regression: ``_ensure_project_loaded`` must actually load the
    target project's configs (``load_all_configs()``) so ``MODEL_REGISTRY``
    is populated — previously it only ran ``run_pre_flight()``, which reads
    already-populated registries but never populates them itself, so
    ``generate-rls`` silently emitted only the hardcoded system tables."""
    import yaml

    from tuvl.core.config import settings
    from tuvl.core.models.loader import MODEL_REGISTRY

    project_dir = tmp_path / "project"
    (project_dir / "models").mkdir(parents=True)
    (project_dir / "models" / "candidate.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": "ModelDefinition",
                "metadata": {"name": "TdCandidate"},
                "spec": {
                    "tablename": "td42_candidates",
                    "fields": [
                        {"name": "id", "type": "uuid", "primary_key": True},
                        {"name": "name", "type": "string", "required": True},
                    ],
                },
            }
        )
    )

    monkeypatch.delenv("TUVL_PROJECT_DIR", raising=False)
    monkeypatch.setattr(settings, "tuvl_project_dir", settings.tuvl_project_dir)
    # No datasource configured, so run_pre_flight() no-ops to single_tenant
    # without needing a live DB — let it actually run.
    db_mod._ensure_project_loaded(project_dir)

    assert "TdCandidate" in MODEL_REGISTRY
