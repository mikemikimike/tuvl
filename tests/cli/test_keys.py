"""`tuvl keys generate` — signing-key printing and .env writing."""

from __future__ import annotations

import stat
from pathlib import Path

from typer.testing import CliRunner

from tuvl.cli import app

runner = CliRunner()

_ENV_VAR = "TUVL_SIGNING_KEY"


def test_generate_prints_key_without_write(tmp_path: Path) -> None:
    res = runner.invoke(app, ["generate", "key"])
    assert res.exit_code == 0, res.output
    assert _ENV_VAR in res.output
    assert not (tmp_path / ".env").exists()


def test_generate_write_creates_fresh_env(tmp_path: Path) -> None:
    res = runner.invoke(app, ["generate", "key", "--write", "-d", str(tmp_path)])
    assert res.exit_code == 0, res.output

    env_path = tmp_path / ".env"
    assert env_path.exists()
    content = env_path.read_text()
    assert content.count(_ENV_VAR) == 1
    assert content.startswith(f"{_ENV_VAR}=")
    key_value = content.split("=", 1)[1].strip()
    assert len(key_value) == 64
    int(key_value, 16)  # valid hex


def test_generate_write_sets_owner_only_perms(tmp_path: Path) -> None:
    res = runner.invoke(app, ["generate", "key", "--write", "-d", str(tmp_path)])
    assert res.exit_code == 0, res.output
    mode = stat.S_IMODE((tmp_path / ".env").stat().st_mode)
    assert mode == 0o600


def test_generate_write_preserves_other_vars(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\nBAZ=qux\n")

    res = runner.invoke(app, ["generate", "key", "--write", "-d", str(tmp_path)])
    assert res.exit_code == 0, res.output

    content = env_path.read_text()
    assert "FOO=bar" in content
    assert "BAZ=qux" in content
    assert _ENV_VAR in content


def test_generate_write_appends_after_existing_content(tmp_path: Path) -> None:
    """Pin the actual append behaviour: new key is appended, unrelated lines untouched."""
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\n")

    runner.invoke(app, ["generate", "key", "--write", "-d", str(tmp_path)])

    lines = env_path.read_text().splitlines()
    assert lines[0] == "FOO=bar"
    assert any(line.startswith(f"{_ENV_VAR}=") for line in lines[1:])


def test_generate_write_refuses_overwrite_without_force(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(f"{_ENV_VAR}=deadbeef\n")

    res = runner.invoke(app, ["generate", "key", "--write", "-d", str(tmp_path)])
    assert res.exit_code == 1
    assert "--force" in res.output
    # Original value untouched.
    assert env_path.read_text() == f"{_ENV_VAR}=deadbeef\n"


def test_generate_write_force_overwrites_existing_key(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(f"OTHER=1\n{_ENV_VAR}=deadbeef\n")

    res = runner.invoke(app, ["generate", "key", "--write", "--force", "-d", str(tmp_path)])
    assert res.exit_code == 0, res.output

    content = env_path.read_text()
    assert "OTHER=1" in content
    assert content.count(_ENV_VAR) == 1
    assert "deadbeef" not in content


def test_generate_write_force_replaces_only_the_key_line_in_place(tmp_path: Path) -> None:
    """--force rewrites the matching line in place rather than appending a duplicate."""
    env_path = tmp_path / ".env"
    env_path.write_text(f"FOO=1\n{_ENV_VAR}=deadbeef\nBAR=2\n")

    runner.invoke(app, ["generate", "key", "--write", "--force", "-d", str(tmp_path)])

    lines = env_path.read_text().splitlines()
    assert lines[0] == "FOO=1"
    assert lines[1].startswith(f"{_ENV_VAR}=")
    assert lines[2] == "BAR=2"
