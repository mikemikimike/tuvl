"""``tuvl storage``: runs without loading workflows, reports problems per store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tuvl.cli import app

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "storage").mkdir()
    (tmp_path / "storage" / "scratch.yaml").write_text(
        "kind: Storage\nversion: v1\nmetadata: {name: scratch}\nspec: {provider: local, root: ./blobs}\n"
    )
    (tmp_path / "storage" / "locked.yaml").write_text(
        "kind: Storage\nversion: v1\nmetadata: {name: locked}\n"
        "spec: {provider: s3, bucket: b, access_key: '${NEEDED_KEY}', secret_key: '${NEEDED_SECRET}'}\n"
    )
    return tmp_path


def test_check_reports_each_store(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEEDED_KEY", raising=False)
    res = runner.invoke(app, ["check", "storage", "-d", str(project), "--json"])
    assert res.exit_code == 1, res.output
    report = json.loads(res.output[res.output.index("{") :])
    assert report["healthy"] is False
    assert report["stores"]["scratch"]["ok"] is True
    assert [s["step"] for s in report["stores"]["scratch"]["steps"]] == [
        "list",
        "put",
        "head",
        "get",
        "delete",
    ]
    assert report["stores"]["locked"]["missing"] == ["NEEDED_KEY", "NEEDED_SECRET"]


def test_check_one_store_and_unknown_name(project: Path) -> None:
    ok = runner.invoke(app, ["check", "storage", "scratch", "-d", str(project)])
    assert ok.exit_code == 0 and "scratch" in ok.output
    unknown = runner.invoke(app, ["check", "storage", "nope", "-d", str(project)])
    assert unknown.exit_code == 1 and "No Storage named" in unknown.output


def test_a_broken_workflow_does_not_hide_the_stores(project: Path) -> None:
    (project / "workflows").mkdir()
    (project / "workflows" / "bad.yaml").write_text(
        "kind: Workflow\nversion: tuvl/v2\nmetadata: {name: bad}\nspec: {nonsense: true}\n"
    )
    res = runner.invoke(app, ["check", "storage", "scratch", "-d", str(project)])
    assert res.exit_code == 0, res.output
    assert "Traceback" not in res.output


def test_an_invalid_store_file_is_reported_not_a_traceback(project: Path) -> None:
    (project / "storage" / "bad.yaml").write_text(
        "kind: Storage\nversion: v1\nmetadata: {name: bad}\nspec: {provider: s3}\n"
    )
    res = runner.invoke(app, ["check", "storage", "-d", str(project)])
    assert res.exit_code == 1
    assert "needs 'bucket'" in res.output and "Traceback" not in res.output


def test_ls_lists_objects(project: Path) -> None:
    (project / "blobs").mkdir()
    (project / "blobs" / "a.txt").write_text("hello")
    res = runner.invoke(app, ["list", "objects", "scratch", "-d", str(project)])
    assert res.exit_code == 0 and "a.txt" in res.output
