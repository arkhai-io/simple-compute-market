"""VM's default mock output: the fact a run of the job prints, for its own guest.

Read back through the real codec, through the shared fact reader, as the mock
profile's lanes read it. Addresses are RFC 5737 documentation addresses and the
key is a placeholder: development fixture values that must never be used on a
public network.
"""

from __future__ import annotations

from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.jobs import JobRun
from compute_provisioning_ansible import MockPlaybook, read_fact
from compute_provisioning_ansible.runner import AnsibleResult, extract_fact, inventory_target
from compute_provisioning_contracts import CreateJobResult

from vm_provisioning_adapter.codec import VmAnsibleCodec
from vm_provisioning_adapter.services.mock_output import (
    MOCK_FORWARDED_PORT,
    tenant_account,
    vm_mock_output,
)

_GUEST = "tenant-0a1b2c3d4e5f60718293a4b5"
_KEY = "ssh-ed25519 AAAAplaceholder buyer@example.invalid"
_HOST = ExecutionHost(
    host_id="kvm1",
    pool_id="default",
    connection=ConnectionEnvelope(
        kind="ssh",
        version=2,
        public={
            "ssh_host": "198.51.100.7",
            "public_host": "192.0.2.7",
            "ssh_port": 22,
            "ssh_user": "root",
            "key_path": "/keys/id_ed25519",
        },
    ),
)


def _parameters(action: str = "create", **extra) -> dict:
    return {
        "host_id": "kvm1",
        "vm_target": _GUEST,
        "vm_action": action,
        "executor_action": action,
        "executor_target": _GUEST,
        "offering_mode": "vm",
        **extra,
    }


def _rendered(parameters: dict) -> str:
    return vm_mock_output(
        MockPlaybook(parameters=parameters, limit="kvm1", hosts={"kvm1": inventory_target(_HOST)})
    )


def _interpreted(parameters: dict, action: str = "create"):
    run = JobRun(
        job_id="job-1",
        offering_mode="vm",
        action=action,
        host=_HOST,
        parameters=parameters,
        report_handle=lambda handle: None,
        report_logs=lambda logs: None,
    )
    output = AnsibleResult(stdout=_rendered(parameters), stderr="", process_id=1)
    return VmAnsibleCodec().interpret(run, inventory_target(_HOST), output)


def test_the_tenant_account_is_the_guest_name_as_the_role_derives_it() -> None:
    assert tenant_account("Tenant-0A_1.b") == "tenant0a1b"


def test_a_create_prints_the_shipped_form_for_the_jobs_own_guest() -> None:
    stdout = _rendered(_parameters(ssh_pubkey=_KEY))

    assert "vm_creation_data:" in stdout and "msg: |-" in stdout
    assert extract_fact(stdout, "vm_creation_data") is None
    fact = read_fact(stdout, "vm_creation_data", action="create")
    assert (fact["vm_name"], fact["tenant_user"], fact["status"]) == (
        _GUEST, tenant_account(_GUEST), "success",
    )
    assert fact["external_ssh_port"] == MOCK_FORWARDED_PORT
    assert fact["authentication"]["tenant"]["key_type"] == "provided"
    assert fact["frp"]["enabled"] is False


def test_a_create_without_the_buyers_key_prints_the_generated_key_fact() -> None:
    fact = read_fact(_rendered(_parameters()), "vm_creation_data", action="create")

    assert fact["authentication"]["tenant"]["key_type"] == "generated"
    assert "frp" not in fact and fact["relay"]["enabled"] is False


def test_the_mocked_create_yields_evidence_through_the_codec() -> None:
    interpretation = _interpreted(_parameters(ssh_pubkey=_KEY))

    created = CreateJobResult.model_validate(interpretation.result.value)
    (endpoint,) = created.evidence.endpoints
    assert (endpoint.host, endpoint.port, endpoint.user) == (
        "192.0.2.7", int(MOCK_FORWARDED_PORT), tenant_account(_GUEST),
    )
    assert "mismatch" not in created.detail
    assert [c.credential_kind for c in interpretation.credentials] == ["root", "tenant"]
    assert "mock-tenant-password" not in str(interpretation.result.value)


def test_a_remove_prints_the_remove_fact_naming_the_jobs_guest() -> None:
    stdout = _rendered(_parameters("vm_remove"))

    fact = read_fact(stdout, "vm_remove_data", action="vm_remove")
    assert (fact["action"], fact["vm_name"], fact["status"]) == ("vm_remove", _GUEST, "success")
    assert read_fact(stdout, "vm_creation_data", action="create") is None


def test_a_remove_reports_the_guest_present_as_the_role_does_after_its_cleanup_script() -> None:
    """The role reports whether the create's cleanup script ran and whether
    anything of the guest was there, both as text. A default remove stands for
    a delivered guest's; a case needing an absent guest arms a rule."""
    fact = read_fact(_rendered(_parameters("vm_remove")), "vm_remove_data", action="vm_remove")

    assert (fact["cleanup_record"], fact["guest_present"]) == ("true", "true")
