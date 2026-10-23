"""
Integration tests for the resource pool admin API.

All calls go through ProvisioningClients methods — no route strings in test
code. ComputeProvisioningError is raised by the client on non-2xx responses.

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
from compute_provisioning_ansible import ssh_connection

from .conftest import ProvisioningClients
from compute_provisioning_client import ComputeProvisioningError
import pytest
import yaml

from compute_provisioning_service import container as _container_module
from market_resource_pools import ResourcePoolService
from bare_metal_provisioning_adapter.services.bare_metal_pool_config_handler import BareMetalPoolConfigHandler
from vm_provisioning_adapter.services.ansible_pool_config_handler import AnsiblePoolConfigHandler

from market_resource_pools_contracts import PoolCreate, PoolReplace, PoolUpdate
from compute_provisioning_contracts import HostCreate, HostUpdate


_ANSIBLE_CONFIG = {
    "playbook_path": "playbooks/vm-operations.yaml",
}


async def _create_pool(client: ProvisioningClients, pool_id: str = "hetzner-eu"):
    return await client.pools.create_pool(
        PoolCreate(
            id=pool_id,
            label="Hetzner EU",
            provider="vm.ansible",
            policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
            provider_config=_ANSIBLE_CONFIG,
        )
    )


class TestDefaultPool:
    async def test_default_pool_exists_at_startup(self, client_and_queue):
        client, _ = client_and_queue
        pool = await client.pools.get_pool("default")
        assert pool.enabled is True
        assert pool.provider == "vm.ansible"

    async def test_default_pool_appears_in_list(self, client_and_queue):
        client, _ = client_and_queue
        result = await client.pools.list_pools()
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
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await _create_pool(client)
        assert exc_info.value.status_code == 409

    async def test_create_unknown_provider_returns_400(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.pools.create_pool(
                PoolCreate(
                    id="k8s-1",
                    label="K8s",
                    provider="kubernetes",
                    policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
                    provider_config={},
                )
            )
        assert exc_info.value.status_code == 400


class TestPolicyHintValidationThroughAdminApi:
    """Model refusals cross the HTTP boundary without changing stored state."""

    async def test_create_malformed_hint_returns_422_without_creating_pool(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        before = await client.pools.export_pools_yaml()
        # Rejection-path test: bypass local construction to exercise the
        # server's model validation through the canonical typed client.
        malformed = PoolCreate.model_construct(
            id="malformed", label="Malformed", provider="vm.ansible", enabled=True,
            policy_tags={"advertisable_modes": [], "capacity_backing": "backed",
                         "max_reservation_hold_seconds": -1},
            provider_config=_ANSIBLE_CONFIG,
        )
        with pytest.raises(ComputeProvisioningError) as refused:
            await client.pools.create_pool(malformed)
        assert refused.value.status_code == 422
        assert await client.pools.export_pools_yaml() == before

    async def test_replace_malformed_hint_returns_422_without_mutation(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        original = await _create_pool(client)
        # Rejection-path test: deliberately construct a body the local model
        # rejects. The typed client still owns routing and serialization.
        malformed = PoolReplace.model_construct(
            label="Changed", provider="vm.ansible", enabled=False,
            policy_tags={"advertisable_modes": [], "capacity_backing": "backed",
                         "asking_rates": None},
            provider_config={**_ANSIBLE_CONFIG, "default_vm_vcpus": 8},
        )
        with pytest.raises(ComputeProvisioningError) as refused:
            await client.pools.replace_pool(original.id, malformed)
        assert refused.value.status_code == 422
        assert await client.pools.get_pool(original.id) == original

    async def test_patch_malformed_hint_returns_422_without_mutation(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        original = await _create_pool(client)
        # Rejection-path test: send malformed tags past local construction;
        # assert only HTTP status and stored state, not validation-body fields.
        malformed = PoolUpdate.model_construct(
            label="Changed", enabled=False,
            policy_tags={"advertisable_modes": [], "capacity_backing": "backed",
                         "pricing": {"memory": {"rates": "invalid"}}},
            provider_config={**_ANSIBLE_CONFIG, "default_vm_ram": 65536},
        )
        with pytest.raises(ComputeProvisioningError) as refused:
            await client.pools.patch_pool(original.id, malformed)
        assert refused.value.status_code == 422
        assert await client.pools.get_pool(original.id) == original

    async def test_valid_hints_round_trip_through_create_replace_patch_and_read(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        tags = {
            "advertisable_modes": [], "capacity_backing": "backed",
            "max_reservation_hold_seconds": 120, "sla": 99.9,
            "listing_shapes": {"vm": [{"gpu": {"count": 1, "model": "H100"}}]},
            "asking_rates": {"vm": [{
                "shape": {"gpu": {"count": 1, "model": "H100"}},
                "amount": "2.10", "asset": "usd", "period": "hour",
            }]},
            "pricing": {"memory": {"rates": [{"asset": "usd", "rate": "0.05", "per": "hour"}]}},
            "opaque_future_hint": {"value": [1, "two"]},
        }
        created = await client.pools.create_pool(PoolCreate(
            id="hinted", label="Hinted", provider="vm.ansible",
            policy_tags=tags, provider_config=_ANSIBLE_CONFIG,
        ))
        assert created.policy_tags == tags
        replaced = await client.pools.replace_pool("hinted", PoolReplace(
            label="Replaced", provider="vm.ansible", enabled=True,
            policy_tags=tags, provider_config=_ANSIBLE_CONFIG,
        ))
        assert replaced.policy_tags == tags
        patched = await client.pools.patch_pool("hinted", PoolUpdate(policy_tags=tags))
        assert patched.policy_tags == tags
        renamed = await client.pools.patch_pool("hinted", PoolUpdate(label="Renamed"))
        assert renamed.policy_tags == tags
        assert (await client.pools.get_pool("hinted")).policy_tags == tags

    async def test_raw_document_malformed_hint_keeps_400_and_structured_problems(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        before = await client.pools.export_pools_yaml()
        document = _declared_document(
            "    policy_tags:\n"
            "      advertisable_modes: []\n"
            "      capacity_backing: backed\n"
            "      max_reservation_hold_seconds: -1"
        )
        result = await client.pools.validate_pools(document)
        assert result.valid is False
        assert result.diff is None
        assert [(p.path, p.code) for p in result.problems] == [
            ("pools[1].policy_tags.max_reservation_hold_seconds", "invalid_hold_preference"),
        ]
        with pytest.raises(ComputeProvisioningError) as refused:
            await client.pools.import_pools(document)
        assert refused.value.status_code == 400
        assert await client.pools.export_pools_yaml() == before


class TestVmSizeDefaultsThroughAdminApi:
    """Proves `default_vm_*` round-trips through the real typed client,
    the real HTTP API, the real `AnsiblePoolConfigHandler`, and the real
    database -- not only at the loader/DB level.
    """

    async def test_create_with_vm_size_defaults_round_trips_through_the_api(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        created = await client.pools.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="vm.ansible",
                policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
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

        fetched = await client.pools.get_pool("hetzner-eu")
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
        await client.pools.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="vm.ansible",
                policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
                provider_config={**_ANSIBLE_CONFIG, "default_vm_ram": 65536},
            )
        )

        await client.pools.replace_pool(
            "hetzner-eu",
            PoolReplace(
                label="Hetzner EU",
                enabled=True,
                provider="vm.ansible",
                policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
                provider_config=_ANSIBLE_CONFIG,
            ),
        )

        fetched = await client.pools.get_pool("hetzner-eu")
        assert fetched.provider_config.get("default_vm_ram") is None

    @pytest.mark.parametrize("bad_value", [0, -1, "16", 16.5])
    async def test_create_rejects_non_positive_or_non_integer_ram(
        self, client_and_queue, bad_value,
    ):
        client, _ = client_and_queue
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.pools.create_pool(
                PoolCreate(
                    id="hetzner-eu",
                    label="Hetzner EU",
                    provider="vm.ansible",
                    policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
                    provider_config={**_ANSIBLE_CONFIG, "default_vm_ram": bad_value},
                )
            )
        assert exc_info.value.status_code == 400


class TestPlaybookLeftToTheService:
    async def test_a_vm_pool_stating_no_configuration_is_accepted_and_exported(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        created = await client.pools.create_pool(
            PoolCreate(
                id="vm-unstated",
                label="VM, service playbook",
                provider="vm.ansible",
                policy_tags={
                    "deliverable_modes": ["vm"],
                    "advertisable_modes": ["vm"],
                    "capacity_backing": "backed",
                },
                provider_config={},
            )
        )
        assert created.provider_config["playbook_path"] is None

        exported = yaml.safe_load(await client.pools.export_pools_yaml())
        (entry,) = [pool for pool in exported["pools"] if pool["id"] == "vm-unstated"]
        assert entry["provider_config"]["playbook_path"] is None
        assert "inventory_group" not in entry["provider_config"]


class TestGetAndListPools:
    async def test_get_missing_pool_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.pools.get_pool("does-not-exist")
        assert exc_info.value.status_code == 404

    async def test_list_includes_created_pool(self, client_and_queue):
        client, _ = client_and_queue
        await _create_pool(client)
        result = await client.pools.list_pools()
        assert any(p.id == "hetzner-eu" for p in result.pools)
        assert result.total == len(result.pools)


class TestUpdatePool:
    async def test_put_replaces_and_patch_updates_partially(self, client_and_queue):
        client, _ = client_and_queue
        await _create_pool(client)

        patched = await client.pools.patch_pool(
            "hetzner-eu", PoolUpdate(label="Hetzner EU (patched)")
        )
        assert patched.label == "Hetzner EU (patched)"

        replaced = await client.pools.replace_pool(
            "hetzner-eu",
            PoolReplace(
                label="Replacement",
                provider="vm.ansible",
                enabled=False,
                policy_tags={"advertisable_modes": [], "capacity_backing": "backed", "region": "eu"},
                provider_config=_ANSIBLE_CONFIG,
            ),
        )
        assert replaced.enabled is False
        assert replaced.label == "Replacement"

    async def test_update_missing_pool_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.pools.patch_pool("does-not-exist", PoolUpdate(label="X"))
        assert exc_info.value.status_code == 404


class TestDeletePool:
    async def test_delete_disables_not_hard_deletes(self, client_and_queue):
        client, _ = client_and_queue
        await _create_pool(client)

        deleted = await client.pools.delete_pool("hetzner-eu")
        assert deleted.enabled is False

        # Still resolvable via GET — not gone.
        pool = await client.pools.get_pool("hetzner-eu")
        assert pool.enabled is False
        assert pool.provider_config == deleted.provider_config
        assert pool.provider_config["playbook_path"] == _ANSIBLE_CONFIG["playbook_path"]

    async def test_delete_missing_pool_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.pools.delete_pool("does-not-exist")
        assert exc_info.value.status_code == 404

    async def test_delete_default_pool_disables_but_keeps_it_resolvable(
        self, client_and_queue
    ):
        """`default` is disabled like any other pool, and like any other it
        is never hard-deleted."""
        client, _ = client_and_queue

        # The test fixture seeds "default" as a bare ResourcePool row with
        # no matching Ansible side-table config (unlike the real migration
        # seed). Give it one first — otherwise any update, not just
        # disable, would 400 on missing provider_config.
        await client.pools.replace_pool(
            "default",
            PoolReplace(
                label="Default Pool",
                provider="vm.ansible",
                enabled=True,
                policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
                provider_config=_ANSIBLE_CONFIG,
            ),
        )

        deleted = await client.pools.delete_pool("default")
        assert deleted.enabled is False

        # Still resolvable via GET — not gone.
        pool = await client.pools.get_pool("default")
        assert pool.enabled is False

        # Still the fallback for hosts that omit pool_id.
        host = await client.family.register_host(
            HostCreate(
                host_id="kvm1",
                connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="ubuntu", key_path="/key"),
            )
        )
        assert host.pool_id == "default"


class TestImportAndValidatePools:
    _YAML = """
