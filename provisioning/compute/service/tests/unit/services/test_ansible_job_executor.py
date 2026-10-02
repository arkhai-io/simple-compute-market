"""The Ansible job executor's interpretation of parameters and playbook output.

Covers how a job's stored parameters are rebuilt, which failures are retryable,
redaction, and the result payload a playbook's facts become. Running a job end
to end through the job service is exercised in the service's integration tests.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost, ProtectedValue
from compute_provisioning.jobs import JobFailure, JobRun, JobSuccess

from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams, AnsibleRunResult
from vm_provisioning_adapter.services.ansible_job_executor import AnsibleJobExecutor
from compute_provisioning_ansible.runner import inventory_target
from compute_provisioning_ansible import SshConnectionCodec
from compute_provisioning_ansible.runner import (
    AnsibleError,
    AnsibleResult,
    AnsibleRunner,
    MaterializedInventory,
)
from cryptography.fernet import Fernet
from market_config import encrypt_secret


def _make_executor(**settings_overrides) -> AnsibleJobExecutor:
    settings = MagicMock()
    settings.default_host_id = "kvm1"
    settings.non_retryable_errors = [
        "Invalid SSH key",
        "VM target not found",
        "Permission denied",
        "Authentication failed",
        "UNREACHABLE",
        "Domain not found",
    ]
    for k, v in settings_overrides.items():
        setattr(settings, k, v)
    return AnsibleJobExecutor(
        MagicMock(),
        Path("/playbooks/vm-operations.yaml"),
        settings=settings,
        result_kind=lambda action: f"vm_{action}",
    )


# ---------------------------------------------------------------------------
# build_params
# ---------------------------------------------------------------------------


class TestBuildParams:
    def test_basic_fields_mapped(self):
        executor = _make_executor()
        params = executor.build_params({
            "host_id": "ww2",
            "offering_mode": "vm",
            "vm_target": "my-vm",
            "vm_action": "shutdown",
        })
        assert params.host_id == "ww2"
        assert params.vm_target == "my-vm"
        assert params.vm_action == "shutdown"

    def test_defaults_applied_for_missing_keys(self):
        executor = _make_executor()
        params = executor.build_params({"offering_mode": "vm"})
        assert params.host_id == "kvm1"  # from settings.default_host_id
        assert params.vm_action == "create"
        assert params.image_setup_type == "scratch"

    def test_optional_fields_are_none_when_absent(self):
        executor = _make_executor()
        params = executor.build_params({
            "offering_mode": "vm",
            "host_id": "kvm1",
            "vm_action": "list",
        })
        assert params.vm_ram is None
        assert params.vm_vcpus is None
        assert params.ssh_pubkey is None
        assert params.gpu_provisioned is None

    def test_all_optional_fields_mapped(self):
        executor = _make_executor()
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
        params = executor.build_params(raw)
        assert params.image_setup_type == "golden"
        assert params.vm_ram == 8192
        assert params.vm_vcpus == 8
        assert params.vm_disk_size == "40G"
        assert params.vm_os_variant == "ubuntu22.04"
        assert params.ssh_pubkey == "ssh-ed25519 AAAA..."
        assert params.gpu_provisioned is True
        assert params.vm_gpu_count == 2
        assert params.vm_gpu_device == "0000:03:00.0"
        assert params.vm_gpu_devices == ["0000:03:00.0", "0000:04:00.0"]
        assert params.vm_gpu_partition_size == "1g.5gb"
        assert params.relay_id == "site-a"
        assert params.vm_remote_port == 6100
        # Stored params never carry the endpoint or the token.
        assert params.relay_addr is None
        assert params.relay_token is None
        assert params.golden_image_name == "base-v3"
        assert params.gcs_bucket_url == "gs://bucket"
        assert params.gcs_image_path == "images/img.qcow2"

    def test_relay_fields_have_no_settings_fallback(self):
        """A service-wide relay default would let a job reach a relay its pool
        does not name, and would substitute one relay's window for another's.
        Relay location is resolved from the pool's referenced relay at dispatch
        or it is absent."""
        executor = _make_executor()
        params = executor.build_params(
            {"host_id": "kvm1", "vm_action": "create", "offering_mode": "vm"}
        )
        assert params.relay_id is None
        assert params.vm_remote_port is None
        assert params.relay_addr is None
        assert params.relay_token is None

    def test_returns_ansible_job_params_instance(self):
        executor = _make_executor()
        params = executor.build_params({"offering_mode": "vm"})
        assert isinstance(params, AnsibleJobParams)

    def test_bare_metal_fields_mapped(self):
        executor = _make_executor()
        params = executor.build_params({
            "host_id": "bm-node-1",
            "vm_target": "bm-node-1",
            "vm_action": NODE_GRANT_ACCESS_ACTION,
            "offering_mode": "bare_metal",
            "executor_action": NODE_GRANT_ACCESS_ACTION,
            "executor_target": "bm-node-1",
            "executor_ref": {
                "physical_host_id": "host-physical-1",
                "ssh_user": "tenant-a",
            },
            "escrow_uid": "0xbm",
            "physical_host_id": "host-physical-1",
            "ssh_user": "tenant-a",
            "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
            "access_ref": {"ssh_user": "tenant-a"},
            "bare_metal_reclaim_policy": "delete_user",
        })

        assert params.escrow_uid == "0xbm"
        assert params.offering_mode == "bare_metal"
        assert params.executor_action == NODE_GRANT_ACCESS_ACTION
        assert params.executor_target == "bm-node-1"
        assert params.executor_ref == {
            "physical_host_id": "host-physical-1",
            "ssh_user": "tenant-a",
        }
        assert params.physical_host_id == "host-physical-1"
        assert params.ssh_user == "tenant-a"
        assert params.ssh_public_key == "ssh-ed25519 AAAA tenant-a"
        assert params.access_ref == {"ssh_user": "tenant-a"}
        assert params.bare_metal_reclaim_policy == "delete_user"

    def test_explicit_vm_identity_maps_legacy_vm_action_fields(self):
        executor = _make_executor()
        params = executor.build_params({
            "offering_mode": "vm",
            "host_id": "kvm1",
            "vm_target": "test-vm",
            "vm_action": "shutdown",
        })

        assert params.offering_mode == "vm"
        assert params.executor_action == "shutdown"
        assert params.executor_target == "test-vm"

    def test_missing_offering_mode_fails_closed(self):
        executor = _make_executor()

        with pytest.raises(KeyError, match="offering_mode"):
            executor.build_params({
                "host_id": "kvm1",
                "vm_target": "test-vm",
                "vm_action": "shutdown",
            })

    def test_executor_target_does_not_force_vm_target(self):
        executor = _make_executor()
        params = executor.build_params({
            "host_id": "kvm1",
            "vm_action": "list",
            "offering_mode": "vm",
            "executor_action": "list",
            "executor_target": "kvm1",
        })

        assert params.vm_target is None
        assert params.executor_target == "kvm1"


# ---------------------------------------------------------------------------
# _redact_logs
# ---------------------------------------------------------------------------


class TestRedactLogs:
    def test_redacts_json_password_field(self):
        executor = _make_executor()
        logs = '"password": "supersecret"'
        result = executor.redact(logs)
        assert "supersecret" not in result
        assert '"password": "[REDACTED]"' in result

    def test_redacts_json_ssh_key_path_host(self):
        executor = _make_executor()
        logs = '"ssh_key_path_host": "/root/.ssh/id_ed25519"'
        result = executor.redact(logs)
        assert "/root/.ssh/id_ed25519" not in result
        assert '"ssh_key_path_host": "[REDACTED]"' in result

    def test_redacts_yaml_password_line(self):
        executor = _make_executor()
        logs = "password: mysecretpassword"
        result = executor.redact(logs)
        assert "mysecretpassword" not in result
        assert "password: [REDACTED]" in result

    def test_does_not_double_redact_already_redacted(self):
        executor = _make_executor()
        logs = "password: [REDACTED]"
        result = executor.redact(logs)
        assert result.count("[REDACTED]") == 1

    def test_redacts_ssh_key_in_cli_flag(self):
        executor = _make_executor()
        logs = "ansible -i inv ... -i /root/.ssh/id_ed25519 host"
        result = executor.redact(logs)
        assert "/root/.ssh/id_ed25519" not in result
        assert "-i [REDACTED]" in result

    def test_redacts_sshpass_password(self):
        executor = _make_executor()
        logs = "sshpass -p mysecretpw ssh root@host"
        result = executor.redact(logs)
        assert "mysecretpw" not in result
        assert "sshpass -p [REDACTED]" in result

    def test_non_sensitive_content_preserved(self):
        executor = _make_executor()
        logs = "TASK [Create VM] *** ok: [kvm1] => status: running"
        result = executor.redact(logs)
        assert result == logs

    def test_redacts_backslash_escaped_json_password(self):
        """`json-output.yml`'s `debug: msg: "{{ vm_creation_json }}"` task
        is the literal transport `_extract_ansible_json` parses, so it
        cannot get `no_log`. Depending on Ansible's
        stdout_callback/result_format, that debug message can render as a
        backslash-escaped JSON string nested inside the outer task result
        -- the redaction pattern must match both the unescaped and
        escaped forms.
        """
        executor = _make_executor()
        logs = (
            'ok: [kvm1] => {\n'
            '    "msg": "{\\n    \\"authentication\\": {\\n        '
            '\\"root\\": {\\n            \\"password\\": \\"aB3xY9zQ1mK7pL2n\\"'
            '\\n        }\\n    }\\n}"\n'
            '}'
        )
        result = executor.redact(logs)
        assert "aB3xY9zQ1mK7pL2n" not in result

    def test_redacts_nested_yaml_authentication_block(self):
        """`json-output.yml`'s `debug: var: vm_creation_data` task renders
        as a nested YAML dump, not a top-level `password:` key -- the
        scrubber must catch this shape too."""
        executor = _make_executor()
        logs = (
            "ok: [kvm1] => \n"
            "  vm_creation_data:\n"
            "    authentication:\n"
            "      root:\n"
            "        password: aB3xY9zQ1mK7pL2n\n"
            "      tenant:\n"
            "        password: zQ1mK7pL2naB3xY9\n"
        )
        result = executor.redact(logs)
        assert "aB3xY9zQ1mK7pL2n" not in result
        assert "zQ1mK7pL2naB3xY9" not in result

    def test_empty_string_returned_unchanged(self):
        executor = _make_executor()
        assert executor.redact("") == ""

    def test_none_returned_unchanged(self):
        executor = _make_executor()
        assert executor.redact(None) is None


# ---------------------------------------------------------------------------
# is_retryable
# ---------------------------------------------------------------------------


class TestIsRetryable:
    def test_retryable_generic_error(self):
        executor = _make_executor()
        assert executor.is_retryable("Unexpected connection reset") is True

    def test_non_retryable_exact_match(self):
        executor = _make_executor()
        assert executor.is_retryable("Invalid SSH key") is False

    def test_non_retryable_substring_match(self):
        executor = _make_executor()
        assert executor.is_retryable("Fatal: Invalid SSH key provided") is False

    def test_non_retryable_case_insensitive(self):
        executor = _make_executor()
        assert executor.is_retryable("INVALID SSH KEY") is False

    def test_unreachable_is_non_retryable(self):
        executor = _make_executor()
        assert executor.is_retryable("host UNREACHABLE: timeout") is False

    def test_empty_error_is_retryable(self):
        executor = _make_executor()
        assert executor.is_retryable("") is True


# ---------------------------------------------------------------------------
# build_result_payload
# ---------------------------------------------------------------------------


def _base_run_result(**overrides) -> AnsibleRunResult:
    defaults = dict(
        stdout="",
        stderr="",
        ssh_port=None,
        tenant_user=None,
        host_ip=None,
        ssh_command=None,
        ansible_result=None,
        process_id=12345,
    )
    defaults.update(overrides)
    return AnsibleRunResult(**defaults)


class TestBuildResultPayload:
    def test_no_ansible_result_returns_base_fields(self):
        executor = _make_executor()
        result = _base_run_result(ssh_port="2222", tenant_user="agent", host_ip="10.0.0.1")
        payload = executor.build_result_payload(result)
        assert payload["ssh_port"] == "2222"
        assert payload["tenant_user"] == "agent"
        assert payload["host_ip"] == "10.0.0.1"
        assert payload["ansible_result"] is None

    def test_ansible_result_fields_promoted(self):
        executor = _make_executor()
        ar = {
            "action": "create",
            "vm_name": "test-vm",
            "status": "running",
            "host": "kvm1",
            "timestamp": "2025-01-01T00:00:00Z",
        }
        payload = executor.build_result_payload(_base_run_result(ansible_result=ar))
        assert payload["action"] == "create"
        assert payload["vm_name"] == "test-vm"
        assert payload["status"] == "running"

    def test_authentication_block_nested_correctly(self):
        executor = _make_executor()
        ar = {
            "action": "create",
            "authentication": {
                "tenant": {
                    "password": "pw",
                    "key_type": "provided",
                    "ssh_commands": {"external": "ssh -p 2222 user@host"},
                },
                "root": {
                    "password": "rootpw",
                    "ssh_commands": {},
                    "ssh_key_path_host": "/root/.ssh/id_ed25519",
                },
            },
        }
        payload = executor.build_result_payload(_base_run_result(ansible_result=ar))
        assert payload["authentication"]["tenant"]["password"] == "pw"
        assert payload["authentication"]["root"]["ssh_key_path_host"] == "/root/.ssh/id_ed25519"

    def test_tenant_ssh_command_overrides_top_level(self):
        executor = _make_executor()
        ar = {
            "action": "create",
            "authentication": {
                "tenant": {
                    "ssh_commands": {"external": "ssh -p 9000 agent@frp.host"},
                    "password": "pw",
                    "key_type": "provided",
                },
                "root": {},
            },
        }
        payload = executor.build_result_payload(
            _base_run_result(ssh_command="ssh -p 0 fallback@host", ansible_result=ar)
        )
        assert payload["ssh_command"] == "ssh -p 9000 agent@frp.host"

    def test_frp_remote_port_overrides_ssh_port(self):
        executor = _make_executor()
        ar = {"action": "create", "frp": {"remote_port": "54321", "subdomain": "vm-abc"}}
        payload = executor.build_result_payload(_base_run_result(ssh_port="2222", ansible_result=ar))
        assert payload["ssh_port"] == "54321"
        assert payload["frp"]["subdomain"] == "vm-abc"

    def test_vms_list_with_count(self):
        executor = _make_executor()
        vms = [{"name": "vm-a"}, {"name": "vm-b"}]
        ar = {"action": "list", "vms": vms, "vm_count": 2}
        payload = executor.build_result_payload(_base_run_result(ansible_result=ar))
        assert payload["vms"] == vms
        assert payload["vm_count"] == 2

    def test_flat_resource_fields_restructured(self):
        executor = _make_executor()
        ar = {
            "action": "monitor",
            "cpu_usage_percent": 42.0,
            "memory_used_mb": 4096,
            "memory_available_mb": 4096,
            "memory_usage_percent": 50.0,
        }
        payload = executor.build_result_payload(_base_run_result(ansible_result=ar))
        assert payload["resources"]["cpu"]["usage_percent"] == 42.0
        assert payload["resources"]["memory"]["used_mb"] == 4096

    def test_prebuilt_resources_block_used_directly(self):
        executor = _make_executor()
        resources = {"vcpus_total": 32, "vcpus_available": 16}
        ar = {"action": "check", "resources": resources}
        payload = executor.build_result_payload(_base_run_result(ansible_result=ar))
        assert payload["resources"] == resources

    def test_ansible_result_included_in_payload(self):
        executor = _make_executor()
        ar = {"action": "create", "vm_name": "test-vm"}
        payload = executor.build_result_payload(_base_run_result(ansible_result=ar))
        assert payload["ansible_result"] is ar


# ---------------------------------------------------------------------------
# execute and cancel
# ---------------------------------------------------------------------------

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
_CREATE_OUTPUT = AnsibleRunResult(
    stdout="password: hunter2",
    stderr="",
    ssh_port="2222",
    tenant_user="tenant",
    host_ip="203.0.113.1",
    ssh_command=None,
    ansible_result={
        "action": "create",
        "authentication": {
            "tenant": {"password": "t", "ssh_commands": {"external": "ssh -p 2222"}},
            "root": {"password": "r", "ssh_key_path_host": "/root/key"},
        },
    },
    process_id=4242,
)


def _runner(*, failure: AnsibleError | None = None):
    runner = MagicMock()
    runner.build_vars_file.return_value = Path("/tmp/vars.yml")
    runner.write_inventory.return_value = MaterializedInventory(
        path=Path("/tmp/does-not-exist.ini")
    )
    runner.start_playbook.return_value = SimpleNamespace(process_id=4242)

    async def wait(run, timeout_seconds, log_callback=None):
        log_callback("password: hunter2", "")
        if failure is not None:
            raise failure
        return AnsibleResult(stdout="", stderr="", process_id=4242)

    runner.wait_for_playbook = wait
    runner.parse_playbook_result.return_value = _CREATE_OUTPUT
    return runner


def _run(**overrides) -> tuple[JobRun, list, list]:
    handles: list = []
    logs: list = []
    values = dict(
        job_id="job-1",
        offering_mode="vm",
        action="create",
        host=_HOST,
        parameters={"offering_mode": "vm", "vm_action": "create", "host_id": "kvm1"},
        report_handle=handles.append,
        report_logs=logs.append,
    )
    values.update(overrides)
    return JobRun(**values), handles, logs


def _executor_over(runner) -> AnsibleJobExecutor:
    settings = MagicMock(ansible_timeout_seconds=30, default_host_id="kvm1")
    settings.non_retryable_errors = ["UNREACHABLE"]
    return AnsibleJobExecutor(
        runner,
        Path("/playbooks/vm.yaml"),
        settings=settings,
        result_kind=lambda action: f"vm_{action}",
    )


def test_a_successful_run_reports_its_handle_result_and_credentials() -> None:
    runner = _runner()
    run, handles, logs = _run()

    outcome = asyncio.run(_executor_over(runner).execute(run))

    assert isinstance(outcome, JobSuccess)
    assert handles == [{"pid": 4242}]
    assert logs and "hunter2" not in logs[0]
    assert "hunter2" not in outcome.logs
    assert outcome.result.offering_mode == "vm"
    assert outcome.result.result_kind == "vm_create"
    assert "authentication" not in outcome.result.value
    assert "authentication" not in outcome.result.value["ansible_result"]
    assert [c.credential_kind for c in outcome.credentials] == ["root", "tenant"]
    assert outcome.credentials[1].value["ssh_commands"] == {"external": "ssh -p 2222"}
    inventory_host = runner.write_inventory.call_args.args[0][0]
    assert (inventory_host.host_id, inventory_host.ssh_host) == ("kvm1", "10.0.0.1")
    assert runner.parse_playbook_result.call_args.kwargs["tenant_address"] == "203.0.113.1"


@pytest.mark.parametrize(
    "message,retryable",
    [("host UNREACHABLE", False), ("connection reset", True)],
)
def test_a_playbook_failure_is_classified(message, retryable) -> None:
    run, _, _ = _run()

    outcome = asyncio.run(
        _executor_over(
            _runner(failure=AnsibleError(message, stdout="password: x", stderr=""))
        ).execute(run)
    )

    assert isinstance(outcome, JobFailure)
    assert outcome.error.message == message
    assert outcome.error.retryable is retryable
    assert "password: x" not in outcome.logs


def test_a_host_reached_other_than_over_ssh_is_refused_before_anything_runs() -> None:
    runner = _runner()
    run, _, _ = _run(
        host=ExecutionHost("kvm1", "default", ConnectionEnvelope(kind="cloud_api", version=1))
    )

    with pytest.raises(ValueError, match="over ssh"):
        asyncio.run(_executor_over(runner).execute(run))
    runner.start_playbook.assert_not_called()


def test_cancel_stops_the_reported_process() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        asyncio.run(_executor_over(_runner()).cancel({"pid": process.pid}))
        assert process.wait(timeout=10) != 0
    finally:
        if process.poll() is None:
            process.kill()


def test_cancelling_a_process_that_already_ended_is_not_an_error() -> None:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=10)

    asyncio.run(_executor_over(_runner()).cancel({"pid": process.pid}))


def test_an_embedded_key_reaches_the_runner_still_protected() -> None:
    host = ExecutionHost(
        host_id="bm1",
        pool_id="default",
        connection=ConnectionEnvelope(
            kind="ssh",
            version=1,
            public={"ssh_host": "10.0.1.1", "ssh_port": 2201, "ssh_user": "ops", "key_path": None},
            protected={"private_key": ProtectedValue("fernet-v1", "gAAAA-token")},
        ),
    )

    target = inventory_target(host)

    assert (target.ssh_key_type, target.ssh_key_value, target.ssh_port) == (
        "embedded",
        "gAAAA-token",
        2201,
    )
    assert "gAAAA-token" not in repr(target)


@pytest.mark.parametrize("ending", ["success", "failure", "timeout", "cancelled"])
def test_a_decrypted_key_exists_only_while_its_playbook_runs(ending) -> None:
    """Whatever ends the run, the decrypted key and the inventory are removed."""
    key = Fernet.generate_key().decode()
    runner = _runner()
    runner.write_inventory = AnsibleRunner(
        SimpleNamespace(), ssh_codec=SshConnectionCodec(key)
    ).write_inventory
    seen: dict = {}

    async def wait(run, timeout_seconds, log_callback=None):
        inventory_path = runner.start_playbook.call_args.kwargs["inventory_path"]
        reference = inventory_path.read_text().split("ansible_ssh_private_key_file=")[1]
        seen["inventory"] = inventory_path
        seen["key"] = Path(reference.split()[0])
        seen["key existed"] = seen["key"].exists()
        if ending == "failure":
            raise AnsibleError("boom", stdout="", stderr="")
        if ending == "timeout":
            raise AnsibleError("Playbook timed out", stdout="", stderr="")
        if ending == "cancelled":
            raise asyncio.CancelledError()
        return AnsibleResult(stdout="", stderr="", process_id=4242)

    runner.wait_for_playbook = wait
    host = ExecutionHost(
        host_id="bm1",
        pool_id="default",
        connection=ConnectionEnvelope(
            kind="ssh",
            version=1,
            public={"ssh_host": "10.0.1.1", "ssh_port": 22, "ssh_user": "ops", "key_path": None},
            protected={"private_key": ProtectedValue("fernet-v1", encrypt_secret("PEM", key))},
        ),
    )
    run, _, _ = _run(host=host)

    if ending == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(_executor_over(runner).execute(run))
    else:
        asyncio.run(_executor_over(runner).execute(run))

    assert seen["key existed"]
    assert not seen["key"].exists()
    assert not seen["inventory"].exists()
