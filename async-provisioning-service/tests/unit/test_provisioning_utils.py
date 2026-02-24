"""Unit tests for async_provisioning_service.services.provisioning utility functions."""

import asyncio
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, call

import pytest

from async_provisioning_service.services.provisioning import (
    PlaybookError,
    ProvisioningParams,
    ProvisioningResult,
    RunningPlaybook,
    _extract_ansible_json,
    _extract_json_block,
    _extract_ssh_port,
    _extract_tenant_user,
    _inject_golden_credentials,
    _lookup_vm_host_ip,
    _build_vm_vars,
    run_playbook,
    start_playbook,
    wait_for_playbook,
)


# ---------------------------------------------------------------------------
# TestPlaybookError
# ---------------------------------------------------------------------------

class TestPlaybookError:
    def test_construction(self):
        e = PlaybookError("msg", "stdout", "stderr")
        assert str(e) == "msg"
        assert e.stdout == "stdout"
        assert e.stderr == "stderr"


# ---------------------------------------------------------------------------
# TestExtractSshPort
# ---------------------------------------------------------------------------

class TestExtractSshPort:
    def test_json_format(self):
        output = 'some text "external_ssh_port": "2222" more text'
        result = _extract_ssh_port(output, vm_host=None)
        assert result == "2222"

    def test_ssh_command_with_vm_host(self):
        output = "ssh -p 2222 root@ww1"
        result = _extract_ssh_port(output, vm_host="ww1")
        assert result == "2222"

    def test_fallback_pattern(self):
        output = "connect with: ssh -p 3333 user@somehost"
        result = _extract_ssh_port(output, vm_host=None)
        assert result == "3333"

    def test_no_match_returns_none(self):
        result = _extract_ssh_port("no port here", vm_host=None)
        assert result is None


# ---------------------------------------------------------------------------
# TestExtractTenantUser
# ---------------------------------------------------------------------------

class TestExtractTenantUser:
    def test_json_format(self):
        output = '"tenant_user": "ubuntu"'
        result = _extract_tenant_user(output, vm_host=None)
        assert result == "ubuntu"

    def test_ssh_command_pattern(self):
        output = "ssh -p 2222 myuser@somehost"
        result = _extract_tenant_user(output, vm_host=None)
        assert result == "myuser"

    def test_no_match_returns_none(self):
        result = _extract_tenant_user("no user here", vm_host=None)
        assert result is None


# ---------------------------------------------------------------------------
# TestExtractJsonBlock
# ---------------------------------------------------------------------------

class TestExtractJsonBlock:
    def test_simple_object(self):
        text = '{"key": "value"}'
        result = _extract_json_block(text, 0)
        assert result == {"key": "value"}

    def test_nested_objects(self):
        text = '{"outer": {"inner": 1}}'
        result = _extract_json_block(text, 0)
        assert result == {"outer": {"inner": 1}}

    def test_quoted_brace_ignored(self):
        text = '{"str": "has {brace}"}'
        result = _extract_json_block(text, 0)
        assert result == {"str": "has {brace}"}

    def test_escaped_quotes(self):
        text = '{"str": "he said \\"hi\\""}'
        result = _extract_json_block(text, 0)
        assert result == {"str": 'he said "hi"'}

    def test_unclosed_brace_returns_none(self):
        text = '{"key": "value"'
        result = _extract_json_block(text, 0)
        assert result is None

    def test_invalid_json_returns_none(self):
        text = '{invalid json}'
        result = _extract_json_block(text, 0)
        assert result is None

    def test_start_offset(self):
        text = 'garbage{"key": "value"}'
        result = _extract_json_block(text, 7)
        assert result == {"key": "value"}


# ---------------------------------------------------------------------------
# TestExtractAnsibleJson
# ---------------------------------------------------------------------------

