"""
Integration tests for the resource pool admin API.

All calls go through ProvisioningClient methods — no route strings in test
code. ProvisioningError is raised by the client on non-2xx responses.

Coverage:
  - The "default" pool always exists (seeded by db_engine, mirroring the
    real migration's guarantee).
  - CRUD endpoints round-trip correctly through the client.
  - PUT replaces complete mutable state; PATCH updates only supplied fields.
  - DELETE disables non-default pools; the default pool remains enabled.
  - Import/validate round-trip through the client and produce the expected
    created/updated/disabled/unchanged diff.
  - Hosts can be created against a pool created through this API, and
    reassigned via PUT/PATCH on /hosts/{name}.

What is NOT covered here (unit test jurisdiction):
  - YAML parsing edge cases, provider-config validation details
  - Diff computation internals
"""

from __future__ import annotations

import pytest

from compute_provisioning import PoolCreate, PoolReplace, PoolUpdate
from vm_provisioning_operator import ProvisioningClient, ProvisioningError
from vm_provisioning_operator.models import HostCreate, HostUpdate


_ANSIBLE_CONFIG = {
    "playbook_path": "playbooks/vm-operations.yaml",
}


async def _create_pool(client: ProvisioningClient, pool_id: str = "hetzner-eu"):
    return await client.create_pool(
        PoolCreate(
            id=pool_id,
            label="Hetzner EU",
            provider="ansible",
            provider_config=_ANSIBLE_CONFIG,
        )
    )


class TestDefaultPool:
    async def test_default_pool_exists_at_startup(self, client_and_queue):
        client, _ = client_and_queue
        pool = await client.get_pool("default")
        assert pool.enabled is True
        assert pool.provider == "ansible"

    async def test_default_pool_appears_in_list(self, client_and_queue):
        client, _ = client_and_queue
        result = await client.list_pools()
        assert any(p.id == "default" for p in result.pools)


class TestCreatePool:
    async def test_create_returns_pool_response(self, client_and_queue):
        client, _ = client_and_queue
        pool = await _create_pool(client)
        assert pool.id == "hetzner-eu"
        assert pool.enabled is True
        assert pool.provider_config["playbook_path"] == _ANSIBLE_CONFIG["playbook_path"]

    async def test_create_duplicate_id_returns_409(self, client_and_queue):
        client, _ = client_and_queue
        await _create_pool(client)
        with pytest.raises(ProvisioningError) as exc_info:
            await _create_pool(client)
        assert exc_info.value.status_code == 409

    async def test_create_unknown_provider_returns_400(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.create_pool(
                PoolCreate(
                    id="k8s-1",
                    label="K8s",
                    provider="kubernetes",
                    provider_config={},
                )
            )
        assert exc_info.value.status_code == 400


class TestVmSizeDefaultsThroughAdminApi:
    """Proves `default_vm_*` round-trips through the real typed client,
    the real HTTP API, the real `AnsiblePoolConfigHandler`, and the real
    database -- not only at the loader/DB level.
    """

    async def test_create_with_vm_size_defaults_round_trips_through_the_api(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        created = await client.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                provider_config={
                    **_ANSIBLE_CONFIG,
                    "default_vm_ram": 65536,
                    "default_vm_vcpus": 16,
                    "default_vm_disk_size": "500G",
                },
            )
        )
        assert created.provider_config["default_vm_ram"] == 65536
        assert created.provider_config["default_vm_vcpus"] == 16
        assert created.provider_config["default_vm_disk_size"] == "500G"

        fetched = await client.get_pool("hetzner-eu")
        assert fetched.provider_config["default_vm_ram"] == 65536
        assert fetched.provider_config["default_vm_vcpus"] == 16
        assert fetched.provider_config["default_vm_disk_size"] == "500G"

    async def test_create_without_vm_size_defaults_leaves_them_absent(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        created = await _create_pool(client)
        assert created.provider_config.get("default_vm_ram") is None
        assert created.provider_config.get("default_vm_vcpus") is None
        assert created.provider_config.get("default_vm_disk_size") is None

    async def test_replace_can_clear_a_previously_set_default(self, client_and_queue):
        client, _ = client_and_queue
        await client.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                provider_config={**_ANSIBLE_CONFIG, "default_vm_ram": 65536},
            )
        )

        await client.replace_pool(
            "hetzner-eu",
            PoolReplace(
                label="Hetzner EU",
                enabled=True,
                provider="ansible",
                provider_config=_ANSIBLE_CONFIG,
            ),
        )

        fetched = await client.get_pool("hetzner-eu")
        assert fetched.provider_config.get("default_vm_ram") is None

    @pytest.mark.parametrize("bad_value", [0, -1, "16", 16.5])
    async def test_create_rejects_non_positive_or_non_integer_ram(
        self, client_and_queue, bad_value,
    ):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.create_pool(
                PoolCreate(
                    id="hetzner-eu",
                    label="Hetzner EU",
                    provider="ansible",
                    provider_config={**_ANSIBLE_CONFIG, "default_vm_ram": bad_value},
                )
            )
        assert exc_info.value.status_code == 400


