"""
Integration tests for the host registry API.

All calls go through ProvisioningClient methods — no route strings in test code.
ProvisioningError is raised by the client on non-2xx responses.

Coverage:
  - All CRUD endpoints round-trip correctly through the client
  - INI import upserts correctly and returns the seeded list
  - enable/disable lifecycle transitions are persisted
  - connectivity endpoint delegates to AnsibleService with DB-rendered inventory
  - ProvisioningClient host methods match the API contract end-to-end

What is NOT covered here (unit test jurisdiction):
  - INI parsing edge cases
  - Fernet encryption/decryption correctness
  - render_inventory_ini output format
"""

from __future__ import annotations

import pytest

from client.provisioning_client import ProvisioningClient, ProvisioningError
from models.host_model import HostCreate, HostResponse, HostListResponse, HostUpdate


_SAMPLE_HOST = HostCreate(
    name="ww1",
    kvm_host="10.0.0.1",
    ssh_user="ubuntu",
    ssh_key_type="path",
    ssh_key_value="/home/appuser/.ssh/id_ed25519",
    gpu_count=2,
)

_SAMPLE_INI = (
    "[kvm_hosts]\n"
    "ww1  ansible_host=10.0.0.1  ansible_user=ubuntu  "
    "ansible_ssh_private_key_file=/home/appuser/.ssh/id_ed25519\n"
    "ww2  ansible_host=10.0.0.2  ansible_user=ubuntu  "
    "ansible_ssh_private_key_file=/home/appuser/.ssh/id_ed25519\n"
)


async def _register(client: ProvisioningClient, body: HostCreate = _SAMPLE_HOST) -> HostResponse:
    return await client.register_host(body)


class TestListHostsEmpty:
    async def test_empty_table_returns_empty_list(self, client_and_queue):
        client, _ = client_and_queue
        result = await client.list_hosts()
        assert isinstance(result, HostListResponse)
        assert result.hosts == []


class TestRegisterHost:
    async def test_register_returns_host_response(self, client_and_queue):
        client, _ = client_and_queue
        host = await _register(client)
        assert isinstance(host, HostResponse)
        assert host.name == "ww1"
        assert host.kvm_host == "10.0.0.1"
        assert host.ssh_user == "ubuntu"
        assert host.gpu_count == 2
        assert host.enabled is True

    async def test_register_appears_in_list(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        result = await client.list_hosts()
        assert any(h.name == "ww1" for h in result.hosts)

    async def test_register_host_client_contract(self, client_and_queue):
        """register_host return value is a typed HostResponse — contract enforced."""
        client, _ = client_and_queue
        host = await _register(client)
        assert isinstance(host, HostResponse)
        assert host.name == _SAMPLE_HOST.name
        assert host.kvm_host == _SAMPLE_HOST.kvm_host


class TestGetHost:
    async def test_get_registered_host(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        host = await client.get_host("ww1")
        assert isinstance(host, HostResponse)
        assert host.name == "ww1"

    async def test_get_unknown_host_raises_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.get_host("does-not-exist")
        assert exc_info.value.status_code == 404


class TestUpdateHost:
    async def test_update_kvm_host_ip(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        updated = await client.update_host("ww1", HostUpdate(kvm_host="10.0.0.99"))
        assert isinstance(updated, HostResponse)
        assert updated.kvm_host == "10.0.0.99"

    async def test_update_persisted_on_get(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        await client.update_host("ww1", HostUpdate(ssh_user="root"))
        host = await client.get_host("ww1")
        assert host.ssh_user == "root"

    async def test_update_unknown_host_raises_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.update_host("ghost", HostUpdate(kvm_host="1.2.3.4"))
        assert exc_info.value.status_code == 404


class TestEnableDisableHost:
    async def test_disable_sets_enabled_false(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        host = await client.disable_host("ww1")
        assert isinstance(host, HostResponse)
        assert host.enabled is False

    async def test_disabled_host_excluded_from_default_list(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        await client.disable_host("ww1")
        result = await client.list_hosts()
        assert not any(h.name == "ww1" for h in result.hosts)

    async def test_disabled_host_visible_with_include_disabled(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        await client.disable_host("ww1")
        result = await client.list_hosts(include_disabled=True)
        assert any(h.name == "ww1" for h in result.hosts)

    async def test_enable_restores_visibility(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        await client.disable_host("ww1")
        await client.enable_host("ww1")
        result = await client.list_hosts()
        assert any(h.name == "ww1" for h in result.hosts)

    async def test_disable_unknown_host_raises_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.disable_host("ghost")
        assert exc_info.value.status_code == 404


class TestImportHosts:
    async def test_import_ini_upserts_hosts(self, client_and_queue):
        client, _ = client_and_queue
        result = await client.import_hosts_from_text(_SAMPLE_INI, ssh_key_type="path")
        assert isinstance(result, HostListResponse)
        names = [h.name for h in result.hosts]
        assert "ww1" in names
        assert "ww2" in names

    async def test_import_is_idempotent(self, client_and_queue):
        client, _ = client_and_queue
        for _ in range(2):
            await client.import_hosts_from_text(_SAMPLE_INI, ssh_key_type="path")
        result = await client.list_hosts()
        names = [h.name for h in result.hosts]
        assert len(names) == len(set(names))
        assert "ww1" in names
        assert "ww2" in names

    async def test_import_does_not_disable_absent_hosts(self, client_and_queue):
        """Hosts not in the new INI must be left untouched (append-only)."""
        client, _ = client_and_queue
        await _register(client)
        ini_ww2_only = (
            "[kvm_hosts]\n"
            "ww2  ansible_host=10.0.0.2  ansible_user=ubuntu  "
            "ansible_ssh_private_key_file=/home/appuser/.ssh/id_ed25519\n"
        )
        await client.import_hosts_from_text(ini_ww2_only, ssh_key_type="path")
        host = await client.get_host("ww1")
        assert host.enabled is True


class TestConnectivity:
    async def test_connectivity_registered_host(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        result = await client.check_connectivity("ww1")
        assert result.host == "ww1"
        assert "reachable" in result.__dict__

    async def test_connectivity_uses_db_inventory(self, client_and_queue, fake_ansible):
        client, _ = client_and_queue
        await _register(client)
        await client.check_connectivity("ww1")
        fake_ansible.write_inventory.assert_called_once()
        called_hosts = fake_ansible.write_inventory.call_args[0][0]
        assert len(called_hosts) == 1
        assert called_hosts[0].name == "ww1"

    async def test_connectivity_unknown_host_raises_404(self, client_and_queue):
        client, _ = client_and_queue
        from client.provisioning_client import ProvisioningError
        with pytest.raises(ProvisioningError) as exc_info:
            await client.check_connectivity("ghost")
        assert exc_info.value.status_code == 404
