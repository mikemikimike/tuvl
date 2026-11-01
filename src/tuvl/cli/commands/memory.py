"""``tuvl prune memory`` — erase what agents remember: one owner's memories, or everything older than an age."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

console = Console()


def prune_memory_cmd(
    collection: Annotated[str, typer.Argument(help="The memory collection.")],
    key: Annotated[
        str | None, typer.Option("--key", "-k", help="Erase every memory of this owner.")
    ] = None,
    older_than: Annotated[
        str | None, typer.Option("--older-than", help="Erase memories older than this (30d, 12h).")
    ] = None,
    project_dir: Annotated[
        Path, typer.Option("--project-dir", "-d", help="Project directory.", file_okay=False)
    ] = Path("."),
) -> None:
    """Erase memories: all of one owner's (--key), or those older than an age (--older-than). Not both."""
    from tuvl.contract.schema import duration_seconds

    if (key is None) == (older_than is None):
        console.print("[red]Give exactly one of --key or --older-than.[/red]")
        raise typer.Exit(2)
    age: timedelta | None = None
    if older_than is not None:
        try:
            age = timedelta(seconds=duration_seconds(older_than))
        except ValueError as exc:
            console.print(f"[red]{escape(str(exc))}[/red]")
            raise typer.Exit(2) from exc

    from tuvl.cli.commands.db import _ensure_project_loaded

    _ensure_project_loaded(project_dir)
    from tuvl.core.config import settings
    from tuvl.core.datasources import postgres
    from tuvl.runtime import memory

    datasource = settings.vector_datasource or postgres._PRIMARY_DS

    async def run() -> int:
        async with postgres.get_session_factory(datasource, True)() as session:
            if key is not None:
                removed = await memory.forget(session, collection, key)
            else:
                assert age is not None
                removed = await memory.expire(session, collection, age)
            await session.commit()
            return removed

    removed = asyncio.run(run())
    what = f"of '{key}'" if key is not None else f"older than {older_than}"
    console.print(
        f"Erased {removed} memor{'y' if removed == 1 else 'ies'} {what} in '{collection}'."
    )
