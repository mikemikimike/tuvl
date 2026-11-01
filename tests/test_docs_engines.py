"""README.md and AGENTS.md must list every engine in the closed set."""

import re
from pathlib import Path

from tuvl.contract.schema import ENGINES

ROOT = Path(__file__).resolve().parents[1]


def test_readme_engine_table_lists_every_engine() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"^\| `(\w+)` \|", text, flags=re.M))
    assert set(ENGINES) <= listed, f"README engine table misses {set(ENGINES) - listed}"


def test_agents_closed_set_lists_every_engine() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    match = re.search(r"Engines: `([^`]+)`", text)
    assert match, "AGENTS.md has no 'Engines: `...`' line"
    assert set(match.group(1).split()) == set(ENGINES)
