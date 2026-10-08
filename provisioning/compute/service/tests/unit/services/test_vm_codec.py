"""The VM codec: VM job parameters, playbook variables, output, and credentials.

Covers how a VM job's stored parameters are read back, the variables the
VM-operations playbook receives (golden-image root credentials and relay
endpoints included), which VM failures are retried, the VM fields its output
is scrubbed of, the facts each action prints, the result payload they become,
and the ``root`` and ``tenant`` credentials it carries. The executor's own
mechanics are the Ansible distribution's tests; running a job end to end is
the service's integration tests.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.jobs import JobRun, JobSuccess
from compute_provisioning_ansible import AnsibleJobExecutor, render_extra_vars
from compute_provisioning_ansible.runner import (
    AnsibleResult,
    MaterializedInventory,
    inventory_target,
)
from types import SimpleNamespace

from vm_provisioning_adapter.codec import (
    VM_CREATE_DETAIL,
    VM_INVENTORY_GROUP,
    GoldenImageCredentials,
    VmAnsibleCodec,
    VmPlaybookOutput,
    build_result_payload,
    create_result,
    extract_ssh_port,
    extract_tenant_user,
    extract_vm_fact,
    parse_vm_output,
    split_credentials,
    vm_job_params,
)
from vm_provisioning_adapter.models.jobs_model import VmJobParams
from compute_provisioning_contracts import CREATE_JOB_RESULT_KIND, CreateJobResult

_ANSIBLE_ROOT = (
    Path(__file__).resolve().parents[6] / "domains/vms/provisioning/iac/ansible"
)

_HOST = ExecutionHost(
    host_id="kvm1",
    pool_id="default",
    connection=ConnectionEnvelope(
        kind="ssh",
        version=1,
        public={
            "ssh_host": "10.0.0.1",
            "public_host": "203.0.113.1",
            "ssh_port": 22,
            "ssh_user": "root",
            "key_path": "/keys/id_ed25519",
        },
    ),
)


def _params(**overrides) -> VmJobParams:
    values = dict(host_id="kvm1", vm_target="test-vm", vm_action="create", offering_mode="vm")
    values.update(overrides)
    return VmJobParams(**values)


def _variables(codec: VmAnsibleCodec | None = None, **overrides) -> dict:
    return (codec or VmAnsibleCodec()).variables(_params(**overrides))


def _golden(**overrides) -> VmAnsibleCodec:
    values = dict(root_ssh_filename="id_ed25519", root_ssh_password="hunter2")
    values.update(overrides)
    return VmAnsibleCodec(golden_image=GoldenImageCredentials(**values))


def _executor(codec: VmAnsibleCodec | None = None, runner=None) -> AnsibleJobExecutor:
    return AnsibleJobExecutor(
        runner if runner is not None else MagicMock(),
        codec or VmAnsibleCodec(),
        Path("/playbooks/vm-operations.yaml"),
        timeout_seconds=30,
    )


def _run(parameters: dict, *, action: str = "create") -> JobRun:
    return JobRun(
        job_id="job-1",
        offering_mode="vm",
        action=action,
        host=_HOST,
        parameters=parameters,
        report_handle=lambda handle: None,
        report_logs=lambda logs: None,
    )


# ---------------------------------------------------------------------------
# Stored parameters
# ---------------------------------------------------------------------------


class TestStoredParameters:
    def test_basic_fields_mapped(self):
        params = vm_job_params(
            {"host_id": "ww2", "offering_mode": "vm", "vm_target": "my-vm", "vm_action": "shutdown"}
        )
        assert (params.host_id, params.vm_target, params.vm_action) == ("ww2", "my-vm", "shutdown")

    def test_a_job_naming_no_host_runs_against_the_host_it_was_routed_to(self):
        params = vm_job_params({"offering_mode": "vm"}, host_id="kvm7")
        assert params.host_id == "kvm7"
        assert params.vm_action == "create"
        assert params.image_setup_type == "scratch"

    def test_optional_fields_are_none_when_absent(self):
        params = vm_job_params({"offering_mode": "vm", "host_id": "kvm1", "vm_action": "list"})
        assert params.vm_ram is None
        assert params.ssh_pubkey is None
        assert params.gpu_provisioned is None

    def test_all_optional_fields_mapped(self):
        raw = {
            "host_id": "kvm1",
            "vm_target": "test-vm",
            "vm_action": "create",
            "offering_mode": "vm",
            "image_setup_type": "golden",
            "vm_ram": 8192,
            "vm_vcpus": 8,
            "vm_disk_size": "40G",
            "vm_os_variant": "ubuntu22.04",
            "ssh_pubkey": "ssh-ed25519 AAAA...",
            "gpu_provisioned": True,
            "vm_gpu_count": 2,
            "vm_gpu_device": "0000:03:00.0",
            "vm_gpu_devices": ["0000:03:00.0", "0000:04:00.0"],
            "vm_gpu_partition_size": "1g.5gb",
            "relay_id": "site-a",
            "vm_remote_port": 6100,
            "golden_image_name": "base-v3",
            "gcs_bucket_url": "gs://bucket",
            "gcs_image_path": "images/img.qcow2",
        }
        params = vm_job_params(raw)
        for name, value in raw.items():
            assert getattr(params, name) == value, name
        # Stored params never carry the relay endpoint or the token.
        assert params.relay_addr is None
        assert params.relay_token is None

    def test_explicit_vm_identity_maps_legacy_vm_action_fields(self):
        params = vm_job_params(
            {"offering_mode": "vm", "host_id": "kvm1", "vm_target": "test-vm", "vm_action": "shutdown"}
        )
        assert params.executor_action == "shutdown"
        assert params.executor_target == "test-vm"

    def test_missing_offering_mode_fails_closed(self):
        with pytest.raises(KeyError, match="offering_mode"):
            vm_job_params({"host_id": "kvm1", "vm_action": "shutdown"})

    def test_executor_target_does_not_force_vm_target(self):
        params = vm_job_params(
            {
                "host_id": "kvm1",
                "vm_action": "list",
                "offering_mode": "vm",
                "executor_action": "list",
                "executor_target": "kvm1",
            }
        )
        assert params.vm_target is None
        assert params.executor_target == "kvm1"


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------


class TestVariables:
    def test_identity_fields_always_present(self):
        variables = _variables()
        assert variables["host_id"] == "kvm1"
        assert variables["vm_action"] == "create"
        assert variables["vm_target"] == "test-vm"
        assert variables["offering_mode"] == "vm"
        assert variables["executor_action"] == "create"

    def test_vm_target_absent_when_none(self):
        assert "vm_target" not in _variables(vm_target=None, vm_action="list")

    def test_image_setup_type_only_on_create(self):
        assert "image_setup_type" in _variables(vm_action="create")
        assert "image_setup_type" not in _variables(vm_action="monitor")

    def test_sizing_fields_present_only_when_set(self):
        sized = _variables(vm_ram=4096, vm_vcpus=4, vm_disk_size="20G")
        assert (sized["vm_ram"], sized["vm_vcpus"], sized["vm_disk_size"]) == (4096, 4, "20G")
        unsized = _variables()
        assert not {"vm_ram", "vm_vcpus", "vm_disk_size"} & set(unsized)

    def test_the_tenant_key_reads_back_whole_whatever_it_contains(self):
        key = 'ssh-ed25519 AAAA "quoted": rest'
        rendered = yaml.safe_load(render_extra_vars(_variables(ssh_pubkey=key)))
        assert rendered["vm_tenant_pubkey"] == key
        assert "vm_tenant_pubkey" not in _variables()

    @pytest.mark.parametrize("provisioned", [True, False])
    def test_gpu_provisioned_is_a_boolean(self, provisioned):
        assert _variables(gpu_provisioned=provisioned)["gpu_provisioned"] is provisioned
        assert "gpu_provisioned" not in _variables()

    def test_gpu_devices_are_a_list(self):
        devices = ["0000:03:00.0", "0000:04:00.0"]
        assert _variables(vm_gpu_devices=devices)["vm_gpu_devices"] == devices

    def test_relay_fields_present_when_resolved(self):
        variables = _variables(
            relay_addr="203.0.113.4",
            relay_port=7000,
            relay_token="admission-token",
            vm_remote_port=6100,
        )
        # The remote port is supplied rather than chosen by the playbook, and
        # no dashboard credential is among them.
        assert variables["frp_server_addr"] == "203.0.113.4"
        assert variables["frp_server_port"] == 7000
        assert variables["frp_auth_token"] == "admission-token"
        assert variables["vm_remote_port"] == 6100
        assert not {"frp_domain", "frp_dashboard_password"} & set(variables)

    def test_relay_fields_absent_when_none(self):
        assert not {"frp_server_addr", "frp_auth_token", "vm_remote_port"} & set(_variables())

    def test_executor_fields_reach_the_playbook(self):
        variables = _variables(
            executor_action="destroy",
            executor_target="kvm1",
            executor_ref={"vm": "test-vm"},
        )
        assert variables["executor_action"] == "destroy"
        assert variables["executor_target"] == "kvm1"
        assert variables["executor_ref"] == {"vm": "test-vm"}

    def test_gcs_fields_included_when_set(self):
        variables = _variables(gcs_bucket_url="gs://bucket", gcs_image_path="images/img.qcow2")
        assert variables["gcs_bucket_url"] == "gs://bucket"
        assert variables["gcs_image_path"] == "images/img.qcow2"

    def test_no_bare_metal_variable_is_rendered(self):
        assert not any(name.startswith("bare_metal_") for name in _variables())


class TestGoldenImageCredentials:
    def test_scratch_mode_names_no_credentials(self):
        variables = _variables(_golden(), image_setup_type="scratch")
        assert variables["root_ssh_filename"] == "not_provided"
        assert variables["root_ssh_password"] == "not_provided"

    def test_golden_credentials_injected_when_configured(self):
        variables = _variables(_golden(), image_setup_type="golden")
        assert variables["root_ssh_filename"] == "id_ed25519"
        assert variables["root_ssh_password"] == "hunter2"

    def test_the_configured_image_name_replaces_the_jobs(self):
        variables = _variables(
            _golden(image_name="base-image-v3"),
            image_setup_type="golden",
            golden_image_name="from-the-job",
        )
        assert variables["golden_image_name"] == "base-image-v3"

    def test_golden_image_name_absent_when_neither_names_one(self):
        assert "golden_image_name" not in _variables(_golden(), image_setup_type="golden")

    def test_placeholders_when_credentials_not_configured(self):
        variables = _variables(image_setup_type="golden")
        assert variables["root_ssh_filename"] == "not_provided"
        assert variables["root_ssh_password"] == "not_provided"

    def test_the_password_is_not_in_the_credentials_representation(self):
        assert "hunter2" not in repr(GoldenImageCredentials(root_ssh_password="hunter2"))


class TestPrepare:
    def test_a_referenced_relay_is_resolved_at_preparation(self):
        class Resolver:
            def resolve_into(self, params):
                return replace(params, relay_addr="203.0.113.4", relay_token="fresh")

        stored = {"host_id": "kvm1", "vm_action": "create", "offering_mode": "vm", "relay_id": "r"}
        plan = VmAnsibleCodec(relay_resolver=Resolver()).prepare(_run(stored))

        assert plan.variables["frp_auth_token"] == "fresh"
        assert plan.limit == "kvm1"

    def test_pool_variables_and_playbook_come_from_the_stored_parameters(self):
        stored = {
            "host_id": "kvm1",
            "vm_action": "create",
            "offering_mode": "vm",
            "playbook_path": "playbooks/custom.yaml",
            "provider_extra_vars": {"region": "eu"},
        }
        plan = VmAnsibleCodec().prepare(_run(stored))

        assert plan.extra_variables == {"region": "eu"}
        assert plan.playbook_path == Path("playbooks/custom.yaml")
        assert "region" not in plan.variables

    def test_reserved_keys_are_the_jobs_own_variables(self):
        codec = VmAnsibleCodec()
        params = _params(provider_extra_vars={"region": "eu"})
        assert codec.reserved_var_keys(params) == frozenset(codec.variables(params))
        assert "region" not in codec.reserved_var_keys(params)


# ---------------------------------------------------------------------------
# Retry classification and redaction, as the executor applies them for VM
# ---------------------------------------------------------------------------


class TestRetryClassification:
    @pytest.mark.parametrize(
        "message",
        ["VM target not found", "error: failed to get domain 'vm-1'", "DOMAIN NOT FOUND"],
    )
    def test_vm_failures_are_not_retried(self, message):
        assert VmAnsibleCodec().is_retryable(message) is False
        assert _executor().is_retryable(message) is False

    def test_transport_failures_are_not_retried(self):
        assert _executor().is_retryable("Fatal: Invalid SSH key provided") is False
        assert _executor().is_retryable("host UNREACHABLE: timeout") is False

    @pytest.mark.parametrize("message", ["Unexpected connection reset", ""])
    def test_other_failures_are_retried(self, message):
        assert _executor().is_retryable(message) is True


class TestRedaction:
    def test_the_root_keys_path_is_redacted(self):
        result = _executor().redact('"ssh_key_path_host": "/root/.ssh/id_ed25519"')
        assert '"ssh_key_path_host": "[REDACTED]"' in result

    def test_a_relay_token_is_redacted_in_json_and_yaml(self):
        executor = _executor()
        assert "admission" not in executor.redact('"frp_auth_token": "admission"')
        assert "admission" not in executor.redact("frp_auth_token: admission")

    def test_passwords_are_redacted_and_not_twice(self):
        executor = _executor()
        assert executor.redact("password: mysecret") == "password: [REDACTED]"
        assert executor.redact("password: [REDACTED]").count("[REDACTED]") == 1

    def test_a_backslash_escaped_printed_fact_is_redacted(self):
        """``json-output.yml``'s ``debug: msg:`` task is the transport the codec
        parses, so it cannot set ``no_log``; Ansible may render it escaped."""
        logs = (
            'ok: [kvm1] => {\n'
            '    "msg": "{\\n    \\"authentication\\": {\\n        '
            '\\"root\\": {\\n            \\"password\\": \\"aB3xY9zQ1mK7pL2n\\"'
            '\\n        }\\n    }\\n}"\n'
            '}'
        )
        assert "aB3xY9zQ1mK7pL2n" not in _executor().redact(logs)

    def test_a_nested_yaml_authentication_block_is_redacted(self):
        logs = (
            "ok: [kvm1] => \n"
            "  vm_creation_data:\n"
            "    authentication:\n"
            "      root:\n"
            "        password: aB3xY9zQ1mK7pL2n\n"
            "      tenant:\n"
            "        password: zQ1mK7pL2naB3xY9\n"
        )
        result = _executor().redact(logs)
        assert "aB3xY9zQ1mK7pL2n" not in result
        assert "zQ1mK7pL2naB3xY9" not in result

    def test_non_sensitive_content_is_preserved(self):
        logs = "TASK [Create VM] *** ok: [kvm1] => status: running"
        assert _executor().redact(logs) == logs


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class TestExtractSshPort:
    def test_extracts_from_json_field(self):
        assert extract_ssh_port('text "external_ssh_port": "54321" more') == "54321"

    def test_extracts_from_ssh_command_with_host(self):
        assert extract_ssh_port("ssh -i key -p 2222 root@kvm1", "kvm1") == "2222"

    def test_falls_back_to_a_generic_pattern(self):
        assert extract_ssh_port("connect using: ssh -p 9000 user@some.host.com") == "9000"

    def test_json_field_takes_precedence(self):
        assert extract_ssh_port('"external_ssh_port": "1111" ssh -p 2222 root@kvm1', "kvm1") == "1111"

    @pytest.mark.parametrize("output", ["no port info here", ""])
    def test_none_when_no_port_found(self, output):
        assert extract_ssh_port(output) is None


class TestExtractTenantUser:
    def test_extracts_from_json_field(self):
        assert extract_tenant_user('"tenant_user": "agentuser" and more') == "agentuser"

    def test_extracts_from_ssh_command_with_host(self):
        assert extract_tenant_user("ssh -p 2222 myuser@kvm1", "kvm1") == "myuser"

    def test_json_field_takes_precedence(self):
        assert extract_tenant_user('"tenant_user": "fromjson" ssh -p 22 fromcmd@kvm1', "kvm1") == "fromjson"

    def test_none_when_no_user_found(self):
        assert extract_tenant_user("nothing useful") is None


class TestExtractVmFact:
    def test_extracts_the_named_fact(self):
        output = 'ok: [kvm1] => {\n    "vm_list_data": {"action": "list", "vm_count": 2}\n}\n'
        assert extract_vm_fact(output, "list") == {"action": "list", "vm_count": 2}

    def test_falls_back_to_the_last_json_output_block(self):
        output = 'msg: |\n  {"action": "create", "vm_name": "a"}\nmsg: |\n  {"action": "create", "vm_name": "b"}\n'
        assert extract_vm_fact(output, "create")["vm_name"] == "b"

    @pytest.mark.parametrize("action,output", [("unknown", "anything"), ("create", "no json")])
    def test_none_without_a_fact(self, action, output):
        assert extract_vm_fact(output, action) is None

    @pytest.mark.parametrize(
        "action,fact_name",
        [
            ("create", "vm_creation_data"),
            ("list", "vm_list_data"),
            ("start", "vm_start_data"),
            ("shutdown", "vm_shutdown_data"),
            ("destroy", "vm_destroy_data"),
            ("reboot", "vm_reboot_data"),
            ("undefine", "vm_undefine_data"),
            ("monitor", "vm_monitoring_data"),
            ("reset_password", "vm_password_reset_data"),
            ("vm_remove", "vm_remove_data"),
            ("check", "check_data"),
        ],
    )
    def test_every_vm_action_has_its_fact(self, action, fact_name):
        assert extract_vm_fact(f'"{fact_name}": {{"action": "{action}"}}', action) == {"action": action}

    def test_extraction_sees_the_raw_unredacted_output(self):
        raw = '"vm_creation_data": {"action": "create", "authentication": {"root": {"password": "pw"}}}'
        assert extract_vm_fact(raw, "create")["authentication"]["root"]["password"] == "pw"


class TestTenantAddress:
    def test_host_ip_and_ssh_command_use_the_supplied_tenant_address(self):
        output = AnsibleResult(
            stdout='"external_ssh_port": "9000"\n"tenant_user": "tenantx"', stderr="", process_id=1
        )
        parsed = parse_vm_output(output, _params(), tenant_address="203.0.113.9")
        assert parsed.host_ip == "203.0.113.9"
        assert parsed.ssh_command == "ssh -i <your_private_key> -p 9000 tenantx@203.0.113.9"

    def test_without_an_address_no_command_is_built(self):
        output = AnsibleResult(
            stdout='"external_ssh_port": "9000"\n"tenant_user": "tenantx"', stderr="", process_id=1
        )
        parsed = parse_vm_output(output, _params(), tenant_address=None)
        assert parsed.host_ip is None
        assert parsed.ssh_command is None


def _output(**overrides) -> VmPlaybookOutput:
    values = dict(
        stdout="", stderr="", ssh_port=None, tenant_user=None, host_ip=None,
        ssh_command=None, ansible_result=None,
    )
    values.update(overrides)
    return VmPlaybookOutput(**values)


class TestBuildResultPayload:
    def test_no_fact_returns_base_fields(self):
        payload = build_result_payload(_output(ssh_port="2222", tenant_user="agent", host_ip="10.0.0.1"))
        assert (payload["ssh_port"], payload["tenant_user"], payload["host_ip"]) == ("2222", "agent", "10.0.0.1")
        assert payload["ansible_result"] is None

    def test_fact_fields_promoted(self):
        fact = {"action": "create", "vm_name": "test-vm", "status": "running", "host": "kvm1"}
        payload = build_result_payload(_output(ansible_result=fact))
        assert (payload["action"], payload["vm_name"], payload["status"]) == ("create", "test-vm", "running")
        assert payload["ansible_result"] is fact

    def test_authentication_block_nested(self):
        fact = {
            "action": "create",
            "authentication": {
                "tenant": {"password": "pw", "key_type": "provided", "ssh_commands": {"external": "ssh -p 2222 u@h"}},
                "root": {"password": "rootpw", "ssh_commands": {}, "ssh_key_path_host": "/root/key"},
            },
        }
        payload = build_result_payload(_output(ansible_result=fact, ssh_command="ssh -p 0 fallback@host"))
        assert payload["authentication"]["tenant"]["password"] == "pw"
        assert payload["authentication"]["root"]["ssh_key_path_host"] == "/root/key"
        assert payload["ssh_command"] == "ssh -p 2222 u@h"

    def test_relay_remote_port_overrides_ssh_port(self):
        fact = {"action": "create", "frp": {"remote_port": "54321", "subdomain": "vm-abc"}}
        payload = build_result_payload(_output(ssh_port="2222", ansible_result=fact))
        assert payload["ssh_port"] == "54321"
        assert payload["frp"]["subdomain"] == "vm-abc"

    def test_vm_list_with_count(self):
        vms = [{"name": "vm-a"}, {"name": "vm-b"}]
        payload = build_result_payload(_output(ansible_result={"action": "list", "vms": vms, "vm_count": 2}))
        assert (payload["vms"], payload["vm_count"]) == (vms, 2)

    def test_flat_resource_fields_restructured(self):
        fact = {"action": "monitor", "cpu_usage_percent": 42.0, "memory_used_mb": 4096}
        payload = build_result_payload(_output(ansible_result=fact))
        assert payload["resources"]["cpu"]["usage_percent"] == 42.0
        assert payload["resources"]["memory"]["used_mb"] == 4096

    def test_prebuilt_resources_used_directly(self):
        resources = {"vcpus_total": 32}
        payload = build_result_payload(_output(ansible_result={"action": "check", "resources": resources}))
        assert payload["resources"] == resources


class TestCredentials:
    def test_each_role_becomes_a_credential_and_leaves_the_result(self):
        payload = build_result_payload(
            _output(
                ansible_result={
                    "action": "create",
                    "authentication": {
                        "tenant": {"password": "t", "ssh_commands": {"external": "ssh -p 2222"}},
                        "root": {"password": "r", "ssh_key_path_host": "/root/key"},
                    },
                }
            )
        )

        value, credentials = split_credentials(payload, "vm")

        assert [c.credential_kind for c in credentials] == ["root", "tenant"]
        assert credentials[0].value == {"password": "r", "ssh_key_path_host": "/root/key"}
        assert credentials[1].value["ssh_commands"] == {"external": "ssh -p 2222"}
        assert "authentication" not in value
        assert "authentication" not in value["ansible_result"]

    def test_a_result_without_authentication_carries_no_credential(self):
        payload = {"action": "list"}
        assert split_credentials(payload, "vm") == (payload, ())


def test_a_run_reports_the_vm_result_and_credentials() -> None:
    """End to end through the executor with a stand-in runner."""
    stdout = (
        'ok: [kvm1] => {\n    "vm_creation_data": {"action": "create", "status": "running", '
        '"tenant_user": "tenant", "external_ssh_port": "2222", '
        '"authentication": {"root": {"password": "r"}, "tenant": {"password": "t"}}}\n}\n'
    )
    runner = MagicMock()
    runner.write_inventory.return_value = MaterializedInventory(path=Path("/tmp/does-not-exist.ini"))
    runner.start_playbook.return_value = SimpleNamespace(process_id=4242)

    async def wait(run, timeout_seconds, log_callback=None, redact=None):
        return AnsibleResult(stdout=stdout, stderr="", process_id=4242)

    runner.wait_for_playbook = wait

    outcome = asyncio.run(
        _executor(runner=runner).execute(
            _run({"host_id": "kvm1", "vm_action": "create", "offering_mode": "vm"})
        )
    )

    assert isinstance(outcome, JobSuccess)
    assert outcome.result.result_kind == CREATE_JOB_RESULT_KIND
    created = CreateJobResult.model_validate(outcome.result.value)
    assert created.evidence is None  # the fact reported no time it became ready
    assert created.detail["host_ip"] == "203.0.113.1"
    assert created.detail["ssh_port"] == "2222"
    assert [c.credential_kind for c in outcome.credentials] == ["root", "tenant"]
    assert "authentication" not in str(outcome.result.value)
    assert '"password": "[REDACTED]"' in outcome.logs
    assert runner.write_inventory.call_args.kwargs["group"] == VM_INVENTORY_GROUP


_DIRECT = {
    "action": "create", "status": "running", "vm_name": "tenant-1", "host": "kvm1",
    "timestamp": "2030-01-01T00:00:01Z", "tenant_user": "tenant1",
    "host_ip": "203.0.113.1", "ssh_port": "2222", "vm_ip_internal": "192.168.122.9",
    "ansible_result": {"raw": "fact"},
}
_RELAY = {
    **_DIRECT,
    "ssh_port": "40001",
    "frp": {"enabled": "True", "relay_addr": "relay.example", "remote_port": "40001"},
}


def _create_params(**fields) -> VmJobParams:
    return VmJobParams(host_id="kvm1", vm_action="create", offering_mode="vm", **fields)


class TestCreateResult:
    """A create's result: evidence by the relay rule, and a projected detail."""

    def test_a_direct_guest_is_reached_at_its_hosts_address_and_forwarded_port(self):
        created = create_result(_DIRECT, _create_params())

        (endpoint,) = created.evidence.endpoints
        assert (endpoint.host, endpoint.port, endpoint.user) == ("203.0.113.1", 2222, "tenant1")
        assert created.evidence.ready_at.isoformat() == "2030-01-01T00:00:01+00:00"

    def test_a_relayed_guest_is_reached_at_the_relay_and_its_leased_port(self):
        created = create_result(_RELAY, _create_params(relay_id="r1", vm_remote_port=40001))

        (endpoint,) = created.evidence.endpoints
        assert (endpoint.host, endpoint.port) == ("relay.example", 40001)

    def test_a_reported_relay_port_other_than_the_lease_yields_no_evidence(self):
        created = create_result(_RELAY, _create_params(relay_id="r1", vm_remote_port=40002))

        assert created.evidence is None
        assert created.detail["frp"]["remote_port"] == "40001"

    def test_a_relayed_guest_with_no_relay_reported_yields_no_evidence(self):
        assert create_result(_DIRECT, _create_params(relay_id="r1", vm_remote_port=40001)).evidence is None

    @pytest.mark.parametrize("user", [None, "", "  "])
    def test_an_endpoint_naming_no_tenant_account_is_no_evidence(self, user):
        assert create_result({**_DIRECT, "tenant_user": user}, _create_params()).evidence is None

    def test_the_detail_is_the_named_operator_fields_and_never_the_raw_fact(self):
        created = create_result(_DIRECT, _create_params())

        assert created.detail["vm_ip_internal"] == "192.168.122.9"
        assert created.detail["vm_name"] == "tenant-1"
        assert set(created.detail) <= set(VM_CREATE_DETAIL)
        assert "ansible_result" not in created.detail

    def test_the_playbooks_tenant_command_uses_the_same_address_and_port(self):
        """The playbook builds the tenant's external command from the forwarded
        port and the host's tenant address on the direct path, and from the
        leased port and the relay's address behind a relay: the pairs the
        evidence names on each path."""
        create = (_ANSIBLE_ROOT / "roles/vm-management/tasks/vm-create.yml").read_text()
        tenant = next(
            line for line in create.splitlines()
            if "external:" in line and "<your_private_key>" in line
        )
        direct, relay = tenant.split(" else ", 1)
        assert "external_ssh_port" in direct and "tenant_ssh_host" in direct
        assert "vm_remote_port" in relay and "frp_server_addr" in relay


class TestPlaybookContract:
    """The codec renders the host as ``host_id`` and the VM playbook reads it.

    The playbook defaults an unset host to ``localhost``, so reading a name the
    codec no longer renders would run against the provisioner itself rather
    than fail; pinning both ends keeps a rename from degrading into that.
    """

    playbook = (_ANSIBLE_ROOT / "playbooks/single-tenant/vm-operations.yaml").read_text()

    def test_the_variables_name_the_host_host_id(self):
        variables = _variables(host_id="kvm7")
        assert variables["host_id"] == "kvm7"
        assert not any(name.startswith("vm_host") for name in variables)

    def test_the_playbook_targets_host_id(self):
        assert "target_host: \"{{ host_id | default('localhost') }}\"" in self.playbook
        assert not re.search(r"\bvm_host\b", self.playbook)

    def test_the_playbook_targets_the_codecs_inventory_group(self):
        assert f"hosts: {VM_INVENTORY_GROUP}" in self.playbook

    def test_the_inventory_target_carries_the_tenant_address(self):
        target = inventory_target(_HOST)
        assert (target.public_host, target.ssh_host) == ("203.0.113.1", "10.0.0.1")
