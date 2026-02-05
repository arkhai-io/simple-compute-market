import asyncio
import logging
import re
import select
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
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
    vm_lease_end: Optional[str] = None
    image_setup_type: str = "scratch"
    root_ssh_filename: Optional[str] = None
    root_ssh_password: Optional[str] = None


@dataclass
class ProvisioningResult:
    """Result of a successful playbook execution."""
    stdout: str
    stderr: str
    ssh_port: Optional[str]  # Port on VM host for SSH access to the VM
    tenant_user: Optional[str]
    vm_host_ip: Optional[str]
    ssh_command: Optional[str]
    process_id: Optional[int] = None


@dataclass
class RunningPlaybook:
    """Handle to a running ansible playbook process."""
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
    """Extract the SSH port from playbook stdout.

    This is the port on the VM host that forwards to the VM's SSH service (port 22).
    """
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
    vm_vars = (
        f"vm_host: {params.vm_host}\n"
        f"vm_target: {params.vm_target}\n"
        f"vm_action: {params.vm_action}\n"
        f"vm_ram: {params.vm_ram}\n"
        f"vm_vcpus: {params.vm_vcpus}\n"
        f"vm_disk_size: {params.vm_disk_size}\n"
        f'vm_tenant_pubkey: "{escaped_pubkey}"\n'
    )

    # Add vm_lease_end if present (for lease_end action)
    if params.vm_lease_end:
        vm_vars += f"vm_lease_end: {params.vm_lease_end}\n"

    # Add image setup type (scratch or golden)
    vm_vars += f"image_setup_type: {params.image_setup_type}\n"

    # Add golden image credentials if provided (required for golden mode)
    if params.root_ssh_filename:
        vm_vars += f"root_ssh_filename: {params.root_ssh_filename}\n"
    else:
        # Provide placeholder to prevent undefined variable errors in playbook
        vm_vars += "root_ssh_filename: not_provided\n"

    if params.root_ssh_password:
        vm_vars += f"root_ssh_password: {params.root_ssh_password}\n"
    else:
        # Provide placeholder to prevent undefined variable errors in playbook
        vm_vars += "root_ssh_password: not_provided\n"

    return vm_vars


async def start_playbook(params: ProvisioningParams) -> RunningPlaybook:
    """
    Start ansible playbook and return immediately with process handle.

    This function starts the ansible-playbook process but does NOT wait for it to complete.
    The process ID is immediately available for storage/cancellation.

    Returns:
        RunningPlaybook with process_id available for immediate storage/cancellation
    """
    # Create temp vars file
    nonce = uuid.uuid4().hex
    vm_vars_path = Path(f"/tmp/vm_vars_{nonce}.yml")
    vm_vars_path.write_text(_build_vm_vars(params), encoding="utf-8")

    # Build ansible command
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

    # Start process (non-blocking)
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
    """
    Wait for a running playbook to complete and return results.

    This function streams output in real-time and calls log_callback periodically
    with accumulated logs so they can be stored/displayed during execution.

    Args:
        running: Handle to the running playbook process
        log_callback: Optional callback function(stdout, stderr) called periodically with logs

    Returns:
        ProvisioningResult with stdout, stderr, and extracted connection info

    Raises:
        PlaybookError: If the playbook fails, times out, or encounters an error
    """
    stdout_lines = []
    stderr_lines = []

    async def stream_output():
        """Stream stdout and stderr in real-time."""
        last_callback = time.time()

        while True:
            # Check if process has finished
            if running.process.poll() is not None:
                # Read any remaining output
                if running.process.stdout:
                    remaining = running.process.stdout.read()
                    if remaining:
                        stdout_lines.append(remaining)
                if running.process.stderr:
                    remaining = running.process.stderr.read()
                    if remaining:
                        stderr_lines.append(remaining)
                break

            # Read available output (non-blocking)
            if running.process.stdout:
                try:
                    # Use select to check if data is available (Unix only)
                    if sys.platform != 'win32':
                        readable, _, _ = select.select([running.process.stdout], [], [], 0.1)
                        if readable:
                            line = running.process.stdout.readline()
                            if line:
                                stdout_lines.append(line)
                                logger.debug("Ansible stdout: %s", line.rstrip())
                    else:
                        # Windows: just try to read with timeout
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

            # Call log callback every 2 seconds with accumulated logs
            now = time.time()
            if log_callback and (now - last_callback) >= 2.0:
                stdout_so_far = "".join(stdout_lines)
                stderr_so_far = "".join(stderr_lines)
                try:
                    await asyncio.to_thread(log_callback, stdout_so_far, stderr_so_far)
                except Exception as e:
                    logger.warning("Log callback failed: %s", e)
                last_callback = now

            # Small sleep to avoid busy-waiting
            await asyncio.sleep(0.1)

    try:
        # Stream output with timeout
        await asyncio.wait_for(
            stream_output(),
            timeout=settings.ansible_timeout_seconds
        )

        # Final callback with all logs
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
        # Try to kill and get any output
        try:
            running.process.kill()
            running.process.wait()
        except Exception:
            pass
        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
        raise PlaybookError(f"Playbook error: {exc}", stdout or "", stderr or str(exc)) from exc
    finally:
        # Cleanup temp file
        try:
            running.vm_vars_path.unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to delete temp vars file: %s", running.vm_vars_path)

    # Extract results from output
    stdout = stdout or ""
    stderr = stderr or ""
    ssh_port = _extract_ssh_port(stdout, running.params.vm_host)
    tenant_user = _extract_tenant_user(stdout, running.params.vm_host)
    vm_host_ip = _lookup_vm_host_ip(running.params.vm_host)

    ssh_command = None
    if ssh_port and tenant_user and vm_host_ip:
        ssh_command = f"ssh -i <your_private_key> -p {ssh_port} {tenant_user}@{vm_host_ip}"

    return ProvisioningResult(
        stdout=stdout,
        stderr=stderr,
        ssh_port=ssh_port,
        tenant_user=tenant_user,
        vm_host_ip=vm_host_ip,
        ssh_command=ssh_command,
        process_id=running.process_id,  # Already captured earlier
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
    ssh_port = _extract_ssh_port(stdout, params.vm_host)
    tenant_user = _extract_tenant_user(stdout, params.vm_host)
    vm_host_ip = _lookup_vm_host_ip(params.vm_host)

    ssh_command = None
    if ssh_port and tenant_user and vm_host_ip:
        ssh_command = f"ssh -i <your_private_key> -p {ssh_port} {tenant_user}@{vm_host_ip}"

    return ProvisioningResult(
        stdout=stdout,
        stderr=stderr,
        ssh_port=ssh_port,
        tenant_user=tenant_user,
        vm_host_ip=vm_host_ip,
        ssh_command=ssh_command,
        process_id=process_id if process else None,
    )
