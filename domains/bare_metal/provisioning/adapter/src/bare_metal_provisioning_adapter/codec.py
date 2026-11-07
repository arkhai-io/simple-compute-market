"""How a bare-metal access job runs as a playbook, and what its output means.

``BareMetalAnsibleCodec`` is the bare-metal domain's contribution to the compute
family's Ansible executor. A grant installs the buyer's key for a tenant account
on the whole host the lease sells; a reclaim removes access by the configured
reclaim policy. Each job stores a ``BareMetalJobParams``, which names the access
playbook frozen when the job was prepared, or none, leaving the executor's.

The fact the ``bare-metal-access`` role prints is read through the compute
family's fact reader, whichever result format the callback uses, and is taken
for the job only when it names the job's action, its execution host, the tenant
account its parameters name, the physical machine they name, if any, and
success. That guards against taking another document from the run's output; it
is not proof of provenance across runs.

A grant's result is the compute family's ``CreateJobResult``: the delivery
evidence and the fact's named fields as operator detail. The evidence's endpoint
is the relay address and leased port for a relayed grant, otherwise the
registered host's tenant-facing route, its ``public_host`` else its
``ssh_host`` and its ``public_port`` else its ``ssh_port``, with the tenant
account the fact confirmed: the host registry owns how tenants reach the host,
and the fact's own host and port describe the provisioner's route, so they stay
detail. A grant whose fact does not match its job, or cannot say when access
became ready, reports no evidence, its detail naming any mismatch, so the
family's provider fails the create while an operator can still read why. A
reclaim's result retains its activity diagnostics unchanged as detail. Job
status alone decides teardown; these fields are never release evidence. The
result is its fact, or only the mismatch when the fact does not match
its job. No result carries a credential: the buyer already holds the private
half of the key that was installed.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from arkhai_bare_metal import (
    BARE_METAL_OFFERING_MODE,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
)
from compute_provisioning_contracts import (
    CREATE_JOB_RESULT_KIND,
    AccessEndpoint,
    CreateJobResult,
    DeliveryEvidence,
    ResultEnvelope,
)
from compute_provisioning.jobs import JobRun
from compute_provisioning.relays import RELAY_SECRET_VARIABLES
from compute_provisioning_ansible import AnsibleJobInterpretation, AnsibleJobPlan, read_fact
from compute_provisioning_ansible.runner import AnsibleResult, InventoryTarget
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

#: The inventory group the bare-metal access playbook targets.
BARE_METAL_INVENTORY_GROUP = "bare_metal_nodes"

#: The kind of a reclaim's result; a grant's is the family's create result.
BARE_METAL_ACCESS_RESULT_KIND = "bare_metal_access"

#: All policies end tenant activity; they then keep the account after key
#: removal, lock it, delete its home, or verify bounded working-data removal.
BARE_METAL_RECLAIM_POLICIES = frozenset({"remove_lease_key", "lock_user", "delete_user", "bounded_working_data"})
DEFAULT_BARE_METAL_RECLAIM_POLICY = "remove_lease_key"

#: The fact the access role prints for each action. The role prints the job's
#: action as the fact's own ``action``, which is what the fact reader selects by.
BARE_METAL_RESULT_FACTS: Mapping[str, str] = {
    NODE_GRANT_ACCESS_ACTION: "node_grant_access_data",
    NODE_RECLAIM_ACCESS_ACTION: "node_reclaim_access_data",
}


def reclaim_policy_from(value: Any) -> str:
    """The configured reclaim policy, the default when none is configured.

    A value naming no policy is refused, so a deployment cannot start with a
    reclaim that would do something other than what its operator wrote.
    """
    policy = str(value or "").strip() or DEFAULT_BARE_METAL_RECLAIM_POLICY
    if policy not in BARE_METAL_RECLAIM_POLICIES:
        allowed = ", ".join(sorted(BARE_METAL_RECLAIM_POLICIES))
        raise ValueError(
            f"Invalid bare_metal_reclaim_policy {policy!r}; expected one of: {allowed}"
        )
    return policy


class BareMetalJobParams(BaseModel):
    """One bare-metal access job's parameters, as the job authority stores them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["node_grant_access", "node_reclaim_access"]
    host_id: str = Field(min_length=1)
    capacity_reservation_id: str | None = None
    relay_id: str | None = None
    remote_port: int | None = None
    relay_addr: str | None = None
    relay_port: int | None = None
    relay_token: str | None = Field(default=None, repr=False)
    relay_grant: str | None = Field(default=None, repr=False)
    physical_host_id: str | None = None
    escrow_uid: str | None = None
    executor_ref: dict[str, Any] | None = None
    access_ref: dict[str, Any] | None = None
    ssh_user: str | None = None
    ssh_public_key: str | None = None
    # Bounded grants freeze their cleanup policy before any host effect.
    reclaim_policy: str | None = None
    working_data_policy_id: str | None = None
    # The access playbook, frozen when the job is prepared so a later
    # configuration change never rewrites an accepted operation. A job stored
    # without one runs the executor's configured playbook.
    playbook_path: str | None = None

    @model_validator(mode="after")
    def bounded_identity(self) -> "BareMetalJobParams":
        if self.reclaim_policy == "bounded_working_data":
            if not self.capacity_reservation_id or not self.capacity_reservation_id.strip():
                raise ValueError("bounded cleanup requires capacity_reservation_id")
            if not self.working_data_policy_id or not self.working_data_policy_id.strip():
                raise ValueError("bounded cleanup requires working_data_policy_id")
        elif self.working_data_policy_id is not None:
            raise ValueError("working_data_policy_id requires bounded_working_data")
        return self


