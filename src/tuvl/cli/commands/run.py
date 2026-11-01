import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()


def serve_cmd(
    port: int = typer.Option(8885, "--port", "-p", help="Port to bind the engine on."),
    host: str = typer.Option("0.0.0.0", "--host", help="Host interface to bind."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of uvicorn workers."),
    project_dir: Path = typer.Option(
        None,
        "--project-dir",
        "-d",
        help="Path to the tuvl project directory (contains models/, workflows/, etc.). Defaults to current directory.",
        exists=True,
        file_okay=False,
    ),
    allow_hosts: list[str] = typer.Option(
        [],
        "--allow-host",
        "-H",
        help=(
            "Restrict access to this IP or CIDR (e.g. --allow-host 10.0.0.0/8). "
            "Can be repeated. When set, all other IPs (except localhost) are rejected."
        ),
    ),
    role: str = typer.Option(
        "all",
        "--role",
        help=(
            "all: serve HTTP and execute queued runs; api: serve HTTP, executing only "
            "synchronous requests inline; worker: execute queued runs (HTTP still serves health)."
        ),
    ),
    concurrency: int = typer.Option(
        8, "--concurrency", "-c", help="Runs each process executes at once.", min=1
    ),
    graceful_timeout: int = typer.Option(
        20,
        "--graceful-timeout",
        help="Seconds to let open requests finish after SIGTERM, before the runtime drains.",
        min=1,
    ),
    drain_timeout: float = typer.Option(
        20.0,
        "--drain-timeout",
        help=(
            "Seconds the worker waits for running runs at shutdown. A run still going is "
            "interrupted; its lease expires and another worker resumes it."
        ),
        min=0,
    ),
    forwarded_allow_ips: str = typer.Option(
        None,
        "--forwarded-allow-ips",
        help=(
            "Proxies (IPs or CIDRs, comma-separated) whose X-Forwarded-For is trusted, so "
            "--allow-host sees the real client. Behind an ingress set the ingress network; "
            "'*' trusts every sender and lets a client spoof its address. Default: 127.0.0.1."
        ),
    ),
    limit_max_requests: int = typer.Option(
        None,
        "--limit-max-requests",
        help="Restart each worker after this many requests (bounds slow memory growth).",
        min=1,
    ),
) -> None:
    """Start the engine in production mode (uvicorn)."""
    if role not in ("all", "api", "worker"):
        raise typer.BadParameter("--role must be one of: all, api, worker")
    resolved = (project_dir or Path(".")).resolve()
    hosts_line = (
        f"\n[dim]Allowed hosts:[/dim] [cyan]{', '.join(allow_hosts)}[/cyan]" if allow_hosts else ""
    )
    console.print(
        Panel(
            f"Starting tuvl engine in [bold]production mode[/bold]\n"
            f"Project: [bold]{resolved}[/bold]\n"
            f"Listening on [bold]{host}:{port}[/bold] with [bold]{workers}[/bold] worker(s), "
            f"role [bold]{role}[/bold].{hosts_line}",
            title="[blue]tuvl serve app[/blue]",
            border_style="blue",
        )
    )

    env = os.environ.copy()
    env["TUVL_PROJECT_DIR"] = str(resolved)
    env["TUVL_ROLE"] = role
    env["TUVL_WORKER_CONCURRENCY"] = str(concurrency)
    env["TUVL_SHUTDOWN_DRAIN_SECONDS"] = str(drain_timeout)
    if allow_hosts:
        env["TUVL_ALLOWED_HOSTS"] = ",".join(allow_hosts)

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "tuvl.core.app:app",
        "--host",
        host,
        "--port",
        str(port),
        "--workers",
        str(workers),
        "--timeout-graceful-shutdown",
        str(graceful_timeout),
        "--no-server-header",
    ]
    if forwarded_allow_ips:
        cmd += ["--forwarded-allow-ips", forwarded_allow_ips]
    if limit_max_requests:
        cmd += ["--limit-max-requests", str(limit_max_requests)]

    if os.name == "nt":  # no exec on Windows: run uvicorn as a child
        raise typer.Exit(subprocess.run(cmd, env=env).returncode)
    # uvicorn replaces this process, so it is PID 1 in a container and receives SIGTERM itself;
    # a child process would be killed with its parent and never shut down cleanly.
    sys.stdout.flush()
    sys.stderr.flush()
    os.execvpe(cmd[0], cmd, env)


run_cmd = serve_cmd
