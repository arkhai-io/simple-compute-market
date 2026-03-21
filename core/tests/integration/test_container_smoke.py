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


ROOT = Path(__file__).resolve().parents[3]
DOCKER_TIMEOUT_SECS = 1800
WAIT_TIMEOUT_SECS = 180
CANONICAL_AGENT_ID = "eip155:84532:0x0000000000000000000000000000000000000001:7"
ZEROTIER_IP = "100.64.0.9"


def _run(
    *args: str,
    cwd: Path = ROOT,
    check: bool = True,
    timeout: int = DOCKER_TIMEOUT_SECS,
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


def _wait_for_port(container_name: str, container_port: str) -> int:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_output = ""

    while time.monotonic() < deadline:
        result = _run(
            "docker",
            "port",
            container_name,
            container_port,
            check=False,
            timeout=30,
        )
        output = result.stdout.strip()
        if output:
            last_output = output
            return int(output.rsplit(":", 1)[1])
        time.sleep(2)

    logs = _run("docker", "logs", container_name, check=False, timeout=30)
    raise AssertionError(
        f"container port {container_port} was never published, last output: {last_output!r}\n"
        f"stdout:\n{logs.stdout}\nstderr:\n{logs.stderr}"
    )


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


def _wait_for_logs(container_name: str, token: str) -> str:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_logs = ""

    while time.monotonic() < deadline:
        result = _run("docker", "logs", container_name, check=False, timeout=30)
        last_logs = f"{result.stdout}\n{result.stderr}"
        if token in last_logs:
            return last_logs
        time.sleep(2)

    raise AssertionError(
        f"Timed out waiting for log token {token!r} in {container_name}.\nLogs:\n{last_logs}"
    )


def _clean_container(container_name: str) -> None:
    _run("docker", "rm", "-f", container_name, check=False, timeout=30)


@pytest.mark.integration
def test_agent_container_persists_env_file_and_skips_reregistration_on_restart(
    tmp_path: Path,
) -> None:
    # This smoke test uses docker build + docker run against the real core
    # image, mounts a writable ENV_FILE, and verifies the entrypoint persists
    # ONCHAIN_AGENT_ID, BASE_URL_OVERRIDE, and ZEROTIER_IP before serving the
    # well-known registration routes.
    _require_docker()

    env_file = tmp_path / "agent.env"
    env_file.write_text(
        "AGENT_ID=smoke_seller\nAGENT_NAME=Smoke Seller\n",
        encoding="utf-8",
    )

    register_stub = tmp_path / "register_onchain.py"
    register_stub.write_text(
        textwrap.dedent(
            f"""
            from __future__ import annotations

            import argparse
            import os
            from pathlib import Path

            CANONICAL_AGENT_ID = "{CANONICAL_AGENT_ID}"
            ZEROTIER_IP = "{ZEROTIER_IP}"


            def _upsert(path: Path, key: str, value: str) -> None:
                lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
                updated = False
                for index, line in enumerate(lines):
                    if line.startswith(f"{{key}}="):
                        lines[index] = f"{{key}}={{value}}"
                        updated = True
                        break
                if not updated:
                    lines.append(f"{{key}}={{value}}")
                path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")


            parser = argparse.ArgumentParser()
            parser.add_argument("--env-file", required=True)
            args = parser.parse_args()

            env_path = Path(args.env_file)
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.touch()

            port = os.getenv("PORT", "8080")
            _upsert(env_path, "ONCHAIN_AGENT_ID", CANONICAL_AGENT_ID)
            _upsert(env_path, "ZEROTIER_IP", ZEROTIER_IP)
            _upsert(env_path, "BASE_URL_OVERRIDE", f"http://{{ZEROTIER_IP}}:{{port}}/")

            marker = os.getenv("SMOKE_REGISTER_MARKER")
            if marker:
                marker_path = Path(marker)
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                count = int(marker_path.read_text(encoding="utf-8").strip() or "0") if marker_path.exists() else 0
                marker_path.write_text(str(count + 1), encoding="utf-8")

            print(f"stub registration wrote {{env_path}}")
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    image_tag = f"sms-core-smoke:{uuid.uuid4().hex[:12]}"
    first_container = f"sms-core-smoke-{uuid.uuid4().hex[:8]}"
    second_container = f"{first_container}-restart"
    marker_file = tmp_path / "register-count.txt"

    try:
        _run(
            "docker",
            "build",
            "-f",
            "core/Dockerfile",
            "-t",
            image_tag,
            ".",
            cwd=ROOT,
        )

        _run(
            "docker",
            "run",
            "-d",
            "--name",
            first_container,
            "-p",
            "127.0.0.1::8080",
            "-e",
            "PORT=8080",
            "-e",
            "ENV_FILE=/smoke/agent.env",
            "-e",
            "SMOKE_REGISTER_MARKER=/smoke/register-count.txt",
            "-v",
            f"{tmp_path}:/smoke",
            "-v",
            f"{register_stub}:/app/core/agent/scripts/register_onchain.py:ro",
            image_tag,
        )

        first_port = _wait_for_port(first_container, "8080")
        agent_card = _wait_for_json(
            f"http://127.0.0.1:{first_port}/.well-known/agent-card.json"
        )
        registration = _wait_for_json(
            f"http://127.0.0.1:{first_port}/.well-known/erc-8004-registration.json"
        )
        first_logs = _wait_for_logs(first_container, "Registering agent on-chain...")

        persisted_env = env_file.read_text(encoding="utf-8")
        assert "AGENT_ID=smoke_seller" in persisted_env
        assert "AGENT_NAME=Smoke Seller" in persisted_env
        assert f"ONCHAIN_AGENT_ID={CANONICAL_AGENT_ID}" in persisted_env
        assert f"ZEROTIER_IP={ZEROTIER_IP}" in persisted_env
        assert f"BASE_URL_OVERRIDE=http://{ZEROTIER_IP}:8080/" in persisted_env
        assert marker_file.read_text(encoding="utf-8").strip() == "1"
        assert str(agent_card["url"]).rstrip("/") == f"http://{ZEROTIER_IP}:8080"
        assert registration["registrations"] == [
            {
                "agentId": 7,
                "agentRegistry": "eip155:84532:0x0000000000000000000000000000000000000001",
            }
        ]
        assert "Skipping on-chain registration" not in first_logs

        _clean_container(first_container)

        _run(
            "docker",
            "run",
            "-d",
            "--name",
            second_container,
            "-p",
            "127.0.0.1::8080",
            "-e",
            "PORT=8080",
            "-e",
            "ENV_FILE=/smoke/agent.env",
            "-e",
            "SMOKE_REGISTER_MARKER=/smoke/register-count.txt",
            "-v",
            f"{tmp_path}:/smoke",
            "-v",
            f"{register_stub}:/app/core/agent/scripts/register_onchain.py:ro",
            image_tag,
        )

        second_port = _wait_for_port(second_container, "8080")
        second_agent_card = _wait_for_json(
            f"http://127.0.0.1:{second_port}/.well-known/agent-card.json"
        )
        second_registration = _wait_for_json(
            f"http://127.0.0.1:{second_port}/.well-known/erc-8004-registration.json"
        )
        second_logs = _wait_for_logs(
            second_container,
            "Skipping on-chain registration (required identity fields already set).",
        )

        assert marker_file.read_text(encoding="utf-8").strip() == "1"
        assert str(second_agent_card["url"]).rstrip("/") == f"http://{ZEROTIER_IP}:8080"
        assert second_registration["registrations"] == registration["registrations"]
        assert "Registering agent on-chain..." not in second_logs
    finally:
        _clean_container(first_container)
        _clean_container(second_container)
        _run("docker", "rmi", "-f", image_tag, check=False, timeout=60)