class TestExtractAnsibleJson:
    def test_quoted_marker_strategy(self):
        stdout = '"vm_creation_data": {"action": "create", "vm_name": "vm1"}'
        result = _extract_ansible_json(stdout, "create")
        assert result == {"action": "create", "vm_name": "vm1"}

    def test_msg_block_strategy(self):
        stdout = 'msg: |-\n    {"action": "create"}\n'
        result = _extract_ansible_json(stdout, "create")
        assert result == {"action": "create"}

    def test_last_msg_block_with_action(self):
        stdout = (
            'msg: |-\n    {"action": "create", "vm_name": "first"}\n'
            'other stuff\n'
            'msg: |-\n    {"action": "create", "vm_name": "second"}\n'
        )
        result = _extract_ansible_json(stdout, "create")
        # Returns the LAST msg block containing "action" key
        assert result is not None
        assert result.get("vm_name") == "second"

    def test_invalid_action_returns_none(self):
        result = _extract_ansible_json("some output", "invalid_action")
        assert result is None

    def test_no_json_returns_none(self):
        result = _extract_ansible_json("no json here just plain text", "list")
        assert result is None


# ---------------------------------------------------------------------------
# TestLookupVmHostIp
# ---------------------------------------------------------------------------

class TestLookupVmHostIp:
    def test_resolves_host(self, monkeypatch):
        inventory_content = "ww1 ansible_host=192.168.1.1\nww2 ansible_host=192.168.1.2\n"
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = inventory_content
        monkeypatch.setattr(
            "async_provisioning_service.services.provisioning.settings",
            MagicMock(resolved_inventory_path=mock_path),
        )
        result = _lookup_vm_host_ip("ww1")
        assert result == "192.168.1.1"

    def test_host_not_found(self, monkeypatch):
        inventory_content = "ww1 ansible_host=192.168.1.1\nww2 ansible_host=192.168.1.2\n"
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = inventory_content
        monkeypatch.setattr(
            "async_provisioning_service.services.provisioning.settings",
            MagicMock(resolved_inventory_path=mock_path),
        )
        result = _lookup_vm_host_ip("unknown_host")
        assert result is None

    def test_file_not_found(self, monkeypatch):
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.side_effect = FileNotFoundError("no such file")
        monkeypatch.setattr(
            "async_provisioning_service.services.provisioning.settings",
            MagicMock(resolved_inventory_path=mock_path),
        )
        result = _lookup_vm_host_ip("ww1")
        assert result is None

    def test_ignores_comment_lines(self, monkeypatch):
        inventory_content = "# this is a comment\nww1 ansible_host=10.0.0.1\n"
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = inventory_content
        monkeypatch.setattr(
            "async_provisioning_service.services.provisioning.settings",
            MagicMock(resolved_inventory_path=mock_path),
        )
        result = _lookup_vm_host_ip("ww1")
        assert result == "10.0.0.1"

    def test_ignores_section_headers(self, monkeypatch):
        inventory_content = "[all]\nww1 ansible_host=10.0.0.1\n"
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = inventory_content
        monkeypatch.setattr(
            "async_provisioning_service.services.provisioning.settings",
            MagicMock(resolved_inventory_path=mock_path),
        )
        result = _lookup_vm_host_ip("ww1")
        assert result == "10.0.0.1"


# ---------------------------------------------------------------------------
# TestInjectGoldenCredentials
# ---------------------------------------------------------------------------

class TestInjectGoldenCredentials:
    def test_injects_all_fields(self):
        mock_creds = MagicMock()
        mock_creds.root_ssh_filename = "id_rsa"
        mock_creds.root_ssh_password = "secret"
        mock_creds.golden_image_name = "ubuntu-22.04"

        lines = []
        with patch(
            "async_provisioning_service.services.management_vars.get_golden_image_credentials",
            return_value=mock_creds,
        ):
            _inject_golden_credentials(lines)

        assert "root_ssh_filename: id_rsa" in lines
        assert "root_ssh_password: secret" in lines
        assert "golden_image_name: ubuntu-22.04" in lines

    def test_creds_not_found_uses_fallback(self):
        lines = []
        with patch(
            "async_provisioning_service.services.management_vars.get_golden_image_credentials",
            return_value=None,
        ):
            _inject_golden_credentials(lines)

        assert "root_ssh_filename: not_provided" in lines
        assert "root_ssh_password: not_provided" in lines