#: The grant fact's fields kept as operator detail: what the role did, on which
#: machine, for which account and deal. None is secret.
BARE_METAL_GRANT_DETAIL = (
    "action", "status", "host_id", "physical_host_id", "ssh_user", "escrow_uid",
    "host", "port", "timestamp", "relay",
)


def fact_mismatch(
    fact: Mapping[str, Any], action: str, host: InventoryTarget, params: BareMetalJobParams
) -> str | None:
    """How an access fact differs from the job that printed it, or ``None``.

    The role echoes the job's action, its target host, the tenant account, and
    the physical machine it was given, and reports ``success``. Each value
    compared is one the job itself passed to the role, and none is secret.
    """
    expected = {
        "action": action,
        "host_id": host.host_id,
        "ssh_user": params.ssh_user,
    }
    if params.physical_host_id:
        expected["physical_host_id"] = params.physical_host_id
    found = []
    for name, value in expected.items():
        if value is None:
            found.append(f"{name}: the job names none")
        elif fact.get(name) != value:
            found.append(f"{name}: the fact names {fact.get(name)!r}, the job {value!r}")
    if fact.get("status") != "success":
        found.append(f"status: the fact reports {fact.get('status')!r}, not 'success'")
    return "; ".join(found) or None


def grant_evidence(
    fact: Mapping[str, Any], host: InventoryTarget, user: str,
    params: BareMetalJobParams | None = None
) -> DeliveryEvidence | None:
    """How the buyer reaches the granted host, or ``None`` when the fact cannot
    say when access became ready.

    A relayed endpoint uses the fact's relay address and the job's leased
    port. Other grants use the host's tenant-facing route, each part falling
    back to the connection's. ``user`` is the account the fact confirmed, and
    the role prints the time as an ISO 8601 UTC instant.
    """
    address = host.public_host or host.ssh_host
    port = host.public_port or host.ssh_port
    if params is not None and (params.relay_id or params.remote_port is not None):
        relay = fact.get("relay")
        if (not isinstance(relay, Mapping) or relay.get("enabled") is not True
                or params.remote_port is None
                or str(relay.get("remote_port")) != str(params.remote_port)):
            return None
        address, port = relay.get("relay_addr"), params.remote_port
    try:
        return DeliveryEvidence(
            endpoints=(
                AccessEndpoint(
                    protocol="ssh",
                    host=address,
                    port=port,
                    user=user,
                ),
            ),
            ready_at=fact.get("timestamp"),
        )
    except (TypeError, ValueError, ValidationError):
        return None


