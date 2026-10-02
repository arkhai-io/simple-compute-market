"""Runs a provisioning job as an Ansible playbook against its registered host.

``AnsibleJobExecutor`` is the job executor for every Ansible-run action: the job
authority hands it a job's stored parameters and the host the job runs against,
and it renders the variables and inventory, runs the playbook, and reports one
outcome. Everything the job authority must not know lives here: playbooks,
inventory, process ids, the facts a playbook prints, which errors are worth
retrying, and redaction of what is reported.

The host arrives as an ``ExecutionHost`` whose connection is an ``ssh``
envelope; the runner renders its inventory from that connection alone, so a job
runs only against the registered host record it names.
"""

from __future__ import annotations

import copy
import logging
import os
import signal
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compute_provisioning.contracts import (
    CredentialEnvelope,
    ProvisioningErrorEnvelope,
    ResultEnvelope,
)
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.jobs import JobFailure, JobOutcome, JobRun, JobSuccess

from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams, AnsibleRunResult
from vm_provisioning_adapter.services.ansible_service import (
    AnsibleError,
    redact_ansible_output,
)

logger = logging.getLogger(__name__)

SSH_CONNECTION_KIND = "ssh"
SSH_CONNECTION_VERSION = 1
_SSH_CONNECTION_FIELDS = (
    "ssh_host",
    "public_host",
    "ssh_port",
    "ssh_user",
    "ssh_key_type",
    "ssh_key_value",
)
# The roles a playbook's ``authentication`` fact may carry, in the order their
# credentials are reported.
_CREDENTIAL_ROLES = ("root", "tenant")
_CREDENTIAL_FIELDS = ("password", "ssh_commands", "ssh_key_path_host", "key_type")


def execution_host_from_record(host: Any) -> ExecutionHost:
    """The execution host for a registered host record with an SSH connection."""

    return ExecutionHost(
        host_id=str(host.host_id),
        pool_id=getattr(host, "pool_id", None),
        connection=ConnectionEnvelope(
            kind=SSH_CONNECTION_KIND,
            version=SSH_CONNECTION_VERSION,
            payload={name: getattr(host, name, None) for name in _SSH_CONNECTION_FIELDS},
        ),
    )


@dataclass(frozen=True)
class _InventoryHost:
    """The host attributes the runner renders one inventory line from."""

    host_id: str
    ssh_host: str
    public_host: str | None
    ssh_port: int
    ssh_user: str
    ssh_key_type: str
    ssh_key_value: str

    @classmethod
    def from_execution_host(cls, host: ExecutionHost) -> "_InventoryHost":
        connection = host.connection
        if connection.kind != SSH_CONNECTION_KIND:
            raise ValueError(
                f"host {host.host_id!r} has a {connection.kind!r} connection; "
                "an Ansible job reaches its host over ssh"
            )
        return cls(host_id=host.host_id, **{
            name: connection.payload.get(name) for name in _SSH_CONNECTION_FIELDS
        })