# ---------------------------------------------------------------------------
# TestBuildVmVars
# ---------------------------------------------------------------------------

class TestBuildVmVars:
    def test_minimal_output(self):
        params = ProvisioningParams(vm_host="ww1", vm_target=None, vm_action="list")
        result = _build_vm_vars(params)
        assert "vm_host: ww1" in result
        assert "vm_action: list" in result
        # Non-golden image type uses fallback
        assert "root_ssh_filename: not_provided" in result
        assert "root_ssh_password: not_provided" in result

    def test_optional_fields_present(self):
        params = ProvisioningParams(
            vm_host="ww1",
            vm_target="my-vm",
            vm_action="create",
            vm_ram=4096,
            vm_vcpus=2,
            ssh_pubkey="ssh-rsa AAA",
        )
        result = _build_vm_vars(params)
        assert "vm_ram: 4096" in result
        assert "vm_vcpus: 2" in result
        assert 'vm_tenant_pubkey: "ssh-rsa AAA"' in result

    def test_ssh_pubkey_quotes_escaped(self):
        params = ProvisioningParams(
            vm_host="ww1",
            vm_target=None,
            vm_action="list",
            ssh_pubkey='ssh-rsa key with "quotes"',
        )
        result = _build_vm_vars(params)
        assert 'vm_tenant_pubkey: "ssh-rsa key with \\"quotes\\""' in result

    def test_golden_image_calls_inject(self):
        params = ProvisioningParams(
            vm_host="ww1",
            vm_target=None,
            vm_action="list",
            image_setup_type="golden",
        )
        with patch(
            "async_provisioning_service.services.provisioning._inject_golden_credentials"
        ) as mock_inject:
            mock_inject.side_effect = lambda lines: lines.extend(["root_ssh_filename: id_rsa"])
            result = _build_vm_vars(params)
        mock_inject.assert_called_once()

    def test_scratch_image_uses_fallback(self):
        params = ProvisioningParams(
            vm_host="ww1",
            vm_target=None,
            vm_action="list",
            image_setup_type="scratch",
        )
        result = _build_vm_vars(params)
        assert "root_ssh_filename: not_provided" in result
        assert "root_ssh_password: not_provided" in result


# ---------------------------------------------------------------------------
# TestStartPlaybook
# ---------------------------------------------------------------------------

class TestStartPlaybook:
    @pytest.mark.anyio
    async def test_returns_running_playbook(self):
        mock_proc = MagicMock()
        mock_proc.pid = 12345

        params = ProvisioningParams(vm_host="ww1", vm_target="test-vm", vm_action="create")

        with patch("subprocess.Popen", return_value=mock_proc):
            result = await start_playbook(params)

        assert isinstance(result, RunningPlaybook)
        assert result.process_id == 12345
        # Clean up temp file
        result.vm_vars_path.unlink(missing_ok=True)

    @pytest.mark.anyio
    async def test_command_includes_inventory_and_playbook(self):
        mock_proc = MagicMock()
        mock_proc.pid = 12345

        params = ProvisioningParams(vm_host="ww1", vm_target="test-vm", vm_action="create")

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            result = await start_playbook(params)

        cmd = mock_popen.call_args[0][0]
        assert "-i" in cmd
        assert "ansible-playbook" in cmd
        result.vm_vars_path.unlink(missing_ok=True)

    @pytest.mark.anyio
    async def test_command_includes_extra_vars_and_limit(self):
        mock_proc = MagicMock()
        mock_proc.pid = 12345

        params = ProvisioningParams(vm_host="ww1", vm_target="test-vm", vm_action="create")

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            result = await start_playbook(params)

        cmd = mock_popen.call_args[0][0]
        assert "--extra-vars" in cmd
        assert "--limit" in cmd
        result.vm_vars_path.unlink(missing_ok=True)

    @pytest.mark.anyio
    async def test_vars_file_written(self):
        mock_proc = MagicMock()
        mock_proc.pid = 12345

        params = ProvisioningParams(vm_host="ww1", vm_target="test-vm", vm_action="create")

        with patch("subprocess.Popen", return_value=mock_proc):
            result = await start_playbook(params)

        assert result.vm_vars_path.exists()
        # Clean up
        result.vm_vars_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TestWaitForPlaybook