class BareMetalAnsibleCodec:
    """The bare-metal domain's ``AnsibleJobCodec``; see the module docstring."""

    inventory_group = BARE_METAL_INVENTORY_GROUP
    secret_fields: frozenset[str] = RELAY_SECRET_VARIABLES

    def __init__(self, *, relay_resolver: Any | None = None) -> None:
        self._relay_resolver = relay_resolver

    def prepare(self, run: JobRun) -> AnsibleJobPlan:
        params = BareMetalJobParams.model_validate(dict(run.parameters))
        if params.action != run.action:
            raise ValueError(
                f"bare-metal job parameters name action {params.action!r}, "
                f"but the job runs {run.action!r}"
            )
        if self._relay_resolver is not None:
            params = self._relay_resolver.resolve_into(
                params,
                remote_port=params.remote_port if run.action == NODE_GRANT_ACCESS_ACTION else None,
                owner_id=params.capacity_reservation_id,
            )
        return AnsibleJobPlan(
            variables=self.variables(params),
            limit=run.host.host_id,
            playbook_path=Path(params.playbook_path) if params.playbook_path else None,
        )

    def interpret(
        self, run: JobRun, host: InventoryTarget, output: AnsibleResult
    ) -> AnsibleJobInterpretation:
        fact = read_fact(output.stdout, BARE_METAL_RESULT_FACTS[run.action], action=run.action)
        if fact is None:
            return AnsibleJobInterpretation(result=None)
        params = BareMetalJobParams.model_validate(dict(run.parameters))
        mismatch = fact_mismatch(fact, run.action, host, params)
        if run.action == NODE_GRANT_ACCESS_ACTION:
            detail = {
                name: fact[name]
                for name in BARE_METAL_GRANT_DETAIL
                if fact.get(name) not in (None, "")
            }
            if mismatch is not None:
                detail["mismatch"] = mismatch
            created = CreateJobResult(
                evidence=(
                    None if mismatch is not None
                    else grant_evidence(fact, host, str(params.ssh_user), params)
                ),
                detail=detail,
            )
            return AnsibleJobInterpretation(
                result=ResultEnvelope(
                    offering_mode=run.offering_mode,
                    result_kind=CREATE_JOB_RESULT_KIND,
                    value=created.model_dump(mode="json"),
                )
            )
        return AnsibleJobInterpretation(
            result=ResultEnvelope(
                offering_mode=run.offering_mode,
                result_kind=BARE_METAL_ACCESS_RESULT_KIND,
                value=fact if mismatch is None else {"mismatch": mismatch},
            )
        )

    def is_retryable(self, message: str) -> bool:
        return True

    @staticmethod
    def variables(params: BareMetalJobParams) -> dict[str, Any]:
        """The bare-metal access playbook's variables for a job."""
        variables: dict[str, Any] = {
            "host_id": params.host_id,
            "offering_mode": BARE_METAL_OFFERING_MODE,
            "executor_action": params.action,
            "executor_target": params.host_id,
            "bare_metal_reclaim_policy": params.reclaim_policy or DEFAULT_BARE_METAL_RECLAIM_POLICY,
        }
        optional = {
            "relay_id": params.relay_id,
            "bare_metal_remote_port": params.remote_port,
            "frp_server_addr": params.relay_addr,
            "frp_server_port": params.relay_port,
            "frp_auth_token": params.relay_token,
            "relay_grant": params.relay_grant,
            "executor_ref": params.executor_ref,
            "escrow_uid": params.escrow_uid,
            "physical_host_id": params.physical_host_id,
            "bare_metal_ssh_user": params.ssh_user,
            "bare_metal_ssh_public_key": params.ssh_public_key,
            "bare_metal_access_ref": params.access_ref,
            "bare_metal_capacity_reservation_id": params.capacity_reservation_id,
            "bare_metal_working_data_policy_id": params.working_data_policy_id,
        }
        variables.update({name: value for name, value in optional.items() if value})
        return variables


__all__ = [
    "BARE_METAL_ACCESS_RESULT_KIND",
    "BARE_METAL_GRANT_DETAIL",
    "BARE_METAL_INVENTORY_GROUP",
    "BARE_METAL_RECLAIM_POLICIES",
    "BARE_METAL_RESULT_FACTS",
    "BareMetalAnsibleCodec",
    "BareMetalJobParams",
    "DEFAULT_BARE_METAL_RECLAIM_POLICY",
    "fact_mismatch",
    "grant_evidence",
    "reclaim_policy_from",
]