pools:
  - id: default
    label: Default Pool
    provider: vm.ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
  - id: hetzner-eu-central
    label: Hetzner EU Central
    provider: vm.ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
    provider_config:
      playbook_path: playbooks/vm-operations-frp.yaml
"""

    async def test_import_creates_pool(self, client_and_queue):
        client, _ = client_and_queue
        result = await client.pools.import_pools(self._YAML)
        assert result.applied is True
        assert "hetzner-eu-central" in result.diff.created

        pool = await client.pools.get_pool("hetzner-eu-central")
        assert pool.provider_config["playbook_path"] == "playbooks/vm-operations-frp.yaml"
        assert "inventory_group" not in pool.provider_config

    async def test_reimport_is_unchanged(self, client_and_queue):
        client, _ = client_and_queue
        await client.pools.import_pools(self._YAML)
        result = await client.pools.import_pools(self._YAML)
        assert "hetzner-eu-central" in result.diff.unchanged

    async def test_validate_only_does_not_write(self, client_and_queue):
        client, _ = client_and_queue
        result = await client.pools.validate_pools(self._YAML)
        assert result.valid is True
        assert "hetzner-eu-central" in result.diff.created

        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.pools.get_pool("hetzner-eu-central")
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
        result = await client.pools.validate_pools(bad_yaml)
        assert result.valid is False
        assert result.diff is None
        assert "unknown_provider" in {problem.code for problem in result.problems}

    async def test_a_document_naming_no_default_pool_imports(self, client_and_queue):
        """No pool name is required of a document. Applied authoritatively, it
        disables the stored `default` it does not name, as any omitted pool."""
        client, _ = client_and_queue
        no_default = """
