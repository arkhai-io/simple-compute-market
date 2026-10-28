"""
Integration tests for the host registry API.

All calls go through the canonical typed clients — no route strings in test code.
ComputeProvisioningError is raised by the client on non-2xx responses.

Coverage:
  - All CRUD endpoints round-trip correctly through the client
  - INI import upserts correctly and returns the seeded list
  - enable/disable lifecycle transitions are persisted
  - connectivity endpoint delegates to AnsibleService with DB-rendered inventory
  - The family client's host methods match the API contract end-to-end

What is NOT covered here (unit test jurisdiction):
  - INI parsing edge cases
  - Fernet encryption/decryption correctness
  - the rendered inventory's exact format (``AnsibleRunner.write_inventory``)

A representative case does follow a host's connection fields from the API and
the store into the inventory a job renders, reading the rendered line's fields
rather than its layout.
"""

from __future__ import annotations
import shlex
from types import SimpleNamespace

from compute_provisioning.hosts.db import Host
from compute_provisioning_ansible import ssh_connection
from compute_provisioning_ansible.runner import AnsibleRunner
from vm_provisioning_operator.models import CreateVmRequest

from compute_provisioning_client import ComputeProvisioningError
import pytest

from .conftest import ProvisioningClients, TEST_CONNECTION_KEY
from compute_provisioning_contracts import (
    HostCreate,
    HostListResponse,
    HostResponse,
    HostUpdate,
)
from market_config import decrypt_secret


def _connection(**changes):
    """The sample host's connection, with ``changes`` applied: an update
    replaces the whole connection."""
    fields = {
        "ssh_host": "10.0.0.1",
        "ssh_user": "ubuntu",
        "key_path": "/home/appuser/.ssh/id_ed25519",
    }
    fields.update(changes)
    return ssh_connection(**fields)


_SAMPLE_HOST = HostCreate(
    host_id="kvm1",
    connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="ubuntu", key_path="/home/appuser/.ssh/id_ed25519"),
    gpu_count=2,
)

_SAMPLE_INI = (
    "[kvm_hosts]\n"
    "kvm1  ansible_host=10.0.0.1  ansible_user=ubuntu  "
    "ansible_ssh_private_key_file=/home/appuser/.ssh/id_ed25519\n"
    "ww2  ansible_host=10.0.0.2  ansible_user=ubuntu  "
    "ansible_ssh_private_key_file=/home/appuser/.ssh/id_ed25519\n"
)


async def _register(client: ProvisioningClients, body: HostCreate = _SAMPLE_HOST) -> HostResponse:
    return await client.family.register_host(body)


class TestListHostsEmpty:
    async def test_empty_table_returns_empty_list(self, client_and_queue):
        client, _ = client_and_queue
        result = await client.family.list_hosts()
        assert isinstance(result, HostListResponse)
        assert result.hosts == []
        assert result.total == 0


