"""The tuvl feather and name for the screen `tuvl` shows with no command, drawn in braille and block characters.

The feather is the dotted logo from Insight: every other dot of its lattice, so the dots show as points."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

COLOR = "#3fafd1"
#: below this terminal width the feather would not fit beside the name
MIN_WIDTH = 64

FEATHER = (
    "                ⢀  ",
    "             ⢀⢀⢄⢔  ",
    "          ⢀⢔⢕⢕⢕⢕⠕  ",
    "       ⢀⢔⢕⢕⠕⢕⢕⢕⠕⠁  ",
    "    ⢀⢔⢕⢕⢕⢕⢕⢑⢕⢕⠕⠁   ",
    "   ⢐⢕⢕⠕⢕⢕⢑⢕⢑⢕⠑⠁    ",
    "  ⢀⢕⢕⢕⢕⢑⢑⢕⠕⠑⠁      ",
    "  ⢐⢕⢕⢕⢕⠕⠁⠁         ",
    "⢀⠔⢁⠁               ",
    " ⠁ ⠁               ",
)

WORDMARK = (
    "  ▄▄█                             ███",
    "  ███                             ███",
    "███████  ███    ███ ▀██▄    ▄██▀  ███",
    "  ███    ███    ███  ███▄   ███   ███",
    "  ███    ███    ███   ███  ███    ███",
    "  ███    ███    ███    ███▄██▀    ███",
    "  ███    ███   ▄███    ▀████▀     ███",
    "  ▀████  ▀█████▀███     ▀███      ███",
)

MINI_FEATHER = (
    "       ⢀⠄ ",
    "   ⢀⢄⢔⢕⢕⠅ ",
    " ⢀⢔⢕⢕⢕⠕⠁  ",
    " ⢔⢕⢕⠕⠁    ",
    "⠐⠁        ",
)

MINI_WORDMARK = (
    " ▄▄                ██",
    "▀██▀ █   █ ▀█  ▄█  ██",
    " ██  █   █  ██ █▀  ██",
    " ██  █▄ ▄█   ███   ██",
    " ▀▀▀  ▀▀▀▀   ▀▀    ▀▀",
)

MALAYALAM = "തൂവൽ"
TAGLINE = "Intelligent Workflows. Deterministic Execution."


def brand() -> RenderableType:
    """The small mark for the terminal UI: the feather beside the name, and what the name means."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(no_wrap=True)
    grid.add_column(vertical="middle", no_wrap=True)
    grid.add_row(
        Text("\n".join(MINI_FEATHER), style=COLOR), Text("\n".join(MINI_WORDMARK), style="bold")
    )
    return Group(
        grid,
        Text(f"{MALAYALAM} (Thoo-val) · feather", style="dim"),
        Text(
            TAGLINE.replace(". ", ".\n"), style="bold white"
        ),  # two lines: the side panel is narrow
    )


def header(version: str, width: int) -> RenderableType:
    """The feather beside the name, the tagline below; the name alone on a narrow terminal."""
    name = Text("\n".join(WORDMARK), style="bold")
    tagline = Text.assemble((TAGLINE, "bold white"), (f"  v{version}", "dim"))
    if width < MIN_WIDTH:
        return Group(name, Text(""), tagline, Text(""))
    grid = Table.grid(padding=(0, 3))
    grid.add_column(no_wrap=True)
    grid.add_column(vertical="middle", no_wrap=True)
    side = Group(name, Text(""), Text(f"{MALAYALAM} (Thoo-val) · feather", style="dim"))
    grid.add_row(Text("\n".join(FEATHER), style=COLOR), side)
    return Group(grid, Text(""), tagline, Text(""))
