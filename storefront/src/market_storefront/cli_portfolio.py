from __future__ import annotations

from pathlib import Path

import typer

from .cli_common import REPO_ROOT, read_env_value, container_db_to_host, run_step, DEFAULT_AGENT_ENV

portfolio_app = typer.Typer(no_args_is_help=True)


@portfolio_app.command("import-csv")
def portfolio_import_csv(
    csv_path: str = typer.Argument(..., help="Path to CSV file to import."),
    env: str | None = typer.Option(
        None,
        "--env",
        "-e",
        help="Path to env file used by core/agent script (default: storefront/.env).",
    ),
    db_path: str | None = typer.Option(
        None,
        "--db-path",
        help="Override AGENT_DB_PATH for import target DB.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and report without writing to DB.",
    ),
) -> None:
    """Import resource portfolio rows from CSV into the Agent DB."""
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise typer.BadParameter(f"CSV file not found: {csv_path}")

    # In container mode, resolve the container DB path to its host-side volume mount
    # so the import script can write directly without needing docker exec.
    if not db_path:
        agent_mode = read_env_value(env or DEFAULT_AGENT_ENV, "AGENT_MODE", default="host")
        if agent_mode == "container":
            raw = read_env_value(env or DEFAULT_AGENT_ENV, "AGENT_DB_PATH", default="")
            if raw:
                db_path = str(container_db_to_host(raw))

    cmd = ["make", "import-resources", f"CSV={csv_file.resolve()}"]
    if env:
        cmd.append(f"ENV_FILE={env}")
    if db_path:
        cmd.append(f"DB_PATH={db_path}")
    if dry_run:
        cmd.append("DRY_RUN=true")

    run_step(
        "Import resource portfolio from CSV",
        cmd,
        REPO_ROOT / "core" / "agent",
    )

