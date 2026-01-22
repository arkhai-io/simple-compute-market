import logging
import re
import subprocess
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    """Walk up the tree to locate the repo root (uses compute-provisioning-iac or .git as sentinels)."""
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "compute-provisioning-iac").exists():
            return parent
        if (parent / ".git").exists():
            return parent
    # Fallback: go up four levels (expected repo layout)
    return current.parents[3]


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


def run_vm_provisioning_playbook(ssh_pubkey: str, vm_host: str = "vm1", vm_target: str = "tenant-vm") -> Optional[str]:
    """
    Run the Ansible playbook that provisions a VM using the shared inventory and vars file.

    Args:
        ssh_pubkey: The SSH public key to inject into the VM.
        vm_host: The host where the VM is located.
        vm_target: The name of the VM to schedule for shutdown.

    Returns:
        SSH command string if all connection details were found, otherwise None.

    Raises:
        subprocess.CalledProcessError if the playbook exits with a non-zero status.
    """
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

    vm_vars_path.write_text(vm_vars_payload, encoding="utf-8")

    project_root = _find_project_root()

    management_vars_path = project_root / "compute-provisioning-iac/ansible/inventory/management-vars.yml"

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
        "kvm_hosts"
    ]
    cwd = project_root

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except subprocess.CalledProcessError as exc:
        logger.error(
            "VM provisioning playbook failed (code %s). stdout:\n%s\nstderr:\n%s",
            exc.returncode,
            exc.stdout,
            exc.stderr,
        )
        raise

    logger.info("VM provisioning playbook output:\n%s", result.stdout)
    if result.stderr:
        logger.warning("VM provisioning playbook stderr:\n%s", result.stderr)

    external_port = _extract_external_port(result.stdout, vm_host)
    if external_port:
        logger.info("External SSH port for %s: %s", vm_host, external_port)
    else:
        logger.warning("External SSH port not found in playbook output.")

    vm_host_ip = _lookup_vm_host_ip(vm_host)
    if vm_host_ip:
        logger.info("External IP for %s: %s", vm_host, vm_host_ip)
    else:
        logger.warning("Could not determine external IP for %s.", vm_host)

    tenant_user = _extract_tenant_user(result.stdout, vm_host)
    if tenant_user:
        logger.info("Tenant SSH user: %s", tenant_user)
    else:
        logger.warning("Tenant SSH user not found in playbook output.")

    ssh_command = None
    if external_port and vm_host_ip and tenant_user:
        ssh_command = f"ssh -i <your_private_key> -p {external_port} {tenant_user}@{vm_host_ip}"
        logger.info("SSH command: %s", ssh_command)

    return ssh_command


def schedule_vm_shutdown(lease_end_utc: str, vm_host: str = "vm1", vm_target: str = "tenant-vm") -> None:
    """
    Schedule a VM shutdown by setting its lease end time.

    Args:
        lease_end_utc: The UTC time string for when the VM should be shut down (format: 'YYYY-MM-DD HH:MM').
        vm_host: The host where the VM is located.
        vm_target: The name of the VM to schedule for shutdown.
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

    management_vars_path = project_root / "compute-provisioning-iac/ansible/inventory/management-vars.yml"

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
        "kvm_hosts",
    ]
    cwd = project_root

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        logger.info("Scheduled VM shutdown for %s on %s at %s UTC.", vm_target, vm_host, lease_end_utc)
    except subprocess.CalledProcessError as exc:
        logger.error(
            "Failed to schedule VM shutdown (code %s). stdout:\n%s\nstderr:\n%s",
            exc.returncode,
            exc.stdout,
            exc.stderr,
        )
        raise

    logger.info("VM shutdown scheduling playbook output:\n%s", result.stdout)
