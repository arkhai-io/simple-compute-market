"""How a bare-metal access job runs as a playbook, and what its output means.

``BareMetalAnsibleCodec`` is the bare-metal domain's contribution to the compute
family's Ansible executor. A grant installs the buyer's key for a tenant account
on the whole host the lease sells; a reclaim removes access by the configured
reclaim policy. Each job stores a ``BareMetalJobParams``, and its result is the
access fact the ``bare-metal-access`` role prints, which carries no credential:
the buyer already holds the private half of the key that was installed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from arkhai_bare_metal import (
    BARE_METAL_OFFERING_MODE,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
)
from compute_provisioning_contracts import ResultEnvelope
from compute_provisioning.jobs import JobRun
from compute_provisioning_ansible import AnsibleJobInterpretation, AnsibleJobPlan
from compute_provisioning_ansible.runner import (
    AnsibleResult,
    InventoryTarget,
    extract_fact,
)
from pydantic import BaseModel, ConfigDict, Field

#: The inventory group the bare-metal access playbook targets.
BARE_METAL_INVENTORY_GROUP = "bare_metal_nodes"

#: The kind of the result both access actions produce.
BARE_METAL_ACCESS_RESULT_KIND = "bare_metal_access"

#: What a reclaim does to the tenant account: remove only the lease's key,
#: also lock the account, or delete the account and its home directory.
BARE_METAL_RECLAIM_POLICIES = frozenset({"remove_lease_key", "lock_user", "delete_user"})
DEFAULT_BARE_METAL_RECLAIM_POLICY = "remove_lease_key"

#: The fact the access role prints for each action.
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
    physical_host_id: str | None = None
    escrow_uid: str | None = None
    executor_ref: dict[str, Any] | None = None
    access_ref: dict[str, Any] | None = None
    ssh_user: str | None = None
    ssh_public_key: str | None = None
    # Set on a reclaim only; a grant has nothing to reclaim.
    reclaim_policy: str | None = None


class BareMetalAnsibleCodec:
    """The bare-metal domain's ``AnsibleJobCodec``; see the module docstring."""

    inventory_group = BARE_METAL_INVENTORY_GROUP
    # The access role prints the tenant account and the host's address, neither
    # of them secret; the installed key is public.
    secret_fields: frozenset[str] = frozenset()

    def prepare(self, run: JobRun) -> AnsibleJobPlan:
        params = BareMetalJobParams.model_validate(dict(run.parameters))
        if params.action != run.action:
            raise ValueError(
                f"bare-metal job parameters name action {params.action!r}, "
                f"but the job runs {run.action!r}"
            )
        return AnsibleJobPlan(variables=self.variables(params), limit=run.host.host_id)

    def interpret(
        self, run: JobRun, host: InventoryTarget, output: AnsibleResult
    ) -> AnsibleJobInterpretation:
        fact = extract_fact(output.stdout, BARE_METAL_RESULT_FACTS[run.action])
        if fact is None:
            return AnsibleJobInterpretation(result=None)
        return AnsibleJobInterpretation(
            result=ResultEnvelope(
                offering_mode=run.offering_mode,
                result_kind=BARE_METAL_ACCESS_RESULT_KIND,
                value=fact,
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
        }
        optional = {
            "executor_ref": params.executor_ref,
            "escrow_uid": params.escrow_uid,
            "physical_host_id": params.physical_host_id,
            "bare_metal_ssh_user": params.ssh_user,
            "bare_metal_ssh_public_key": params.ssh_public_key,
            "bare_metal_access_ref": params.access_ref,
            "bare_metal_reclaim_policy": params.reclaim_policy,
        }
        variables.update({name: value for name, value in optional.items() if value})
        return variables


__all__ = [
    "BARE_METAL_ACCESS_RESULT_KIND",
    "BARE_METAL_INVENTORY_GROUP",
    "BARE_METAL_RECLAIM_POLICIES",
    "BARE_METAL_RESULT_FACTS",
    "BareMetalAnsibleCodec",
    "BareMetalJobParams",
    "DEFAULT_BARE_METAL_RECLAIM_POLICY",
    "reclaim_policy_from",
]
