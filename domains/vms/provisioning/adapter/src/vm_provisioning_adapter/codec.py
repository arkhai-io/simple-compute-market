"""How a VM job runs as a playbook, and what its output means.

``VmAnsibleCodec`` is the VM domain's contribution to the compute family's
Ansible executor. It owns everything VM about a job: the ``VmJobParams`` a job
stores, the variables the VM-operations playbook reads (golden-image root
credentials and relay endpoints included), which VM failures are not worth
retrying, the facts the playbook prints for each action, the result payload
those facts become, and the ``root`` and ``tenant`` credentials it carries.

A create's result is the compute family's ``CreateJobResult``, whoever submitted
the job. Its evidence says how a buyer reaches the guest. Behind a relay that
is the relay's address and the port leased for the guest: the lease, recorded
in the job's parameters, is the authority for the port, and a run reporting
another port says nothing a buyer can use, so it reports no evidence. A guest
on the direct path is reached at its host's buyer-facing address and the
external port the playbook forwarded. Its detail is VM's named operator facts,
the guest's internal address among them; secrets are never among them, being
reported as credentials.
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

from compute_provisioning_contracts import (
    CREATE_JOB_RESULT_KIND,
    AccessEndpoint,
    CreateJobResult,
    CredentialEnvelope,
    DeliveryEvidence,
    ResultEnvelope,
)
from pydantic import ValidationError
from compute_provisioning.jobs import JobRun
from compute_provisioning_ansible import (
    AnsibleJobInterpretation,
    AnsibleJobPlan,
    matches_any,
)
from compute_provisioning_ansible.runner import (
    AnsibleResult,
    InventoryTarget,
    extract_fact,
    extract_json_block,
)

from vm_provisioning_adapter.models.jobs_model import VmJobParams

logger = logging.getLogger(__name__)

#: The inventory group the VM-operations playbook targets.
VM_INVENTORY_GROUP = "kvm_hosts"

#: Fields the VM playbooks print whose values are secret: the root key's path
#: on the host and a relay's admission token.
VM_SECRET_FIELDS = frozenset({"ssh_key_path_host", "frp_auth_token"})

#: VM failures that running the same job again cannot fix.
VM_NON_RETRYABLE_FAILURES: tuple[str, ...] = (
    "VM target not found",
    'Failed to get "resize" lock',
    "Is another process using the image",
    "Cannot determine IP address for VM",
    "failed to get domain",
    "Domain not found",
)

#: The fact the VM-operations playbook prints for each action's result.
VM_RESULT_FACTS: Mapping[str, str] = {
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
    "check": "check_data",
}

# The roles a playbook's ``authentication`` fact may carry, in the order their
# credentials are reported.
_CREDENTIAL_ROLES = ("root", "tenant")
_CREDENTIAL_FIELDS = ("password", "ssh_commands", "ssh_key_path_host", "key_type")


def vm_result_kind(action: str) -> str:
    """The kind of the result a VM action's job produces."""
    return f"vm_{action}"


@dataclass(frozen=True)
class GoldenImageCredentials:
    """Root credentials baked into the golden image, from deployment configuration.

    The ``golden-image-build`` role writes them to ``management-vars.yaml`` when
    the image is built; the deployment loads them through its profile.
    """

    root_ssh_filename: str = ""
    root_ssh_password: str = field(default="", repr=False)
    image_name: str = ""


class RelayResolver(Protocol):
    def resolve_into(self, params: VmJobParams) -> VmJobParams:
        """``params`` with the referenced relay's address and token filled in."""


@dataclass
class VmPlaybookOutput:
    """What the VM codec reads out of one playbook run."""

    stdout: str
    stderr: str
    ssh_port: Optional[str]
    tenant_user: Optional[str]
    host_ip: Optional[str]
    ssh_command: Optional[str]
    ansible_result: Optional[dict] = None


