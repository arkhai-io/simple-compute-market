"""Unit tests for async_provisioning_service.services.job_processor."""

import asyncio
import copy
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from async_provisioning_service.config import settings
from async_provisioning_service.db.models import (
    Base,
    Credential,
    CredentialRole,
    JobStatus,
    ProvisioningJob,
)
from async_provisioning_service.services.job_processor import (
    _UNSET,
    _build_params,
    _build_result_payload,
    _calculate_retry_delay,
    _extract_and_store_credentials,
    _process_job,
    _redact_logs,
    _should_retry_error,
    _update_job,
    process_jobs,
)
from async_provisioning_service.services.provisioning import (
    PlaybookError,
    ProvisioningParams,
    ProvisioningResult,
    RunningPlaybook,
)

AGENT_1 = "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1"
AGENT_2 = "eip155:31337:0x70997970C51812dc3A010C7d01b50e0d17dc79C8:2"


@pytest.fixture()
def make_db():
    """Create in-memory SQLite and return (session_factory, seed_session)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield TestingSession
    Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Helper sentinel for tracking which attributes have been set
# ---------------------------------------------------------------------------

_MISSING = object()


class TrackingJob:
    """A plain job-like object that starts with sentinel values for all fields."""

    def __init__(self):
        self.status = _MISSING
        self.result = _MISSING
        self.error = _MISSING
        self.logs = _MISSING
        self.process_id = _MISSING


# ===========================================================================
# TestUpdateJob
# ===========================================================================


class TestUpdateJob:
    def test_only_status_set(self):
        db = MagicMock()
        job = TrackingJob()

        _update_job(db, job, status="running")

        assert job.status == "running"
        assert job.result is _MISSING  # not assigned
        assert job.error is _MISSING  # not assigned
        assert job.logs is _MISSING  # not assigned
        assert job.process_id is _MISSING  # not assigned
        db.add.assert_called_once_with(job)
        db.commit.assert_called_once()

    def test_all_fields_set(self):
        db = MagicMock()
        job = TrackingJob()

        _update_job(
            db,
            job,
            status="succeeded",
            result={"key": "val"},
            error="err",
            logs="logs",
            process_id="123",
        )

        assert job.status == "succeeded"
        assert job.result == {"key": "val"}
        assert job.error == "err"
        assert job.logs == "logs"
        assert job.process_id == "123"

    def test_partial_fields(self):
        db = MagicMock()
        job = TrackingJob()

        _update_job(db, job, status="succeeded", result={"k": "v"})

        assert job.status == "succeeded"
        assert job.result == {"k": "v"}
        assert job.error is _MISSING  # not assigned
        assert job.logs is _MISSING   # not assigned

    def test_commits_to_db(self):
        db = MagicMock()
        job = TrackingJob()

        _update_job(db, job, status="running")

        db.add.assert_called_once_with(job)
        db.commit.assert_called_once()

    def test_process_id_not_set_when_none(self):
        """When process_id=None (the default), job.process_id should not be touched."""
        db = MagicMock()
        job = TrackingJob()

        _update_job(db, job, status="running")

        assert job.process_id is _MISSING  # not assigned

    def test_process_id_set_when_provided(self):
        db = MagicMock()
        job = TrackingJob()

        _update_job(db, job, status="running", process_id="9999")

        assert job.process_id == "9999"


# ===========================================================================
# TestCalculateRetryDelay
# ===========================================================================


class TestCalculateRetryDelay:
    def test_base_case(self):
        # retry_count=0  →  60 * (2.0 ** 0) = 60
        result = _calculate_retry_delay(0)
        assert result == 60

    def test_exponential(self):
        # retry_count=2  →  60 * (2.0 ** 2) = 240
        result = _calculate_retry_delay(2)
        assert result == 240

    def test_capped_at_max(self):
        # retry_count=100  →  capped at 3600
        result = _calculate_retry_delay(100)
        assert result == 3600

    def test_first_retry(self):
        # retry_count=1  →  60 * (2.0 ** 1) = 120
        result = _calculate_retry_delay(1)
        assert result == 120


# ===========================================================================
# TestShouldRetryError
# ===========================================================================


class TestShouldRetryError:
    def test_retryable_error(self):
        assert _should_retry_error("random playbook error") is True

    def test_non_retryable_match(self):
        # "Invalid SSH key" is in settings.non_retryable_errors
        assert _should_retry_error("Invalid SSH key provided") is False

    def test_non_retryable_case_insensitive(self):
        assert _should_retry_error("INVALID SSH KEY problem") is False

    def test_non_retryable_unreachable(self):
        assert _should_retry_error("host UNREACHABLE error") is False

    def test_empty_list(self, monkeypatch):
        monkeypatch.setattr(settings, "non_retryable_errors", [])
        assert _should_retry_error("any error") is True

    def test_empty_string_error_message(self):
        # Empty error message should be retryable (nothing matches)
        assert _should_retry_error("") is True


# ===========================================================================
# TestBuildParams
# ===========================================================================


class TestBuildParams:
    def test_minimal_dict(self):
        result = _build_params({})
        assert isinstance(result, ProvisioningParams)
        assert result.vm_host == "ww1"
        assert result.vm_action == "create"
        assert result.image_setup_type == "scratch"
        assert result.vm_target is None

    def test_all_values(self):
        params_dict = {
            "vm_host": "myhost",
            "vm_target": "my-vm",
            "vm_action": "destroy",
            "image_setup_type": "golden",
            "vm_ram": 4096,
            "vm_vcpus": 4,
            "vm_disk_size": "50G",
            "vm_os_variant": "ubuntu22.04",
            "ssh_pubkey": "ssh-rsa AAAA",
            "gpu_provisioned": True,
            "vm_gpu_count": 1,
            "vm_gpu_device": "A100",
            "vm_gpu_devices": ["gpu0"],
            "vm_gpu_partition_size": "20G",
            "frp_server_addr": "1.2.3.4",
            "frp_domain": "example.com",
            "frp_dashboard_password": "pwd",
            "golden_image_name": "my-image",
            "gcs_bucket_url": "gs://bucket",
            "gcs_image_path": "path/to/img",
            "vm_lease_end": "2025-12-31",
        }
        result = _build_params(params_dict)
        assert result.vm_host == "myhost"
        assert result.vm_target == "my-vm"
        assert result.vm_action == "destroy"
        assert result.vm_ram == 4096
        assert result.vm_vcpus == 4
        assert result.gpu_provisioned is True
        assert result.frp_server_addr == "1.2.3.4"
        assert result.golden_image_name == "my-image"
        assert result.vm_lease_end == "2025-12-31"

    def test_frp_falls_back_to_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "frp_server_addr", "10.0.0.1")
        monkeypatch.setattr(settings, "frp_domain", "fallback.example.com")
        monkeypatch.setattr(settings, "frp_dashboard_password", "fallback_pwd")

        result = _build_params({"frp_server_addr": None})
        assert result.frp_server_addr == "10.0.0.1"
        assert result.frp_domain == "fallback.example.com"
        assert result.frp_dashboard_password == "fallback_pwd"

    def test_frp_explicit_value_overrides_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "frp_server_addr", "10.0.0.1")

        result = _build_params({"frp_server_addr": "192.168.0.1"})
        assert result.frp_server_addr == "192.168.0.1"


# ===========================================================================
# TestRedactLogs
# ===========================================================================


class TestRedactLogs:
    def test_redacts_json_password(self):
        logs = '"password": "secret123"'
        result = _redact_logs(logs)
        assert '"password": "[REDACTED]"' in result
        assert "secret123" not in result

    def test_redacts_yaml_password(self):
        logs = "password: mysecret"
        result = _redact_logs(logs)
        assert "password: [REDACTED]" in result
        assert "mysecret" not in result

    def test_no_double_redaction(self):
        # The YAML regex backtracks when lookahead fails with space consumed,
        # so "password: [REDACTED]" becomes "password:[REDACTED]" (space stripped).
        # The key property is that the value is not double-wrapped with [REDACTED].
        logs = "password: [REDACTED]"
        result = _redact_logs(logs)
        assert "[REDACTED]" in result
        assert result.count("[REDACTED]") == 1

    def test_redacts_ssh_key_path_host(self):
        logs = '"ssh_key_path_host": "/path/to/key"'
        result = _redact_logs(logs)
        assert '"ssh_key_path_host": "[REDACTED]"' in result
        assert "/path/to/key" not in result

    def test_redacts_dash_i_key(self):
        logs = "ssh -i /home/user/.ssh/id_rsa root@host"
        result = _redact_logs(logs)
        assert "-i [REDACTED]" in result
        assert "id_rsa" not in result

    def test_redacts_sshpass(self):
        logs = "sshpass -p mypassword user@host"
        result = _redact_logs(logs)
        assert "sshpass -p [REDACTED]" in result
        assert "mypassword" not in result

    def test_safe_logs_unchanged(self):
        logs = "TASK [debug] ***** ok"
        result = _redact_logs(logs)
        assert result == logs

    def test_none_logs(self):
        assert _redact_logs(None) is None

    def test_empty_string_logs(self):
        assert _redact_logs("") == ""

    def test_non_ssh_dash_i_not_redacted(self):
        """Paths without .ssh/ in the path should NOT be redacted."""
        logs = "ssh -i /home/user/mykey root@host"
        result = _redact_logs(logs)
        # No .ssh/ in path, so pattern should not match
        assert "/home/user/mykey" in result

    def test_multiple_sensitive_fields(self):
        logs = '"password": "abc" and "ssh_key_path_host": "/root/.ssh/key"'
        result = _redact_logs(logs)
        assert "abc" not in result
        assert "/root/.ssh/key" not in result
        assert '[REDACTED]' in result


# ===========================================================================
# TestExtractAndStoreCredentials
# ===========================================================================


class TestExtractAndStoreCredentials:
    def test_no_authentication_key(self):
        db = MagicMock()
        job = MagicMock()
        result = _extract_and_store_credentials(db, job, {"status": "ok"})
        assert "authentication" not in result
        db.add.assert_not_called()

    def test_seller_gets_root_and_tenant(self, make_db):
        TestingSession = make_db
        db = TestingSession()
        job_id = str(uuid.uuid4())
        job = ProvisioningJob(
            id=job_id,
            status="queued",
            params={},
            agent_id=AGENT_1,
            retry_count=0,
            max_retries=3,
        )
        db.add(job)
        db.commit()

        auth_payload = {
            "authentication": {
                "root": {"password": "rootpass", "ssh_commands": {"external": "ssh root@host"}},
                "tenant": {"password": "tenantpass"},
            }
        }
        sanitized = _extract_and_store_credentials(db, job, auth_payload)
        db.commit()

        creds = db.query(Credential).filter_by(job_id=job_id).all()
        assert len(creds) == 2
        assert "authentication" not in sanitized
        db.close()

    def test_buyer_gets_tenant_only(self, make_db):
        TestingSession = make_db
        db = TestingSession()
        job_id = str(uuid.uuid4())
        job = ProvisioningJob(
            id=job_id,
            status="queued",
            params={},
            agent_id=AGENT_1,
            buyer_agent_id=AGENT_2,
            retry_count=0,
            max_retries=3,
        )
        db.add(job)
        db.commit()

        auth_payload = {
            "authentication": {
                "root": {"password": "rootpass"},
                "tenant": {"password": "tenantpass"},
            }
        }
        sanitized = _extract_and_store_credentials(db, job, auth_payload)
        db.commit()

        creds = db.query(Credential).filter_by(job_id=job_id).all()
        # seller gets root + tenant = 2, buyer gets tenant = 1 → 3 total
        assert len(creds) == 3
        assert "authentication" not in sanitized

        granted_to_values = {c.granted_to for c in creds}
        assert AGENT_1 in granted_to_values
        assert AGENT_2 in granted_to_values

        buyer_creds = [c for c in creds if c.granted_to == AGENT_2]
        assert len(buyer_creds) == 1
        assert buyer_creds[0].role == CredentialRole.tenant.value
        db.close()

    def test_no_agent_ids(self, make_db):
        TestingSession = make_db
        db = TestingSession()
        job_id = str(uuid.uuid4())
        job = ProvisioningJob(
            id=job_id,
            status="queued",
            params={},
            agent_id=None,
            buyer_agent_id=None,
            retry_count=0,
            max_retries=3,
        )
        db.add(job)
        db.commit()

        auth_payload = {
            "authentication": {
                "root": {"password": "rootpass"},
                "tenant": {"password": "tenantpass"},
            }
        }
        _extract_and_store_credentials(db, job, auth_payload)
        db.commit()

        creds = db.query(Credential).filter_by(job_id=job_id).all()
        assert len(creds) == 0
        db.close()

    def test_sanitizes_authentication_from_result(self, make_db):
        TestingSession = make_db
        db = TestingSession()
        job_id = str(uuid.uuid4())
        job = ProvisioningJob(
            id=job_id,
            status="queued",
            params={},
            agent_id=AGENT_1,
            retry_count=0,
            max_retries=3,
        )
        db.add(job)
        db.commit()

        original = {
            "status": "ok",
            "authentication": {
                "root": {"password": "secret"},
                "tenant": {"password": "tpwd"},
            },
        }
        original_copy = copy.deepcopy(original)

        sanitized = _extract_and_store_credentials(db, job, original)

        # Original should not be mutated (function deepcopies before modifying)
        assert original == original_copy
        # Sanitized result should not contain authentication
        assert "authentication" not in sanitized
        assert "status" in sanitized
        db.close()

    def test_sanitizes_nested_ansible_result(self, make_db):
        TestingSession = make_db
        db = TestingSession()
        job_id = str(uuid.uuid4())
        job = ProvisioningJob(
            id=job_id,
            status="queued",
            params={},
            agent_id=AGENT_1,
            retry_count=0,
            max_retries=3,
        )
        db.add(job)
        db.commit()

        payload = {
            "authentication": {
                "root": {"password": "rootpwd"},
                "tenant": {"password": "tenantpwd"},
            },
            "ansible_result": {
                "authentication": {
                    "root": {"password": "rootpwd"},
                    "tenant": {"password": "tenantpwd"},
                },
                "status": "created",
            },
        }
        sanitized = _extract_and_store_credentials(db, job, payload)

        assert "authentication" not in sanitized
        assert "authentication" not in sanitized.get("ansible_result", {})
        assert sanitized["ansible_result"]["status"] == "created"
        db.close()

    def test_empty_auth_block_no_credentials(self, make_db):
        """An empty authentication dict results in no credentials stored."""
        TestingSession = make_db
        db = TestingSession()
        job_id = str(uuid.uuid4())
        job = ProvisioningJob(
            id=job_id,
            status="queued",
            params={},
            agent_id=AGENT_1,
            retry_count=0,
            max_retries=3,
        )
        db.add(job)
        db.commit()

        payload = {
            "authentication": {
                "root": {},
                "tenant": {},
            },
        }
        _extract_and_store_credentials(db, job, payload)
        db.commit()

        creds = db.query(Credential).filter_by(job_id=job_id).all()
        # empty dicts are falsy → _store_role skips them
        assert len(creds) == 0
        db.close()


# ===========================================================================
# TestBuildResultPayload
# ===========================================================================


def _make_result(**kwargs) -> ProvisioningResult:
    """Helper to create a ProvisioningResult with sensible defaults."""
    defaults = dict(
        stdout="",
        stderr="",
        ssh_port=None,
        tenant_user=None,
        vm_host_ip=None,
        ssh_command=None,
        ansible_result=None,
        process_id=None,
    )
    defaults.update(kwargs)
    return ProvisioningResult(**defaults)


class TestBuildResultPayload:
    def test_no_ansible_result(self):
        result = _make_result(ssh_port="2222", tenant_user="ubuntu", vm_host_ip="1.2.3.4")
        payload = _build_result_payload(result)

        assert payload["ansible_result"] is None
        assert payload["ssh_port"] == "2222"
        assert payload["tenant_user"] == "ubuntu"
        assert payload["vm_host_ip"] == "1.2.3.4"

    def test_basic_ansible_fields(self):
        ansible_result = {"status": "created", "action": "create", "vm_name": "vm1"}
        result = _make_result(ansible_result=ansible_result)
        payload = _build_result_payload(result)

        assert payload["status"] == "created"
        assert payload["action"] == "create"
        assert payload["vm_name"] == "vm1"

    def test_frp_overrides_ssh_port(self):
        ansible_result = {"frp": {"remote_port": "3000"}}
        result = _make_result(ssh_port="2222", ansible_result=ansible_result)
        payload = _build_result_payload(result)

        assert payload["ssh_port"] == "3000"
        assert payload["frp"] == {"remote_port": "3000"}

    def test_authentication_block(self):
        ansible_result = {
            "authentication": {
                "tenant": {"password": "p"},
                "root": {},
            }
        }
        result = _make_result(ansible_result=ansible_result)
        payload = _build_result_payload(result)

        assert "authentication" in payload
        assert payload["authentication"]["tenant"]["password"] == "p"
        # no "external" in ssh_commands so ssh_command stays as-is (None from defaults)
        assert payload["ssh_command"] is None

    def test_ssh_command_from_tenant_auth(self):
        ansible_result = {
            "authentication": {
                "tenant": {
                    "password": "pwd",
                    "ssh_commands": {"external": "ssh ubuntu@host"},
                },
                "root": {},
            }
        }
        result = _make_result(ansible_result=ansible_result)
        payload = _build_result_payload(result)

        assert payload["ssh_command"] == "ssh ubuntu@host"

    def test_resource_monitor_format(self):
        ansible_result = {
            "cpu_usage_percent": 45,
            "memory_used_mb": 1024,
        }
        result = _make_result(ansible_result=ansible_result)
        payload = _build_result_payload(result)

        assert "resources" in payload
        assert payload["resources"]["cpu"]["usage_percent"] == 45
        assert payload["resources"]["memory"]["used_mb"] == 1024

    def test_gpu_network_vm_state(self):
        ansible_result = {
            "gpu": {"count": 1, "device": "A100"},
            "network": {"interface": "eth0"},
            "vm_state": "running",
            "vm_ip_internal": "10.0.0.1",
        }
        result = _make_result(ansible_result=ansible_result)
        payload = _build_result_payload(result)

        assert payload["gpu"] == {"count": 1, "device": "A100"}
        assert payload["network"] == {"interface": "eth0"}
        assert payload["vm_state"] == "running"
        assert payload["vm_ip_internal"] == "10.0.0.1"

    def test_operation_metadata(self):
        ansible_result = {
            "result_message": "done",
            "note": "n",
            "operation_initiated": True,
            "vms": ["vm1"],
            "vm_count": 1,
        }
        result = _make_result(ansible_result=ansible_result)
        payload = _build_result_payload(result)

        assert payload["result_message"] == "done"
        assert payload["note"] == "n"
        assert payload["operation_initiated"] is True
        assert payload["vms"] == ["vm1"]
        assert payload["vm_count"] == 1

    def test_ansible_result_in_payload(self):
        ansible_result = {"status": "ok", "action": "list"}
        result = _make_result(ansible_result=ansible_result)
        payload = _build_result_payload(result)

        assert payload["ansible_result"] == ansible_result

    def test_tenant_user_from_ansible_result(self):
        ansible_result = {"tenant_user": "myuser"}
        result = _make_result(tenant_user="other", ansible_result=ansible_result)
        payload = _build_result_payload(result)

        assert payload["tenant_user"] == "myuser"


# ===========================================================================
# TestProcessJob (async)
# ===========================================================================


def _make_queued_job(job_id: str, **kwargs) -> ProvisioningJob:
    defaults = dict(
        id=job_id,
        status=JobStatus.queued.value,
        params={"vm_host": "ww1", "vm_target": "test-vm", "vm_action": "create"},
        agent_id=AGENT_1,
        retry_count=0,
        max_retries=3,
    )
    defaults.update(kwargs)
    return ProvisioningJob(**defaults)


def _make_mock_running(process_id: int = 12345) -> MagicMock:
    mock_running = MagicMock()
    mock_running.process_id = process_id
    return mock_running


def _make_mock_result(**kwargs) -> ProvisioningResult:
    defaults = dict(
        stdout="success output",
        stderr="",
        ssh_port="2222",
        tenant_user="ubuntu",
        vm_host_ip="192.168.1.1",
        ssh_command=None,
        ansible_result=None,
        process_id=12345,
    )
    defaults.update(kwargs)
    return ProvisioningResult(**defaults)


class TestProcessJob:
    @pytest.mark.anyio
    async def test_job_not_found(self, make_db, monkeypatch):
        monkeypatch.setattr(
            "async_provisioning_service.services.job_processor.SessionLocal", make_db
        )
        # No jobs in DB — should complete without error
        await _process_job("nonexistent-id")

    @pytest.mark.anyio
    async def test_retry_not_yet_due(self, make_db, monkeypatch):
        monkeypatch.setattr(
            "async_provisioning_service.services.job_processor.SessionLocal", make_db
        )

        db = make_db()
        job_id = str(uuid.uuid4())
        job = _make_queued_job(
            job_id,
            next_retry_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.add(job)
        db.commit()
        db.close()

        mock_enqueue = AsyncMock()
        mock_sleep = AsyncMock()

        with patch("async_provisioning_service.services.job_processor.enqueue_job", mock_enqueue):
            with patch("asyncio.sleep", mock_sleep):
                await _process_job(job_id)

        mock_sleep.assert_called_once_with(1)
        mock_enqueue.assert_called_once_with(job_id)

    @pytest.mark.anyio
    async def test_happy_path_success(self, make_db, monkeypatch):
        monkeypatch.setattr(
            "async_provisioning_service.services.job_processor.SessionLocal", make_db
        )

        db = make_db()
        job_id = str(uuid.uuid4())
        job = _make_queued_job(job_id)
        db.add(job)
        db.commit()
        db.close()

        mock_running = _make_mock_running()
        mock_result = _make_mock_result()

        with patch(
            "async_provisioning_service.services.job_processor.start_playbook",
            AsyncMock(return_value=mock_running),
        ):
            with patch(
                "async_provisioning_service.services.job_processor.wait_for_playbook",
                AsyncMock(return_value=mock_result),
            ):
                with patch(
                    "async_provisioning_service.services.job_processor.enqueue_job",
                    AsyncMock(),
                ):
                    await _process_job(job_id)

        verify_db = make_db()
        updated_job = verify_db.query(ProvisioningJob).filter_by(id=job_id).one()
        assert updated_job.status == JobStatus.succeeded.value
        assert updated_job.result is not None
        verify_db.close()

    @pytest.mark.anyio
    async def test_pid_stored_on_start(self, make_db, monkeypatch):
        monkeypatch.setattr(
            "async_provisioning_service.services.job_processor.SessionLocal", make_db
        )

        db = make_db()
        job_id = str(uuid.uuid4())
        job = _make_queued_job(job_id)
        db.add(job)
        db.commit()
        db.close()

        mock_running = _make_mock_running(process_id=99999)
        mock_result = _make_mock_result(process_id=99999)

        with patch(
            "async_provisioning_service.services.job_processor.start_playbook",
            AsyncMock(return_value=mock_running),
        ):
            with patch(
                "async_provisioning_service.services.job_processor.wait_for_playbook",
                AsyncMock(return_value=mock_result),
            ):
                with patch(
                    "async_provisioning_service.services.job_processor.enqueue_job",
                    AsyncMock(),
                ):
                    await _process_job(job_id)

        verify_db = make_db()
        updated_job = verify_db.query(ProvisioningJob).filter_by(id=job_id).one()
        assert updated_job.process_id == "99999"
        verify_db.close()

    @pytest.mark.anyio
    async def test_retryable_error_retries(self, make_db, monkeypatch):
        monkeypatch.setattr(
            "async_provisioning_service.services.job_processor.SessionLocal", make_db
        )

        db = make_db()
        job_id = str(uuid.uuid4())
        job = _make_queued_job(job_id, retry_count=0, max_retries=3)
        db.add(job)
        db.commit()
        db.close()

        mock_running = _make_mock_running()
        mock_enqueue = AsyncMock()

        with patch(
            "async_provisioning_service.services.job_processor.start_playbook",
            AsyncMock(return_value=mock_running),
        ):
            with patch(
                "async_provisioning_service.services.job_processor.wait_for_playbook",
                AsyncMock(side_effect=PlaybookError("some playbook error", "out", "err")),
            ):
                with patch(
                    "async_provisioning_service.services.job_processor.enqueue_job",
                    mock_enqueue,
                ):
                    await _process_job(job_id)

        verify_db = make_db()
        updated_job = verify_db.query(ProvisioningJob).filter_by(id=job_id).one()
        assert updated_job.status == JobStatus.queued.value
        assert updated_job.retry_count == 1
        verify_db.close()

        mock_enqueue.assert_called_once_with(job_id)

    @pytest.mark.anyio
    async def test_non_retryable_error_fails(self, make_db, monkeypatch):
        monkeypatch.setattr(
            "async_provisioning_service.services.job_processor.SessionLocal", make_db
        )

        db = make_db()
        job_id = str(uuid.uuid4())
        job = _make_queued_job(job_id, retry_count=0, max_retries=3)
        db.add(job)
        db.commit()
        db.close()

        mock_running = _make_mock_running()
        mock_enqueue = AsyncMock()

        with patch(
            "async_provisioning_service.services.job_processor.start_playbook",
            AsyncMock(return_value=mock_running),
        ):
            with patch(
                "async_provisioning_service.services.job_processor.wait_for_playbook",
                AsyncMock(
                    side_effect=PlaybookError("Invalid SSH key bad", "out", "err")
                ),
            ):
                with patch(
                    "async_provisioning_service.services.job_processor.enqueue_job",
                    mock_enqueue,
                ):
                    await _process_job(job_id)

        verify_db = make_db()
        updated_job = verify_db.query(ProvisioningJob).filter_by(id=job_id).one()
        assert updated_job.status == JobStatus.failed.value
        verify_db.close()

        mock_enqueue.assert_not_called()

    @pytest.mark.anyio
    async def test_max_retries_exceeded(self, make_db, monkeypatch):
        monkeypatch.setattr(
            "async_provisioning_service.services.job_processor.SessionLocal", make_db
        )

        db = make_db()
        job_id = str(uuid.uuid4())
        # retry_count == max_retries → already at max
        job = _make_queued_job(job_id, retry_count=3, max_retries=3)
        db.add(job)
        db.commit()
        db.close()

        mock_running = _make_mock_running()
        mock_enqueue = AsyncMock()

        with patch(
            "async_provisioning_service.services.job_processor.start_playbook",
            AsyncMock(return_value=mock_running),
        ):
            with patch(
                "async_provisioning_service.services.job_processor.wait_for_playbook",
                AsyncMock(
                    side_effect=PlaybookError("some retryable error", "out", "err")
                ),
            ):
                with patch(
                    "async_provisioning_service.services.job_processor.enqueue_job",
                    mock_enqueue,
                ):
                    await _process_job(job_id)

        verify_db = make_db()
        updated_job = verify_db.query(ProvisioningJob).filter_by(id=job_id).one()
        assert updated_job.status == JobStatus.failed.value
        verify_db.close()

        mock_enqueue.assert_not_called()

    @pytest.mark.anyio
    async def test_unexpected_exception_marks_failed(self, make_db, monkeypatch):
        monkeypatch.setattr(
            "async_provisioning_service.services.job_processor.SessionLocal", make_db
        )

        db = make_db()
        job_id = str(uuid.uuid4())
        job = _make_queued_job(job_id)
        db.add(job)
        db.commit()
        db.close()

        with patch(
            "async_provisioning_service.services.job_processor.start_playbook",
            AsyncMock(side_effect=ValueError("boom")),
        ):
            with patch(
                "async_provisioning_service.services.job_processor.enqueue_job",
                AsyncMock(),
            ):
                await _process_job(job_id)

        verify_db = make_db()
        updated_job = verify_db.query(ProvisioningJob).filter_by(id=job_id).one()
        assert updated_job.status == JobStatus.failed.value
        assert "Internal error: boom" in updated_job.error
        verify_db.close()

    @pytest.mark.anyio
    async def test_db_closed_in_finally(self, monkeypatch):
        """Even when an exception occurs, db.close() must be called."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None

        monkeypatch.setattr(
            "async_provisioning_service.services.job_processor.SessionLocal",
            lambda: mock_db,
        )

        await _process_job("any-id")

        mock_db.close.assert_called_once()

    @pytest.mark.anyio
    async def test_error_message_in_failed_job(self, make_db, monkeypatch):
        monkeypatch.setattr(
            "async_provisioning_service.services.job_processor.SessionLocal", make_db
        )

        db = make_db()
        job_id = str(uuid.uuid4())
        # retry_count == max_retries forces a permanent failure
        job = _make_queued_job(job_id, retry_count=3, max_retries=3)
        db.add(job)
        db.commit()
        db.close()

        mock_running = _make_mock_running()

        with patch(
            "async_provisioning_service.services.job_processor.start_playbook",
            AsyncMock(return_value=mock_running),
        ):
            with patch(
                "async_provisioning_service.services.job_processor.wait_for_playbook",
                AsyncMock(
                    side_effect=PlaybookError("Playbook failed", "out", "err")
                ),
            ):
                with patch(
                    "async_provisioning_service.services.job_processor.enqueue_job",
                    AsyncMock(),
                ):
                    await _process_job(job_id)

        verify_db = make_db()
        updated_job = verify_db.query(ProvisioningJob).filter_by(id=job_id).one()
        assert updated_job.status == JobStatus.failed.value
        assert updated_job.error is not None
        assert "Playbook failed" in updated_job.error
        verify_db.close()


