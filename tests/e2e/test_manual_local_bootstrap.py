from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest


ROOT = Path(__file__).resolve().parents[2]
CORE_AGENT_DIR = ROOT / "core/agent"
REGISTRY_DIR = ROOT / "erc-8004-registry-py"
ALKAHEST_CONFIG = ROOT / "core/agent/app/data/alkahest_anvil_addresses.json"
WAIT_TIMEOUT_SECS = 240


def _require_local_bootstrap_tools() -> None:
    for command in ("make", "uv"):
        if shutil.which(command) is None:
            pytest.skip(f"{command} is not installed")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_http_ok(url: str, *, timeout: int = WAIT_TIMEOUT_SECS) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=5) as response:
                payload = response.read()
            if payload:
                return
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise AssertionError(f"Timed out waiting for {url}: {last_error}")


def _normalize_http_rpc_url(rpc_url: str) -> str:
    if rpc_url.startswith("ws://"):
        return "http://" + rpc_url[len("ws://") :]
    if rpc_url.startswith("wss://"):
        return "https://" + rpc_url[len("wss://") :]
    return rpc_url


def _read_until_local_bootstrap_ready(process: subprocess.Popen[str]) -> tuple[str, str]:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    rpc_url: str | None = None
    alkahest_path: str | None = None
    output_lines: list[str] = []

    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if line:
            output_lines.append(line)
            if line.startswith("rpc_url:"):
                rpc_url = line.split(":", 1)[1].strip()
            if "ALKAHEST_ADDRESS_CONFIG_PATH=" in line:
                raw_path = Path(line.split("=", 1)[1].strip())
                alkahest_path = str(
                    raw_path if raw_path.is_absolute() else (CORE_AGENT_DIR / raw_path).resolve()
                )
            if rpc_url and alkahest_path:
                return rpc_url, alkahest_path

        if process.poll() is not None:
            raise AssertionError(
                "make test-env exited before reporting the local bootstrap contract.\n"
                f"output:\n{''.join(output_lines)}"
            )

    raise AssertionError(
        "Timed out waiting for make test-env to report the local bootstrap contract.\n"
        f"output:\n{''.join(output_lines)}"
    )


def test_manual_local_bootstrap_smoke(tmp_path: Path) -> None:
    _require_local_bootstrap_tools()

    original_alkahest = ALKAHEST_CONFIG.read_text(encoding="utf-8")
    test_env_process: subprocess.Popen[str] | None = None
    registry_process: subprocess.Popen[str] | None = None

    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        test_env_process = subprocess.Popen(
            ["make", "test-env"],
            cwd=CORE_AGENT_DIR,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        assert test_env_process.stdout is not None
        rpc_url, alkahest_path = _read_until_local_bootstrap_ready(test_env_process)
        normalized_rpc_url = _normalize_http_rpc_url(rpc_url)

        artifact_path = tmp_path / "local-bootstrap-artifact.json"
        deploy_result = subprocess.run(
            [
                "python",
                "scripts/deploy_local_contracts.py",
                "--rpc-url",
                rpc_url,
                "--output",
                str(artifact_path),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=1800,
            check=True,
        )
        assert deploy_result.returncode == 0

        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert artifact["rpc_url"] == normalized_rpc_url
        assert artifact["alkahest_address_config_path"] == alkahest_path
        assert Path(alkahest_path).exists()
        for key in (
            "IDENTITY_REGISTRY_ADDRESS",
            "REPUTATION_REGISTRY_ADDRESS",
            "VALIDATION_REGISTRY_ADDRESS",
        ):
            value = artifact["contracts"][key]
            assert re.fullmatch(r"0x[0-9a-fA-F]{40}", value), artifact

        registry_port = _free_port()
        registry_env = os.environ.copy()
        registry_env.update(
            {
                "DATABASE_URL": f"sqlite:///{tmp_path / 'registry.db'}",
                "CHAIN_ID": "1337",
                "RPC_URL": artifact["rpc_url"],
                "IDENTITY_REGISTRY_ADDRESS": artifact["contracts"]["IDENTITY_REGISTRY_ADDRESS"],
                "REPUTATION_REGISTRY_ADDRESS": artifact["contracts"]["REPUTATION_REGISTRY_ADDRESS"],
                "VALIDATION_REGISTRY_ADDRESS": artifact["contracts"]["VALIDATION_REGISTRY_ADDRESS"],
                "PORT": str(registry_port),
                "HOST": "127.0.0.1",
                "LOG_LEVEL": "warning",
            }
        )
        registry_process = subprocess.Popen(
            [
                "uv",
                "--no-config",
                "run",
                "uvicorn",
                "src.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(registry_port),
            ],
            cwd=REGISTRY_DIR,
            env=registry_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        _wait_for_http_ok(f"http://127.0.0.1:{registry_port}/health")
    finally:
        if registry_process is not None and registry_process.poll() is None:
            registry_process.terminate()
            try:
                registry_process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                registry_process.kill()
                registry_process.wait(timeout=30)

        if test_env_process is not None:
            if test_env_process.stdin is not None and test_env_process.poll() is None:
                test_env_process.stdin.write("\n")
                test_env_process.stdin.flush()
            try:
                test_env_process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                test_env_process.terminate()
                try:
                    test_env_process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    test_env_process.kill()
                    test_env_process.wait(timeout=30)

        ALKAHEST_CONFIG.write_text(original_alkahest, encoding="utf-8")