class AnsibleJobExecutor:
    """One Ansible runner and the playbook it runs for the actions it is registered for.

    ``non_retryable_errors`` are operator-configured substrings: a failure whose
    message contains one is reported as not retryable. ``relay_resolver``, when
    given, fills a referenced relay's address and token into the parameters
    immediately before the variables file is written, so the token never enters
    the job's stored parameters and a rotation takes effect on a retry.
    """

    def __init__(
        self,
        runner: Any,
        playbook_path: Any,
        *,
        settings: Any,
        relay_resolver: Any = None,
    ) -> None:
        self._runner = runner
        self._playbook_path = playbook_path
        self._settings = settings
        self._relay_resolver = relay_resolver

    @property
    def runner(self) -> Any:
        return self._runner

    @property
    def rules(self) -> Any:
        """The mock mechanism's rules when the runner is a mock, else ``None``."""
        return getattr(self._runner, "rules", None)

    def reserved_var_keys(self, params: AnsibleJobParams) -> frozenset[str]:
        """Built-in variable keys the runner would emit for these parameters."""
        return self._runner.reserved_var_keys(params)

    async def execute(self, run: JobRun) -> JobOutcome:
        params = self.build_params(run.parameters)
        if self._relay_resolver is not None:
            params = self._relay_resolver.resolve_into(params)
        host = _InventoryHost.from_execution_host(run.host)
        runner = self._runner
        vars_path = runner.build_vars_file(params)
        inventory_path = runner.write_inventory([host])
        try:
            # Buyers may reach the host on a different network than the
            # provisioner does; with no public address configured, the
            # connection address is the one there is.
            tenant_address = host.public_host or host.ssh_host
            playbook_run = runner.start_playbook(
                playbook_path=params.playbook_path or self._playbook_path,
                inventory_path=inventory_path,
                extra_vars_path=vars_path,
                limit=params.host_id,
            )
            # The programmable mock matches its rules against the run's
            # parameters; a real run ignores the attribute.
            playbook_run._params = params  # type: ignore[attr-defined]
            run.report_handle({"pid": playbook_run.process_id})
            logger.info("Job %s running with PID=%d", run.job_id, playbook_run.process_id)

            def log_callback(stdout: str, stderr: str) -> None:
                run.report_logs(self.redact(_joined(stdout, stderr)))

            try:
                playbook_result = await runner.wait_for_playbook(
                    playbook_run,
                    timeout_seconds=self._settings.ansible_timeout_seconds,
                    log_callback=log_callback,
                )
                run_result: AnsibleRunResult = runner.parse_playbook_result(
                    playbook_result, params, tenant_address=tenant_address
                )
            except AnsibleError as exc:
                message = str(exc)
                return JobFailure(
                    error=ProvisioningErrorEnvelope(
                        code="execution_failed",
                        message=message,
                        retryable=self.is_retryable(message),
                    ),
                    logs=self.redact(_joined(exc.stdout, exc.stderr)),
                )
            payload = self.build_result_payload(run_result)
            value, credentials = self.split_credentials(payload, run.offering_mode)
            return JobSuccess(
                result=ResultEnvelope(
                    offering_mode=run.offering_mode,
                    result_kind=run.action,
                    value=value,
                ),
                credentials=credentials,
                logs=self.redact(_joined(run_result.stdout, run_result.stderr)),
            )
        finally:
            try:
                Path(inventory_path).unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Failed to remove temp inventory %s: %s", inventory_path, exc)

    async def cancel(self, handle: Mapping[str, Any]) -> None:
        pid = int(handle["pid"])
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("Sent SIGTERM to process %d", pid)
        except ProcessLookupError:
            logger.warning("Process %d not found (already terminated)", pid)

    # ------------------------------------------------------------------
    # Interpretation of a job's parameters and a playbook's output
    # ------------------------------------------------------------------

    def is_retryable(self, message: str) -> bool:
        lowered = message.lower()
        return not any(
            pattern.lower() in lowered
            for pattern in self._settings.non_retryable_errors
        )

    @staticmethod
    def redact(logs: str) -> str:
        """Scrub credential-shaped values; see ``redact_ansible_output``."""
        return redact_ansible_output(logs)

    def build_params(self, params: Mapping[str, Any]) -> AnsibleJobParams:
        """Reconstruct ``AnsibleJobParams`` from a job's stored parameters."""
        executor_action = params.get("executor_action") or params.get(
            "vm_action", "create"
        )
        executor_target = params.get("executor_target") or params.get("vm_target")
        return AnsibleJobParams(
            host_id=params.get(
                "host_id",
                executor_target or self._settings.default_host_id,
            ),
            vm_target=params.get("vm_target"),
            vm_action=params.get("vm_action") or executor_action,
            offering_mode=params["offering_mode"],
            executor_action=executor_action,
            executor_target=executor_target,
            executor_ref=params.get("executor_ref"),
            image_setup_type=params.get("image_setup_type", "scratch"),
            vm_ram=params.get("vm_ram"),
            vm_vcpus=params.get("vm_vcpus"),
            vm_disk_size=params.get("vm_disk_size"),
            vm_os_variant=params.get("vm_os_variant"),
            ssh_pubkey=params.get("ssh_pubkey"),
            gpu_provisioned=params.get("gpu_provisioned"),
            vm_gpu_count=params.get("vm_gpu_count"),
            vm_gpu_device=params.get("vm_gpu_device"),
            vm_gpu_devices=params.get("vm_gpu_devices"),
            vm_gpu_partition_size=params.get("vm_gpu_partition_size"),
            # No settings fallback. Relay location is a property of the relay a
            # pool references, resolved at dispatch; a service-wide default
            # would let a job reach a relay its pool does not name, and would
            # silently substitute one relay's window for another's.
            # Only the reference and the leased port come from stored params.
            # The address and token are absent by construction and are filled
            # in immediately before the vars file is written.
            relay_id=params.get("relay_id"),
            vm_remote_port=params.get("vm_remote_port"),
            golden_image_name=params.get("golden_image_name"),
            gcs_bucket_url=params.get("gcs_bucket_url"),
            gcs_image_path=params.get("gcs_image_path"),
            escrow_uid=params.get("escrow_uid"),
            physical_host_id=params.get("physical_host_id"),
            ssh_user=params.get("ssh_user"),
            ssh_public_key=params.get("ssh_public_key"),
            access_ref=params.get("access_ref"),
            bare_metal_reclaim_policy=params.get("bare_metal_reclaim_policy"),
            max_retries=params.get("max_retries"),
            playbook_path=params.get("playbook_path"),
            provider_extra_vars=params.get("provider_extra_vars") or {},
        )

    @staticmethod
    def split_credentials(
        payload: dict, offering_mode: str
    ) -> tuple[dict, tuple[CredentialEnvelope, ...]]:
        """Separate the credentials a result carries from the rest of it.

        Each role in the playbook's ``authentication`` fact becomes one
        credential, kind named by its role; the result keeps everything else.
        """
        auth = payload.get("authentication")
        if not auth:
            return payload, ()
        sanitized = copy.deepcopy(payload)
        credentials = tuple(
            CredentialEnvelope(
                offering_mode=offering_mode,
                credential_kind=role,
                value={name: role_data.get(name) for name in _CREDENTIAL_FIELDS},
            )
            for role, role_data in _roles(auth)
        )
        sanitized.pop("authentication", None)
        if isinstance(sanitized.get("ansible_result"), dict):
            sanitized["ansible_result"].pop("authentication", None)
        return sanitized, credentials

    @staticmethod
    def build_result_payload(result: AnsibleRunResult) -> dict:
        ar = result.ansible_result or {}
        payload: dict = {
            "ssh_port": result.ssh_port,
            "tenant_user": result.tenant_user,
            "host_ip": result.host_ip,
            "ssh_command": result.ssh_command,
        }
        if not ar:
            payload["ansible_result"] = None
            return payload

        payload["status"] = ar.get("status")
        payload["action"] = ar.get("action")
        payload["vm_name"] = ar.get("vm_name")
        payload["host"] = ar.get("host")
        payload["timestamp"] = ar.get("timestamp")

        if ar.get("tenant_user"):
            payload["tenant_user"] = ar["tenant_user"]

        auth = ar.get("authentication")
        if auth:
            tenant_auth = auth.get("tenant", {})
            root_auth = auth.get("root", {})
            payload["authentication"] = {
                "tenant": {
                    "password": tenant_auth.get("password"),
                    "key_type": tenant_auth.get("key_type"),
                    "ssh_commands": tenant_auth.get("ssh_commands"),
                },
                "root": {
                    "password": root_auth.get("password"),
                    "ssh_commands": root_auth.get("ssh_commands"),
                    "ssh_key_path_host": root_auth.get("ssh_key_path_host"),
                },
            }
            tenant_cmds = tenant_auth.get("ssh_commands", {})
            if tenant_cmds.get("external"):
                payload["ssh_command"] = tenant_cmds["external"]

        frp = ar.get("frp")
        if frp:
            payload["frp"] = frp
            if frp.get("remote_port"):
                payload["ssh_port"] = frp["remote_port"]

        for key in ("gpu", "network", "vm_ip_internal", "vm_state",
                    "result_message", "note", "operation_initiated"):
            if ar.get(key):
                payload[key] = ar[key]

        if ar.get("vms"):
            payload["vms"] = ar["vms"]
            payload["vm_count"] = ar.get("vm_count")

        if ar.get("resources"):
            payload["resources"] = ar["resources"]
        elif ar.get("cpu_usage_percent") is not None or ar.get("memory_used_mb") is not None:
            payload["resources"] = {
                "cpu": {
                    "usage_percent": ar.get("cpu_usage_percent"),
                    "vcpus_provisioned": ar.get("cpu_vcpus_provisioned"),
                },
                "memory": {
                    "used_mb": ar.get("memory_used_mb"),
                    "available_mb": ar.get("memory_available_mb"),
                    "usage_percent": ar.get("memory_usage_percent"),
                },
                "storage": {
                    "allocation_gb": ar.get("host_storage_allocation_gb"),
                    "capacity_gb": ar.get("host_storage_capacity_gb"),
                    "usage_percent": ar.get("host_storage_usage_percent"),
                    "guest_total": ar.get("guest_storage_total"),
                    "guest_used": ar.get("guest_storage_used"),
                    "guest_available": ar.get("guest_storage_available"),
                },
                "network_interfaces": ar.get("network_interfaces"),
                "error": ar.get("error") or None,
            }

        payload["ansible_result"] = ar
        return payload


def _joined(stdout: str, stderr: str) -> str:
    return stdout + ("\n\nSTDERR:\n" + stderr if stderr else "")


def _roles(auth: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for role in _CREDENTIAL_ROLES:
        role_data = auth.get(role) or {}
        if role_data:
            yield role, role_data


__all__ = [
    "AnsibleJobExecutor",
    "SSH_CONNECTION_KIND",
    "execution_host_from_record",
]
