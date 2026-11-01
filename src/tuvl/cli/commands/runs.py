"""``tuvl runs`` — inspect runs on a server, pin them as fixtures, replay
fixtures locally.

``list``/``get``/``tail``/``pin`` talk to a running server (``--url``,
``--token``; ``TUVL_URL`` / ``TUVL_TOKEN`` work too). ``tail`` follows a run's
SSE stream (it replaces ``stream-watch``) and can start the run first.
``replay`` is offline: it re-runs a pinned journal through the local project
and checks the end and output match the recording (engine-change
equivalence, spec §19.5).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from tuvl.core.config import use_project

console = Console()
runs_app = typer.Typer(help="Inspect, follow, pin and replay runs.", no_args_is_help=True)

Url = Annotated[str, typer.Option("--url", "-u", envvar="TUVL_URL", help="tuvl server base URL")]
Token = Annotated[
    str | None,
    typer.Option(
        "--token", "-t", envvar="TUVL_TOKEN", help="Bearer token (a run you started, or iam:admin)"
    ),
]
DEFAULT_URL = "http://localhost:8885"

_STYLES = {
    "run_completed": "bold green",
    "run_failed": "bold red",
    "run_aborted": "bold red",
    "agent_started": "cyan",
    "agent_completed": "blue",
    "approval_requested": "bold yellow",
    "paused": "yellow",
}
_FAILED = ("run_failed", "run_aborted")


def _client(url: str, token: str | None) -> httpx.Client:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.Client(
        base_url=url.rstrip("/"), headers=headers, timeout=httpx.Timeout(30.0, read=None)
    )


def _ok(response: httpx.Response, expected: int = 200) -> Any:
    if response.status_code != expected:
        console.print(f"[bold red]{response.status_code}[/bold red] {escape(response.text)}")
        raise typer.Exit(1)
    return response.json()


def parse_sse(lines: Iterable[str]) -> Iterable[dict[str, Any]]:
    data: list[str] = []
    for line in lines:
        if line.startswith("data: "):
            data.append(line[6:])
        elif not line.strip() and data:
            yield json.loads("\n".join(data))
            data = []
    if data:
        yield json.loads("\n".join(data))


def render(event: dict[str, Any]) -> str:
    kind = event["type"]
    payload = event.get("payload") or {}
    where = f" [dim]{escape(event['agent_id'])}[/dim]" if event.get("agent_id") else ""
    detail = ""
    if kind == "agent_completed":
        detail = f" → {escape(str(payload.get('signal')))}"
        if payload.get("error_type"):
            detail += f" [red]{escape(payload['error_type'])}: {escape(str(payload.get('message')))}[/red]"
    elif kind == "run_completed":
        detail = f" END.{escape(str(payload.get('end')))} ({payload.get('status')})"
    elif kind in _FAILED:
        detail = f" [red]{escape(str(payload.get('error_type')))}: {escape(str(payload.get('message')))}[/red]"
    elif kind == "approval_requested":
        detail = f" {escape(str(payload.get('title')))}"
    tokens = f" [dim]{event['tokens']} tok[/dim]" if event.get("tokens") else ""
    style = _STYLES.get(kind, "white")
    return f"[dim]{event['seq']:>4}[/dim] [{style}]{kind}[/{style}]{where}{detail}{tokens}"


@runs_app.command("list")
def list_cmd(
    workflow: Annotated[
        str | None, typer.Option("--workflow", "-w", help="Only this workflow")
    ] = None,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Only this status")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
    as_json: Annotated[bool, typer.Option("--json")] = False,
    url: Url = DEFAULT_URL,
    token: Token = None,
) -> None:
    """Recent runs, newest first."""
    params: dict[str, Any] = {"limit": limit}
    if workflow:
        params["workflow"] = workflow
    if status:
        params["status"] = status
    with _client(url, token) as client:
        runs = _ok(client.get("/api/runs", params=params))
    if as_json:
        print(json.dumps(runs, indent=2))
        return
    table = Table("run", "workflow", "status", "end", "tokens", "created")
    for run in runs:
        table.add_row(
            run["run_id"],
            run["workflow"],
            run["status"],
            run.get("end") or "",
            str(run.get("tokens_used") or 0),
            run.get("created_at") or "",
        )
    console.print(table)


@runs_app.command("get")
def get_cmd(
    run_id: Annotated[str, typer.Argument(help="The run")],
    url: Url = DEFAULT_URL,
    token: Token = None,
) -> None:
    """One run: status, end, output, cost (JSON)."""
    with _client(url, token) as client:
        print(json.dumps(_ok(client.get(f"/api/runs/{run_id}")), indent=2))


@runs_app.command("tail")
def tail_cmd(
    run_id: Annotated[str | None, typer.Argument(help="The run to follow")] = None,
    workflow: Annotated[
        str | None, typer.Option("--workflow", "-w", help="Start a run of this workflow")
    ] = None,
    payload: Annotated[
        str, typer.Option("--payload", "-p", help="Input for --workflow, as JSON")
    ] = "{}",
    url: Url = DEFAULT_URL,
    token: Token = None,
) -> None:
    """Follow a run's events until it ends (or start one with --workflow). Exits 1 if it fails."""
    if (workflow is None) == (run_id is None):
        console.print("[bold red]Error:[/bold red] give a run id or --workflow, not both")
        raise typer.Exit(2)
    with _client(url, token) as client:
        if run_id is None:
            try:
                body = {"input": json.loads(payload)}
            except json.JSONDecodeError as exc:
                console.print(f"[bold red]Error:[/bold red] --payload is not valid JSON: {exc}")
                raise typer.Exit(1) from exc
            run_id = _ok(
                client.post(f"/api/workflows/{workflow}/runs", params={"wait": "false"}, json=body),
                202,
            )["run_id"]
            console.print(f"[bold]run[/bold] {run_id}")
        failed = False
        with client.stream("GET", f"/api/runs/{run_id}/events") as response:
            if response.status_code != 200:
                console.print(
                    f"[bold red]{response.status_code}[/bold red] {escape(response.read().decode())}"
                )
                raise typer.Exit(1)
            for event in parse_sse(response.iter_lines()):
                console.print(render(event))
                failed = failed or event["type"] in _FAILED
    raise typer.Exit(1 if failed else 0)


