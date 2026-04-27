"""CLI helpers for the storefront's `market-storefront` console script.

Mirror of buyer/market_buyer/common.py. Both CLIs expose small admin
utilities (start, register, provide, etc.) that need the same env-file
parsing + venv-aware subprocess wrappers; duplicating the helpers
keeps each CLI self-contained without a forced cross-package import.
If these drift apart it'll be obvious; if they don't, a follow-up can
factor them into a shared module.
"""

from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

import typer

# parents[3]: market_storefront → src → storefront → repo root
REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_AGENT_ENV = REPO_ROOT / "storefront" / ".env"


def read_env_value(env_file: str | Path | None, key: str, default: str = "") -> str:
    """Read a single KEY=value from an env file, returning default if absent."""
    if not env_file:
        return default
    path = Path(env_file)
    if not path.exists():
        return default
    try:
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() != key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            return value
    except Exception:
        return default
    return default


def resolve_config_value(
    env_name: str,
    *,
    override: str | None = None,
    env_file: str | Path | None = None,
    toml_path: str | None = None,
    default: str = "",
) -> str:
    """One-stop lookup for a scalar config value across all our sources.

    Precedence:
      1. Explicit `override` (CLI flag)
      2. `env_file` (e.g. storefront/.env passed via --env)
      3. Shell `env_name` environment variable
      4. Dotted `toml_path` key in the user config.toml
      5. `default`
    """
    if override:
        return override
    if env_file:
        v = read_env_value(env_file, env_name)
        if v:
            return v
    v = os.environ.get(env_name)
    if v:
        return v
    if toml_path:
        from service.config_loader import get_dotted, load_user_config
        v = get_dotted(load_user_config(), toml_path)
        if v not in (None, ""):
            return str(v)
    return default


def container_db_to_host(db_path: str) -> Path:
    """Resolve a container-side AGENT_DB_PATH to its host-side equivalent under REPO_ROOT.

    Container paths are relative to the container WORKDIR (/app), e.g.:
      ./src/market_storefront/data/sell-agent/agent.db  →  REPO_ROOT/src/market_storefront/data/sell-agent/agent.db
      /app/src/market_storefront/data/sell-agent/agent.db  →  same
    """
    rel = db_path
    if rel.startswith("/app/"):
        rel = rel[len("/app/"):]
    elif rel.startswith("./"):
        rel = rel[2:]
    return REPO_ROOT / rel


def resolve_agent_url(
    agent_url: str | None,
    env_file: str | Path | None,
    default_port: int = 8000,
) -> str:
    """Resolve the URL the CLI should dial to reach the storefront.

    Precedence:
      1. Explicit --agent-url flag.
      2. AGENT_MODE=container → http://localhost:{PORT} (env-file PORT,
         or default_port).
      3. Env-file BASE_URL_OVERRIDE (host mode).
      4. Process-env AGENT_URL / BASE_URL_OVERRIDE.
      5. http://localhost:{default_port}.
    """
    if agent_url:
        return agent_url
    env_path = Path(env_file) if env_file else None
    agent_mode = read_env_value(env_path, "AGENT_MODE", default="host") if env_path else "host"
    port = read_env_value(env_path, "PORT", default=str(default_port)) if env_path else str(default_port)
    if agent_mode == "container":
        return f"http://localhost:{port}"
    env_url = read_env_value(env_path, "BASE_URL_OVERRIDE") if env_path else None
    return (
        env_url
        or os.getenv("AGENT_URL")
        or os.getenv("BASE_URL_OVERRIDE")
        or f"http://localhost:{default_port}"
    )


def _normalize_registry_url(raw_url: str) -> str:
    return raw_url.rstrip("/")


def _get_cli_http_timeout() -> float:
    raw = os.getenv("MARKET_CLI_HTTP_TIMEOUT", "120")
    try:
        return float(raw)
    except ValueError:
        return 120.0


def _get_auth_headers(operation: str, resource_id: str, private_key: str | None) -> dict[str, str]:
    """Build X-Signature / X-Timestamp headers for a CLI→storefront request.

    Returns an empty dict if no private_key is provided or if
    eth_account is not installed (request is sent unsigned; the
    storefront will reject it if it requires auth).
    """
    if not private_key:
        return {}
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError:
        return {}
    ts = int(time.time())
    message = f"{operation}:{resource_id}:{ts}"
    msg_hash = encode_defunct(text=message)
    sig = Account.sign_message(msg_hash, private_key).signature.hex()
    return {"X-Signature": sig, "X-Timestamp": str(ts)}


def _post_json(url: str, payload: dict, extra_headers: dict[str, str] | None = None) -> dict:
    try:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=_get_cli_http_timeout()) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        typer.secho(f"Storefront error ({exc.code}): {detail}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.secho(f"Failed to call storefront endpoint: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)


def _resolve_db_path(db: str | None, env: str | None) -> str | None:
    """Return the SQLite DB path from explicit arg, env file, or env var."""
    if db:
        return db
    env_path = Path(env) if env else DEFAULT_AGENT_ENV
    db_path_from_env = read_env_value(env_path, "AGENT_DB_PATH")
    if db_path_from_env:
        agent_mode = read_env_value(env_path, "AGENT_MODE", default="host")
        resolved = (
            str(container_db_to_host(db_path_from_env))
            if agent_mode == "container"
            else db_path_from_env
        )
        if Path(resolved).exists():
            return resolved
    from_env = os.getenv("AGENT_DB_PATH")
    if from_env and Path(from_env).exists():
        return from_env
    return None


def run_step(
    label: str,
    cmd: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> None:
    typer.echo(f"==> {label} at {cwd}")
    env = os.environ.copy()
    venv_path = cwd / ".venv"
    if cwd.resolve() == (REPO_ROOT / "storefront").resolve():
        storefront_venv = REPO_ROOT / "storefront" / ".venv"
        if storefront_venv.exists():
            venv_path = storefront_venv
    venv_bin = venv_path / "bin"
    if venv_bin.exists():
        env["VIRTUAL_ENV"] = str(venv_path)
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
    subprocess.run(cmd, cwd=cwd, check=True, env=env)