class TestGetAndListPools:
    async def test_get_missing_pool_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.get_pool("does-not-exist")
        assert exc_info.value.status_code == 404

    async def test_list_includes_created_pool(self, client_and_queue):
        client, _ = client_and_queue
        await _create_pool(client)
        result = await client.list_pools()
        assert any(p.id == "hetzner-eu" for p in result.pools)
        assert result.total == len(result.pools)


class TestUpdatePool:
    async def test_put_replaces_and_patch_updates_partially(self, client_and_queue):
        client, _ = client_and_queue
        await _create_pool(client)

        patched = await client.patch_pool(
            "hetzner-eu", PoolUpdate(label="Hetzner EU (patched)")
        )
        assert patched.label == "Hetzner EU (patched)"

        replaced = await client.replace_pool(
            "hetzner-eu",
            PoolReplace(
                label="Replacement",
                provider="ansible",
                enabled=False,
                policy_tags={"region": "eu"},
                provider_config=_ANSIBLE_CONFIG,
            ),
        )
        assert replaced.enabled is False
        assert replaced.label == "Replacement"

    async def test_update_missing_pool_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.patch_pool("does-not-exist", PoolUpdate(label="X"))
        assert exc_info.value.status_code == 404


class TestDeletePool:
    async def test_delete_disables_not_hard_deletes(self, client_and_queue):
        client, _ = client_and_queue
        await _create_pool(client)

        deleted = await client.delete_pool("hetzner-eu")
        assert deleted.enabled is False

        # Still resolvable via GET — not gone.
        pool = await client.get_pool("hetzner-eu")
        assert pool.enabled is False

    async def test_delete_missing_pool_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.delete_pool("does-not-exist")
        assert exc_info.value.status_code == 404

    async def test_delete_default_pool_disables_but_keeps_it_resolvable(
        self, client_and_queue
    ):
        """`default` can be disabled like any other pool it just can never
        be hard-deleted or stop being the fallback for hosts that omit pool_id.
        See openspec/specs/fulfillment/spec.md,
        decision 8."""
        client, _ = client_and_queue

        # The test fixture seeds "default" as a bare ResourcePool row with
        # no matching Ansible side-table config (unlike the real migration
        # seed). Give it one first — otherwise any update, not just
        # disable, would 400 on missing provider_config.
        await client.replace_pool(
            "default",
            PoolReplace(
                label="Default Pool",
                provider="ansible",
                enabled=True,
                policy_tags={},
                provider_config=_ANSIBLE_CONFIG,
            ),
        )

        deleted = await client.delete_pool("default")
        assert deleted.enabled is False

        # Still resolvable via GET — not gone.
        pool = await client.get_pool("default")
        assert pool.enabled is False

        # Still the fallback for hosts that omit pool_id.
        host = await client.register_host(
            HostCreate(
                name="kvm1",
                kvm_host="10.0.0.1",
                ssh_user="ubuntu",
                ssh_key_type="path",
                ssh_key_value="/key",
            )
        )
        assert host.pool_id == "default"


