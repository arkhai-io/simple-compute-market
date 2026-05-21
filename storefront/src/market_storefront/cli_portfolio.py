"""`market-storefront portfolio` — manage the local resource portfolio."""

from __future__ import annotations

from pathlib import Path

import typer

from .cli_common import REPO_ROOT


portfolio_app = typer.Typer(no_args_is_help=True)


@portfolio_app.command("import-csv")
def portfolio_import_csv(
    csv_path: str = typer.Argument(..., help="Path to CSV file to import."),
    db_path: str | None = typer.Option(
        None, "--db-path",
        help="Override the target SQLite DB path "
             "(default: seller.db_path from config.toml).",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Validate and report without writing to DB.",
    ),
) -> None:
    """Import resource portfolio rows from CSV into the agent DB.

    Calls `storefront/scripts/import_resources_csv.py` directly. Used
    on a freshly provisioned seller before `provide` to seed the
    `resources` table.
    """
    from .utils.config import settings

    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise typer.BadParameter(f"CSV file not found: {csv_path}")

    if not db_path:
        if settings.db_path:
            db_path = settings.db_path

    script = REPO_ROOT / "storefront" / "scripts" / "import_resources_csv.py"
    if not script.exists():
        raise typer.BadParameter(f"Import script not found: {script}")

    import subprocess
    import sys

    cmd = [sys.executable, str(script), "--csv", str(csv_file.resolve())]
    if db_path:
        cmd += ["--db-path", db_path]
    if dry_run:
        cmd += ["--dry-run"]

    typer.echo(f"==> Import resource portfolio from CSV: {csv_file}")
    subprocess.run(cmd, cwd=str(REPO_ROOT / "storefront"), check=True)
