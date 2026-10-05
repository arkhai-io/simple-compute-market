"""VM's job submissions: the route key, host, and parameters a VM job carries.

How the engine persists and runs a job is the job authority's, covered in the
family kit's suites; how the VM codec reads parameters and output is
test_vm_codec.py's.
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from arkhai_bare_metal import BARE_METAL_ACCESS_ACTIONS, NODE_RECLAIM_ACCESS_ACTION
from bare_metal_provisioning_adapter.codec import BareMetalAnsibleCodec
from compute_provisioning import JobExecutorTable, UnsupportedExecutorActionError
from compute_provisioning_ansible import AnsibleJobExecutor
from vm_provisioning_adapter.bundle import VM_JOB_ACTIONS
from vm_provisioning_adapter.codec import VmAnsibleCodec
from vm_provisioning_adapter.models.jobs_model import VmJobParams
from vm_provisioning_adapter.services.job_submitter import VmJobSubmitter


class _RecordingEngine:
    def __init__(self) -> None:
        self.submitted: list[dict] = []

    async def submit(self, **fields):
        self.submitted.append(fields)
        return None


def _submitted(params: VmJobParams, *, default_host_id: str | None = "kvm1") -> dict:
    engine = _RecordingEngine()
    asyncio.run(VmJobSubmitter(engine, default_host_id=default_host_id).submit(params, object()))
    return engine.submitted[0]


class TestSubmission:
    def test_a_vm_job_is_submitted_under_its_mode_action_and_host(self):
        fields = _submitted(VmJobParams(host_id="kvm1", vm_action="create", offering_mode="vm"))

        assert (fields["offering_mode"], fields["action"], fields["host_id"]) == ("vm", "create", "kvm1")

    def test_executor_action_takes_precedence_over_vm_action(self):
        params = VmJobParams(
            host_id="kvm1", vm_action="vm_remove", offering_mode="vm", executor_action="destroy"
        )

        assert _submitted(params)["action"] == "destroy"

    def test_a_job_naming_no_host_runs_against_its_target_or_the_default(self):
        targeted = VmJobParams(host_id=None, vm_action="create", offering_mode="vm", executor_target="kvm9")
        untargeted = VmJobParams(host_id=None, vm_action="create", offering_mode="vm")

        assert _submitted(targeted)["host_id"] == "kvm9"
        assert _submitted(untargeted)["host_id"] == "kvm1"

    def test_its_parameters_are_stored_as_submitted(self):
        params = VmJobParams(host_id="kvm1", vm_action="create", offering_mode="vm")

        assert _submitted(params)["params"] == dataclasses.asdict(params)


def _registered_table() -> JobExecutorTable:
    runner = MagicMock()
    table = JobExecutorTable()
    vm = AnsibleJobExecutor(runner, VmAnsibleCodec(), Path("/playbooks/vm-operations.yaml"), timeout_seconds=30)
    bare_metal = AnsibleJobExecutor(
        runner, BareMetalAnsibleCodec(), Path("/playbooks/node-access.yaml"), timeout_seconds=30
    )
    for action in VM_JOB_ACTIONS:
        table.register("vm", action, vm)
    for action in BARE_METAL_ACCESS_ACTIONS:
        table.register("bare_metal", action, bare_metal)
    table.freeze()
    return table


class TestRegistration:
    """Each mode's actions resolve to that mode's executor and playbook."""

    def test_vm_actions_resolve_to_the_vm_playbook(self):
        assert _registered_table().resolve("vm", "create").playbook_path == Path(
            "/playbooks/vm-operations.yaml"
        )

    def test_bare_metal_actions_resolve_to_the_bare_metal_playbook(self):
        assert _registered_table().resolve(
            "bare_metal", NODE_RECLAIM_ACCESS_ACTION
        ).playbook_path == Path("/playbooks/node-access.yaml")

    def test_an_unregistered_mode_and_action_is_refused(self):
        with pytest.raises(UnsupportedExecutorActionError):
            _registered_table().resolve("bare_metal", "create")