class TestImportAndValidatePools:
    _YAML = """
pools:
  - id: default
    label: Default Pool
    provider: ansible
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
  - id: hetzner-eu-central
    label: Hetzner EU Central
    provider: ansible
    provider_config:
      playbook_path: playbooks/vm-operations-frp.yaml
"""

    async def test_import_creates_pool(self, client_and_queue):
        client, _ = client_and_queue
        result = await client.import_pools(self._YAML)
        assert result.applied is True
        assert "hetzner-eu-central" in result.diff.created

        pool = await client.get_pool("hetzner-eu-central")
        assert pool.provider_config["playbook_path"] == "playbooks/vm-operations-frp.yaml"
        assert "inventory_group" not in pool.provider_config

    async def test_reimport_is_unchanged(self, client_and_queue):
        client, _ = client_and_queue
        await client.import_pools(self._YAML)
        result = await client.import_pools(self._YAML)
        assert "hetzner-eu-central" in result.diff.unchanged

    async def test_validate_only_does_not_write(self, client_and_queue):
        client, _ = client_and_queue
        result = await client.validate_pools(self._YAML)
        assert result.valid is True
        assert "hetzner-eu-central" in result.diff.created

        with pytest.raises(ProvisioningError) as exc_info:
            await client.get_pool("hetzner-eu-central")
        assert exc_info.value.status_code == 404

    async def test_validate_rejects_invalid_document(self, client_and_queue):
        client, _ = client_and_queue
        bad_yaml = """
pools:
  - id: bad-pool
    label: Bad Pool
    provider: kubernetes
    provider_config: {}
"""
        result = await client.validate_pools(bad_yaml)
        assert result.valid is False
        assert result.diff is None
        assert {problem.code for problem in result.problems} >= {
            "unknown_provider",
            "missing_default_pool",
        }

    async def test_export_round_trips(self, client_and_queue):
        client, _ = client_and_queue
        await client.import_pools(self._YAML)
        exported = await client.export_pools_yaml()
        result = await client.validate_pools(exported)
        assert result.valid is True
        assert "default" in result.diff.unchanged


class TestHostPoolIntegration:
    async def test_register_host_against_created_pool(self, client_and_queue):
        client, _ = client_and_queue
        await _create_pool(client)

        host = await client.register_host(
            HostCreate(
                name="kvm1",
                kvm_host="10.0.0.1",
                ssh_user="ubuntu",
                ssh_key_type="path",
                ssh_key_value="/key",
                pool_id="hetzner-eu",
            )
        )
        assert host.pool_id == "hetzner-eu"

    async def test_register_host_defaults_to_default_pool(self, client_and_queue):
        client, _ = client_and_queue
        host = await client.register_host(
            HostCreate(
                name="kvm1",
                kvm_host="10.0.0.1",
                ssh_user="ubuntu",
                ssh_key_type="path",
                ssh_key_value="/key",
            )
        )
        assert host.pool_id == "default"

    async def test_register_host_with_nonexistent_pool_returns_400(
        self, client_and_queue
    ):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.register_host(
                HostCreate(
                    name="kvm1",
                    kvm_host="10.0.0.1",
                    ssh_user="ubuntu",
                    ssh_key_type="path",
                    ssh_key_value="/key",
                    pool_id="does-not-exist",
                )
            )
        assert exc_info.value.status_code == 400

    async def test_update_host_reassigns_pool(self, client_and_queue):
        client, _ = client_and_queue
        await _create_pool(client)
        await client.register_host(
            HostCreate(
                name="kvm1",
                kvm_host="10.0.0.1",
                ssh_user="ubuntu",
                ssh_key_type="path",
                ssh_key_value="/key",
            )
        )
        updated = await client.update_host("kvm1", HostUpdate(pool_id="hetzner-eu"))
        assert updated.pool_id == "hetzner-eu"