def vm_job_params(stored: Mapping[str, Any], *, host_id: str | None = None) -> VmJobParams:
    """A VM job's ``VmJobParams`` from the parameters the job authority stored.

    ``host_id`` is the host the job runs against, used when the stored
    parameters do not name it.
    """
    executor_action = stored.get("executor_action") or stored.get("vm_action", "create")
    executor_target = stored.get("executor_target") or stored.get("vm_target")
    return VmJobParams(
        host_id=stored.get("host_id") or host_id or executor_target,
        vm_target=stored.get("vm_target"),
        vm_action=stored.get("vm_action") or executor_action,
        offering_mode=stored["offering_mode"],
        executor_action=executor_action,
        executor_target=executor_target,
        executor_ref=stored.get("executor_ref"),
        image_setup_type=stored.get("image_setup_type", "scratch"),
        vm_ram=stored.get("vm_ram"),
        vm_vcpus=stored.get("vm_vcpus"),
        vm_disk_size=stored.get("vm_disk_size"),
        vm_os_variant=stored.get("vm_os_variant"),
        ssh_pubkey=stored.get("ssh_pubkey"),
        gpu_provisioned=stored.get("gpu_provisioned"),
        vm_gpu_count=stored.get("vm_gpu_count"),
        vm_gpu_device=stored.get("vm_gpu_device"),
        vm_gpu_devices=stored.get("vm_gpu_devices"),
        vm_gpu_partition_size=stored.get("vm_gpu_partition_size"),
        # No settings fallback. Relay location is a property of the relay a
        # pool references, resolved at dispatch; a service-wide default would
        # let a job reach a relay its pool does not name. Only the reference
        # and the leased port are stored; the address and token are filled in
        # immediately before the variables are written.
        relay_id=stored.get("relay_id"),
        vm_remote_port=stored.get("vm_remote_port"),
        golden_image_name=stored.get("golden_image_name"),
        gcs_bucket_url=stored.get("gcs_bucket_url"),
        gcs_image_path=stored.get("gcs_image_path"),
        escrow_uid=stored.get("escrow_uid"),
        max_retries=stored.get("max_retries"),
        playbook_path=stored.get("playbook_path"),
        provider_extra_vars=stored.get("provider_extra_vars") or {},
    )


