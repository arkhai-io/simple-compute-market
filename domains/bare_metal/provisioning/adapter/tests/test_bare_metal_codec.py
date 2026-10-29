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

from execution import HOST, host_with, job_run, json_output, shipped_output

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


def test_the_plan_carries_the_stored_playbook_and_no_playbook_variable() -> None:
    plan = BareMetalAnsibleCodec().prepare(
        job_run(_grant(playbook_path="/opt/service/node-access.yaml"))
    )

    assert plan.playbook_path == Path("/opt/service/node-access.yaml")
    assert "playbook_path" not in plan.variables


def test_parameters_stored_without_a_playbook_name_none_in_the_plan() -> None:
    """Stored parameters naming no playbook validate, and the plan names none,
    leaving the executor's configured playbook to run."""
    stored = _grant().model_dump(mode="json")
    del stored["playbook_path"]

    plan = BareMetalAnsibleCodec().prepare(
        job_run(BareMetalJobParams.model_validate(stored))
    )

    assert plan.playbook_path is None


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


def _fact(action: str = NODE_GRANT_ACCESS_ACTION, **changes) -> dict:
    """The access fact the role prints for ``_grant()``'s job: development
    values only, never for use on a public network."""
    fact = {
        "action": action,
        "host_id": HOST.host_id,
        "physical_host_id": "physical-1",
        "ssh_user": "tenant-a",
        "escrow_uid": "escrow-1",
        "timestamp": "2030-01-01T00:00:01Z",
        "host": "10.0.0.5",
        "port": "2201",
        "status": "success",
    }
    fact.update(changes)
    return fact


def _output(stdout: str) -> AnsibleResult:
    return AnsibleResult(stdout=stdout, stderr="", process_id=1)


def _interpret(params: BareMetalJobParams, stdout: str, host=HOST):
    return BareMetalAnsibleCodec().interpret(job_run(params, host), inventory_target(host), _output(stdout))


_GRANT_FACT = "node_grant_access_data"
_RECLAIM_FACT = "node_reclaim_access_data"
_DETAIL = {
    "action": "node_grant_access",
    "status": "success",
    "host_id": "bm-node-1",
    "physical_host_id": "physical-1",
    "ssh_user": "tenant-a",
    "escrow_uid": "escrow-1",
    "host": "10.0.0.5",
    "port": "2201",
    "timestamp": "2030-01-01T00:00:01Z",
}


@pytest.mark.parametrize("render", [shipped_output, json_output], ids=["shipped yaml", "json"])
def test_a_grant_reports_its_hosts_tenant_route_and_no_credential(render) -> None:
    """The endpoint is the registered host's tenant-facing address, else its
    connection address, with its tenant-facing port, else its connection port.
    The fact's own host and port, the provisioner's route, stay detail."""
    outcome = _interpret(_grant(), render(_GRANT_FACT, _fact()))

    assert outcome.credentials == ()
    assert outcome.result.result_kind == CREATE_JOB_RESULT_KIND
    assert outcome.result.offering_mode == "bare_metal"
    assert outcome.result.value == {
        "evidence": {
            "endpoints": [
                {"protocol": "ssh", "host": "203.0.113.5", "port": 2201, "user": "tenant-a"}
            ],
            "ready_at": "2030-01-01T00:00:01Z",
        },
        "detail": _DETAIL,
    }


@pytest.mark.parametrize(
    "public,endpoint",
    [
        ({"public_host": "192.0.2.10", "public_port": 22}, ("192.0.2.10", 22)),
        ({"public_host": None, "public_port": 22}, ("10.0.0.5", 22)),
        ({"public_host": None}, ("10.0.0.5", 2201)),
    ],
    ids=["tenant route", "tenant port only", "connection route"],
)
def test_the_endpoint_falls_back_field_by_field_to_the_connection(public, endpoint) -> None:
    host = host_with(**public)

    outcome = _interpret(_grant(), shipped_output(_GRANT_FACT, _fact()), host)

    (reached,) = outcome.result.value["evidence"]["endpoints"]
    assert (reached["host"], reached["port"]) == endpoint


