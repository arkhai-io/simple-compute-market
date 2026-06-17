"""
Unit tests for AnsibleJobService private utility methods.

Covers: _build_params, _redact_logs, _calculate_retry_delay,
_should_retry_error, _build_result_payload.

Orchestration methods (submit, list_jobs, _process_job, etc.) delegate to
the DB and queue — they are exercised in integration tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from models.jobs_model import AnsibleJobParams, AnsibleRunResult
from services.job_service import AnsibleJobService


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _make_service(**settings_overrides) -> AnsibleJobService:
    settings = MagicMock()
    settings.default_vm_host = "kvm1"
    settings.default_max_retries = 3
    settings.retry_backoff_initial_seconds = 60
    settings.retry_backoff_multiplier = 2.0
    settings.retry_backoff_max_seconds = 3600
    settings.non_retryable_errors = [
        "Invalid SSH key",
        "VM target not found",
        "Permission denied",
        "Authentication failed",
        "UNREACHABLE",
        "Domain not found",
    ]
    settings.frp_server_addr = ""
    settings.frp_domain = ""
    settings.frp_dashboard_password = ""
    for k, v in settings_overrides.items():
        setattr(settings, k, v)

    return AnsibleJobService(
        settings=settings,
        session_factory=MagicMock(),
        ansible_service=MagicMock(),
    )


# ---------------------------------------------------------------------------
# _build_params
# ---------------------------------------------------------------------------


class TestBuildParams:
    def test_basic_fields_mapped(self):
        svc = _make_service()
        params = svc._build_params({
            "vm_host": "ww2",
            "vm_target": "my-vm",
            "vm_action": "shutdown",
        })
        assert params.vm_host == "ww2"
        assert params.vm_target == "my-vm"
        assert params.vm_action == "shutdown"

    def test_defaults_applied_for_missing_keys(self):
        svc = _make_service()
        params = svc._build_params({})
        assert params.vm_host == "kvm1"  # from settings.default_vm_host
        assert params.vm_action == "create"
        assert params.image_setup_type == "scratch"

    def test_optional_fields_are_none_when_absent(self):
        svc = _make_service()
        params = svc._build_params({"vm_host": "kvm1", "vm_action": "list"})
        assert params.vm_ram is None
        assert params.vm_vcpus is None
        assert params.ssh_pubkey is None
        assert params.gpu_provisioned is None

    def test_all_optional_fields_mapped(self):
        svc = _make_service()
        raw = {
            "vm_host": "kvm1",
            "vm_target": "test-vm",
            "vm_action": "create",
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
            "frp_server_addr": "1.2.3.4",
            "frp_domain": "example.com",
            "frp_dashboard_password": "secret",
            "golden_image_name": "base-v3",
            "gcs_bucket_url": "gs://bucket",
            "gcs_image_path": "images/img.qcow2",
        }
        params = svc._build_params(raw)
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
        assert params.frp_server_addr == "1.2.3.4"
        assert params.frp_domain == "example.com"
        assert params.frp_dashboard_password == "secret"
        assert params.golden_image_name == "base-v3"
        assert params.gcs_bucket_url == "gs://bucket"
        assert params.gcs_image_path == "images/img.qcow2"

    def test_frp_falls_back_to_settings_when_not_in_params(self):
        svc = _make_service(frp_server_addr="9.9.9.9", frp_domain="fallback.com")
        params = svc._build_params({"vm_host": "kvm1", "vm_action": "create"})
        assert params.frp_server_addr == "9.9.9.9"
        assert params.frp_domain == "fallback.com"

    def test_frp_param_overrides_settings(self):
        svc = _make_service(frp_server_addr="9.9.9.9")
        params = svc._build_params({
            "vm_host": "kvm1",
            "vm_action": "create",
            "frp_server_addr": "1.1.1.1",
        })
        assert params.frp_server_addr == "1.1.1.1"

    def test_returns_ansible_job_params_instance(self):
        svc = _make_service()
        params = svc._build_params({})
        assert isinstance(params, AnsibleJobParams)


# ---------------------------------------------------------------------------
# _redact_logs
# ---------------------------------------------------------------------------


class TestRedactLogs:
    def test_redacts_json_password_field(self):
        svc = _make_service()
        logs = '"password": "supersecret"'
        result = svc._redact_logs(logs)
        assert "supersecret" not in result
        assert '"password": "[REDACTED]"' in result

    def test_redacts_json_ssh_key_path_host(self):
        svc = _make_service()
        logs = '"ssh_key_path_host": "/root/.ssh/id_ed25519"'
        result = svc._redact_logs(logs)
        assert "/root/.ssh/id_ed25519" not in result
        assert '"ssh_key_path_host": "[REDACTED]"' in result

    def test_redacts_yaml_password_line(self):
        svc = _make_service()
        logs = "password: mysecretpassword"
        result = svc._redact_logs(logs)
        assert "mysecretpassword" not in result
        assert "password: [REDACTED]" in result

    def test_does_not_double_redact_already_redacted(self):
        svc = _make_service()
        logs = "password: [REDACTED]"
        result = svc._redact_logs(logs)
        assert result.count("[REDACTED]") == 1

    def test_redacts_ssh_key_in_cli_flag(self):
        svc = _make_service()
        logs = "ansible -i inv ... -i /root/.ssh/id_ed25519 host"
        result = svc._redact_logs(logs)
        assert "/root/.ssh/id_ed25519" not in result
        assert "-i [REDACTED]" in result

    def test_redacts_sshpass_password(self):
        svc = _make_service()
        logs = "sshpass -p mysecretpw ssh root@host"
        result = svc._redact_logs(logs)
        assert "mysecretpw" not in result
        assert "sshpass -p [REDACTED]" in result

    def test_non_sensitive_content_preserved(self):
        svc = _make_service()
        logs = "TASK [Create VM] *** ok: [kvm1] => status: running"
        result = svc._redact_logs(logs)
        assert result == logs

    def test_empty_string_returned_unchanged(self):
        svc = _make_service()
        assert svc._redact_logs("") == ""

    def test_none_returned_unchanged(self):
        svc = _make_service()
        assert svc._redact_logs(None) is None


# ---------------------------------------------------------------------------
# _calculate_retry_delay
# ---------------------------------------------------------------------------


class TestCalculateRetryDelay:
    def test_first_retry_uses_initial_seconds(self):
        svc = _make_service(retry_backoff_initial_seconds=60, retry_backoff_multiplier=2.0)
        assert svc._calculate_retry_delay(0) == 60

    def test_second_retry_doubles(self):
        svc = _make_service(retry_backoff_initial_seconds=60, retry_backoff_multiplier=2.0)
        assert svc._calculate_retry_delay(1) == 120

    def test_third_retry_quadruples(self):
        svc = _make_service(retry_backoff_initial_seconds=60, retry_backoff_multiplier=2.0)
        assert svc._calculate_retry_delay(2) == 240

    def test_capped_at_max(self):
        svc = _make_service(
            retry_backoff_initial_seconds=60,
            retry_backoff_multiplier=2.0,
            retry_backoff_max_seconds=200,
        )
        assert svc._calculate_retry_delay(2) == 200

    def test_returns_int(self):
        svc = _make_service()
        assert isinstance(svc._calculate_retry_delay(0), int)


# ---------------------------------------------------------------------------
# _should_retry_error
# ---------------------------------------------------------------------------


class TestShouldRetryError:
    def test_retryable_generic_error(self):
        svc = _make_service()
        assert svc._should_retry_error("Unexpected connection reset") is True

    def test_non_retryable_exact_match(self):
        svc = _make_service()
        assert svc._should_retry_error("Invalid SSH key") is False

    def test_non_retryable_substring_match(self):
        svc = _make_service()
        assert svc._should_retry_error("Fatal: Invalid SSH key provided") is False

    def test_non_retryable_case_insensitive(self):
        svc = _make_service()
        assert svc._should_retry_error("INVALID SSH KEY") is False

    def test_unreachable_is_non_retryable(self):
        svc = _make_service()
        assert svc._should_retry_error("host UNREACHABLE: timeout") is False

    def test_empty_error_is_retryable(self):
        svc = _make_service()
        assert svc._should_retry_error("") is True


# ---------------------------------------------------------------------------
# _build_result_payload
# ---------------------------------------------------------------------------


def _base_run_result(**overrides) -> AnsibleRunResult:
    defaults = dict(
        stdout="",
        stderr="",
        ssh_port=None,
        tenant_user=None,
        vm_host_ip=None,
        ssh_command=None,
        ansible_result=None,
        process_id=12345,
    )
    defaults.update(overrides)
    return AnsibleRunResult(**defaults)


class TestBuildResultPayload:
    def test_no_ansible_result_returns_base_fields(self):
        svc = _make_service()
        result = _base_run_result(ssh_port="2222", tenant_user="agent", vm_host_ip="10.0.0.1")
        payload = svc._build_result_payload(result)
        assert payload["ssh_port"] == "2222"
        assert payload["tenant_user"] == "agent"
        assert payload["vm_host_ip"] == "10.0.0.1"
        assert payload["ansible_result"] is None

    def test_ansible_result_fields_promoted(self):
        svc = _make_service()
        ar = {
            "action": "create",
            "vm_name": "test-vm",
            "status": "running",
            "host": "kvm1",
            "timestamp": "2025-01-01T00:00:00Z",
        }
        payload = svc._build_result_payload(_base_run_result(ansible_result=ar))
        assert payload["action"] == "create"
        assert payload["vm_name"] == "test-vm"
        assert payload["status"] == "running"

    def test_authentication_block_nested_correctly(self):
        svc = _make_service()
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
        payload = svc._build_result_payload(_base_run_result(ansible_result=ar))
        assert payload["authentication"]["tenant"]["password"] == "pw"
        assert payload["authentication"]["root"]["ssh_key_path_host"] == "/root/.ssh/id_ed25519"

    def test_tenant_ssh_command_overrides_top_level(self):
        svc = _make_service()
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
        payload = svc._build_result_payload(
            _base_run_result(ssh_command="ssh -p 0 fallback@host", ansible_result=ar)
        )
        assert payload["ssh_command"] == "ssh -p 9000 agent@frp.host"

    def test_frp_remote_port_overrides_ssh_port(self):
        svc = _make_service()
        ar = {"action": "create", "frp": {"remote_port": "54321", "subdomain": "vm-abc"}}
        payload = svc._build_result_payload(_base_run_result(ssh_port="2222", ansible_result=ar))
        assert payload["ssh_port"] == "54321"
        assert payload["frp"]["subdomain"] == "vm-abc"

    def test_vms_list_with_count(self):
        svc = _make_service()
        vms = [{"name": "vm-a"}, {"name": "vm-b"}]
        ar = {"action": "list", "vms": vms, "vm_count": 2}
        payload = svc._build_result_payload(_base_run_result(ansible_result=ar))
        assert payload["vms"] == vms
        assert payload["vm_count"] == 2

    def test_flat_resource_fields_restructured(self):
        svc = _make_service()
        ar = {
            "action": "monitor",
            "cpu_usage_percent": 42.0,
            "memory_used_mb": 4096,
            "memory_available_mb": 4096,
            "memory_usage_percent": 50.0,
        }
        payload = svc._build_result_payload(_base_run_result(ansible_result=ar))
        assert payload["resources"]["cpu"]["usage_percent"] == 42.0
        assert payload["resources"]["memory"]["used_mb"] == 4096

    def test_prebuilt_resources_block_used_directly(self):
        svc = _make_service()
        resources = {"vcpus_total": 32, "vcpus_available": 16}
        ar = {"action": "check", "resources": resources}
        payload = svc._build_result_payload(_base_run_result(ansible_result=ar))
        assert payload["resources"] == resources

    def test_ansible_result_included_in_payload(self):
        svc = _make_service()
        ar = {"action": "create", "vm_name": "test-vm"}
        payload = svc._build_result_payload(_base_run_result(ansible_result=ar))
        assert payload["ansible_result"] is ar