pools:
  - id: hetzner-eu-central
    label: Hetzner EU Central
    provider: vm.ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
    provider_config:
      playbook_path: playbooks/vm-operations-frp.yaml
"""
        validated = await client.pools.validate_pools(no_default)
        assert validated.valid is True
        assert validated.problems == []

        result = await client.pools.import_pools(no_default)
        assert result.applied is True
        assert result.diff.created == ["hetzner-eu-central"]
        assert result.diff.disabled == ["default"]
        assert (await client.pools.get_pool("hetzner-eu-central")).enabled is True
        assert (await client.pools.get_pool("default")).enabled is False

    async def test_export_round_trips(self, client_and_queue):
        client, _ = client_and_queue
        await client.pools.import_pools(self._YAML)
        exported = await client.pools.export_pools_yaml()
        result = await client.pools.validate_pools(exported)
        assert result.valid is True
        assert "default" in result.diff.unchanged


class TestHostPoolIntegration:
    async def test_register_host_against_created_pool(self, client_and_queue):
        client, _ = client_and_queue
        await _create_pool(client)

        host = await client.family.register_host(
            HostCreate(
                host_id="kvm1",
                connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="ubuntu", key_path="/key"),
                pool_id="hetzner-eu",
            )
        )
        assert host.pool_id == "hetzner-eu"

    async def test_register_host_defaults_to_default_pool(self, client_and_queue):
        client, _ = client_and_queue
        host = await client.family.register_host(
            HostCreate(
                host_id="kvm1",
                connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="ubuntu", key_path="/key"),
            )
        )
        assert host.pool_id == "default"

    async def test_register_host_with_nonexistent_pool_returns_400(
        self, client_and_queue
    ):
        client, _ = client_and_queue
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.family.register_host(
                HostCreate(
                    host_id="kvm1",
                    connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="ubuntu", key_path="/key"),
                    pool_id="does-not-exist",
                )
            )
        assert exc_info.value.status_code == 400

    async def test_update_host_reassigns_pool(self, client_and_queue):
        client, _ = client_and_queue
        await _create_pool(client)
        await client.family.register_host(
            HostCreate(
                host_id="kvm1",
                connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="ubuntu", key_path="/key"),
            )
        )
        updated = await client.family.update_host("kvm1", HostUpdate(pool_id="hetzner-eu"))
        assert updated.pool_id == "hetzner-eu"


# ---------------------------------------------------------------------------
# Advertisement and backing declarations
# ---------------------------------------------------------------------------

_BACKED_VM = {
    "deliverable_modes": ["vm"],
    "advertisable_modes": ["vm"],
    "capacity_backing": "backed",
}


def _declared_document(policy_tags_block: str) -> str:
    """The fixture's `default` pool plus one Ansible pool with the given tags."""
    return f"""
pools:
  - id: default
    label: Default Pool
    provider: vm.ansible
    policy_tags:
      deliverable_modes: [bare_metal, vm]
      advertisable_modes: [bare_metal, vm]
      capacity_backing: backed
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
  - id: hetzner-eu
    label: Hetzner EU
    provider: vm.ansible
{policy_tags_block}
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
"""


