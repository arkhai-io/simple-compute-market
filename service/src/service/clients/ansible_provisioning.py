"""Ansible-direct provisioning client using local playbooks via subprocess.

This module mirrors the public interface of service.clients.provisioning but
executes ansible-playbook directly instead of delegating to the
async-provisioning-service HTTP API. Intended for local dev environments
where the provisioning HTTP service is not available but Ansible + a running
VM host are accessible.

Use PROVISIONING_MODE=ansible to activate this path.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Optional

# TODO(refactor): Provisioning behavior here is compute-domain specific.
# Move this logic into the compute domain package in later refactor phases.

logger = logging.getLogger(__name__)


def _cleanup_temp_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception as exc:
        logger.warning("Failed to remove temp file %s: %s", path, exc)


def _find_management_vars(project_root: Path) -> Path:
    """Return the management-vars file path, accepting either .yaml or .yml extension."""
    base = project_root / "compute-provisioning-iac/ansible/inventory/management-vars"
    for ext in (".yaml", ".yml"):
        candidate = base.with_suffix(ext)
        if candidate.exists():
            return candidate
    # Return the .yaml path unconditionally so ansible-playbook gives a clear error
    return base.with_suffix(".yaml")


def _find_project_root() -> Path:
    """Walk up the tree to locate the directory that contains compute-provisioning-iac.

    Two-pass strategy: prefer the directory that actually contains compute-provisioning-iac
    (even if that means walking past the market-temp .git root), then fall back to the
    nearest .git root if no compute-provisioning-iac sibling is found.
    """
    current = Path(__file__).resolve()
    candidates = [current] + list(current.parents)
    # First pass: find the directory that contains compute-provisioning-iac
    for parent in candidates:
        if (parent / "compute-provisioning-iac").exists():
            return parent
    # Second pass fallback: nearest .git root
    for parent in candidates:
        if (parent / ".git").exists():
            return parent
    # Last resort: go up four levels (expected repo layout)
    return current.parents[3]


def validate_ansible_prerequisites() -> list[str]:
    """Check that all files needed for ansible-mode provisioning exist.

    Returns a list of human-readable error strings (empty = all good).
    Call this at agent startup when PROVISIONING_MODE=ansible so problems are
    surfaced immediately rather than at order-fulfillment time.
    """
    errors: list[str] = []
    project_root = _find_project_root()

    required = {
        "inventory/hosts": project_root / "compute-provisioning-iac/ansible/inventory/hosts",
        "management-vars (yaml/yml)": _find_management_vars(project_root),
        "vm-operations playbook": project_root / "compute-provisioning-iac/ansible/playbooks/single-tenant/vm-operations.yaml",
    }
    for label, path in required.items():
        if not path.exists():
            errors.append(f"Missing {label}: {path}")

    return errors


def _extract_external_port(playbook_output: str, vm_host: str | None = None) -> Optional[str]:
    """Extract the external SSH port from playbook stdout."""
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
    """Extract the tenant SSH username from playbook stdout."""
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
    """Read the Ansible inventory to find the external IP for a given host."""
    project_root = _find_project_root()
    inventory_path = (project_root / "compute-provisioning-iac/ansible/inventory/hosts").resolve()

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


async def provision_machine_async(
    provisioning_service_url: str,
    params: dict[str, Any],
    *,
    timeout: int = 3600,
    poll_interval: int = 15,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Run the Ansible playbook that provisions a VM using the shared inventory and vars file.

    Mirrors the signature of service.clients.provisioning.provision_machine_async but
    executes ansible-playbook locally via asyncio.create_subprocess_exec instead of
    calling the HTTP provisioning service.

    Args:
        provisioning_service_url: Ignored; present for interface parity.
        params: Must contain 'ssh_pubkey'. May contain 'vm_host' and 'vm_target'.
        timeout: Maximum seconds to wait for the playbook to complete.
        poll_interval: Ignored; present for interface parity.
        agent_id: Ignored; present for interface parity.

    Returns:
        Dict with keys: ssh_command, ssh_port, tenant_user, vm_host_ip.

    Raises:
        subprocess.CalledProcessError if the playbook exits with a non-zero status.
    """
    ssh_pubkey = params.get("ssh_pubkey", "")
    vm_host = params.get("vm_host", "ww1")
    vm_target = params.get("vm_target", "tenant-vm")
    frp_server_addr = params.get("frp_server_addr")
    frp_domain = params.get("frp_domain")
    frp_dashboard_password = params.get("frp_dashboard_password")

    nonce = uuid.uuid4().hex
    vm_vars_path = Path(f"/tmp/vm_vars_{nonce}.yml")
    escaped_pubkey = ssh_pubkey.replace('"', '\\"')

    vm_vars_payload = (
        f"vm_host: {vm_host}\n"
        f"vm_target: {vm_target}\n"
        "vm_action: create\n"
        "vm_ram: 2048\n"
        "vm_vcpus: 2\n"
        "vm_disk_size: 25G\n"
        f'vm_tenant_pubkey: "{escaped_pubkey}"\n'
    )
    if frp_server_addr:
        vm_vars_payload += f'frp_server_addr: "{frp_server_addr}"\n'
    if frp_domain:
        vm_vars_payload += f'frp_domain: "{frp_domain}"\n'
    if frp_dashboard_password:
        vm_vars_payload += f'frp_dashboard_password: "{frp_dashboard_password}"\n'

    vm_vars_path.write_text(vm_vars_payload, encoding="utf-8")

    project_root = _find_project_root()
    management_vars_path = _find_management_vars(project_root)

    cmd = [
        "ansible-playbook",
        "-i",
        str(project_root / "compute-provisioning-iac/ansible/inventory/hosts"),
        str(project_root / "compute-provisioning-iac/ansible/playbooks/single-tenant/vm-operations.yaml"),
        "--extra-vars",
        f"@{vm_vars_path}",
        "--extra-vars",
        f"@{management_vars_path}",
        "--limit",
        vm_host,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_root),
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=float(timeout)
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise subprocess.TimeoutExpired(cmd, timeout)

        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")

        if proc.returncode != 0:
            logger.error(
                "VM provisioning playbook failed (code %s). stdout:\n%s\nstderr:\n%s",
                proc.returncode,
                stdout,
                stderr,
            )
            raise subprocess.CalledProcessError(proc.returncode, cmd, stdout, stderr)
    finally:
        _cleanup_temp_file(vm_vars_path)

    logger.info("VM provisioning playbook output:\n%s", stdout)
    if stderr:
        logger.warning("VM provisioning playbook stderr:\n%s", stderr)

    external_port = _extract_external_port(stdout, vm_host)
    if external_port:
        logger.info("External SSH port for %s: %s", vm_host, external_port)
    else:
        logger.warning("External SSH port not found in playbook output.")

    vm_host_ip = _lookup_vm_host_ip(vm_host)
    if vm_host_ip:
        logger.info("External IP for %s: %s", vm_host, vm_host_ip)
    else:
        logger.warning("Could not determine external IP for %s.", vm_host)

    tenant_user = _extract_tenant_user(stdout, vm_host)
    if tenant_user:
        logger.info("Tenant SSH user: %s", tenant_user)
    else:
        logger.warning("Tenant SSH user not found in playbook output.")

    ssh_command = None
    if external_port and vm_host_ip and tenant_user:
        ssh_command = f"ssh -i <your_private_key> -p {external_port} {tenant_user}@{vm_host_ip}"
        logger.info("SSH command: %s", ssh_command)

    return {
        "ssh_command": ssh_command,
        "ssh_port": external_port,
        "tenant_user": tenant_user,
        "vm_host_ip": vm_host_ip,
    }