class VmAnsibleCodec:
    """The VM domain's ``AnsibleJobCodec``; see the module docstring.

    ``relay_resolver``, when given, fills a referenced relay's address and
    token into a job's parameters immediately before its variables are
    written, so the token never enters the job's stored parameters and a
    rotation takes effect on a retry.
    """

    inventory_group = VM_INVENTORY_GROUP
    secret_fields = VM_SECRET_FIELDS

    def __init__(
        self,
        *,
        golden_image: GoldenImageCredentials = GoldenImageCredentials(),
        relay_resolver: RelayResolver | None = None,
    ) -> None:
        self._golden_image = golden_image
        self._relay_resolver = relay_resolver

    # ------------------------------------------------------------------
    # AnsibleJobCodec
    # ------------------------------------------------------------------

    def prepare(self, run: JobRun) -> AnsibleJobPlan:
        params = vm_job_params(run.parameters, host_id=run.host.host_id)
        if self._relay_resolver is not None:
            params = self._relay_resolver.resolve_into(params)
        return AnsibleJobPlan(
            variables=self.variables(params),
            extra_variables=dict(params.provider_extra_vars),
            limit=run.host.host_id,
            playbook_path=Path(params.playbook_path) if params.playbook_path else None,
        )

    def interpret(
        self, run: JobRun, host: InventoryTarget, output: AnsibleResult
    ) -> AnsibleJobInterpretation:
        params = vm_job_params(run.parameters, host_id=run.host.host_id)
        # Buyers may reach the host on a different network than the
        # provisioner does; with no public address configured, the connection
        # address is the one there is.
        parsed = parse_vm_output(
            output, params, tenant_address=host.public_host or host.ssh_host
        )
        value, credentials = split_credentials(
            build_result_payload(parsed), run.offering_mode
        )
        if run.action == "create":
            return AnsibleJobInterpretation(
                result=ResultEnvelope(
                    offering_mode=run.offering_mode,
                    result_kind=CREATE_JOB_RESULT_KIND,
                    value=create_result(value, params).model_dump(mode="json"),
                ),
                credentials=credentials,
            )
        return AnsibleJobInterpretation(
            result=ResultEnvelope(
                offering_mode=run.offering_mode,
                result_kind=vm_result_kind(run.action),
                value=value,
            ),
            credentials=credentials,
        )

    def is_retryable(self, message: str) -> bool:
        return not matches_any(message, VM_NON_RETRYABLE_FAILURES)

    # ------------------------------------------------------------------
    # VM variables
    # ------------------------------------------------------------------

    def reserved_var_keys(self, params: VmJobParams) -> frozenset[str]:
        """The variable names a job with these parameters sets itself.

        Ignores ``params.provider_extra_vars``: this answers what is reserved,
        whatever a caller proposes to add, so pool extra variables can be
        refused when a fulfillment is prepared rather than only when the job
        runs.
        """
        return frozenset(self.variables(params))

    def variables(self, params: VmJobParams) -> dict[str, Any]:
        """The VM-operations playbook's variables for a job, extra ones aside."""
        variables: dict[str, Any] = {
            "host_id": params.host_id,
            "vm_action": params.vm_action,
            "offering_mode": params.offering_mode,
            "executor_action": params.executor_action,
            "executor_target": params.executor_target,
        }
        if params.executor_ref:
            variables["executor_ref"] = params.executor_ref
        if params.vm_target:
            variables["vm_target"] = params.vm_target
        if params.vm_action == "create":
            variables["image_setup_type"] = params.image_setup_type
        for name in ("vm_ram", "vm_vcpus", "vm_disk_size", "vm_os_variant"):
            if getattr(params, name) is not None:
                variables[name] = getattr(params, name)
        if params.ssh_pubkey:
            variables["vm_tenant_pubkey"] = params.ssh_pubkey
        if params.gpu_provisioned is not None:
            variables["gpu_provisioned"] = params.gpu_provisioned
        if params.vm_gpu_count is not None:
            variables["vm_gpu_count"] = params.vm_gpu_count
        for name in ("vm_gpu_device", "vm_gpu_devices", "vm_gpu_partition_size"):
            if getattr(params, name):
                variables[name] = getattr(params, name)
        # Relay inputs. The token is a credential and reaches the playbook the
        # way every other job variable does; the codec's secret fields keep it
        # out of logged output. The remote port is supplied, never chosen:
        # allocation belongs to the service, which is also what can reclaim it
        # when the VM's life ends by any path.
        if params.relay_addr:
            variables["frp_server_addr"] = params.relay_addr
        if params.relay_port:
            variables["frp_server_port"] = params.relay_port
        if params.relay_token:
            variables["frp_auth_token"] = params.relay_token
        if params.vm_remote_port:
            variables["vm_remote_port"] = params.vm_remote_port
        for name in ("golden_image_name", "gcs_bucket_url", "gcs_image_path", "escrow_uid"):
            if getattr(params, name):
                variables[name] = getattr(params, name)
        variables.update(self._root_credentials(params))
        return variables

    def _root_credentials(self, params: VmJobParams) -> dict[str, str]:
        """The image's root credentials for a golden-image create, else placeholders.

        A configured golden image name replaces the job's own, as the image
        whose credentials these are.
        """
        golden = self._golden_image
        filename = golden.root_ssh_filename.strip()
        password = golden.root_ssh_password.strip()
        if params.image_setup_type == "golden":
            if filename and password:
                credentials = {
                    "root_ssh_filename": filename,
                    "root_ssh_password": password,
                }
                if golden.image_name.strip():
                    credentials["golden_image_name"] = golden.image_name.strip()
                return credentials
            logger.warning(
                "Golden mode requested but golden_root_ssh_filename / "
                "golden_root_ssh_password are not configured"
            )
        return {"root_ssh_filename": "not_provided", "root_ssh_password": "not_provided"}


# ----------------------------------------------------------------------
# Output parsing
# ----------------------------------------------------------------------


def parse_vm_output(
    output: AnsibleResult, params: VmJobParams, *, tenant_address: str | None
) -> VmPlaybookOutput:
    """What a VM playbook's raw output reports.

    ``tenant_address`` is the address buyers use to reach the host, resolved
    from the registered host record. It becomes ``host_ip``; nothing here
    reads an inventory file for it.
    """
    ssh_port = extract_ssh_port(output.stdout, params.host_id)
    tenant_user = extract_tenant_user(output.stdout, params.host_id)
    ssh_command = None
    if ssh_port and tenant_user and tenant_address:
        ssh_command = (
            f"ssh -i <your_private_key> -p {ssh_port} {tenant_user}@{tenant_address}"
        )
    return VmPlaybookOutput(
        stdout=output.stdout,
        stderr=output.stderr,
        ssh_port=ssh_port,
        tenant_user=tenant_user,
        host_ip=tenant_address,
        ssh_command=ssh_command,
        ansible_result=extract_vm_fact(output.stdout, params.vm_action),
    )


def extract_ssh_port(playbook_output: str, host_id: str | None = None) -> Optional[str]:
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


def extract_tenant_user(playbook_output: str, host_id: str | None = None) -> Optional[str]:
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


