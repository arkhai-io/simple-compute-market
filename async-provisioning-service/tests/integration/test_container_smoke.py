from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import time
import uuid
from pathlib import Path

import httpx
import pytest


SERVICE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVICE_ROOT.parent
COMPOSE_UP_TIMEOUT_SECS = 600
WAIT_TIMEOUT_SECS = 180
SELLER_AGENT_ID = "eip155:84532:0x1111111111111111111111111111111111111111:7"
BUYER_AGENT_ID = "eip155:84532:0x2222222222222222222222222222222222222222:8"


def _run(
    *args: str,
    cwd: Path = SERVICE_ROOT,
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


def _wait_for_api_port(compose_file: Path, project_name: str) -> int:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_output = ""

    while time.monotonic() < deadline:
        result = _run_compose(
            compose_file,
            project_name,
            "port",
            "provisioner",
            "8081",
            check=False,
            timeout=30,
        )
        output = result.stdout.strip()
        if output:
            last_output = output
            return int(output.rsplit(":", 1)[1])
        time.sleep(2)

    raise AssertionError(f"provisioner port was never published, last output: {last_output!r}")


def _wait_for_health(base_url: str) -> dict[str, object]:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_error = ""

    with httpx.Client(timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(f"{base_url}/health")
                if response.status_code == 200:
                    payload = response.json()
                    if payload.get("status") == "ok":
                        return payload
                    last_error = json.dumps(payload)
                else:
                    last_error = f"status={response.status_code} body={response.text}"
            except httpx.HTTPError as exc:
                last_error = str(exc)
            time.sleep(2)

    raise AssertionError(f"Timed out waiting for healthy API: {last_error}")


def _wait_for_job_status(
    base_url: str,
    job_id: str,
    *,
    expected_status: str,
    agent_id: str,
) -> dict[str, object]:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_payload = ""

    with httpx.Client(timeout=5.0) as client:
        while time.monotonic() < deadline:
            response = client.get(
                f"{base_url}/api/v1/jobs/{job_id}",
                headers={"X-Agent-ID": agent_id},
            )
            if response.status_code == 200:
                payload = response.json()
                last_payload = json.dumps(payload)
                if payload.get("status") == expected_status:
                    return payload
            time.sleep(2)

    raise AssertionError(f"Timed out waiting for job {job_id} status={expected_status}: {last_payload}")


def _wait_for_logs(compose_file: Path, project_name: str, token: str) -> str:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_logs = ""

    while time.monotonic() < deadline:
        result = _run_compose(
            compose_file,
            project_name,
            "logs",
            "--no-color",
            "provisioner",
            check=False,
            timeout=30,
        )
        last_logs = f"{result.stdout}\n{result.stderr}"
        if token in last_logs:
            return last_logs
        time.sleep(2)

    raise AssertionError(f"Timed out waiting for provisioner log token {token!r}.\nLogs:\n{last_logs}")


@pytest.mark.integration
def test_async_provisioning_container_starts_processes_jobs_and_scopes_credentials(
    tmp_path: Path,
) -> None:
    # This smoke test uses docker compose to boot Redis, Postgres, a registry
    # mock, and the real async provisioning container from start.sh.
    _require_docker()

    smoke_inventory = tmp_path / "hosts"
    smoke_inventory.write_text(
        "[kvm_hosts]\nww1 ansible_connection=local\n",
        encoding="utf-8",
    )

    smoke_playbook = tmp_path / "vm-operations.yml"
    smoke_playbook.write_text(
        textwrap.dedent(
            """
            - hosts: all
              gather_facts: false
              vars:
                smoke_result:
                  action: "{{ vm_action }}"
                  status: "success"
                  host: "{{ vm_host }}"
                  vm_name: "{{ vm_target | default('smoke-vm') }}"
                  tenant_user: "tenant-user"
                  authentication:
                    root:
                      password: "seller-root-pass"
                      ssh_commands:
                        external: "ssh -p 7002 root@smoke-host"
                      ssh_key_path_host: "/home/appuser/.ssh/id_ed25519"
                    tenant:
                      password: "tenant-pass"
                      key_type: "generated"
                      ssh_commands:
                        external: "ssh -p 7002 tenant-user@smoke-host"
                  frp:
                    remote_port: "7002"
              tasks:
                - debug:
                    msg: "{{ smoke_result | to_nice_json }}"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    registry_mock = tmp_path / "registry_mock.py"
    registry_mock.write_text(
        textwrap.dedent(
            f"""
            import json
            from http.server import BaseHTTPRequestHandler, HTTPServer
            from urllib.parse import unquote

            VALID_IDS = {{
                "{SELLER_AGENT_ID}",
                "{BUYER_AGENT_ID}",
            }}

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    path = unquote(self.path)
                    if path.startswith("/agents/"):
                        agent_id = path.split("/agents/", 1)[1]
                        if agent_id in VALID_IDS:
                            payload = {{"agentId": agent_id, "status": "healthy"}}
                            body = json.dumps(payload).encode("utf-8")
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.send_header("Content-Length", str(len(body)))
                            self.end_headers()
                            self.wfile.write(body)
                            return

                    self.send_response(404)
                    self.end_headers()

                def log_message(self, fmt, *args):
                    return

            HTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        textwrap.dedent(
            f"""
            services:
              redis:
                image: redis:7-alpine

              postgres:
                image: postgres:16-alpine
                environment:
                  POSTGRES_DB: provisioning
                  POSTGRES_USER: postgres
                  POSTGRES_PASSWORD: postgres
                healthcheck:
                  test: ["CMD-SHELL", "pg_isready -U postgres -d provisioning"]
                  interval: 2s
                  timeout: 2s
                  retries: 30

              registry-mock:
                image: python:3.13-slim
                working_dir: /smoke
                volumes:
                  - {tmp_path.as_posix()}:/smoke:ro
                command: ["python", "/smoke/registry_mock.py"]

              provisioner:
                build:
                  context: {REPO_ROOT.as_posix()}
                  dockerfile: async-provisioning-service/Dockerfile
                depends_on:
                  postgres:
                    condition: service_healthy
                  redis:
                    condition: service_started
                  registry-mock:
                    condition: service_started
                environment:
                  HOST: 0.0.0.0
                  PORT: "8081"
                  LOG_LEVEL: info
                  DATABASE_URL: postgresql+psycopg2://postgres:postgres@postgres:5432/provisioning
                  REDIS_URL: redis://redis:6379/0
                  REDIS_QUEUE_NAME: provisioning_jobs
                  ENABLE_AUTH: "true"
                  AUTH_FAIL_OPEN: "false"
                  REGISTRY_URL: http://registry-mock:8090
                  DEFAULT_VM_HOST: ww1
                  PLAYBOOK_PATH: /smoke/vm-operations.yml
                  INVENTORY_PATH: /smoke/hosts
                  ANSIBLE_TIMEOUT_SECONDS: "30"
                volumes:
                  - {tmp_path.as_posix()}:/smoke:ro
                ports:
                  - "127.0.0.1::8081"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    project_name = f"async-prov-smoke-{uuid.uuid4().hex[:8]}"

    try:
        _run_compose(compose_file, project_name, "up", "--build", "-d")

        port = _wait_for_api_port(compose_file, project_name)
        base_url = f"http://127.0.0.1:{port}"

        health_payload = _wait_for_health(base_url)
        assert health_payload["checks"] == {"api": "ok", "database": "ok", "redis": "ok"}

        with httpx.Client(timeout=5.0) as client:
            missing_header = client.post(
                f"{base_url}/api/v1/jobs",
                json={"vm_host": "ww1", "vm_target": "tenant-smoke", "vm_action": "create"},
            )
            assert missing_header.status_code == 401

            enqueue_response = client.post(
                f"{base_url}/api/v1/jobs",
                json={
                    "vm_host": "ww1",
                    "vm_target": "tenant-smoke",
                    "vm_action": "create",
                    "buyer_agent_id": BUYER_AGENT_ID,
                },
                headers={"X-Agent-ID": SELLER_AGENT_ID},
            )
            assert enqueue_response.status_code == 202
            job_id = enqueue_response.json()["job_id"]

        status_payload = _wait_for_job_status(
            base_url,
            job_id,
            expected_status="succeeded",
            agent_id=SELLER_AGENT_ID,
        )
        assert status_payload["result"]["ssh_port"] == "7002"
        assert "authentication" not in status_payload["result"]

        with httpx.Client(timeout=5.0) as client:
            seller_credentials = client.get(
                f"{base_url}/api/v1/jobs/{job_id}/credentials",
                headers={"X-Agent-ID": SELLER_AGENT_ID},
            )
            buyer_credentials = client.get(
                f"{base_url}/api/v1/jobs/{job_id}/credentials",
                headers={"X-Agent-ID": BUYER_AGENT_ID},
            )
            logs_response = client.get(
                f"{base_url}/api/v1/jobs/{job_id}/logs",
                headers={"X-Agent-ID": SELLER_AGENT_ID},
            )

        assert seller_credentials.status_code == 200
        seller_roles = sorted(item["role"] for item in seller_credentials.json()["credentials"])
        assert seller_roles == ["root", "tenant"]

        assert buyer_credentials.status_code == 200
        buyer_items = buyer_credentials.json()["credentials"]
        assert len(buyer_items) == 1
        assert buyer_items[0]["role"] == "tenant"
        assert buyer_items[0]["password"] == "tenant-pass"

        assert logs_response.status_code == 200
        assert "seller-root-pass" not in (logs_response.json()["logs"] or "")

        db_status = _run_compose(
            compose_file,
            project_name,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "provisioning",
            "-tAc",
            f"select status from provisioning_jobs where id = '{job_id}';",
            timeout=30,
        ).stdout.strip()
        assert db_status == "succeeded"

        credential_count = _run_compose(
            compose_file,
            project_name,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "provisioning",
            "-tAc",
            f"select count(*) from credentials where job_id = '{job_id}';",
            timeout=30,
        ).stdout.strip()
        assert credential_count == "3"

        redis_queue_depth = _run_compose(
            compose_file,
            project_name,
            "exec",
            "-T",
            "redis",
            "redis-cli",
            "LLEN",
            "provisioning_jobs",
            timeout=30,
        ).stdout.strip()
        assert redis_queue_depth == "0"

        logs = _wait_for_logs(compose_file, project_name, "Processing job")
        assert "Provisioning worker started" in logs
        assert "Processing job" in logs

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