@runs_app.command("pin")
def pin_cmd(
    run_id: Annotated[str, typer.Argument(help="The run to pin")],
    name: Annotated[
        str | None, typer.Option("--name", "-n", help="Fixture name (default: the run id)")
    ] = None,
    project_dir: Annotated[Path, typer.Option("--project-dir", "-d")] = Path("."),
    url: Url = DEFAULT_URL,
    token: Token = None,
) -> None:
    """Export a run's journal to tests/fixtures/<workflow>/<name>.journal.json for `replay:`."""
    with _client(url, token) as client:
        document = _ok(client.get(f"/api/runs/{run_id}/export"))
    workflow = document["run"]["workflow"]
    target = project_dir / "tests" / "fixtures" / workflow / f"{name or run_id}.journal.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2) + "\n")
    relative = target.relative_to(project_dir) if target.is_relative_to(project_dir) else target
    console.print(
        f"pinned → [bold]{relative}[/bold]\nreference it from a Test with  replay: {relative}"
    )


def replay_test(fixture: Path, project: Path) -> Any:
    """A Test that replays *fixture* and expects its recorded end and output."""
    from tuvl.contract.schema import TestDocument

    run = json.loads(fixture.read_text())["run"]
    expect: dict[str, Any] = {"output": run.get("output")}
    if run.get("status") in ("completed", "compensated") and run.get("end_name"):
        expect["end"] = run["end_name"]
    relative = (
        fixture.resolve().relative_to(project)
        if fixture.resolve().is_relative_to(project)
        else fixture
    )
    return TestDocument.model_validate(
        {
            "kind": "Test",
            "version": "tuvl/v2",
            "metadata": {"name": f"replay-{fixture.stem}"},
            "spec": {
                "workflow": run["workflow"],
                "input": run.get("input") or {},
                "replay": str(relative),
                "expect": expect,
            },
        }
    )


@runs_app.command("replay")
def replay_cmd(
    fixtures: Annotated[
        list[Path], typer.Argument(help="Pinned journals (tests/fixtures/…/*.journal.json)")
    ],
    project_dir: Annotated[Path, typer.Option("--project-dir", "-d")] = Path("."),
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Re-run pinned journals through the local project; fail if the end or output differ."""
    from tuvl.contract.registry import WORKFLOWS
    from tuvl.core.config import settings
    from tuvl.core.config_loader import load_all_configs
    from tuvl.runtime.code import load_agents
    from tuvl.testing import run_test

    project = project_dir.resolve()
    use_project(str(project))
    load_all_configs(project)
    load_agents(settings.dir_for("agents"))

    async def run_all() -> list[Any]:
        return [
            await run_test(replay_test(f, project), dict(WORKFLOWS), base=project) for f in fixtures
        ]

    results = asyncio.run(run_all())
    if as_json:
        print(
            json.dumps(
                {
                    "passed": all(r.passed for r in results),
                    "replays": [r.to_json() for r in results],
                },
                indent=2,
            )
        )
    else:
        for fixture, r in zip(fixtures, results, strict=True):
            mark = "[green]SAME[/green]" if r.passed else "[red]DIFF[/red]"
            console.print(f"{mark} {escape(str(fixture))} [dim](END.{r.end or '?'})[/dim]")
            for failure in r.failures:
                console.print(f"     [red]•[/red] {escape(failure)}")
    raise typer.Exit(0 if all(r.passed for r in results) else 1)