def extract_vm_fact(stdout: str, action: str) -> Optional[dict]:
    """The result fact a VM action's playbook printed.

    The fact is printed by name; failing that, the last ``msg: |`` block
    carrying an ``action`` is the one ``json-output.yml`` printed.
    """
    fact_name = VM_RESULT_FACTS.get(action)
    if not fact_name:
        return None
    result = extract_fact(stdout, fact_name)
    if result is not None:
        return result
    last_result = None
    for match in re.finditer(r"msg:\s*\|[-]?\s*\n", stdout):
        candidate = extract_json_block(stdout, match.end())
        if candidate is not None and "action" in candidate:
            last_result = candidate
    return last_result


def split_credentials(
    payload: dict, offering_mode: str
) -> tuple[dict, tuple[CredentialEnvelope, ...]]:
    """Separate the credentials a result carries from the rest of it.

    Each role in the playbook's ``authentication`` fact becomes one credential,
    kind named by its role; the result keeps everything else.
    """
    auth = payload.get("authentication")
    if not auth:
        return payload, ()
    sanitized = copy.deepcopy(payload)
    credentials = tuple(
        CredentialEnvelope(
            offering_mode=offering_mode,
            credential_kind=role,
            value={
                name: role_data[name]
                for name in _CREDENTIAL_FIELDS
                if role_data.get(name) is not None
            },
        )
        for role, role_data in _roles(auth)
    )
    sanitized.pop("authentication", None)
    if isinstance(sanitized.get("ansible_result"), dict):
        sanitized["ansible_result"].pop("authentication", None)
    return sanitized, credentials


def build_result_payload(result: VmPlaybookOutput) -> dict:
    """The VM result a playbook's facts become."""
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


#: A create result's fields kept as its operator detail. None is secret: the
#: playbook's credentials have already been split out as credentials.
VM_CREATE_DETAIL = (
    "action", "status", "vm_name", "vm_state", "host", "timestamp", "tenant_user",
    "host_ip", "ssh_port", "vm_ip_internal", "gpu", "network", "frp",
    "result_message", "note", "operation_initiated",
)


def _relay_reported(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    frp = payload.get("frp")
    if not isinstance(frp, Mapping):
        return None
    enabled = frp.get("enabled")
    if enabled is True or str(enabled).lower() == "true":
        return frp
    return None


def create_evidence(payload: Mapping[str, Any], params: VmJobParams) -> DeliveryEvidence | None:
    """How a buyer reaches the guest a create reported, or ``None``.

    A job that leased a relay port is reached through the relay, at exactly
    that port; a run reporting none, or another, yields nothing. Otherwise the
    guest is reached at its host's buyer-facing address and forwarded port.
    """
    if params.relay_id or params.vm_remote_port is not None:
        relay = _relay_reported(payload)
        if relay is None or params.vm_remote_port is None:
            return None
        if str(relay.get("remote_port")) != str(params.vm_remote_port):
            return None
        host, port = relay.get("relay_addr"), params.vm_remote_port
    else:
        host, port = payload.get("host_ip"), payload.get("ssh_port")
    if not isinstance(host, str) or not host.strip() or host.strip() == "N/A":
        return None
    try:
        return DeliveryEvidence(
            endpoints=(
                AccessEndpoint(
                    protocol="ssh",
                    host=host.strip(),
                    port=int(str(port)),
                    user=str(payload.get("tenant_user") or "") or None,
                ),
            ),
            ready_at=payload.get("timestamp"),
        )
    except (TypeError, ValueError, ValidationError):
        return None


def create_result(payload: Mapping[str, Any], params: VmJobParams) -> CreateJobResult:
    """A create's result: its delivery evidence, and its named operator detail."""
    return CreateJobResult(
        evidence=create_evidence(payload, params),
        detail={
            name: payload[name]
            for name in VM_CREATE_DETAIL
            if payload.get(name) not in (None, "")
        },
    )


def _roles(auth: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for role in _CREDENTIAL_ROLES:
        role_data = auth.get(role) or {}
        if role_data:
            yield role, role_data


__all__ = [
    "GoldenImageCredentials",
    "VM_INVENTORY_GROUP",
    "VM_NON_RETRYABLE_FAILURES",
    "VM_RESULT_FACTS",
    "VM_CREATE_DETAIL",
    "VM_SECRET_FIELDS",
    "VmAnsibleCodec",
    "VmPlaybookOutput",
    "build_result_payload",
    "create_evidence",
    "create_result",
    "extract_ssh_port",
    "extract_tenant_user",
    "extract_vm_fact",
    "parse_vm_output",
    "split_credentials",
    "vm_job_params",
    "vm_result_kind",
]
