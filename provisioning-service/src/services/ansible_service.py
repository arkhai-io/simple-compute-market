"""Single subprocess boundary for all Ansible invocations.

Responsibilities
----------------
* Spawn and stream ``ansible-playbook`` processes (``start_playbook`` /
  ``wait_for_playbook``).
* Build the extra-vars YAML file consumed by the VM-operations playbook
  (``build_vars_file``).  This was previously ``ProvisioningService._write_vars_file``.
* Parse structured JSON output from playbook stdout (``parse_playbook_result``).
  Previously ``ProvisioningService._parse_result`` and helpers.
* Parse the Ansible INI inventory (``parse_inventory``, ``lookup_host_ip``).
* Run ``ansible -m ping`` connectivity checks (``check_connectivity``).

This is the only class in the codebase that spawns ansible / ansible-playbook
subprocesses.  All other services depend on this class and work with
``AnsibleRun`` / ``AnsibleRunResult`` — they never touch subprocess directly.
Mocking ``AnsibleService`` in tests is sufficient to isolate all external
Ansible I/O.
"""

from __future__ import annotations

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
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import Settings
from models.ansible import (
    ConnectivityResult,
    InventoryHost,
    InventoryResponse,
)
from models.jobs_model import AnsibleJobParams, AnsibleRunResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Process handle types — owned by AnsibleService, consumed by callers
# ---------------------------------------------------------------------------


@dataclass
class AnsibleRun:
    """Handle to a running ansible-playbook process."""

    process: subprocess.Popen
    process_id: int
    vars_path: Path


@dataclass
class AnsibleResult:
    """Captured output from a completed ansible-playbook invocation."""

    stdout: str
    stderr: str
    process_id: int


