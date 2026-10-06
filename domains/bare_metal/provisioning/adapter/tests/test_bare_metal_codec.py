"""The bare-metal codec: access parameters, playbook variables, and the access fact."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pydantic
import pytest
from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION, NODE_RECLAIM_ACCESS_ACTION
from compute_provisioning_ansible.runner import AnsibleResult, inventory_target
from compute_provisioning_contracts import CREATE_JOB_RESULT_KIND

from bare_metal_provisioning_adapter.codec import (
    BARE_METAL_INVENTORY_GROUP,
    DEFAULT_BARE_METAL_RECLAIM_POLICY,
    BareMetalAnsibleCodec,
    BareMetalJobParams,
    reclaim_policy_from,
)

from execution import HOST, job_run

_ANSIBLE_ROOT = Path(__file__).resolve().parents[2] / "iac" / "ansible"


def _grant(**overrides) -> BareMetalJobParams:
    values = {
        "action": NODE_GRANT_ACCESS_ACTION,
        "host_id": HOST.host_id,
        "physical_host_id": "physical-1",
        "escrow_uid": "escrow-1",
        "ssh_user": "tenant-a",
        "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
        "access_ref": {"ssh_user": "tenant-a"},
        "executor_ref": {"physical_host_id": "physical-1"},
    }
    values.update(overrides)
    return BareMetalJobParams(**values)


def test_a_grant_renders_the_access_playbooks_variables() -> None:
    plan = BareMetalAnsibleCodec().prepare(job_run(_grant()))

    assert plan.limit == HOST.host_id
    assert plan.extra_variables == {}
    assert plan.playbook_path is None
    assert plan.variables == {
        "host_id": "bm-node-1",
        "offering_mode": "bare_metal",
        "executor_action": NODE_GRANT_ACCESS_ACTION,
        "executor_target": "bm-node-1",
        "executor_ref": {"physical_host_id": "physical-1"},
        "escrow_uid": "escrow-1",
        "physical_host_id": "physical-1",
        "bare_metal_ssh_user": "tenant-a",
        "bare_metal_ssh_public_key": "ssh-ed25519 AAAA tenant-a",
        "bare_metal_access_ref": {"ssh_user": "tenant-a"},
    }


def test_a_reclaim_names_its_policy_and_no_vm_variable_reaches_the_playbook() -> None:
    params = _grant(action=NODE_RECLAIM_ACCESS_ACTION, reclaim_policy="lock_user")

    variables = BareMetalAnsibleCodec().prepare(job_run(params)).variables

    assert variables["bare_metal_reclaim_policy"] == "lock_user"
    assert not any(name.startswith(("vm_", "root_ssh_")) for name in variables)


def test_stored_parameters_naming_another_action_are_refused() -> None:
    mismatched = dataclasses.replace(job_run(_grant()), action=NODE_RECLAIM_ACCESS_ACTION)

    with pytest.raises(ValueError, match="parameters name action"):
        BareMetalAnsibleCodec().prepare(mismatched)


def test_parameters_in_another_shape_are_refused() -> None:
    with pytest.raises(pydantic.ValidationError):
        BareMetalJobParams.model_validate(
            {"action": NODE_GRANT_ACCESS_ACTION, "host_id": "h", "vm_action": "create"}
        )


def _granted(fact: str) -> AnsibleResult:
    stdout = "ok: [bm-node-1] => {\n" f'    "node_grant_access_data": {fact}\n}}\n'
    return AnsibleResult(stdout=stdout, stderr="", process_id=1)


def test_a_grant_reports_delivery_evidence_and_no_credential() -> None:
    outcome = BareMetalAnsibleCodec().interpret(
        job_run(_grant()),
        inventory_target(HOST),
        _granted(
            '{"action": "node_grant_access", "host": "10.0.0.5", "port": "2201", '
            '"ssh_user": "tenant-a", "timestamp": "2030-01-01T00:00:01Z", '
            '"physical_host_id": "physical-1"}'
        ),
    )

    assert outcome.credentials == ()
    assert outcome.result.result_kind == CREATE_JOB_RESULT_KIND
    assert outcome.result.offering_mode == "bare_metal"
    assert outcome.result.value == {
        "evidence": {
            "endpoints": [
                {"protocol": "ssh", "host": "10.0.0.5", "port": 2201, "user": "tenant-a"}
            ],
            "ready_at": "2030-01-01T00:00:01Z",
        },
        "detail": {
            "action": "node_grant_access",
            "host": "10.0.0.5",
            "port": "2201",
            "ssh_user": "tenant-a",
            "timestamp": "2030-01-01T00:00:01Z",
            "physical_host_id": "physical-1",
        },
    }


def test_a_grant_whose_fact_cannot_say_how_to_connect_reports_no_evidence() -> None:
    """The family's provider then fails the create, and an operator can still
    read the fact's named fields; anything else the role printed is not kept."""
    fact = (
        '{"action": "node_grant_access", "host": "10.0.0.5", "port": "2201", '
        '"unvetted": "x"}'
    )

    outcome = BareMetalAnsibleCodec().interpret(
        job_run(_grant()), inventory_target(HOST), _granted(fact)
    )

    assert outcome.result.result_kind == CREATE_JOB_RESULT_KIND
    assert outcome.result.value == {
        "evidence": None,
        "detail": {"action": "node_grant_access", "host": "10.0.0.5", "port": "2201"},
    }


