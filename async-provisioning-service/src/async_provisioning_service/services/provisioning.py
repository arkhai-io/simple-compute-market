import asyncio
import json
import logging
import re
import select
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from async_provisioning_service.config import settings


logger = logging.getLogger(__name__)


@dataclass
class ProvisioningParams:
    vm_host: str
    vm_target: Optional[str]
    vm_action: str
    image_setup_type: str = "scratch"
    vm_ram: Optional[int] = None
    vm_vcpus: Optional[int] = None
    vm_disk_size: Optional[str] = None
    vm_os_variant: Optional[str] = None
    ssh_pubkey: Optional[str] = None
    gpu_provisioned: Optional[bool] = None
    vm_gpu_count: Optional[int] = None
    vm_gpu_device: Optional[str] = None
    vm_gpu_devices: Optional[list[str]] = field(default=None)
    vm_gpu_partition_size: Optional[str] = None
    frp_server_addr: Optional[str] = None
    frp_domain: Optional[str] = None
    frp_dashboard_password: Optional[str] = None
    golden_image_name: Optional[str] = None
    gcs_bucket_url: Optional[str] = None
    gcs_image_path: Optional[str] = None
    vm_lease_end: Optional[str] = None


@dataclass
class ProvisioningResult:
    stdout: str
    stderr: str
    ssh_port: Optional[str]
    tenant_user: Optional[str]
    vm_host_ip: Optional[str]
    ssh_command: Optional[str]
    ansible_result: Optional[dict] = None
    process_id: Optional[int] = None


@dataclass
class RunningPlaybook:
    process: subprocess.Popen
    process_id: int
    vm_vars_path: Path
    params: ProvisioningParams


class PlaybookError(RuntimeError):
    def __init__(self, message: str, stdout: str, stderr: str):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def _extract_ssh_port(playbook_output: str, vm_host: str | None = None) -> Optional[str]:
    """Extract the forwarded SSH port from playbook stdout (host port to VM port 22)."""
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


