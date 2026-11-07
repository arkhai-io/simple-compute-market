"""VM's pool view: a pool's configured VM size defaults.

Hosted in the service's suite with VM's other adapter tests, because the view
reads the Ansible pool configuration table the service still owns.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from compute_provisioning import InventoryPoolContext, ResourceViews
from market_resource_pools_contracts.backing import BACKED
from market_resource_pools_contracts.hints import PoolDeclarations
from vm_provisioning_adapter.db import AnsiblePoolConfig
from vm_provisioning_adapter.inventory_views import (
    VM_ANSIBLE_POOL_DEFAULTS_VIEW,
    AnsiblePoolDefaultsViews,
)


class _Db:
    def __init__(self, *configs) -> None:
        self._configs = {config.pool_id: config for config in configs}

    def get(self, model, pool_id):
        assert model is AnsiblePoolConfig
        return self._configs.get(pool_id)


def _config(**defaults):
    values = dict(default_vm_ram=None, default_vm_vcpus=None, default_vm_disk_size=None)
    values.update(defaults)
    return SimpleNamespace(pool_id="gpu-pool", **values)


VIEWS = AnsiblePoolDefaultsViews(provider="vm.ansible")


def _views(db, provider="vm.ansible"):
    return VIEWS.pool_views(db, pool_id="gpu-pool", provider=provider)


def test_the_configured_defaults_are_the_view():
    db = _Db(_config(default_vm_ram=65536, default_vm_vcpus=16, default_vm_disk_size="500G"))

    assert _views(db) == {
        VM_ANSIBLE_POOL_DEFAULTS_VIEW: {
            "default_vm_ram": 65536,
            "default_vm_vcpus": 16,
            "default_vm_disk_size": "500G",
        }
    }


def test_only_the_configured_defaults_appear():
    assert _views(_Db(_config(default_vm_ram=65536))) == {
        VM_ANSIBLE_POOL_DEFAULTS_VIEW: {"default_vm_ram": 65536}
    }


@pytest.mark.parametrize("db", [_Db(_config()), _Db()], ids=["no defaults", "no row"])
def test_no_configured_default_is_no_view(db):
    assert _views(db) == {}


def test_a_stale_row_for_a_pool_another_provider_serves_publishes_nothing():
    """A view named for VM's Ansible provider must never be published beside a
    contradicting mechanism, even if a row for the old provider remains."""
    db = _Db(_config(default_vm_ram=65536, default_vm_vcpus=16))

    assert _views(db, provider="k8s") == {}


def test_the_view_contributes_nothing_per_resource():
    pool = InventoryPoolContext(
        pool_id="gpu-pool",
        provider="vm.ansible",
        declarations=PoolDeclarations(advertisable_modes=frozenset({"vm"}), backing=BACKED),
    )

    assert VIEWS.resource_views({"attributes": {}}, pool=pool) == ResourceViews()
    assert (VIEWS.resource_view_ids, VIEWS.consumed_attributes) == (frozenset(), frozenset())