async def _create_backed_vm_pool(client: ProvisioningClients) -> None:
    await client.pools.create_pool(
        PoolCreate(
            id="hetzner-eu",
            label="Hetzner EU",
            provider="vm.ansible",
            policy_tags=dict(_BACKED_VM),
            provider_config=_ANSIBLE_CONFIG,
        )
    )


def _unvalidated_replace(policy_tags: dict) -> PoolReplace:
    # Rejection-path helper: built without the model's own validation so the
    # request reaches the server's validation boundary through the real
    # client. Tests using it assert status and stored state only.
    return PoolReplace.model_construct(
        label="Hetzner EU",
        provider="vm.ansible",
        enabled=True,
        policy_tags=policy_tags,
        provider_config=_ANSIBLE_CONFIG,
    )


class TestExecutionLessPoolAdvertises:
    async def test_unbacked_pool_needs_no_execution_configuration(self, client_and_queue):
        """An execution-less seller's pool names the configuration-free
        provider, declares nothing deliverable, and still authorizes a mode
        for advertisement through the real administration path."""
        client, _ = client_and_queue
        tags = {
            "deliverable_modes": [],
            "advertisable_modes": ["vm"],
            "capacity_backing": "unbacked",
        }

        created = await client.pools.create_pool(
            PoolCreate(
                id="out-of-band",
                label="Out of band",
                provider="bare_metal.ansible",
                policy_tags=tags,
                provider_config={},
            )
        )

        assert created.provider_config == {}
        assert (await client.pools.get_pool("out-of-band")).policy_tags == tags