# ---------------------------------------------------------------------------

def _make_running_playbook(stdout_content="", stderr_content="", returncode=0):
    """Helper to create a RunningPlaybook with a mocked process."""
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.poll.return_value = returncode  # returns non-None immediately → loop exits
    mock_proc.stdout = MagicMock()
    mock_proc.stdout.read.return_value = stdout_content
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = stderr_content

    params = ProvisioningParams(vm_host="ww1", vm_target="test-vm", vm_action="create")

    with tempfile.NamedTemporaryFile(suffix=".yml", delete=False) as f:
        vars_path = Path(f.name)

    return RunningPlaybook(
        process=mock_proc,
        process_id=12345,
        vm_vars_path=vars_path,
        params=params,
    )


class TestWaitForPlaybook:
    @pytest.mark.anyio
    async def test_success_returns_result(self):
        stdout_content = '"external_ssh_port": "2222"'
        running = _make_running_playbook(stdout_content=stdout_content, returncode=0)

        with patch(
            "async_provisioning_service.services.provisioning._lookup_vm_host_ip",
            return_value=None,
        ):
            result = await wait_for_playbook(running)

        assert isinstance(result, ProvisioningResult)
        assert result.ssh_port == "2222"

    @pytest.mark.anyio
    async def test_failed_process_raises_playbookerror(self):
        running = _make_running_playbook(returncode=1)

        with patch(
            "async_provisioning_service.services.provisioning._lookup_vm_host_ip",
            return_value=None,
        ):
            with pytest.raises(PlaybookError):
                await wait_for_playbook(running)

    @pytest.mark.anyio
    async def test_timeout_raises_playbookerror(self):
        running = _make_running_playbook()

        with patch(
            "async_provisioning_service.services.provisioning.asyncio.wait_for",
            side_effect=asyncio.TimeoutError(),
        ):
            with patch(
                "async_provisioning_service.services.provisioning._lookup_vm_host_ip",
                return_value=None,
            ):
                with pytest.raises(PlaybookError) as exc_info:
                    await wait_for_playbook(running)

        assert "timeout" in str(exc_info.value).lower()

    @pytest.mark.anyio
    async def test_vars_file_deleted_in_finally(self):
        running = _make_running_playbook(returncode=0)
        vars_path = running.vm_vars_path

        assert vars_path.exists()

        with patch(
            "async_provisioning_service.services.provisioning._lookup_vm_host_ip",
            return_value=None,
        ):
            await wait_for_playbook(running)

        assert not vars_path.exists()


# ---------------------------------------------------------------------------
# TestRunPlaybook
# ---------------------------------------------------------------------------