class TestRegisterHost:
    async def test_register_returns_host_response(self, client_and_queue):
        client, _ = client_and_queue
        host = await _register(client)
        assert isinstance(host, HostResponse)
        assert host.host_id == "kvm1"
        assert host.connection.public["ssh_host"] == "10.0.0.1"
        assert host.connection.public["ssh_user"] == "ubuntu"
        assert host.gpu_count == 2
        assert host.enabled is True

    async def test_register_appears_in_list(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        result = await client.family.list_hosts()
        assert any(h.host_id == "kvm1" for h in result.hosts)
        assert result.total == len(result.hosts)

    async def test_registering_a_host_twice_is_a_conflict_naming_it(self, client_and_queue):
        """A second registration of one host id is refused as a conflict, and the
        first registration is untouched."""
        client, _ = client_and_queue
        await _register(client)

        with pytest.raises(ComputeProvisioningError) as refused:
            await _register(client)

        assert refused.value.status_code == 409
        assert _SAMPLE_HOST.host_id in str(refused.value)
        assert (await client.family.get_host(_SAMPLE_HOST.host_id)).gpu_count == 2

    async def test_register_host_client_contract(self, client_and_queue):
        """register_host return value is a typed HostResponse — contract enforced."""
        client, _ = client_and_queue
        host = await _register(client)
        assert isinstance(host, HostResponse)
        assert host.host_id == _SAMPLE_HOST.host_id
        assert host.connection.public["ssh_host"] == _SAMPLE_HOST.connection.public["ssh_host"]

    async def test_register_with_gpu_model_round_trips_through_the_real_api(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        host = await client.family.register_host(HostCreate(
            host_id="kvm1", connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="ubuntu", key_path="/home/appuser/.ssh/id_ed25519"),
            gpu_count=8, gpu_model="H100",
        ))
        assert host.gpu_model == "H100"
        fetched = await client.family.get_host("kvm1")
        assert fetched.gpu_model == "H100"

    async def test_register_without_gpu_model_leaves_it_absent(self, client_and_queue):
        client, _ = client_and_queue
        host = await _register(client)  # _SAMPLE_HOST sets no gpu_model
        assert host.gpu_model is None


class TestGetHost:
    async def test_get_registered_host(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        host = await client.family.get_host("kvm1")
        assert isinstance(host, HostResponse)
        assert host.host_id == "kvm1"

    async def test_get_unknown_host_raises_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.family.get_host("does-not-exist")
        assert exc_info.value.status_code == 404


class TestUpdateHost:
    async def test_update_kvm_host_ip(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        updated = await client.family.update_host("kvm1", HostUpdate(connection=_connection(ssh_host="10.0.0.99")))
        assert isinstance(updated, HostResponse)
        assert updated.connection.public["ssh_host"] == "10.0.0.99"

    async def test_update_persisted_on_get(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        await client.family.update_host("kvm1", HostUpdate(connection=_connection(ssh_user="root")))
        host = await client.family.get_host("kvm1")
        assert host.connection.public["ssh_user"] == "root"

    async def test_update_gpu_model_round_trips_through_the_real_api(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        updated = await client.family.update_host("kvm1", HostUpdate(gpu_model="A100"))
        assert updated.gpu_model == "A100"
        fetched = await client.family.get_host("kvm1")
        assert fetched.gpu_model == "A100"

    async def test_update_unknown_host_raises_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.family.update_host("ghost", HostUpdate(connection=_connection(ssh_host="1.2.3.4")))
        assert exc_info.value.status_code == 404


class TestEnableDisableHost:
    async def test_disable_sets_enabled_false(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        host = await client.family.disable_host("kvm1")
        assert isinstance(host, HostResponse)
        assert host.enabled is False

    async def test_disabled_host_excluded_from_default_list(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        await client.family.disable_host("kvm1")
        result = await client.family.list_hosts()
        assert not any(h.host_id == "kvm1" for h in result.hosts)
        assert result.total == len(result.hosts)

    async def test_disabled_host_visible_with_include_disabled(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        await client.family.disable_host("kvm1")
        result = await client.family.list_hosts(include_disabled=True)
        assert any(h.host_id == "kvm1" for h in result.hosts)
        assert result.total == len(result.hosts)

    async def test_enable_restores_visibility(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        await client.family.disable_host("kvm1")
        await client.family.enable_host("kvm1")
        result = await client.family.list_hosts()
        assert any(h.host_id == "kvm1" for h in result.hosts)
        assert result.total == len(result.hosts)

    async def test_disable_unknown_host_raises_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.family.disable_host("ghost")
        assert exc_info.value.status_code == 404


class TestImportHosts:
    async def test_import_ini_upserts_hosts(self, client_and_queue):
        client, _ = client_and_queue
        result = await client.host_import.import_hosts_from_text(_SAMPLE_INI, ssh_key_type="path")
        assert isinstance(result, HostListResponse)
        names = [h.host_id for h in result.hosts]
        assert "kvm1" in names
        assert "ww2" in names
        assert result.total == len(result.hosts)

    async def test_import_is_idempotent(self, client_and_queue):
        client, _ = client_and_queue
        for _ in range(2):
            await client.host_import.import_hosts_from_text(_SAMPLE_INI, ssh_key_type="path")
        result = await client.family.list_hosts()
        names = [h.host_id for h in result.hosts]
        assert len(names) == len(set(names))
        assert "kvm1" in names
        assert "ww2" in names
        assert result.total == len(result.hosts)

    async def test_import_does_not_disable_absent_hosts(self, client_and_queue):
        """Hosts not in the new INI must be left untouched (append-only)."""
        client, _ = client_and_queue
        await _register(client)
        ini_ww2_only = (
            "[kvm_hosts]\n"
            "ww2  ansible_host=10.0.0.2  ansible_user=ubuntu  "
            "ansible_ssh_private_key_file=/home/appuser/.ssh/id_ed25519\n"
        )
        await client.host_import.import_hosts_from_text(ini_ww2_only, ssh_key_type="path")
        host = await client.family.get_host("kvm1")
        assert host.enabled is True


def _inventory_line(host_id: str, address: str, pool: str | None) -> str:
    """One INI entry; ``pool`` is the raw ``pool_id=`` value, or ``None`` to
    state no pool at all."""
    pool_var = "" if pool is None else f"  pool_id={pool}"
    return (
        f"{host_id}  ansible_host={address}  ansible_user=ubuntu  "
        f"ansible_ssh_private_key_file=/home/appuser/.ssh/id_ed25519{pool_var}\n"
    )


class TestHostPlacement:
    """A host's pool is optional, and only an explicit statement changes it."""

    async def test_a_host_created_without_a_pool_reads_back_unplaced(self, client_and_queue):
        client, _ = client_and_queue
        created = await _register(client)
        assert created.pool_id is None
        assert (await client.family.get_host("kvm1")).pool_id is None
        listed = await client.family.list_hosts()
        assert [h.pool_id for h in listed.hosts if h.host_id == "kvm1"] == [None]

    async def test_an_update_omitting_the_pool_keeps_it(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client, _SAMPLE_HOST.model_copy(update={"pool_id": "default"}))

        updated = await client.family.update_host("kvm1", HostUpdate(gpu_model="A100"))

        assert (updated.pool_id, updated.gpu_model) == ("default", "A100")

    async def test_an_explicit_null_unplaces_the_host(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client, _SAMPLE_HOST.model_copy(update={"pool_id": "default"}))

        updated = await client.family.update_host("kvm1", HostUpdate(pool_id=None))

        assert updated.pool_id is None
        assert (await client.family.get_host("kvm1")).pool_id is None

    async def test_an_empty_inventory_pool_unplaces_an_existing_host(self, client_and_queue):
        client, _ = client_and_queue
        await client.host_import.import_hosts_from_text(
            "[kvm_hosts]\n" + _inventory_line("kvm1", "10.0.0.1", "default")
        )

        result = await client.host_import.import_hosts_from_text(
            "[kvm_hosts]\n" + _inventory_line("kvm1", "10.0.0.1", "")
        )

        assert [h.pool_id for h in result.hosts] == [None]
        assert (await client.family.get_host("kvm1")).pool_id is None

    async def test_an_inventory_stating_no_pool_keeps_an_existing_host_s_and_places_no_new_one(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        await _register(client, _SAMPLE_HOST.model_copy(update={"pool_id": "default"}))

        result = await client.host_import.import_hosts_from_text(
            "[kvm_hosts]\n"
            + _inventory_line("kvm1", "10.0.0.99", None)
            + _inventory_line("ww2", "10.0.0.2", None)
        )

        pools = {h.host_id: h.pool_id for h in result.hosts}
        assert pools == {"kvm1": "default", "ww2": None}
        kvm1 = await client.family.get_host("kvm1")
        assert (kvm1.pool_id, kvm1.connection.public["ssh_host"]) == ("default", "10.0.0.99")
        assert (await client.family.get_host("ww2")).pool_id is None

    async def test_an_unknown_pool_is_refused_on_every_host_write(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client, _SAMPLE_HOST.model_copy(update={"pool_id": "default"}))

        with pytest.raises(ComputeProvisioningError) as on_create:
            await client.family.register_host(
                _SAMPLE_HOST.model_copy(update={"host_id": "ww2", "pool_id": "missing"})
            )
        with pytest.raises(ComputeProvisioningError) as on_update:
            await client.family.update_host("kvm1", HostUpdate(pool_id="missing"))
        with pytest.raises(ComputeProvisioningError) as on_import:
            await client.host_import.import_hosts_from_text(
                "[kvm_hosts]\n" + _inventory_line("kvm1", "10.0.0.99", "missing")
            )

        assert {on_create.value.status_code, on_update.value.status_code,
                on_import.value.status_code} == {400}
        kvm1 = await client.family.get_host("kvm1")
        assert (kvm1.pool_id, kvm1.connection.public["ssh_host"]) == ("default", "10.0.0.1")
        with pytest.raises(ComputeProvisioningError) as missing:
            await client.family.get_host("ww2")
        assert missing.value.status_code == 404


class TestConnectivity:
    async def test_connectivity_registered_host(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        result = await client.family.check_connectivity("kvm1")
        assert result.host == "kvm1"
        assert "reachable" in result.__dict__

    async def test_connectivity_uses_db_inventory(self, client_and_queue, fake_ansible):
        client, _ = client_and_queue
        await _register(client)
        await client.family.check_connectivity("kvm1")
        fake_ansible.write_inventory.assert_called_once()
        called_hosts = fake_ansible.write_inventory.call_args[0][0]
        assert len(called_hosts) == 1
        assert called_hosts[0].host_id == "kvm1"

    async def test_connectivity_unknown_host_raises_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.family.check_connectivity("ghost")
        assert exc_info.value.status_code == 404


class TestSshPort:
    """The SSH port survives the real client, API, service, and database.

    A host reached through a tunnel answers on a port rather than on 22 at
    `ssh_host`. Unit tests cover each layer that has to carry the port; only
    this level proves the canonical client and the server model agree about the
    field, which is where a serialization mismatch would otherwise hide until a
    real host failed to connect.
    """

    async def test_register_with_a_tunnel_port_round_trips(self, client_and_queue):
        client, _ = client_and_queue
        host = await client.family.register_host(HostCreate(
            host_id="kvm1", connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="ubuntu", ssh_port=6000, key_path="/home/appuser/.ssh/id_ed25519"),
        ))
        assert host.connection.public["ssh_port"] == 6000
        assert (await client.family.get_host("kvm1")).connection.public["ssh_port"] == 6000

    async def test_register_without_a_port_defaults_to_22(self, client_and_queue):
        client, _ = client_and_queue
        host = await _register(client)  # _SAMPLE_HOST sets no ssh_port
        assert host.connection.public["ssh_port"] == 22

    async def test_update_changes_the_port(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client)
        updated = await client.family.update_host("kvm1", HostUpdate(connection=_connection(ssh_port=6005)))
        assert updated.connection.public["ssh_port"] == 6005
        assert (await client.family.get_host("kvm1")).connection.public["ssh_port"] == 6005

    async def test_an_update_without_a_connection_leaves_it_alone(self, client_and_queue):
        client, _ = client_and_queue
        await client.family.register_host(HostCreate(
            host_id="kvm1", connection=_connection(ssh_port=6000),
        ))
        updated = await client.family.update_host("kvm1", HostUpdate(gpu_model="A100"))
        assert updated.connection.public["ssh_port"] == 6000

    async def test_the_port_appears_in_the_list_response(self, client_and_queue):
        client, _ = client_and_queue
        await client.family.register_host(HostCreate(
            host_id="kvm1", connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="ubuntu", ssh_port=6001, key_path="/home/appuser/.ssh/id_ed25519"),
        ))
        listed = await client.family.list_hosts()
        assert [h.connection.public["ssh_port"] for h in listed.hosts if h.host_id == "kvm1"] == [6001]

    async def test_an_imported_inventory_port_reaches_the_registry(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        result = await client.host_import.import_hosts_from_text(
            "[kvm_hosts]\n"
            "kvm1  ansible_host=10.0.0.1  ansible_user=ubuntu  ansible_port=6000  "
            "ansible_ssh_private_key_file=/home/appuser/.ssh/id_ed25519\n",
            ssh_key_type="path",
        )
        assert [h.connection.public["ssh_port"] for h in result.hosts if h.host_id == "kvm1"] == [6000]
        assert (await client.family.get_host("kvm1")).connection.public["ssh_port"] == 6000

    async def test_an_imported_inventory_without_a_port_defaults_to_22(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        await client.host_import.import_hosts_from_text(_SAMPLE_INI, ssh_key_type="path")
        assert (await client.family.get_host("kvm1")).connection.public["ssh_port"] == 22


class TestSshPortRejection:
    """Malformed bodies need raw HTTP: the typed client cannot construct one.

    `ssh_connection` validates the bound before a request exists, so the
    canonical client can only send a valid port. Proving the server rejects an invalid one
    is the narrow case where a raw request is the only way to reach the
    behavior under test.
    """

    async def test_the_typed_client_rejects_an_out_of_range_port(self):
        with pytest.raises(ValueError):
            HostCreate(
                host_id="kvm1", connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="ubuntu", ssh_port=70000, key_path="/keys/id"),
            )

    @pytest.mark.parametrize("port", [0, 70000, "not-a-port"])
    async def test_the_api_rejects_an_out_of_range_port(self, client_and_queue, port):
        client, _ = client_and_queue
        response = await client.family._client.post(  # noqa: SLF001 - malformed body by design
            "/api/v1/hosts/",
            json={
                "host_id": "kvm1",
                "connection": {
                    "kind": "ssh",
                    "public": {
                        "ssh_host": "10.0.0.1", "ssh_user": "ubuntu",
                        "key_path": "/keys/id", "ssh_port": port,
                    },
                },
            },
        )
        # The ssh codec, not the generic wire model, owns the port's range.
        assert response.status_code == 400


class TestEmbeddedKey:
    """A submitted private key is protected before storage and never returned."""

    _PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\nfixture\n-----END OPENSSH PRIVATE KEY-----\n"

    async def test_a_submitted_key_is_stored_protected_and_returned_by_scheme_only(
        self, client_and_queue, session_factory,
    ):
        client, _ = client_and_queue
        registered = await client.family.register_host(HostCreate(
            host_id="bm1",
            connection=ssh_connection(ssh_host="10.0.1.1", private_key=self._PEM),
        ))
        fetched = await client.family.get_host("bm1")

        for response in (registered, fetched):
            assert response.connection.protected == {"private_key": "fernet-v1"}
            assert "fixture" not in response.model_dump_json()
        with session_factory() as db:
            stored = db.get(Host, "bm1").connection_protected["private_key"]
        assert stored["scheme"] == "fernet-v1"
        assert "fixture" not in stored["ciphertext"]
        assert decrypt_secret(stored["ciphertext"], TEST_CONNECTION_KEY) == self._PEM


class TestTenantFacingRoute:
    """A host's tenant-facing address and port survive the typed client, API,
    service, and database, and reach the inventory a job runs against.

    Job execution reaches the real runner's inventory rendering: the fixture's
    runner mock hands ``write_inventory`` to a real ``AnsibleRunner``, while it
    replaces playbook execution, so no command or subprocess is built. The routed
    host's addresses are RFC 5737 documentation addresses, and the other host is
    this module's sample; all are development fixture values that must never be
    used on a public network.
    """

    @staticmethod
    def _render_for_real(fake_ansible) -> list[str]:
        """Render each job's inventory with the real runner, keeping its text."""
        rendered: list[str] = []
        renderer = AnsibleRunner(SimpleNamespace())

        def write_inventory(hosts, *, group):
            inventory = renderer.write_inventory(hosts, group=group)
            rendered.append(inventory.path.read_text())
            return inventory

        fake_ansible.write_inventory.side_effect = write_inventory
        return rendered

    @staticmethod
    def _host_vars(inventory: str, host_id: str) -> dict[str, str]:
        """The variables ``inventory`` renders for ``host_id``, by name."""
        (line,) = [entry for entry in inventory.splitlines() if entry.startswith(f"{host_id} ")]
        return dict(token.split("=", 1) for token in shlex.split(line)[1:])

    @staticmethod
    async def _run_a_job(client, host_id: str) -> None:
        submit = await client.vm.create_vm(host_id, CreateVmRequest(vm_target="tenant-route-vm"))
        final = await client.family.poll_until_complete(
            submit.job_id, timeout=5.0, poll_interval=0.05
        )
        assert final.status == "succeeded"

    async def test_a_registered_route_reads_back_and_renders_into_a_jobs_inventory(
        self, client_and_queue, fake_ansible, session_factory,
    ):
        client, _ = client_and_queue
        rendered = self._render_for_real(fake_ansible)
        await client.family.register_host(HostCreate(
            host_id="routed",
            connection=ssh_connection(
                ssh_host="198.51.100.1", ssh_user="ubuntu", ssh_port=6000,
                public_host="192.0.2.10", public_port=22,
                key_path="/home/appuser/.ssh/id_ed25519",
            ),
        ))

        public = (await client.family.get_host("routed")).connection.public
        assert (public["ssh_port"], public["public_host"], public["public_port"]) == (6000, "192.0.2.10", 22)
        with session_factory() as db:
            assert db.get(Host, "routed").connection_public["public_port"] == 22

        await self._run_a_job(client, "routed")

        host_vars = self._host_vars(rendered[-1], "routed")
        assert {key: host_vars[key] for key in ("ansible_host", "ansible_port", "public_host", "public_port")} == {
            "ansible_host": "198.51.100.1",
            "ansible_port": "6000",
            "public_host": "192.0.2.10",
            "public_port": "22",
        }

    async def test_a_host_stating_no_route_is_stored_and_rendered_as_before(
        self, client_and_queue, fake_ansible, session_factory,
    ):
        """No ``public_port`` key is stored, not even a null, so a reader that
        does not know the field still reads the record."""
        client, _ = client_and_queue
        rendered = self._render_for_real(fake_ansible)
        await _register(client)

        public = (await client.family.get_host("kvm1")).connection.public
        assert public["public_host"] is None and "public_port" not in public
        with session_factory() as db:
            assert db.get(Host, "kvm1").connection_public == {
                "ssh_host": "10.0.0.1",
                "public_host": None,
                "ssh_port": 22,
                "ssh_user": "ubuntu",
                "key_path": "/home/appuser/.ssh/id_ed25519",
            }

        await self._run_a_job(client, "kvm1")

        host_vars = self._host_vars(rendered[-1], "kvm1")
        assert "public_host" not in host_vars and "public_port" not in host_vars
        assert (host_vars["ansible_host"], host_vars["ansible_port"], host_vars["ansible_user"]) == (
            "10.0.0.1", "22", "ubuntu",
        )
