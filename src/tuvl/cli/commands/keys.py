"""``tuvl keys`` subcommands for the access-token signing key.

Production mode (``tuvl serve app``) requires a persistent Ed25519 private key in
``TUVL_SIGNING_KEY`` so minted access tokens survive restarts and are
never signed with an ephemeral dev key. ``tuvl dev`` generates an ephemeral key
automatically; production fails closed and points the operator here.

* ``tuvl generate key`` — print a fresh 64-hex Ed25519 private key (plus the
  ``.env`` line to paste), or write it straight into the project ``.env`` with
  ``--write``.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()

keys_app = typer.Typer(
    name="keys",
    help="Manage the access-token signing key (TUVL_SIGNING_KEY).",
    no_args_is_help=True,
)

_ENV_VAR = "TUVL_SIGNING_KEY"


def _generate_hex() -> str:
    """Return a fresh 32-byte Ed25519 private key as 64 hex chars."""
    from tuvl.core.auth.keys import generate_private_key_hex

    return generate_private_key_hex()


@keys_app.command("generate")
def generate_cmd(
    write: bool = typer.Option(
        False,
        "--write",
        "-w",
        help=f"Write {_ENV_VAR} into the project .env instead of only printing it.",
        is_flag=True,
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help=f"Overwrite an existing {_ENV_VAR} in .env (use with --write).",
        is_flag=True,
    ),
    project_dir: Path = typer.Option(
        Path("."),
        "--project-dir",
        "-d",
        help="Project directory whose .env to update (with --write).",
        file_okay=False,
    ),
) -> None:
    """Generate a persistent Ed25519 private key for signing access tokens."""
    key_hex = _generate_hex()
    env_line = f"{_ENV_VAR}={key_hex}"

    if not write:
        console.print(
            Panel(
                f"[bold]{env_line}[/bold]\n\n"
                "[dim]Add this line to your project .env, then run `tuvl serve app`.\n"
                "Keep it secret and stable — changing it invalidates all existing "
                "tokens.[/dim]",
                title="[green]Signing key[/green]",
                border_style="green",
            )
        )
        return

    env_path = (project_dir / ".env").resolve()
    existing = env_path.read_text() if env_path.exists() else ""
    lines = existing.splitlines()
    has_key = any(line.strip().startswith(f"{_ENV_VAR}=") for line in lines)

    if has_key and not force:
        console.print(
            f"[red]{_ENV_VAR} is already set in {env_path}. Re-run with --force to overwrite.[/red]"
        )
        raise typer.Exit(1)

    if has_key:
        lines = [env_line if line.strip().startswith(f"{_ENV_VAR}=") else line for line in lines]
        new_content = "\n".join(lines) + "\n"
    else:
        sep = "" if existing == "" or existing.endswith("\n") else "\n"
        new_content = f"{existing}{sep}{env_line}\n"

    # Owner-only perms on create — the key is a secret.
    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(new_content)

    console.print(
        Panel(
            f"[green]✓[/green] Wrote {_ENV_VAR} to [bold]{env_path}[/bold]\n"
            "[dim]Keep it secret and stable — changing it invalidates all existing "
            "tokens.[/dim]",
            border_style="green",
        )
    )
