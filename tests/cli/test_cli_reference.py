"""docs/cli-reference.md lists every command and option of the CLI: it is generated, so it must be current."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tuvl.extras import toolchain_installed

ROOT = Path(__file__).resolve().parents[2]


def _generator():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "gen_cli_reference", ROOT / "scripts" / "gen_cli_reference.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pytestmark = pytest.mark.skipif(
    not toolchain_installed(), reason="the page documents the toolchain commands too"
)


def test_the_reference_page_is_up_to_date() -> None:
    gen = _generator()
    page = ROOT / "docs" / "cli-reference.md"
    assert page.read_text() == gen.render(), "run: python scripts/gen_cli_reference.py"


def test_every_command_and_every_option_is_on_the_page() -> None:
    gen = _generator()
    text = (ROOT / "docs" / "cli-reference.md").read_text()
    commands = gen._commands()
    assert len(commands) > 50
    for path, cmd in commands.items():
        assert f"### `tuvl {path}`" in text, path
        for p in cmd.params:
            if getattr(p, "param_type_name", "") != "option":
                continue
            flags = [f for f in p.opts if f.startswith("-")]
            if flags and flags[0] not in ("-h", "--help"):
                assert any(
                    f"`{f}`" in text or f"{f}`" in text or f"`{f}/" in text for f in flags
                ), (path, flags)


def test_every_command_says_what_it_does() -> None:
    gen = _generator()
    blank = [path for path, cmd in gen._commands().items() if not (cmd.help or "").strip()]
    assert blank == []