class AnsibleError(RuntimeError):
    """Raised when ansible-playbook exits non-zero or times out."""

    def __init__(self, message: str, stdout: str, stderr: str):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AnsibleService:
    """Single subprocess boundary + Ansible support layer.

    See module docstring for the full list of responsibilities.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # Playbook execution — async streaming interface
    # ------------------------------------------------------------------

    def start_playbook(
        self,
        playbook_path: Path,
        inventory_path: Path,
        extra_vars_path: Path,
        limit: str,
        extra_cli_vars: dict[str, str] | None = None,
    ) -> AnsibleRun:
        """Spawn ansible-playbook and return immediately with a process handle.

        The caller must pass the returned handle to ``await wait_for_playbook``
        to collect the result.  ``extra_vars_path`` is cleaned up inside
        ``wait_for_playbook``.
        """
        cmd = [
            "ansible-playbook",
            "-i", str(inventory_path),
            str(playbook_path),
            "--extra-vars", f"@{extra_vars_path}",
            "--limit", limit,
        ]
        for k, v in (extra_cli_vars or {}).items():
            cmd += ["-e", f"{k}={v}"]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        logger.info(
            "Started ansible-playbook: PID=%d cmd=%s", process.pid, " ".join(cmd)
        )

        return AnsibleRun(
            process=process,
            process_id=process.pid,
            vars_path=extra_vars_path,
        )

    async def wait_for_playbook(
        self,
        run: AnsibleRun,
        timeout_seconds: int,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> AnsibleResult:
        """Wait for a running playbook to finish, streaming output to log_callback.

        Cleans up ``run.vars_path`` on exit regardless of success or failure.
        Raises ``AnsibleError`` on non-zero exit or timeout.
        """
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        async def _stream() -> None:
            last_callback = time.time()
            while True:
                if run.process.poll() is not None:
                    if run.process.stdout:
                        tail = run.process.stdout.read()
                        if tail:
                            stdout_lines.append(tail)
                    if run.process.stderr:
                        tail = run.process.stderr.read()
                        if tail:
                            stderr_lines.append(tail)
                    break

                if run.process.stdout:
                    try:
                        if sys.platform != "win32":
                            readable, _, _ = select.select(
                                [run.process.stdout], [], [], 0.1
                            )
                            if readable:
                                line = run.process.stdout.readline()
                                if line:
                                    stdout_lines.append(line)
                                    logger.debug("ansible stdout: %s", line.rstrip())
                        else:
                            line = run.process.stdout.readline()
                            if line:
                                stdout_lines.append(line)
                    except Exception:
                        pass

                if run.process.stderr:
                    try:
                        if sys.platform != "win32":
                            readable, _, _ = select.select(
                                [run.process.stderr], [], [], 0.1
                            )
                            if readable:
                                line = run.process.stderr.readline()
                                if line:
                                    stderr_lines.append(line)
                                    logger.debug("ansible stderr: %s", line.rstrip())
                        else:
                            line = run.process.stderr.readline()
                            if line:
                                stderr_lines.append(line)
                    except Exception:
                        pass

                now = time.time()
                if log_callback and (now - last_callback) >= 2.0:
                    try:
                        await asyncio.to_thread(
                            log_callback,
                            "".join(stdout_lines),
                            "".join(stderr_lines),
                        )
                    except Exception as exc:
                        logger.warning("Log callback failed: %s", exc)
                    last_callback = now

                await asyncio.sleep(0.1)

        try:
            await asyncio.wait_for(_stream(), timeout=timeout_seconds)

            stdout = "".join(stdout_lines)
            stderr = "".join(stderr_lines)

            if log_callback:
                try:
                    await asyncio.to_thread(log_callback, stdout, stderr)
                except Exception as exc:
                    logger.warning("Final log callback failed: %s", exc)

            if run.process.returncode != 0:
                raise AnsibleError("Playbook failed", stdout, stderr)

        except asyncio.TimeoutError:
            run.process.kill()
            run.process.wait()
            stdout = "".join(stdout_lines)
            stderr = "".join(stderr_lines)
            raise AnsibleError("Playbook timed out", stdout, stderr)
        except AnsibleError:
            raise
        except Exception as exc:
            try:
                run.process.kill()
                run.process.wait()
            except Exception:
                pass
            stdout = "".join(stdout_lines)
            stderr = "".join(stderr_lines)
            raise AnsibleError(
                f"Playbook error: {exc}", stdout, stderr or str(exc)
            ) from exc
        finally:
            try:
                run.vars_path.unlink(missing_ok=True)
            except Exception:
                logger.warning(
                    "Failed to delete temp vars file: %s", run.vars_path
                )

        return AnsibleResult(
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
            process_id=run.process_id,
        )

    # ------------------------------------------------------------------
    # Vars file construction (formerly ProvisioningService._write_vars_file)
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

    def _build_vm_vars(self, params: AnsibleJobParams) -> str:
        """Render the YAML string for the extra-vars file."""
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
        if params.vm_expiry_at:
            # Passed to Ansible as vm_lease_end; renamed vm_expiry_at on the API side.
            # TODO(lease-watchdog): remove this Ansible pass-through when Item 2
            # (DB-driven lease watchdog) is implemented.
            lines.append(f'vm_lease_end: "{params.vm_expiry_at}"')

        if params.image_setup_type == "golden":
            self._inject_golden_image_credentials(lines)
        else:
            lines.append("root_ssh_filename: not_provided")
            lines.append("root_ssh_password: not_provided")

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
    # Output parsing (formerly ProvisioningService._parse_result)
    # ------------------------------------------------------------------

    def parse_playbook_result(
        self, result: AnsibleResult, params: AnsibleJobParams
    ) -> AnsibleRunResult:
        """Parse raw ``AnsibleResult`` output into a structured ``AnsibleRunResult``."""
        ssh_port = self._extract_ssh_port(result.stdout, params.vm_host)
        tenant_user = self._extract_tenant_user(result.stdout, params.vm_host)
        vm_host_ip = self.lookup_host_ip(params.vm_host)
        ssh_command = None
        if ssh_port and tenant_user and vm_host_ip:
            ssh_command = (
                f"ssh -i <your_private_key> -p {ssh_port} {tenant_user}@{vm_host_ip}"
            )
        ansible_result = self._extract_ansible_json(result.stdout, params.vm_action)
        return AnsibleRunResult(
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

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def parse_inventory(self, search: str | None = None) -> list[InventoryHost]:
        """Parse the Ansible INI inventory and return a list of hosts.

        Skips group headers (``[group_name]``) and comment lines.
        If *search* is provided, only hosts whose name contains the
        string (case-insensitive) are returned.

        Raises ``FileNotFoundError`` if the inventory file does not exist.
        """
        inventory_path = self._settings.resolved_inventory_path
        if not inventory_path.exists():
            raise FileNotFoundError(f"Inventory not found at {inventory_path}")

        hosts: list[InventoryHost] = []
        for line in inventory_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("["):
                continue

            parts = stripped.split()
            name = parts[0]

            if search and search.lower() not in name.lower():
                continue

            host_vars: dict[str, str] = {}
            for part in parts[1:]:
                if "=" in part:
                    k, _, v = part.partition("=")
                    host_vars[k] = v

            hosts.append(
                InventoryHost(
                    name=name,
                    ansible_host=host_vars.pop("ansible_host", None),
                    vars=host_vars,
                )
            )

        return hosts

    def get_inventory(self, search: str | None = None) -> InventoryResponse:
        """Return an ``InventoryResponse`` for the current inventory file."""
        hosts = self.parse_inventory(search=search)
        return InventoryResponse(
            inventory_path=str(self._settings.resolved_inventory_path),
            hosts=hosts,
        )

    def lookup_host_ip(self, vm_host: str) -> Optional[str]:
        """Return the ``ansible_host`` value for *vm_host* from the inventory.

        Returns ``None`` if the host is not found or the inventory is unreadable.
        """
        try:
            for host in self.parse_inventory():
                if host.name == vm_host:
                    return host.ansible_host
        except Exception as exc:
            logger.warning("Failed to read inventory: %s", exc)
        logger.warning("No ansible_host found for %s in inventory", vm_host)
        return None

    # ------------------------------------------------------------------
    # Connectivity check
    # ------------------------------------------------------------------

    async def check_connectivity(self, host: str) -> ConnectivityResult:
        """Run ``ansible -m ping`` against a single named inventory host.

        Returns a ``ConnectivityResult`` with ``reachable=False`` if the
        host is unreachable — not a 404.  The caller should verify the
        host exists in the inventory before calling this.
        """
        cmd = [
            "ansible",
            "-i", str(self._settings.resolved_inventory_path),
            host,
            "-m", "ping",
        ]

        logger.info("Running connectivity check: %s", " ".join(cmd))

        def _run() -> tuple[int, str, str]:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._settings.ansible_timeout_seconds,
            )
            return result.returncode, result.stdout, result.stderr

        try:
            returncode, stdout, stderr = await asyncio.wait_for(
                asyncio.to_thread(_run),
                timeout=self._settings.ansible_timeout_seconds + 5,
            )
        except asyncio.TimeoutError:
            return ConnectivityResult(
                host=host, reachable=False, detail="Connectivity check timed out"
            )
        except Exception as exc:
            return ConnectivityResult(
                host=host, reachable=False, detail=f"Failed to run ansible ping: {exc}"
            )

        reachable = returncode == 0
        detail = stdout.strip() if reachable else (stderr.strip() or stdout.strip())
        logger.info("Connectivity check for %s: reachable=%s", host, reachable)
        return ConnectivityResult(host=host, reachable=reachable, detail=detail)
