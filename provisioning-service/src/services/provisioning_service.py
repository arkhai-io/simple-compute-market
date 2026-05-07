from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import Settings
from services.ansible_service import (
    AnsibleError,
    AnsibleResult,
    AnsibleRun,
    AnsibleService,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass
class ProvisioningParams:
    """Structured representation of a ProvisionRequest for internal use."""
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
    """Parsed result returned to JobService after a playbook completes."""
    stdout: str
    stderr: str
    ssh_port: Optional[str]
    tenant_user: Optional[str]
    vm_host_ip: Optional[str]
    ssh_command: Optional[str]
    ansible_result: Optional[dict] = None
    process_id: Optional[int] = None


# Re-export so JobService can catch a single exception type without importing
# from ansible_service directly.
PlaybookError = AnsibleError


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ProvisioningService:
    """Orchestrates the VM-operations playbook.

    Responsibilities:
    - Build the ansible extra-vars YAML file from a ``ProvisioningParams``.
    - Delegate process spawning and streaming to ``AnsibleService``.
    - Parse structured JSON output from the playbook's stdout into a
      ``ProvisioningResult``.

    This service has no subprocess imports.  All ansible invocations go
    through ``AnsibleService``, which is the sole subprocess boundary and
    the only class that needs to be mocked in tests.
    """

    def __init__(
        self,
        settings: Settings,
        ansible_service: AnsibleService,
    ) -> None:
        self._settings = settings
        self._ansible = ansible_service

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start_playbook(self, params: ProvisioningParams) -> AnsibleRun:
        """Write the vars file and start the playbook process.

        Returns an ``AnsibleRun`` handle.  Callers must pass this to
        ``await wait_for_playbook`` to collect the result.
        """
        vars_path = self._write_vars_file(params)
        return self._ansible.start_playbook(
            playbook_path=self._settings.resolved_playbook_path,
            inventory_path=self._settings.resolved_inventory_path,
            extra_vars_path=vars_path,
            limit=params.vm_host,
        )

    async def wait_for_playbook(
        self,
        run: AnsibleRun,
        params: ProvisioningParams,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> ProvisioningResult:
        """Wait for the process and parse its output into a ProvisioningResult.

        Raises ``PlaybookError`` (== ``AnsibleError``) on non-zero exit or
        timeout.  The vars file temp path is cleaned up inside AnsibleService.
        """
        result: AnsibleResult = await self._ansible.wait_for_playbook(
            run,
            timeout_seconds=self._settings.ansible_timeout_seconds,
            log_callback=log_callback,
        )
        return self._parse_result(result, params)

    # ------------------------------------------------------------------
    # Private: vars file construction
    # ------------------------------------------------------------------

    def _write_vars_file(self, params: ProvisioningParams) -> Path:
        nonce = uuid.uuid4().hex
        path = Path(f"/tmp/vm_vars_{nonce}.yml")
        path.write_text(self._build_vm_vars(params), encoding="utf-8")
        return path

    def _inject_golden_credentials(self, lines: list[str]) -> None:
        filename = str(self._settings.golden_root_ssh_filename or "").strip()
        password = str(self._settings.golden_root_ssh_password or "").strip()
        if filename and password:
            lines.append(f"root_ssh_filename: {filename}")
            lines.append(f"root_ssh_password: {password}")
            image_name = str(self._settings.golden_image_name or "").strip()
            if image_name:
                lines.append(f"golden_image_name: {image_name}")
        else:
            logger.warning(
                "Golden mode requested but golden_root_ssh_filename / "
                "golden_root_ssh_password are not configured"
            )
            lines.append("root_ssh_filename: not_provided")
            lines.append("root_ssh_password: not_provided")

    def _build_vm_vars(self, params: ProvisioningParams) -> str:
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
            lines.append(
                f"gpu_provisioned: {'true' if params.gpu_provisioned else 'false'}"
            )
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
            self._inject_golden_credentials(lines)
        else:
            lines.append("root_ssh_filename: not_provided")
            lines.append("root_ssh_password: not_provided")

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Private: output parsing
    # ------------------------------------------------------------------

    def _parse_result(
        self, result: AnsibleResult, params: ProvisioningParams
    ) -> ProvisioningResult:
        ssh_port = self._extract_ssh_port(result.stdout, params.vm_host)
        tenant_user = self._extract_tenant_user(result.stdout, params.vm_host)
        vm_host_ip = self._ansible.lookup_host_ip(params.vm_host)
        ssh_command = None
        if ssh_port and tenant_user and vm_host_ip:
            ssh_command = (
                f"ssh -i <your_private_key> -p {ssh_port} {tenant_user}@{vm_host_ip}"
            )
        ansible_result = self._extract_ansible_json(result.stdout, params.vm_action)
        return ProvisioningResult(
            stdout=result.stdout,
            stderr=result.stderr,
            ssh_port=ssh_port,
            tenant_user=tenant_user,
            vm_host_ip=vm_host_ip,
            ssh_command=ssh_command,
            ansible_result=ansible_result,
            process_id=result.process_id,
        )

    def _extract_ssh_port(
        self, playbook_output: str, vm_host: str | None = None
    ) -> Optional[str]:
        patterns = [r'"external_ssh_port":\s*"(?P<port>\d+)"']
        if vm_host:
            patterns.extend([
                rf"-p\s*(?P<port>\d{{2,5}})\s+root@{re.escape(vm_host)}",
                rf"-p\s*(?P<port>\d{{2,5}})\s+\S+@{re.escape(vm_host)}",
            ])
        patterns.append(r"-p\s*(?P<port>\d{2,5})\s+\S+@[\w\.-]+")
        for pattern in patterns:
            match = re.search(pattern, playbook_output)
            if match:
                return match.group("port")
        return None

    def _extract_tenant_user(
        self, playbook_output: str, vm_host: str | None = None
    ) -> Optional[str]:
        patterns = [r'"tenant_user":\s*"(?P<user>[^"]+)"']
        if vm_host:
            patterns.append(
                rf"-p\s*\d{{2,5}}\s+(?P<user>[A-Za-z0-9._-]+)@{re.escape(vm_host)}"
            )
        patterns.append(r"-p\s*\d{2,5}\s+(?P<user>[A-Za-z0-9._-]+)@\S+")
        for pattern in patterns:
            match = re.search(pattern, playbook_output)
            if match:
                return match.group("user")
        return None

    def _extract_json_block(self, text: str, search_start: int) -> Optional[dict]:
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
                    json_str = text[brace_start: i + 1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        return None
        return None

    def _extract_ansible_json(self, stdout: str, action: str) -> Optional[dict]:
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

        marker = f'"{fact_name}":'
        idx = stdout.find(marker)
        if idx != -1:
            result = self._extract_json_block(stdout, idx + len(marker))
            if result is not None:
                return result

        last_result = None
        for m in re.finditer(r"msg:\s*\|[-]?\s*\n", stdout):
            result = self._extract_json_block(stdout, m.end())
            if result is not None and "action" in result:
                last_result = result
        return last_result