def _extract_json_block(text: str, search_start: int) -> Optional[dict]:
    """Find and parse the first complete JSON object from *search_start* using brace-depth counting."""
    brace_start = text.find("{", search_start)
    if brace_start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    for i in range(brace_start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            if in_string:
                escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                json_str = text[brace_start : i + 1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    return None
    return None


def _extract_ansible_json(stdout: str, action: str) -> Optional[dict]:
    """Extract structured JSON from Ansible output.

    Tries two strategies:
    1. Quoted fact-variable marker (``"vm_creation_data":``) — works with JSON callback format.
    2. JSON embedded in ``msg: |-`` blocks — works with YAML callback format
       (``callback_result_format = yaml`` in ansible.cfg).
    """
    fact_names = {
        "create": "vm_creation_data",
        "list": "vm_list_data",
        "start": "vm_start_data",
        "shutdown": "vm_shutdown_data",
        "destroy": "vm_destroy_data",
        "reboot": "vm_reboot_data",
        "undefine": "vm_undefine_data",
        "monitor": "vm_monitoring_data",
        "reset_password": "vm_password_reset_data",
        "lease_end": "vm_lease_end_data",
        "lease_remove": "vm_lease_remove_data",
        "check": "check_data",
    }
    fact_name = fact_names.get(action)
    if not fact_name:
        return None

    # Strategy 1: quoted marker — JSON callback format (e.g. "vm_creation_data": {…})
    marker = f'"{fact_name}":'
    idx = stdout.find(marker)
    if idx != -1:
        result = _extract_json_block(stdout, idx + len(marker))
        if result is not None:
            return result

    # Strategy 2: JSON inside msg: |- blocks — YAML callback format.
    # The playbook's "Output VM creation JSON string" task renders as:
    #     msg: |-
    #         { "action": "create", … }
    # Scan for the last such block whose JSON contains an "action" key.
    last_result = None
    for m in re.finditer(r"msg:\s*\|[-]?\s*\n", stdout):
        result = _extract_json_block(stdout, m.end())
        if result is not None and "action" in result:
            last_result = result
    return last_result


def _lookup_vm_host_ip(vm_host: str) -> Optional[str]:
    """Resolve vm_host to its ansible_host IP from the inventory file."""
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


def _inject_golden_credentials(lines: list[str]) -> None:
    """Inject golden image credentials from management-vars into the vars file."""
    from async_provisioning_service.services.management_vars import get_golden_image_credentials

    creds = get_golden_image_credentials()
    if creds:
        lines.append(f"root_ssh_filename: {creds.root_ssh_filename}")
        lines.append(f"root_ssh_password: {creds.root_ssh_password}")
        if creds.golden_image_name:
            lines.append(f"golden_image_name: {creds.golden_image_name}")
    else:
        logger.warning("Golden mode requested but credentials not found in management-vars")
        lines.append("root_ssh_filename: not_provided")
        lines.append("root_ssh_password: not_provided")


def _build_vm_vars(params: ProvisioningParams) -> str:
    """Build the YAML vars content for the ansible-playbook extra-vars file."""
    lines = [
        f"vm_host: {params.vm_host}",
        f"vm_action: {params.vm_action}",
    ]
    if params.vm_target:
        lines.append(f"vm_target: {params.vm_target}")
    if params.vm_action == "create":
        lines.append(f"image_setup_type: {params.image_setup_type}")

    if params.vm_ram is not None:
        lines.append(f"vm_ram: {params.vm_ram}")
    if params.vm_vcpus is not None:
        lines.append(f"vm_vcpus: {params.vm_vcpus}")
    if params.vm_disk_size is not None:
        lines.append(f"vm_disk_size: {params.vm_disk_size}")
    if params.vm_os_variant is not None:
        lines.append(f"vm_os_variant: {params.vm_os_variant}")

    if params.ssh_pubkey:
        escaped = params.ssh_pubkey.replace('"', '\\"')
        lines.append(f'vm_tenant_pubkey: "{escaped}"')

    if params.gpu_provisioned is not None:
        lines.append(f"gpu_provisioned: {'true' if params.gpu_provisioned else 'false'}")
    if params.vm_gpu_count is not None:
        lines.append(f"vm_gpu_count: {params.vm_gpu_count}")
    if params.vm_gpu_device:
        lines.append(f'vm_gpu_device: "{params.vm_gpu_device}"')
    if params.vm_gpu_devices:
        lines.append(f"vm_gpu_devices: {json.dumps(params.vm_gpu_devices)}")
    if params.vm_gpu_partition_size:
        lines.append(f'vm_gpu_partition_size: "{params.vm_gpu_partition_size}"')

    if params.frp_server_addr:
        lines.append(f'frp_server_addr: "{params.frp_server_addr}"')
    if params.frp_domain:
        lines.append(f'frp_domain: "{params.frp_domain}"')
    if params.frp_dashboard_password:
        lines.append(f'frp_dashboard_password: "{params.frp_dashboard_password}"')

    if params.golden_image_name:
        lines.append(f"golden_image_name: {params.golden_image_name}")
    if params.gcs_bucket_url:
        lines.append(f"gcs_bucket_url: {params.gcs_bucket_url}")
    if params.gcs_image_path:
        lines.append(f"gcs_image_path: {params.gcs_image_path}")

    if params.vm_lease_end:
        lines.append(f'vm_lease_end: "{params.vm_lease_end}"')

    if params.image_setup_type == "golden":
        _inject_golden_credentials(lines)
    else:
        lines.append("root_ssh_filename: not_provided")
        lines.append("root_ssh_password: not_provided")
    return "\n".join(lines) + "\n"


async def start_playbook(params: ProvisioningParams) -> RunningPlaybook:
    """Start ansible-playbook and return immediately with a process handle."""
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
        "-e",
        f"vm_host={params.vm_host}",
        "--limit",
        params.vm_host,
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=settings.repo_root,
    )

    logger.info("Started ansible-playbook: PID=%d, job_params=%s", process.pid, params)

    return RunningPlaybook(
        process=process,
        process_id=process.pid,
        vm_vars_path=vm_vars_path,
        params=params,
    )


async def wait_for_playbook(
    running: RunningPlaybook,
    log_callback: Optional[Callable[[str, str], None]] = None
) -> ProvisioningResult:
    """Wait for a running playbook to complete, streaming output to log_callback."""
    stdout_lines = []
    stderr_lines = []

    async def stream_output():
        last_callback = time.time()

        while True:
            if running.process.poll() is not None:
                if running.process.stdout:
                    remaining = running.process.stdout.read()
                    if remaining:
                        stdout_lines.append(remaining)
                if running.process.stderr:
                    remaining = running.process.stderr.read()
                    if remaining:
                        stderr_lines.append(remaining)
                break

            if running.process.stdout:
                try:
                    if sys.platform != 'win32':
                        readable, _, _ = select.select([running.process.stdout], [], [], 0.1)
                        if readable:
                            line = running.process.stdout.readline()
                            if line:
                                stdout_lines.append(line)
                                logger.debug("Ansible stdout: %s", line.rstrip())
                    else:
                        line = running.process.stdout.readline()
                        if line:
                            stdout_lines.append(line)
                except Exception:
                    pass

            if running.process.stderr:
                try:
                    if sys.platform != 'win32':
                        readable, _, _ = select.select([running.process.stderr], [], [], 0.1)
                        if readable:
                            line = running.process.stderr.readline()
                            if line:
                                stderr_lines.append(line)
                                logger.debug("Ansible stderr: %s", line.rstrip())
                    else:
                        line = running.process.stderr.readline()
                        if line:
                            stderr_lines.append(line)
                except Exception:
                    pass

            now = time.time()
            if log_callback and (now - last_callback) >= 2.0:
                stdout_so_far = "".join(stdout_lines)
                stderr_so_far = "".join(stderr_lines)
                try:
                    await asyncio.to_thread(log_callback, stdout_so_far, stderr_so_far)
                except Exception as e:
                    logger.warning("Log callback failed: %s", e)
                last_callback = now

            await asyncio.sleep(0.1)

    try:
        await asyncio.wait_for(
            stream_output(),
            timeout=settings.ansible_timeout_seconds
        )

        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)

        if log_callback:
            try:
                await asyncio.to_thread(log_callback, stdout, stderr)
            except Exception as e:
                logger.warning("Final log callback failed: %s", e)

        if running.process.returncode != 0:
            raise PlaybookError("Playbook failed", stdout or "", stderr or "")

    except asyncio.TimeoutError:
        running.process.kill()
        running.process.wait()
        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        raise PlaybookError("Playbook timeout", stdout or "", stderr or "")
    except PlaybookError:
        raise
    except Exception as exc:
        try:
            running.process.kill()
            running.process.wait()
        except Exception:
            pass
        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        raise PlaybookError(f"Playbook error: {exc}", stdout or "", stderr or str(exc)) from exc
    finally:
        try:
            running.vm_vars_path.unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to delete temp vars file: %s", running.vm_vars_path)

    stdout = stdout or ""
    stderr = stderr or ""
    ssh_port = _extract_ssh_port(stdout, running.params.vm_host)
    tenant_user = _extract_tenant_user(stdout, running.params.vm_host)
    vm_host_ip = _lookup_vm_host_ip(running.params.vm_host)

    ssh_command = None
    if ssh_port and tenant_user and vm_host_ip:
        ssh_command = f"ssh -i <your_private_key> -p {ssh_port} {tenant_user}@{vm_host_ip}"

    ansible_result = _extract_ansible_json(stdout, running.params.vm_action)

    return ProvisioningResult(
        stdout=stdout,
        stderr=stderr,
        ssh_port=ssh_port,
        tenant_user=tenant_user,
        vm_host_ip=vm_host_ip,
        ssh_command=ssh_command,
        ansible_result=ansible_result,
        process_id=running.process_id,
    )


def run_playbook(params: ProvisioningParams) -> ProvisioningResult:
    """Synchronous version of start_playbook + wait_for_playbook."""
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
        "-e",
        f"vm_host={params.vm_host}",
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

        process_id = process.pid
        logger.debug("Started ansible-playbook process: PID=%d", process_id)

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
    ssh_port = _extract_ssh_port(stdout, params.vm_host)
    tenant_user = _extract_tenant_user(stdout, params.vm_host)
    vm_host_ip = _lookup_vm_host_ip(params.vm_host)

    ssh_command = None
    if ssh_port and tenant_user and vm_host_ip:
        ssh_command = f"ssh -i <your_private_key> -p {ssh_port} {tenant_user}@{vm_host_ip}"

    ansible_result = _extract_ansible_json(stdout, params.vm_action)

    return ProvisioningResult(
        stdout=stdout,
        stderr=stderr,
        ssh_port=ssh_port,
        tenant_user=tenant_user,
        vm_host_ip=vm_host_ip,
        ssh_command=ssh_command,
        ansible_result=ansible_result,
        process_id=process_id if process else None,
    )