@pytest.mark.parametrize(
    "changes,named",
    [
        ({"action": NODE_RECLAIM_ACCESS_ACTION}, "action"),
        ({"host_id": "bm-node-2"}, "host_id"),
        ({"ssh_user": "tenant-b"}, "ssh_user"),
        ({"physical_host_id": "physical-2"}, "physical_host_id"),
        ({"status": "failed"}, "status"),
    ],
    ids=["action", "host", "tenant", "machine", "status"],
)
def test_a_grant_whose_fact_does_not_match_its_job_reports_no_evidence(changes, named) -> None:
    """The JSON form, which the reader returns whatever action it names, so the
    codec's own check is what refuses another action's fact."""
    outcome = _interpret(_grant(), json_output(_GRANT_FACT, _fact(**changes)))

    assert outcome.result.result_kind == CREATE_JOB_RESULT_KIND
    assert outcome.result.value["evidence"] is None
    assert outcome.result.value["detail"]["mismatch"].startswith(f"{named}:")


def test_every_mismatch_is_named() -> None:
    outcome = _interpret(
        _grant(), shipped_output(_GRANT_FACT, _fact(ssh_user="tenant-b", status="failed"))
    )

    mismatch = outcome.result.value["detail"]["mismatch"]
    assert "ssh_user:" in mismatch and "status:" in mismatch


def test_a_grant_whose_job_names_no_machine_does_not_compare_one() -> None:
    outcome = _interpret(
        _grant(physical_host_id=None), shipped_output(_GRANT_FACT, _fact(physical_host_id=""))
    )

    assert outcome.result.value["evidence"]["endpoints"][0]["user"] == "tenant-a"


def test_a_grant_whose_job_names_no_tenant_account_reports_no_evidence() -> None:
    outcome = _interpret(_grant(ssh_user=None), shipped_output(_GRANT_FACT, _fact()))

    assert outcome.result.value["evidence"] is None
    assert outcome.result.value["detail"]["mismatch"].startswith("ssh_user:")


def test_another_actions_document_alone_is_no_fact() -> None:
    stdout = shipped_output(_RECLAIM_FACT, _fact(NODE_RECLAIM_ACCESS_ACTION))

    assert _interpret(_grant(), stdout).result is None


def test_a_grant_whose_fact_does_not_name_its_job_reports_no_evidence_and_drops_unvetted_fields() -> None:
    """A fact naming no host, tenant account, or status does not match its job,
    so it yields no evidence and the family's provider fails the create. An
    operator can still read the fact's named fields; anything else the role
    printed is not kept."""
    fact = {"action": "node_grant_access", "host": "10.0.0.5", "port": "2201", "unvetted": "x"}

    outcome = _interpret(_grant(), json_output(_GRANT_FACT, fact))

    assert outcome.result.result_kind == CREATE_JOB_RESULT_KIND
    value = outcome.result.value
    assert value["evidence"] is None
    assert {key: item for key, item in value["detail"].items() if key != "mismatch"} == {
        "action": "node_grant_access", "host": "10.0.0.5", "port": "2201",
    }
    assert "unvetted" not in value["detail"]


def test_a_grant_naming_an_unusable_time_reports_no_evidence() -> None:
    outcome = _interpret(_grant(), json_output(_GRANT_FACT, _fact(timestamp="soon")))

    assert outcome.result.value["evidence"] is None


def _reclaim(**changes) -> BareMetalJobParams:
    return _grant(action=NODE_RECLAIM_ACCESS_ACTION, reclaim_policy="remove_lease_key", **changes)


@pytest.mark.parametrize("render", [shipped_output, json_output], ids=["shipped yaml", "json"])
def test_a_reclaim_reports_its_fact(render) -> None:
    fact = _fact(NODE_RECLAIM_ACCESS_ACTION, reclaim_policy="remove_lease_key", host="bm-node-1")

    outcome = _interpret(_reclaim(), render(_RECLAIM_FACT, fact))

    assert outcome.result.result_kind == "bare_metal_access"
    assert outcome.result.value == fact


@pytest.mark.parametrize("render", [shipped_output, json_output], ids=["shipped yaml", "json"])
@pytest.mark.parametrize("policy", ["remove_lease_key", "lock_user", "delete_user"])
def test_a_reclaim_of_an_account_never_created_reports_it_absent(render, policy) -> None:
    """A reclaim compensating a grant that never created its account succeeds,
    printing ``account_present: false`` with nothing locked or deleted, as the
    role prints its booleans; the fact is the reclaim's result unchanged."""
    fact = _fact(
        NODE_RECLAIM_ACCESS_ACTION,
        reclaim_policy=policy,
        host="bm-node-1",
        account_present=False,
        account_locked=False,
        account_deleted=False,
    )
    del fact["port"]

    params = _grant(action=NODE_RECLAIM_ACCESS_ACTION, reclaim_policy=policy)

    outcome = _interpret(params, render(_RECLAIM_FACT, fact))

    assert outcome.result.result_kind == "bare_metal_access"
    assert outcome.result.value == fact
    assert outcome.result.value["account_present"] is False


