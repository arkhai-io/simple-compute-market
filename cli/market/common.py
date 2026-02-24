from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import urllib.error
import urllib.request

import typer

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_step(
    label: str,
    cmd: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> None:
    typer.echo(f"==> {label} at {cwd}")
    env = os.environ.copy()
    venv_path = cwd / ".venv"
    venv_bin = venv_path / "bin"
    if venv_bin.exists():
        env["VIRTUAL_ENV"] = str(venv_path)
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
    subprocess.run(cmd, cwd=cwd, check=True, env=env)


def _resolve_agent_url(agent_url: str | None) -> str:
    url = agent_url or os.getenv("AGENT_URL") or os.getenv("BASE_URL_OVERRIDE") or "http://localhost:8000"
    return url.rstrip("/")


def _fetch_json(url: str) -> dict:
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        typer.secho(f"HTTP error ({exc.code}): {detail}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.secho(f"Failed to fetch: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)


def _short_ts(value: str | None) -> str:
    if not value:
        return "-"
    return value.replace("T", " ")[:19]
