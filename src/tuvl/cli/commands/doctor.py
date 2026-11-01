"""``tuvl check system`` — is the project healthy? Models, configuration, git and more; ``--live`` also calls each model once."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from tuvl import doctor

console = Console()

_MARK = {
    "ok": "[green]✓[/green]",
    "warn": "[yellow]![/yellow]",
    "fail": "[red]✗[/red]",
    "skip": "[dim]–[/dim]",
}


def _names(value: str | None, valid: list[str], option: str) -> list[str] | None:
    if value is None:
        return None
    names = [n.strip() for n in value.split(",") if n.strip()]
    unknown = [n for n in names if n not in valid]
    if unknown:
        raise typer.BadParameter(
            f"unknown group(s) {', '.join(unknown)}; choose from {', '.join(valid)}",
            param_hint=option,
        )
    return names


def _print(checks: list[doctor.Check], *, quiet: bool, verbose: bool) -> None:
    seen: list[str] = []
    for c in checks:
        if c.group not in seen:
            seen.append(c.group)
    for name in seen:
        rows = [c for c in checks if c.group == name]
        if quiet and all(c.status in ("ok", "skip") for c in rows):
            continue
        console.print(f"[bold]{name}[/bold]")
        for c in rows:
            if quiet and c.status in ("ok", "skip"):
                continue
            line = f"  {_MARK[c.status]} {escape(c.id)}"
            if c.detail and (verbose or c.status != "ok" or name in ("models", "storage")):
                line += f" — {escape(c.detail)}"
            elif c.detail and c.status == "ok":
                line += f" [dim]{escape(c.detail)}[/dim]"
            console.print(line)
            if c.hint and c.status in ("warn", "fail"):
                console.print(f"      [dim]{escape(c.hint)}[/dim]")
            if c.fix and c.status in ("warn", "fail"):
                console.print(f"      [dim]--fix: {escape(c.fix.label)}[/dim]")


def doctor_cmd(
    project_dir: Annotated[
        Path, typer.Option("--project-dir", "-d", help="tuvl project directory")
    ] = Path("."),
    live: Annotated[
        bool,
        typer.Option("--live", help="Also make one minimal call per model (spends a few tokens)"),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable report")] = False,
    only: Annotated[
        str | None, typer.Option("--only", help="Run only these check groups (comma-separated)")
    ] = None,
    skip: Annotated[
        str | None, typer.Option("--skip", help="Skip these check groups (comma-separated)")
    ] = None,
    strict: Annotated[
        bool, typer.Option("--strict", help="Exit 2 when there are warnings (and no failures)")
    ] = False,
    fix: Annotated[
        bool, typer.Option("--fix", help="Apply the safe fixes some checks offer, then re-check")
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Show only warnings and failures")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Show the detail of passing checks too")
    ] = False,
) -> None:
    """Check the project: configuration, models, storage, git and coding-agent files."""
    project = project_dir.resolve()
    valid = doctor.available_groups()
    chosen = _names(only, valid, "--only") or valid
    skipped = _names(skip, valid, "--skip") or []
    names = [n for n in chosen if n not in skipped]

    ctx = doctor.Context(project=project, live=live)
    checks = doctor.run(ctx, names)
    applied: list[str] = []
    if fix:
        for c in checks:
            if c.fix and c.status in ("warn", "fail"):
                c.fix.apply()
                applied.append(c.fix.label)
        if applied:
            ctx = doctor.Context(project=project, live=live)
            checks = doctor.run(ctx, names)

    summary = doctor.summarise(checks)
    healthy = summary.fail == 0
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "healthy": healthy,
                    "models": ctx.data.get("models", {}),
                    "storage": ctx.data.get("storage", {}),
                    "groups": names,
                    "summary": {
                        "ok": summary.ok,
                        "warn": summary.warn,
                        "fail": summary.fail,
                        "skip": summary.skip,
                    },
                    "checks": [
                        {
                            "group": c.group,
                            "id": c.id,
                            "status": c.status,
                            "detail": c.detail,
                            "hint": c.hint,
                            "fixable": c.fix is not None,
                        }
                        for c in checks
                    ],
                    "fixed": applied,
                },
                indent=2,
            )
        )
    else:
        for label in applied:
            console.print(f"[green]fixed[/green] {escape(label)}")
        _print(checks, quiet=quiet, verbose=verbose)
        console.print(
            f"\n{summary.ok} ok · {summary.warn} warning(s) · {summary.fail} failure(s)"
            + (f" · {summary.skip} skipped" if summary.skip else "")
        )
    if not healthy:
        raise typer.Exit(1)
    if strict and summary.warn:
        raise typer.Exit(2)