class TestDeclarationsRequiredOnEveryWrite:
    async def test_explicit_declarations_round_trip_through_every_write(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        await _create_backed_vm_pool(client)
        assert (await client.pools.get_pool("hetzner-eu")).policy_tags == _BACKED_VM

        narrowed = {**_BACKED_VM, "advertisable_modes": []}
        replaced = await client.pools.replace_pool(
            "hetzner-eu",
            PoolReplace(
                label="Hetzner EU", provider="vm.ansible", enabled=True,
                policy_tags=narrowed, provider_config=_ANSIBLE_CONFIG,
            ),
        )
        assert replaced.policy_tags == narrowed

        patched = await client.pools.patch_pool(
            "hetzner-eu", PoolUpdate(policy_tags=dict(_BACKED_VM)),
        )
        assert patched.policy_tags == _BACKED_VM

        imported = await client.pools.import_pools(_declared_document(
            "    policy_tags:\n"
            "      deliverable_modes: [vm]\n"
            "      advertisable_modes: []\n"
            "      capacity_backing: backed"
        ))
        assert "hetzner-eu" in imported.diff.updated
        assert (await client.pools.get_pool("hetzner-eu")).policy_tags == narrowed

    @pytest.mark.parametrize("omitted", ["advertisable_modes", "capacity_backing"])
    async def test_every_write_omitting_a_declaration_is_refused(
        self, client_and_queue, omitted,
    ):
        """Rejection-path test: bodies the typed models refuse to build are
        sent through the real client to prove the server refuses them too.
        Asserts status codes and stored state only; the per-rule detail is
        owned by the kit's unit and library tests."""
        client, _ = client_and_queue
        await _create_backed_vm_pool(client)
        partial = {k: v for k, v in _BACKED_VM.items() if k != omitted}

        with pytest.raises(ComputeProvisioningError) as created:
            await client.pools.create_pool(PoolCreate.model_construct(
                id="fresh", label="Fresh", provider="vm.ansible", enabled=True,
                policy_tags=partial, provider_config=_ANSIBLE_CONFIG,
            ))
        with pytest.raises(ComputeProvisioningError) as replaced:
            await client.pools.replace_pool("hetzner-eu", _unvalidated_replace(partial))
        with pytest.raises(ComputeProvisioningError) as patched:
            await client.pools.patch_pool("hetzner-eu", PoolUpdate.model_construct(
                policy_tags=partial,
            ))

        for refused in (created, replaced, patched):
            assert refused.value.status_code == 422
        with pytest.raises(ComputeProvisioningError):
            await client.pools.get_pool("fresh")
        assert (await client.pools.get_pool("hetzner-eu")).policy_tags == _BACKED_VM

    async def test_document_predating_declarations_imports_nothing(self, client_and_queue):
        client, _ = client_and_queue
        old_format = _declared_document("")

        result = await client.pools.validate_pools(old_format)

        assert result.valid is False
        assert {(p.path, p.code) for p in result.problems} == {
            ("pools[1].policy_tags.advertisable_modes", "missing_declaration"),
            ("pools[1].policy_tags.capacity_backing", "missing_declaration"),
        }
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.pools.import_pools(old_format)
        assert exc_info.value.status_code == 400
        with pytest.raises(ComputeProvisioningError):
            await client.pools.get_pool("hetzner-eu")

    async def test_export_carries_declarations_and_reimports_unchanged(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        # Imported rather than created, so the fixture's directly seeded
        # `default` pool gains the provider configuration an export must carry.
        await client.pools.import_pools(_declared_document(
            "    policy_tags:\n"
            "      deliverable_modes: [vm]\n"
            "      advertisable_modes: [vm]\n"
            "      capacity_backing: backed"
        ))

        exported = await client.pools.export_pools_yaml()
        result = await client.pools.import_pools(exported)

        assert "advertisable_modes" in exported and "capacity_backing" in exported
        assert result.diff.updated == []
        assert set(result.diff.unchanged) == {"default", "hetzner-eu"}


class TestCrossTagRulesThroughAdminApi:
    @pytest.mark.parametrize(
        "tags",
        [
            pytest.param(
                {**_BACKED_VM, "advertisable_modes": ["vm", "bare_metal"]},
                id="advertisement-widened",
            ),
            pytest.param({**_BACKED_VM, "deliverable_modes": []}, id="delivery-narrowed"),
        ],
    )
    async def test_backed_subset_rule_is_enforced_from_both_sides(
        self, client_and_queue, tags,
    ):
        """Rejection-path test: status and stored state only."""
        client, _ = client_and_queue
        await _create_backed_vm_pool(client)

        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.pools.replace_pool("hetzner-eu", _unvalidated_replace(tags))

        assert exc_info.value.status_code == 422
        assert (await client.pools.get_pool("hetzner-eu")).policy_tags == _BACKED_VM

    async def test_malformed_backing_is_refused(self, client_and_queue):
        """Rejection-path test: status and stored state only."""
        client, _ = client_and_queue
        await _create_backed_vm_pool(client)

        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.pools.patch_pool("hetzner-eu", PoolUpdate.model_construct(
                policy_tags={**_BACKED_VM, "capacity_backing": "sometimes"},
            ))

        assert exc_info.value.status_code == 422
        assert (await client.pools.get_pool("hetzner-eu")).policy_tags == _BACKED_VM

    async def test_unbacked_pool_that_delivers_is_refused(self, client_and_queue):
        """Rejection-path test: status and stored state only."""
        client, _ = client_and_queue

        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.pools.create_pool(PoolCreate.model_construct(
                id="out-of-band", label="Out of band", provider="bare_metal.ansible",
                enabled=True,
                policy_tags={**_BACKED_VM, "capacity_backing": "unbacked"},
                provider_config={},
            ))

        assert exc_info.value.status_code == 422
        with pytest.raises(ComputeProvisioningError):
            await client.pools.get_pool("out-of-band")


class TestBackingFixedAtCreationThroughAdminApi:
    _UNBACKED = {
        "deliverable_modes": [],
        "advertisable_modes": ["vm"],
        "capacity_backing": "unbacked",
    }

    async def test_replace_and_patch_changing_backing_are_refused(self, client_and_queue):
        client, _ = client_and_queue
        await _create_backed_vm_pool(client)

        with pytest.raises(ComputeProvisioningError) as replaced:
            await client.pools.replace_pool(
                "hetzner-eu",
                PoolReplace(
                    label="Hetzner EU", provider="vm.ansible", enabled=True,
                    policy_tags=dict(self._UNBACKED), provider_config=_ANSIBLE_CONFIG,
                ),
            )
        with pytest.raises(ComputeProvisioningError) as patched:
            await client.pools.patch_pool(
                "hetzner-eu", PoolUpdate(policy_tags=dict(self._UNBACKED)),
            )

        for refused in (replaced, patched):
            assert refused.value.status_code == 400
        assert (await client.pools.get_pool("hetzner-eu")).policy_tags == _BACKED_VM

    async def test_import_changing_backing_is_refused_and_validate_reports_it(
        self, client_and_queue,
    ):
        client, _ = client_and_queue
        await _create_backed_vm_pool(client)
        document = _declared_document(
            "    policy_tags:\n"
            "      deliverable_modes: []\n"
            "      advertisable_modes: [vm]\n"
            "      capacity_backing: unbacked"
        )

        result = await client.pools.validate_pools(document)
        assert result.valid is False
        assert result.diff is None
        assert [(p.path, p.code) for p in result.problems] == [
            ("pools[1].policy_tags.capacity_backing", "capacity_backing_immutable"),
        ]
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.pools.import_pools(document)

        assert exc_info.value.status_code == 400
        assert (await client.pools.get_pool("hetzner-eu")).policy_tags == _BACKED_VM


class _RecordingAnsiblePoolConfigHandler(AnsiblePoolConfigHandler):
    def __init__(self):
        super().__init__()
        self.writes = []

    def replace_config(self, db, pool_id, config):
        self.writes.append(pool_id)
        super().replace_config(db, pool_id, config)


class TestProviderFixedAtCreationThroughAdminApi:
    @pytest.mark.parametrize("operation", ["replace", "patch"])
    async def test_provider_change_is_400_and_preserves_all_state(self, client_and_queue, operation):
        client, _ = client_and_queue
        original = await _create_pool(client)
        exported = await client.pools.export_pools_yaml()
        data = dict(
            label="Changed", provider="bare_metal.ansible", enabled=False,
            policy_tags={"advertisable_modes": [], "capacity_backing": "backed", "region": "other"},
            provider_config={},
        )

        with pytest.raises(ComputeProvisioningError) as refused:
            if operation == "replace":
                await client.pools.replace_pool(original.id, PoolReplace(**data))
            else:
                await client.pools.patch_pool(original.id, PoolUpdate(**data))

        assert refused.value.status_code == 400
        message = str(refused.value)
        assert "'vm.ansible'" in message and "'bare_metal.ansible'" in message
        assert "declare a second pool" in message and "migrate its members" in message
        assert await client.pools.get_pool(original.id) == original
        assert await client.pools.export_pools_yaml() == exported

    async def test_equal_provider_patch_writes_no_configuration(
        self, client_and_queue, session_factory, monkeypatch,
    ):
        client, _ = client_and_queue
        handler = _RecordingAnsiblePoolConfigHandler()
        service = ResourcePoolService(session_factory, {
            "vm.ansible": handler, "bare_metal.ansible": BareMetalPoolConfigHandler(),
        })
        # The controller resolves its injected service through this accessor;
        # keep real persistence and record only the handler's write boundary.
        monkeypatch.setattr(_container_module, "resolved_resource_pool_service", service)
        original = await _create_pool(client)
        handler.writes.clear()

        unchanged = await client.pools.patch_pool(original.id, PoolUpdate(provider="vm.ansible"))
        assert unchanged == original
        renamed = await client.pools.patch_pool(original.id, PoolUpdate(label="Renamed"))
        assert renamed.policy_tags == original.policy_tags
        assert renamed.provider_config == original.provider_config
        assert handler.writes == []

        replaced = await client.pools.replace_pool(original.id, PoolReplace(
            label="Replaced", provider="vm.ansible", enabled=True,
            policy_tags=original.policy_tags,
            provider_config={**_ANSIBLE_CONFIG, "default_vm_vcpus": 8},
        ))
        assert replaced.provider == "vm.ansible"
        assert replaced.provider_config["default_vm_vcpus"] == 8
        patched = await client.pools.patch_pool(original.id, PoolUpdate(
            provider="vm.ansible", provider_config={**_ANSIBLE_CONFIG, "default_vm_vcpus": 16},
        ))
        assert patched.provider == "vm.ansible"
        assert patched.provider_config["default_vm_vcpus"] == 16
        assert handler.writes == [original.id, original.id]

    async def test_document_provider_change_is_indexed_and_import_is_atomic(self, client_and_queue):
        client, _ = client_and_queue
        await client.pools.import_pools(TestImportAndValidatePools._YAML)
        omitted = await _create_pool(client, "omitted")
        before = await client.pools.list_pools()
        exported = await client.pools.export_pools_yaml()
        document = yaml.safe_load(exported)
        default = next(p for p in document["pools"] if p["id"] == "default")
        changed = next(p for p in document["pools"] if p["id"] == "hetzner-eu-central")
        default["label"] = "Changed default"
        changed.update(provider="bare_metal.ansible", provider_config={}, enabled=False)
        changed["policy_tags"] = {"advertisable_modes": [], "capacity_backing": "unbacked"}
        document["pools"] = [default, {
            "id": "fresh", "label": "Fresh", "provider": "bare_metal.ansible",
            "policy_tags": {"advertisable_modes": [], "capacity_backing": "backed"},
            "provider_config": {},
        }, changed]
        text = yaml.safe_dump(document)

        result = await client.pools.validate_pools(text)
        assert result.valid is False
        assert result.diff is None
        assert [(p.path, p.code) for p in result.problems] == [
            ("pools[2].provider", "provider_immutable"),
            ("pools[2].policy_tags.capacity_backing", "capacity_backing_immutable"),
        ]
        with pytest.raises(ComputeProvisioningError) as refused:
            await client.pools.import_pools(text)
        assert refused.value.status_code == 400
        assert "pools[2].provider:" in str(refused.value)
        assert "migrate its members" in str(refused.value)
        assert await client.pools.list_pools() == before
        assert await client.pools.get_pool(omitted.id) == omitted
        assert await client.pools.export_pools_yaml() == exported