# ===========================================================================
# TestProcessJobs (the worker loop)
# ===========================================================================


class TestProcessJobs:
    @pytest.mark.anyio
    async def test_initializes_db(self, monkeypatch):
        with patch(
            "async_provisioning_service.services.job_processor.init_db"
        ) as mock_init_db:
            with patch(
                "async_provisioning_service.services.job_processor.dequeue_job",
                AsyncMock(side_effect=asyncio.CancelledError()),
            ):
                with pytest.raises(asyncio.CancelledError):
                    await process_jobs()

        mock_init_db.assert_called_once()

    @pytest.mark.anyio
    async def test_processes_single_job(self, monkeypatch):
        call_count = 0

        async def _dequeue_side_effect(timeout_seconds=5):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "job-123"
            raise asyncio.CancelledError()

        mock_create_task = MagicMock(return_value=MagicMock())

        with patch("async_provisioning_service.services.job_processor.init_db"):
            with patch(
                "async_provisioning_service.services.job_processor.dequeue_job",
                new=_dequeue_side_effect,
            ):
                with patch("asyncio.create_task", mock_create_task):
                    with pytest.raises(asyncio.CancelledError):
                        await process_jobs()

        mock_create_task.assert_called_once()

    @pytest.mark.anyio
    async def test_timeout_returns_none_sleeps(self, monkeypatch):
        call_count = 0

        async def _dequeue_side_effect(timeout_seconds=5):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None
            raise asyncio.CancelledError()

        mock_sleep = AsyncMock()

        with patch("async_provisioning_service.services.job_processor.init_db"):
            with patch(
                "async_provisioning_service.services.job_processor.dequeue_job",
                new=_dequeue_side_effect,
            ):
                with patch("asyncio.sleep", mock_sleep):
                    with pytest.raises(asyncio.CancelledError):
                        await process_jobs()

        mock_sleep.assert_any_call(0.1)

    @pytest.mark.anyio
    async def test_dequeue_exception_sleeps_and_continues(self, monkeypatch):
        call_count = 0

        async def _dequeue_side_effect(timeout_seconds=5):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Redis error")
            raise asyncio.CancelledError()

        mock_sleep = AsyncMock()

        with patch("async_provisioning_service.services.job_processor.init_db"):
            with patch(
                "async_provisioning_service.services.job_processor.dequeue_job",
                new=_dequeue_side_effect,
            ):
                with patch("asyncio.sleep", mock_sleep):
                    with pytest.raises(asyncio.CancelledError):
                        await process_jobs()

        mock_sleep.assert_any_call(1)
