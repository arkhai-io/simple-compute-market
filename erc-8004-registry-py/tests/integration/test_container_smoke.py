from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_UP_TIMEOUT_SECS = 600
WAIT_TIMEOUT_SECS = 180


def _run(
    *args: str,
    cwd: Path = ROOT,
    check: bool = True,
    timeout: int = COMPOSE_UP_TIMEOUT_SECS,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        command = " ".join(args)
        raise AssertionError(
            f"command failed: {command}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _require_docker() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")

    result = _run("docker", "info", check=False, timeout=30)
    if result.returncode != 0:
        pytest.skip("docker daemon is not available")


def _run_compose(
    compose_file: Path,
    project_name: str,
    *args: str,
    check: bool = True,
    timeout: int = COMPOSE_UP_TIMEOUT_SECS,
) -> subprocess.CompletedProcess[str]:
    return _run(
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "-p",
        project_name,
        *args,
        check=check,
        timeout=timeout,
    )


def _wait_for_registry_port(compose_file: Path, project_name: str) -> int:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_output = ""

    while time.monotonic() < deadline:
        result = _run_compose(
            compose_file,
            project_name,
            "port",
            "registry",
            "8080",
            check=False,
            timeout=30,
        )
        output = result.stdout.strip()
        if output:
            last_output = output
            return int(output.rsplit(":", 1)[1])
        time.sleep(2)

    raise AssertionError(f"registry port was never published, last output: {last_output!r}")


def _wait_for_json(url: str) -> dict[str, object]:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_error = ""

    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=5) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = str(exc)
            time.sleep(2)

    raise AssertionError(f"Timed out waiting for {url}: {last_error}")


def _wait_for_registry_logs(compose_file: Path, project_name: str, token: str) -> str:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_logs = ""

    while time.monotonic() < deadline:
        result = _run_compose(
            compose_file,
            project_name,
            "logs",
            "--no-color",
            "registry",
            check=False,
            timeout=30,
        )
        last_logs = f"{result.stdout}\n{result.stderr}"
        if token in last_logs:
            return last_logs
        time.sleep(2)

    raise AssertionError(f"Timed out waiting for registry log token {token!r}.\nLogs:\n{last_logs}")


@pytest.mark.integration
def test_registry_container_starts_against_postgres_and_serves_core_routes(
    tmp_path: Path,
) -> None:
    # This smoke test uses docker compose to boot Postgres, Anvil, and the
    # registry container from the checked-in Dockerfile.
    _require_docker()

    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        textwrap.dedent(
            f"""
            services:
              postgres:
                image: postgres:16-alpine
                environment:
                  POSTGRES_DB: registry
                  POSTGRES_USER: postgres
                  POSTGRES_PASSWORD: postgres
                healthcheck:
                  test: ["CMD-SHELL", "pg_isready -U postgres -d registry"]
                  interval: 2s
                  timeout: 2s
                  retries: 30

              anvil:
                image: ghcr.io/foundry-rs/foundry:latest
                command: ["anvil", "--host", "0.0.0.0", "--port", "8545"]
                healthcheck:
                  test: ["CMD-SHELL", "cast block-number --rpc-url http://127.0.0.1:8545 >/dev/null 2>&1"]
                  interval: 2s
                  timeout: 2s
                  retries: 30

              registry:
                build:
                  context: {ROOT.as_posix()}
                  dockerfile: Dockerfile
                depends_on:
                  postgres:
                    condition: service_healthy
                  anvil:
                    condition: service_healthy
                environment:
                  DATABASE_URL: postgresql://postgres:postgres@postgres:5432/registry
                  CHAIN_ID: "1337"
                  RPC_URL: http://anvil:8545
                  IDENTITY_REGISTRY_ADDRESS: 0x8004AA63c570c570eBF15376c0dB199918BFe9Fb
                  REPUTATION_REGISTRY_ADDRESS: 0x8004bd8daB57f14Ed299135749a5CB5c42d341BF
                  VALIDATION_REGISTRY_ADDRESS: 0x8004Cb1BF31DAf7788923b405b754f57acEB4272
                  PORT: "8080"
                  HOST: 0.0.0.0
                  ENABLE_HEALTH_CHECKS: "false"
                  EVENT_SYNC_INITIAL_LOOKBACK_BLOCKS: "0"
                  EVENT_SYNC_CHUNK_SIZE: "10"
                  LOG_LEVEL: info
                ports:
                  - "127.0.0.1::8080"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    project_name = f"registry-smoke-{uuid.uuid4().hex[:8]}"

    try:
        _run_compose(compose_file, project_name, "up", "--build", "-d")

        port = _wait_for_registry_port(compose_file, project_name)
        base_url = f"http://127.0.0.1:{port}"

        health_payload = _wait_for_json(f"{base_url}/health")
        assert health_payload["status"] == "healthy"
        assert health_payload["service"] == "erc-8004-indexer"
        assert health_payload["health_checks_enabled"] is False

        agents_payload = _wait_for_json(f"{base_url}/agents")
        orders_payload = _wait_for_json(f"{base_url}/orders")
        assert agents_payload["items"] == []
        assert orders_payload["items"] == []

        tables = _run_compose(
            compose_file,
            project_name,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "registry",
            "-tAc",
            "select to_regclass('public.agents'), to_regclass('public.market_orders');",
            timeout=30,
        ).stdout.strip()
        assert "agents" in tables
        assert "market_orders" in tables

        logs = _wait_for_registry_logs(
            compose_file,
            project_name,
            "Event sync service started",
        )
        assert "Database initialized" in logs

    finally:
        _run_compose(
            compose_file,
            project_name,
            "down",
            "-v",
            "--remove-orphans",
            check=False,
            timeout=120,
        )
