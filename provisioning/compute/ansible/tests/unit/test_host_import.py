"""Host import from an INI inventory: parsing, refusals, and the response."""

from __future__ import annotations

import pytest
from compute_provisioning.hosts.service import PoolChangeRefusedError
from compute_provisioning.route_errors import ProvisioningRouteError

from compute_provisioning_ansible.host_import import (
    HOST_IMPORT_PATH,
    HOST_IMPORT_ROUTES,
    AnsibleHostImportRouteService,
)

_INVENTORY = b"[kvm_hosts]\nkvm1  ansible_host=192.0.2.10  ansible_user=root  ansible_ssh_private_key_file=/keys/id\n"


class _Hosts:
    def __init__(self) -> None:
        self.applied: list = []

    def apply_inventory(self, entries):
        self.applied = list(entries)
        return []


def test_every_listed_host_is_applied_through_the_host_authority():
    hosts = _Hosts()

    response = AnsibleHostImportRouteService(hosts).import_hosts(_INVENTORY, "path")

    assert [entry.host_id for entry in hosts.applied] == ["kvm1"]
    assert (response.hosts, response.total) == ([], 0)


def test_a_file_that_is_not_utf8_is_a_bad_request():
    with pytest.raises(ProvisioningRouteError) as refused:
        AnsibleHostImportRouteService(_Hosts()).import_hosts(b"\xff\xfe", "path")

    assert refused.value.status_code == 400


def test_a_refused_inventory_is_a_bad_request():
    class _Refusing(_Hosts):
        def apply_inventory(self, entries):
            raise ValueError("pool 'missing' does not exist")

    with pytest.raises(ProvisioningRouteError) as refused:
        AnsibleHostImportRouteService(_Refusing()).import_hosts(_INVENTORY, "path")

    assert (refused.value.status_code, refused.value.detail) == (400, "pool 'missing' does not exist")


def test_an_inventory_moving_a_host_a_subscriber_protects_is_a_conflict():
    class _Refusing(_Hosts):
        def apply_inventory(self, entries):
            raise PoolChangeRefusedError("drain the relay first")

    with pytest.raises(ProvisioningRouteError) as refused:
        AnsibleHostImportRouteService(_Refusing()).import_hosts(_INVENTORY, "path")

    assert (refused.value.status_code, refused.value.detail) == (409, "drain the relay first")


def test_the_route_declaration_admits_admin_at_the_import_path():
    (declaration,) = HOST_IMPORT_ROUTES

    assert (declaration["method"], declaration["path"]) == ("POST", HOST_IMPORT_PATH)
    assert "admin" in declaration["roles"]
