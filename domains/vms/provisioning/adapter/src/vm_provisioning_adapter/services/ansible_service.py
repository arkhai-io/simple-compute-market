"""The Ansible runner, specialised for VM and bare-metal jobs.

``AnsibleService`` adds to ``compute_provisioning_ansible.AnsibleRunner`` what
VM and bare-metal jobs mean to Ansible:

* the extra-vars YAML file a job's playbook reads (``build_vars_file``), and the
  built-in variable names it reserves (``reserved_var_keys``);
* parsing a playbook's output into a structured ``AnsibleRunResult``
  (``parse_playbook_result``).

Spawning processes, inventory rendering, redaction, and connectivity checks are
the runner's.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from arkhai_bare_metal import (
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
)
from compute_provisioning_ansible.runner import AnsibleResult, AnsibleRunner
from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams, AnsibleRunResult

logger = logging.getLogger(__name__)


class AnsibleService(AnsibleRunner):
    """The Ansible runner with VM and bare-metal job variables and results.

    See the module docstring for what this adds to ``AnsibleRunner``.
    """

    # ------------------------------------------------------------------
    # Vars file construction
    # ------------------------------------------------------------------

    def build_vars_file(self, params: AnsibleJobParams) -> Path:
        """Write an extra-vars YAML file for the VM-operations playbook.

        Returns the ``Path`` to the temp file.  The caller (via
        ``wait_for_playbook``) is responsible for cleanup.
        """
        nonce = uuid.uuid4().hex
        path = Path(f"/tmp/vm_vars_{nonce}.yml")
        path.write_text(self._build_vm_vars(params), encoding="utf-8")
        return path

    def _build_builtin_var_lines(self, params: AnsibleJobParams) -> list[str]:
        """Built-in (non-provider-extra) YAML lines for the given params.

        Shared by ``_build_vm_vars`` (actual rendering) and
        ``reserved_var_keys`` (synchronous pre-dispatch validation) so the
        two cannot disagree about which fields are built in.
        """
        lines = [
            f"host_id: {params.host_id}",
            f"vm_action: {params.vm_action}",
            f"offering_mode: {params.offering_mode}",
            f"executor_action: {params.executor_action}",
            f"executor_target: {params.executor_target}",
        ]
        if params.executor_ref:
            lines.append(f"executor_ref: {json.dumps(params.executor_ref)}")
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
        # Relay inputs. The token is a credential and reaches the playbook the
        # same way every other job variable does; the redaction pattern above
        # is what keeps it out of logged command lines. The remote port is
        # supplied, never chosen: allocation belongs to the service, which is
        # also what can reclaim it when the VM's life ends by any path.
        if params.relay_addr:
            lines.append(f'frp_server_addr: "{params.relay_addr}"')
        if params.relay_port:
            lines.append(f"frp_server_port: {params.relay_port}")
        if params.relay_token:
            lines.append(f'frp_auth_token: "{params.relay_token}"')
        if params.vm_remote_port:
            lines.append(f"vm_remote_port: {params.vm_remote_port}")
        if params.golden_image_name:
            lines.append(f"golden_image_name: {params.golden_image_name}")
        if params.gcs_bucket_url:
            lines.append(f"gcs_bucket_url: {params.gcs_bucket_url}")
        if params.gcs_image_path:
            lines.append(f"gcs_image_path: {params.gcs_image_path}")
        if params.escrow_uid:
            lines.append(f'escrow_uid: "{params.escrow_uid}"')
        if params.physical_host_id:
            lines.append(f'physical_host_id: "{params.physical_host_id}"')
        if params.ssh_user:
            lines.append(f'bare_metal_ssh_user: "{params.ssh_user}"')
        if params.ssh_public_key:
            escaped = params.ssh_public_key.replace('"', '\\"')
            lines.append(f'bare_metal_ssh_public_key: "{escaped}"')
        if params.access_ref:
            lines.append(f"bare_metal_access_ref: {json.dumps(params.access_ref)}")
        if params.bare_metal_reclaim_policy:
            lines.append(
                f'bare_metal_reclaim_policy: "{params.bare_metal_reclaim_policy}"'
            )
        if params.image_setup_type == "golden":
            self._inject_golden_image_credentials(lines)
        else:
            lines.append("root_ssh_filename: not_provided")
            lines.append("root_ssh_password: not_provided")
        return lines

    def reserved_var_keys(self, params: AnsibleJobParams) -> frozenset[str]:
        """Built-in variable keys that would be emitted for these params.

        Ignores ``params.provider_extra_vars`` entirely — this answers
        "what's reserved", independent of what a caller is proposing to
        merge in. Callers validate proposed extra-vars against this
        *before* setting them on the params passed to ``submit()``, so a
        collision is rejected synchronously rather than only surfacing
        when the background job worker renders the vars file.
        """
        return frozenset(
            line.split(":", 1)[0].strip()
            for line in self._build_builtin_var_lines(params)
        )

    def _build_vm_vars(self, params: AnsibleJobParams) -> str:
        """Render the YAML string for the extra-vars file."""
        lines = self._build_builtin_var_lines(params)

        if params.provider_extra_vars:
            # Built-in job identity and sizing fields are authoritative, so a colliding
            # key is a pool-configuration error, not a silent override. This
            # is a defensive second check: AnsibleFulfillmentProvider is
            # expected to have already validated via reserved_var_keys()
            # before submit(), but this path is reachable from any caller of
            # build_vars_file, not just that provider.
            built_in_keys = {line.split(":", 1)[0].strip() for line in lines}
            colliding = sorted(set(params.provider_extra_vars) & built_in_keys)
            if colliding:
                raise ValueError(
                    "provider_extra_vars collide with built-in job variables: "
                    f"{', '.join(colliding)}"
                )
            for key in sorted(params.provider_extra_vars):
                lines.append(f"{key}: {json.dumps(params.provider_extra_vars[key])}")

        return "\n".join(lines) + "\n"

    def _inject_golden_image_credentials(self, lines: list[str]) -> None:
        """Append golden image root credentials to the vars YAML lines.

        Golden image credentials (ssh filename + password) are baked into the
        image at Packer build time and output to ``management-vars.yaml`` by the
        ``golden-image-build`` Ansible role.  They are loaded into the service
        config via the standard profile system (``config-production.yml`` or
        equivalent).

        TODO(management-vars): evaluate piping management-vars.yaml into a
        Kubernetes Secret at image-build time so the format stays compatible
        with the dynaconf profile loader (YAML key names must match settings.toml).
        """
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

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    def parse_playbook_result(
        self,
        result: AnsibleResult,
        params: AnsibleJobParams,
        tenant_address: str | None = None,
    ) -> AnsibleRunResult:
        """Parse raw ``AnsibleResult`` output into a structured ``AnsibleRunResult``.

        ``tenant_address`` is the address buyers use to reach the host, which
        the caller resolves from the registered host record. It becomes
        ``host_ip`` in the returned connection info; nothing here reads an
        inventory file for it.
        """
        ssh_port = self._extract_ssh_port(result.stdout, params.host_id)
        tenant_user = self._extract_tenant_user(result.stdout, params.host_id)
        host_ip = tenant_address
        ssh_command = None
        if ssh_port and tenant_user and host_ip:
            ssh_command = (
                f"ssh -i <your_private_key> -p {ssh_port} {tenant_user}@{host_ip}"
            )
        ansible_result = self._extract_ansible_json(result.stdout, params.vm_action)
        return AnsibleRunResult(
            stdout=result.stdout,
            stderr=result.stderr,
            ssh_port=ssh_port,
            tenant_user=tenant_user,
            host_ip=host_ip,
            ssh_command=ssh_command,
            ansible_result=ansible_result,
            process_id=result.process_id,
        )

    def _extract_ssh_port(
        self, playbook_output: str, host_id: str | None = None
    ) -> Optional[str]:
        patterns = [r'"external_ssh_port":\s*"(?P<port>\d+)"']
        if host_id:
            patterns.extend([
                rf"-p\s*(?P<port>\d{{2,5}})\s+root@{re.escape(host_id)}",
                rf"-p\s*(?P<port>\d{{2,5}})\s+\S+@{re.escape(host_id)}",
            ])
        patterns.append(r"-p\s*(?P<port>\d{2,5})\s+\S+@[\w\.-]+")
        for pattern in patterns:
            match = re.search(pattern, playbook_output)
            if match:
                return match.group("port")
        return None

    def _extract_tenant_user(
        self, playbook_output: str, host_id: str | None = None
    ) -> Optional[str]:
        patterns = [r'"tenant_user":\s*"(?P<user>[^"]+)"']
        if host_id:
            patterns.append(
                rf"-p\s*\d{{2,5}}\s+(?P<user>[A-Za-z0-9._-]+)@{re.escape(host_id)}"
            )
        patterns.append(r"-p\s*\d{2,5}\s+(?P<user>[A-Za-z0-9._-]+)@\S+")
        for pattern in patterns:
            match = re.search(pattern, playbook_output)
            if match:
                return match.group("user")
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
            "vm_remove": "vm_remove_data",
            NODE_GRANT_ACCESS_ACTION: "node_grant_access_data",
            NODE_RECLAIM_ACCESS_ACTION: "node_reclaim_access_data",
            "check": "check_data",
        }
        fact_name = fact_names.get(action)
        if not fact_name:
            return None

        marker = f'"{fact_name}":'
        idx = stdout.find(marker)
        if idx != -1:
            result = self.extract_json_block(stdout, idx + len(marker))
            if result is not None:
                return result

        last_result = None
        for m in re.finditer(r"msg:\s*\|[-]?\s*\n", stdout):
            result = self.extract_json_block(stdout, m.end())
            if result is not None and "action" in result:
                last_result = result
        return last_result

    # ------------------------------------------------------------------
    # Connectivity check
    # ------------------------------------------------------------------