def test_a_reclaim_reports_its_fact() -> None:
    reclaim = _grant().model_copy(
        update={"action": NODE_RECLAIM_ACCESS_ACTION, "reclaim_policy": "remove_lease_key"}
    )
    stdout = (
        "ok: [bm-node-1] => {\n"
        '    "node_reclaim_access_data": {"action": "node_reclaim_access", '
        '"status": "success"}\n}\n'
    )

    outcome = BareMetalAnsibleCodec().interpret(
        job_run(reclaim),
        inventory_target(HOST),
        AnsibleResult(stdout=stdout, stderr="", process_id=1),
    )

    assert outcome.result.result_kind == "bare_metal_access"
    assert outcome.result.value == {"action": "node_reclaim_access", "status": "success"}


def test_a_run_that_printed_no_fact_reports_no_result() -> None:
    outcome = BareMetalAnsibleCodec().interpret(
        job_run(_grant()),
        inventory_target(HOST),
        AnsibleResult(stdout="PLAY RECAP", stderr="", process_id=1),
    )

    assert outcome.result is None


@pytest.mark.parametrize("configured", [None, "", "  "])
def test_an_unset_reclaim_policy_is_the_default(configured) -> None:
    assert reclaim_policy_from(configured) == DEFAULT_BARE_METAL_RECLAIM_POLICY


def test_a_configured_reclaim_policy_is_kept() -> None:
    assert reclaim_policy_from("lock_user") == "lock_user"


def test_a_reclaim_policy_the_role_does_not_implement_is_refused() -> None:
    with pytest.raises(ValueError, match="Invalid bare_metal_reclaim_policy"):
        reclaim_policy_from("wipe_disk")


class TestAccessPlaybookContract:
    """The codec renders what the access playbook and role read.

    Both default an unset host to ``localhost``, so a playbook reading a name
    the codec no longer renders would run against the provisioner rather than
    fail; pinning both ends keeps a rename from degrading into that.
    """

    playbook = (_ANSIBLE_ROOT / "playbooks" / "node-access.yaml").read_text()
    role = (_ANSIBLE_ROOT / "roles" / "bare-metal-access" / "tasks" / "main.yml").read_text()

    def test_the_playbook_targets_the_codecs_inventory_group(self) -> None:
        assert f"hosts: {BARE_METAL_INVENTORY_GROUP}" in self.playbook

    def test_the_playbook_targets_the_host_id(self) -> None:
        assert "default(host_id | default('localhost'))" in self.playbook
        assert not re.search(r"\b(vm_host|vm_action|machine_id)\b", self.playbook)

    def test_every_variable_the_role_reads_is_one_the_codec_renders(self) -> None:
        rendered = set(
            BareMetalAnsibleCodec.variables(
                _grant(action=NODE_RECLAIM_ACCESS_ACTION, reclaim_policy="lock_user")
            )
        )
        for name in ("bare_metal_ssh_user", "bare_metal_ssh_public_key",
                     "bare_metal_reclaim_policy", "escrow_uid", "physical_host_id"):
            assert name in self.role
            assert name in rendered
        for name in ("executor_action", "executor_target", "host_id"):
            assert name in self.playbook
            assert name in rendered