@pytest.mark.parametrize(
    "changes,named",
    [
        ({"host_id": "bm-node-2"}, "host_id"),
        ({"ssh_user": "tenant-b"}, "ssh_user"),
        ({"status": "failed"}, "status"),
    ],
    ids=["host", "tenant", "status"],
)
def test_a_reclaim_whose_fact_does_not_match_its_job_reports_only_the_mismatch(changes, named) -> None:
    fact = _fact(NODE_RECLAIM_ACCESS_ACTION, **changes)

    outcome = _interpret(_reclaim(), shipped_output(_RECLAIM_FACT, fact))

    assert outcome.result.result_kind == "bare_metal_access"
    assert list(outcome.result.value) == ["mismatch"]
    assert outcome.result.value["mismatch"].startswith(f"{named}:")


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


def _role_tasks(role: str) -> list[tuple[str, str]]:
    """Each top-level task of the role, as its name and its whole text, in order."""
    blocks = re.split(r"^- name: ", role, flags=re.MULTILINE)[1:]
    return [(block.splitlines()[0].strip(), block) for block in blocks]


class TestReclaimOfAnAbsentAccount:
    """The reclaim looks its tenant account up before anything touches it.

    A compensating reclaim may run for a grant that never created the account:
    the key module then fails looking the user up, and the lock task's
    ``state: present`` would create the account. These read the role's task
    list; running it against a host that lacks the account is a live lane's
    evidence.
    """

    tasks = _role_tasks(TestAccessPlaybookContract.role)
    lookup = "Look up the bare-metal tenant account before reclaim"
    gate = "bare_metal_account_present | bool"

    def _index(self, name: str) -> int:
        return [task for task, _ in self.tasks].index(name)

    def _account_tasks(self) -> list[tuple[int, str, str]]:
        """Every reclaim task that reads or writes the tenant account or its home."""
        return [
            (index, name, body)
            for index, (name, body) in enumerate(self.tasks)
            if 'node_action == "node_reclaim_access"' in body
            and re.search(r"^  (ansible\.posix\.authorized_key|file|user):", body, re.MULTILINE)
        ]

    def test_the_lookup_reads_the_account_and_creates_nothing(self) -> None:
        body = dict(self.tasks)[self.lookup]

        assert "ansible.builtin.command:" in body
        assert "- getent\n" in body and "- passwd\n" in body
        assert '"{{ bare_metal_ssh_user }}"' in body
        assert "changed_when: false" in body
        # getent exits 2 for a name it does not know; any other failure fails.
        assert "failed_when: bare_metal_account_lookup.rc not in [0, 2]" in body
        assert "become" not in body
        assert 'delegate_to: "{{ target_host }}"' in body

    def test_every_task_touching_the_account_follows_the_lookup_and_needs_it(self) -> None:
        lookup = self._index(self.lookup)
        account_tasks = self._account_tasks()

        # Key revocation, authorized_keys removal, lock, and delete.
        assert len(account_tasks) == 4
        for index, name, body in account_tasks:
            assert index > lookup, name
            assert self.gate in body, name

    def test_the_lock_that_would_create_the_account_is_gated(self) -> None:
        name = "Lock bare-metal tenant account after reclaim"
        body = dict(self.tasks)[name]

        assert "state: present" in body
        assert self.gate in body

    def test_the_presence_is_recorded_from_the_lookup_before_it_is_read(self) -> None:
        name = "Record whether the bare-metal tenant account exists"
        body = dict(self.tasks)[name]

        assert self._index(self.lookup) < self._index(name)
        assert "bare_metal_account_present: \"{{ bare_metal_account_lookup.rc == 0 }}\"" in body
        assert all(self._index(name) < index for index, _, _ in self._account_tasks())

    def test_the_reclaim_fact_reports_whether_the_account_was_present(self) -> None:
        body = dict(self.tasks)["Create JSON data structure for node_reclaim_access action"]

        assert 'account_present: "{{ bare_metal_account_present | bool }}"' in body
