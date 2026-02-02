import logging
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from async_provisioning_service.config import settings


logger = logging.getLogger(__name__)


@dataclass
class ProvisioningParams:
    ssh_pubkey: str
    vm_host: str
    vm_target: str
    vm_action: str
    vm_ram: int
    vm_vcpus: int
    vm_disk_size: str


@dataclass
class ProvisioningResult:
    stdout: str
    stderr: str
    external_port: Optional[str]
    tenant_user: Optional[str]
    vm_host_ip: Optional[str]
    ssh_command: Optional[str]
    process_id: Optional[int] = None


class PlaybookError(RuntimeError):
    def __init__(self, message: str, stdout: str, stderr: str):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def _extract_external_port(playbook_output: str, vm_host: str | None = None) -> Optional[str]:
    patterns = [r'"external_ssh_port":\s*"(?P<port>\d+)"']
    if vm_host:
        patterns.extend(
            [
                rf"-p\s*(?P<port>\d{{2,5}})\s+root@{re.escape(vm_host)}",
                rf"-p\s*(?P<port>\d{{2,5}})\s+\S+@{re.escape(vm_host)}",
            ]
        )
    patterns.append(r"-p\s*(?P<port>\d{2,5})\s+\S+@[\w\.-]+")
    for pattern in patterns:
        match = re.search(pattern, playbook_output)
        if match:
            return match.group("port")
    return None


def _extract_tenant_user(playbook_output: str, vm_host: str | None = None) -> Optional[str]:
    patterns = [r'"tenant_user":\s*"(?P<user>[^"]+)"']
    if vm_host:
        patterns.append(rf"-p\s*\d{{2,5}}\s+(?P<user>[A-Za-z0-9._-]+)@{re.escape(vm_host)}")
    patterns.append(r"-p\s*\d{2,5}\s+(?P<user>[A-Za-z0-9._-]+)@\S+")
    for pattern in patterns:
        match = re.search(pattern, playbook_output)
        if match:
            return match.group("user")
    return None


def _lookup_vm_host_ip(vm_host: str) -> Optional[str]:
    inventory_path = settings.resolved_inventory_path
    try:
        for line in inventory_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("["):
                continue
            if not stripped.startswith(vm_host + " "):
                continue
            parts = stripped.split()
            for part in parts:
                if part.startswith("ansible_host="):
                    return part.split("=", 1)[1]
    except Exception as exc:
        logger.warning("Failed to read inventory %s: %s", inventory_path, exc)
    logger.warning("No ansible_host found for %s in inventory", vm_host)
    return None


def _build_vm_vars(params: ProvisioningParams) -> str:
    escaped_pubkey = params.ssh_pubkey.replace('"', '\\"')
    return (
        f"vm_host: {params.vm_host}\n"
        f"vm_target: {params.vm_target}\n"
        f"vm_action: {params.vm_action}\n"
        f"vm_ram: {params.vm_ram}\n"
        f"vm_vcpus: {params.vm_vcpus}\n"
        f"vm_disk_size: {params.vm_disk_size}\n"
        f'vm_tenant_pubkey: "{escaped_pubkey}"\n'
    )


def run_playbook(params: ProvisioningParams) -> ProvisioningResult:
    nonce = uuid.uuid4().hex
    vm_vars_path = Path(f"/tmp/vm_vars_{nonce}.yml")
    vm_vars_path.write_text(_build_vm_vars(params), encoding="utf-8")

    cmd = [
        "ansible-playbook",
        "-i",
        str(settings.resolved_inventory_path),
        str(settings.resolved_playbook_path),
        "--extra-vars",
        f"@{vm_vars_path}",
        "--limit",
        params.vm_host,
    ]

    process = None
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=settings.repo_root,
        )

        # Store process ID for potential cancellation
        process_id = process.pid
        logger.debug("Started ansible-playbook process: PID=%d", process_id)

        # Wait for completion with timeout
        stdout, stderr = process.communicate(timeout=settings.ansible_timeout_seconds)

        if process.returncode != 0:
            raise PlaybookError("Playbook failed", stdout or "", stderr or "")

    except subprocess.TimeoutExpired:
        if process:
            process.kill()
            stdout, stderr = process.communicate()
        raise PlaybookError("Playbook timeout", stdout or "", stderr or "")
    except PlaybookError:
        raise
    except Exception as exc:
        if process:
            process.kill()
        raise PlaybookError(f"Playbook error: {exc}", "", str(exc)) from exc
    finally:
        try:
            vm_vars_path.unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to delete temp vars file: %s", vm_vars_path)

    stdout = stdout or ""
    stderr = stderr or ""
    external_port = _extract_external_port(stdout, params.vm_host)
    tenant_user = _extract_tenant_user(stdout, params.vm_host)
    vm_host_ip = _lookup_vm_host_ip(params.vm_host)

    ssh_command = None
    if external_port and tenant_user and vm_host_ip:
        ssh_command = f"ssh -i <your_private_key> -p {external_port} {tenant_user}@{vm_host_ip}"

    return ProvisioningResult(
        stdout=stdout,
        stderr=stderr,
        external_port=external_port,
        tenant_user=tenant_user,
        vm_host_ip=vm_host_ip,
        ssh_command=ssh_command,
        process_id=process_id if process else None,
    )
