"""CLI wrapper for `market order create` subprocess calls."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CLI_DIR = _REPO_ROOT / "cli"


def cli_create_order(
    agent_url: str,
    env_file: str,
    offer: dict,
    demand: dict,
    duration_hours: int = 1,
    timeout: float = 30,
) -> dict:
    """Run ``market order create`` via subprocess and return parsed output.

    Parameters
    ----------
    agent_url : str
        Agent base URL reachable from host (e.g. ``http://localhost:8001``).
    env_file : str
        Path to agent env file (relative to repo root or absolute).
        Used for ``AGENT_PRIV_KEY`` / ``AGENT_WALLET_ADDRESS``.
    offer, demand : dict
        Order resources as JSON-serialisable dicts.
    duration_hours : int
        Order duration.
    timeout : float
        Subprocess timeout in seconds.

    Returns
    -------
    dict with keys:
        ``status``     – parsed from CLI output (e.g. "created")
        ``order_id``   – parsed from CLI output (may be None)
        ``cli_stdout``  – raw stdout
        ``cli_stderr``  – raw stderr
        ``returncode`` – process exit code
    """
    env_path = Path(env_file)
    if not env_path.is_absolute():
        env_path = _REPO_ROOT / env_path

    cmd = [
        "uv", "run", "market", "order", "create",
        "-a", agent_url,
        "-e", str(env_path),
        "-o", json.dumps(offer),
        "-d", json.dumps(demand),
        "-t", str(duration_hours),
    ]

    log.info("CLI: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        cwd=str(_CLI_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        env={
            **__import__("os").environ,
            "NO_COLOR": "1",  # disable Rich ANSI codes
        },
    )

    stdout = result.stdout
    stderr = result.stderr

    # Always log CLI output for visibility
    if stdout.strip():
        log.info("CLI stdout:\n%s", stdout)
    if stderr.strip():
        log.warning("CLI stderr:\n%s", stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"CLI exited with code {result.returncode}\n"
            f"stdout: {stdout[:1000]}\nstderr: {stderr[:1000]}"
        )

    # Parse status and order_id from Rich table output
    status = _parse_field(stdout, "Status")
    order_id = _parse_field(stdout, "Order ID")

    return {
        "status": status,
        "order_id": order_id,
        "cli_stdout": stdout,
        "cli_stderr": stderr,
        "returncode": result.returncode,
    }


def cli_order_history(
    env_file: str,
    timeout: float = 15,
) -> str:
    """Run ``market order history -e <env>`` and return stdout."""
    env_path = Path(env_file)
    if not env_path.is_absolute():
        env_path = _REPO_ROOT / env_path

    cmd = ["uv", "run", "market", "order", "history", "-e", str(env_path)]
    log.info("CLI: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        cwd=str(_CLI_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**__import__("os").environ, "NO_COLOR": "1"},
    )

    if result.stdout.strip():
        log.info("CLI stdout:\n%s", result.stdout)
    if result.stderr.strip():
        log.warning("CLI stderr:\n%s", result.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"CLI order history exited with code {result.returncode}\n"
            f"stdout: {result.stdout[:1000]}\nstderr: {result.stderr[:1000]}"
        )

    return result.stdout


def cli_order_show(
    order_id: str,
    env_file: str,
    negotiation: bool = False,
    credentials: bool = False,
    show_password: bool = False,
    timeout: float = 15,
) -> str:
    """Run ``market order show <id>`` with optional flags and return stdout."""
    env_path = Path(env_file)
    if not env_path.is_absolute():
        env_path = _REPO_ROOT / env_file

    cmd = [
        "uv", "run", "market", "order", "show", order_id,
        "-e", str(env_path),
    ]
    if negotiation:
        cmd.append("--negotiation")
    if credentials:
        cmd.append("--credentials")
    if show_password:
        cmd.append("--show-password")

    log.info("CLI: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        cwd=str(_CLI_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**__import__("os").environ, "NO_COLOR": "1"},
    )

    if result.stdout.strip():
        log.info("CLI stdout:\n%s", result.stdout)
    if result.stderr.strip():
        log.warning("CLI stderr:\n%s", result.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"CLI order show exited with code {result.returncode}\n"
            f"stdout: {result.stdout[:1000]}\nstderr: {result.stderr[:1000]}"
        )

    return result.stdout


def _parse_field(output: str, field_name: str) -> str | None:
    """Extract a field value from Rich grid table output.

    Handles both formatted (box-drawing) and plain text output.
    Looks for patterns like ``Status   created`` or ``Order ID   abc123``.
    """
    # Try patterns: "FieldName<whitespace>Value" across lines
    pattern = rf"(?:^|\s){re.escape(field_name)}\s+(\S+)"
    m = re.search(pattern, output, re.MULTILINE)
    return m.group(1) if m else None