async def schedule_vm_shutdown_async(
    provisioning_service_url: str,
    lease_end_utc: str,
    vm_host: str = "ww1",
    vm_target: str = "tenant-vm",
    *,
    timeout: int = 300,
    poll_interval: int = 5,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Schedule a VM shutdown by running the Ansible playbook with vm_action=lease_end.

    Mirrors the signature of service.clients.provisioning.schedule_vm_shutdown_async
    but executes ansible-playbook locally via asyncio.create_subprocess_exec.

    Args:
        provisioning_service_url: Ignored; present for interface parity.
        lease_end_utc: UTC time string for when the VM should be shut down (format: 'YYYY-MM-DD HH:MM').
        vm_host: The host where the VM is located.
        vm_target: The name of the VM to schedule for shutdown.
        timeout: Maximum seconds to wait for the playbook to complete.
        poll_interval: Ignored; present for interface parity.
        agent_id: Ignored; present for interface parity.
    """
    nonce = uuid.uuid4().hex
    vm_vars_path = Path(f"/tmp/vm_lease_vars_{nonce}.yml")
    vm_vars_payload = (
        f"vm_host: {vm_host}\n"
        f"vm_target: {vm_target}\n"
        "vm_action: lease_end\n"
        f"vm_lease_end: {lease_end_utc}\n"
    )
    vm_vars_path.write_text(vm_vars_payload, encoding="utf-8")

    project_root = _find_project_root()
    management_vars_path = _find_management_vars(project_root)

    cmd = [
        "ansible-playbook",
        "-i",
        str(project_root / "compute-provisioning-iac/ansible/inventory/hosts"),
        str(project_root / "compute-provisioning-iac/ansible/playbooks/single-tenant/vm-operations.yaml"),
        "--extra-vars",
        f"@{vm_vars_path}",
        "--extra-vars",
        f"@{management_vars_path}",
        "--limit",
        vm_host,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(project_root),
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=float(timeout)
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise subprocess.TimeoutExpired(cmd, timeout)

        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")

        if proc.returncode != 0:
            logger.error(
                "Failed to schedule VM shutdown (code %s). stdout:\n%s\nstderr:\n%s",
                proc.returncode,
                stdout,
                stderr,
            )
            raise subprocess.CalledProcessError(proc.returncode, cmd, stdout, stderr)

        logger.info("Scheduled VM shutdown for %s on %s at %s UTC.", vm_target, vm_host, lease_end_utc)
    finally:
        _cleanup_temp_file(vm_vars_path)

    logger.info("VM shutdown scheduling playbook output:\n%s", stdout)
    return {"status": "ok", "vm_host": vm_host, "vm_target": vm_target, "lease_end_utc": lease_end_utc}


async def get_vm_available_resources(
    provisioning_service_url: str,
    vm_host: str = "ww1",
    *,
    timeout: int = 120,
    poll_interval: int = 5,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Query the VM host for available GPU slots via an Ansible ad-hoc shell command.

    Runs ``virsh list --name`` on the target host and counts the number of
    running tenant VMs. A count of zero means the single GPU slot is free.

    Args:
        provisioning_service_url: Ignored; present for interface parity.
        vm_host: Ansible inventory hostname to query (e.g. "ww1").
        timeout: Maximum seconds to wait for the Ansible command to complete.
        poll_interval: Ignored; present for interface parity.
        agent_id: Ignored; present for interface parity.

    Returns:
        Dict with keys: status, vm_host, available, running_vms.

    Raises:
        subprocess.CalledProcessError: if the Ansible command exits non-zero.
    """
    project_root = _find_project_root()
    inventory_path = project_root / "compute-provisioning-iac/ansible/inventory/hosts"

    cmd = [
        "ansible",
        vm_host,
        "-i",
        str(inventory_path),
        "-m",
        "shell",
        "-a",
        "virsh list --name 2>/dev/null | grep -c . || echo 0",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(project_root),
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=float(timeout)
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout)

    stdout = stdout_bytes.decode(errors="replace").strip()
    stderr = stderr_bytes.decode(errors="replace").strip()

    if proc.returncode != 0:
        logger.error(
            "get_vm_available_resources failed (code %s) for %s. stdout:\n%s\nstderr:\n%s",
            proc.returncode,
            vm_host,
            stdout,
            stderr,
        )
        raise subprocess.CalledProcessError(proc.returncode, cmd, stdout, stderr)

    if stderr:
        logger.debug("get_vm_available_resources stderr for %s:\n%s", vm_host, stderr)

    # Ansible ad-hoc output includes a header line like "ww1 | SUCCESS | ..."
    # followed by the actual command output. Extract the last non-empty line.
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    count_str = lines[-1] if lines else "0"
    try:
        running_count = int(count_str)
    except ValueError:
        logger.warning(
            "Unexpected virsh count output for %s: %r — defaulting to 0", vm_host, count_str
        )
        running_count = 0

    logger.info(
        "get_vm_available_resources: vm_host=%s running_vms=%d available=%s",
        vm_host,
        running_count,
        running_count == 0,
    )
    return {
        "status": "ok",
        "vm_host": vm_host,
        "available": running_count == 0,
        "running_vms": running_count,
    }