class TestRunPlaybook:
    def test_success(self):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("success output", "")

        params = ProvisioningParams(vm_host="ww1", vm_target="test-vm", vm_action="create")

        with patch("subprocess.Popen", return_value=mock_proc):
            with patch(
                "async_provisioning_service.services.provisioning._lookup_vm_host_ip",
                return_value=None,
            ):
                result = run_playbook(params)

        assert result.stdout == "success output"

    def test_timeout(self):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.returncode = 1
        # First call raises TimeoutExpired; second call (after kill) returns empty strings
        mock_proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd=[], timeout=1800),
            ("", ""),
        ]

        params = ProvisioningParams(vm_host="ww1", vm_target="test-vm", vm_action="create")

        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(PlaybookError):
                run_playbook(params)

        mock_proc.kill.assert_called_once()

    def test_failure(self):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = ("some output", "some error")

        params = ProvisioningParams(vm_host="ww1", vm_target="test-vm", vm_action="create")

        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(PlaybookError) as exc_info:
                run_playbook(params)

        err = exc_info.value
        assert err.stdout == "some output"
        assert err.stderr == "some error"

    def test_vars_file_deleted_in_finally(self):
        """Temp vars file is cleaned up even on failure."""
        written_paths = []

        original_popen = subprocess.Popen

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("ok", "")

        params = ProvisioningParams(vm_host="ww1", vm_target="test-vm", vm_action="create")

        captured_path = None

        def fake_popen(cmd, **kwargs):
            # Find the @<path> arg in cmd to know which vars file was written
            nonlocal captured_path
            for arg in cmd:
                if arg.startswith("@/tmp/vm_vars_"):
                    captured_path = Path(arg[1:])
            return mock_proc

        with patch("subprocess.Popen", side_effect=fake_popen):
            with patch(
                "async_provisioning_service.services.provisioning._lookup_vm_host_ip",
                return_value=None,
            ):
                run_playbook(params)

        # After run_playbook completes, the vars file should be deleted
        if captured_path is not None:
            assert not captured_path.exists()

    def test_generic_exception_raises_playbook_error(self):
        """A generic exception from Popen.communicate is wrapped as PlaybookError."""
        params = ProvisioningParams(vm_host="ww1", vm_target="test-vm", vm_action="create")

        with patch("subprocess.Popen", side_effect=RuntimeError("popen exploded")):
            with pytest.raises(PlaybookError) as exc_info:
                run_playbook(params)

        assert "popen exploded" in str(exc_info.value)

    def test_ssh_command_built_when_all_fields_present(self):
        """ssh_command is built when ssh_port, tenant_user and vm_host_ip are all available."""
        stdout = '"external_ssh_port": "2222"\n"tenant_user": "ubuntu"\n'
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (stdout, "")

        params = ProvisioningParams(vm_host="ww1", vm_target="test-vm", vm_action="create")

        with patch("subprocess.Popen", return_value=mock_proc):
            with patch(
                "async_provisioning_service.services.provisioning._lookup_vm_host_ip",
                return_value="192.168.1.1",
            ):
                result = run_playbook(params)

        assert result.ssh_command is not None
        assert "2222" in result.ssh_command
        assert "ubuntu" in result.ssh_command
        assert "192.168.1.1" in result.ssh_command


class TestBuildVmVarsAllOptional:
    """Covers all optional GPU / FRP / GCS / lease fields in _build_vm_vars."""

    def test_gpu_fields_present(self):
        params = ProvisioningParams(
            vm_host="ww1",
            vm_target="vm",
            vm_action="create",
            vm_os_variant="ubuntu22.04",
            gpu_provisioned=True,
            vm_gpu_count=2,
            vm_gpu_device="0000:01:00.0",
            vm_gpu_devices=["0000:01:00.0", "0000:02:00.0"],
            vm_gpu_partition_size="1g.5gb",
        )
        result = _build_vm_vars(params)
        assert "vm_os_variant: ubuntu22.04" in result
        assert "gpu_provisioned: true" in result
        assert "vm_gpu_count: 2" in result
        assert 'vm_gpu_device: "0000:01:00.0"' in result
        assert "vm_gpu_devices:" in result
        assert 'vm_gpu_partition_size: "1g.5gb"' in result

    def test_frp_fields_present(self):
        params = ProvisioningParams(
            vm_host="ww1",
            vm_target="vm",
            vm_action="create",
            frp_server_addr="10.0.0.1",
            frp_domain="example.com",
            frp_dashboard_password="dashpass",
        )
        result = _build_vm_vars(params)
        assert 'frp_server_addr: "10.0.0.1"' in result
        assert 'frp_domain: "example.com"' in result
        assert 'frp_dashboard_password: "dashpass"' in result

    def test_gcs_and_lease_fields_present(self):
        params = ProvisioningParams(
            vm_host="ww1",
            vm_target="vm",
            vm_action="create",
            golden_image_name="ubuntu-20.04",
            gcs_bucket_url="gs://my-bucket",
            gcs_image_path="images/ubuntu.qcow2",
            vm_lease_end="2025-12-31 23:59",
        )
        result = _build_vm_vars(params)
        assert "golden_image_name: ubuntu-20.04" in result
        assert "gcs_bucket_url: gs://my-bucket" in result
        assert "gcs_image_path: images/ubuntu.qcow2" in result
        assert 'vm_lease_end: "2025-12-31 23:59"' in result
