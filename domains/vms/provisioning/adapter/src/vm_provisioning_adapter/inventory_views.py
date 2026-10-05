"""VM's view in the site's resource-pool projection: a pool's VM size defaults.

A pool whose provider is VM's Ansible provider may configure default RAM, vCPU,
and disk sizes, which a VM storefront fills a listing shape's omitted
dimensions from. They are published, under ``vm.ansible_pool_defaults.v1``, as
the pool's view; nothing else from the provider's configuration is.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from compute_provisioning_service.db.models import AnsiblePoolConfig

#: The pool view this projection produces.
VM_ANSIBLE_POOL_DEFAULTS_VIEW = "vm.ansible_pool_defaults.v1"

_DEFAULT_FIELDS = ("default_vm_ram", "default_vm_vcpus", "default_vm_disk_size")


def project_ansible_pool_defaults(raw_view: Mapping[str, Any]) -> dict[str, Any]:
    """Only the configured (non-``None``) defaults, which may be none at all.

    The handler already enforces the values' constraints when a pool is
    written, so the view is the configured scalars as they are.
    """
    return {key: raw_view[key] for key in _DEFAULT_FIELDS if raw_view.get(key) is not None}


class AnsiblePoolDefaultsViews:
    """The VM size defaults of every pool VM's Ansible provider serves.

    The view is gated on the pool's declared provider, not on a configuration
    row existing: a pool whose provider changed keeps no row for the old one
    normally, but the gate means a stale row could never publish VM defaults
    for a pool another provider serves. Only the default-size columns are
    read; the rest of the configuration, which may reference credentials,
    never is.
    """

    resource_view_ids: frozenset[str] = frozenset()
    pool_view_ids = frozenset({VM_ANSIBLE_POOL_DEFAULTS_VIEW})
    consumed_attributes: frozenset[str] = frozenset()

    def __init__(self, *, provider: str) -> None:
        self._provider = provider

    def resource_views(
        self, declaration: Mapping[str, Any], *, pool_id: str
    ) -> Mapping[str, Mapping[str, Any]]:
        return {}

    def pool_views(
        self, db: Any, *, pool_id: str, provider: str
    ) -> Mapping[str, Mapping[str, Any]]:
        if provider != self._provider:
            return {}
        config = db.get(AnsiblePoolConfig, pool_id)
        if config is None:
            return {}
        defaults = project_ansible_pool_defaults(
            {field: getattr(config, field) for field in _DEFAULT_FIELDS}
        )
        return {VM_ANSIBLE_POOL_DEFAULTS_VIEW: defaults} if defaults else {}


__all__ = [
    "AnsiblePoolDefaultsViews",
    "VM_ANSIBLE_POOL_DEFAULTS_VIEW",
    "project_ansible_pool_defaults",
]
