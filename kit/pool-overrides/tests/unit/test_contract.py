"""The signed-resource contract binds every request unambiguously."""

from __future__ import annotations

import pytest
from market_identity import EMPTY_BODY

from market_pool_overrides import PoolOverrideContractError, pool_override_contract
from market_pool_overrides.contract import address_resource, read_resource

BODY = {"site_id": "site/a", "pool_id": "gpu?x=1&y=%", "offering_mode": "vm", "terms": {}}


def test_a_write_binds_its_body_and_its_encoded_address():
    contract = pool_override_contract("PUT", [], BODY)

    assert contract.operation == "admin_put_pool_override"
    assert contract.resource == "site%2Fa/gpu%3Fx%3D1%26y%3D%25/vm"
    assert contract.body == BODY


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (("a/b", "c", "vm"), ("a", "b/c", "vm")),
        (("a", "b%2Fc", "vm"), ("a", "b/c", "vm")),
        (("a", "b", "vm/x"), ("a", "b/vm", "x")),
    ],
)
def test_address_resources_are_injective(first, second):
    assert address_resource(*first) != address_resource(*second)


def test_a_delete_binds_its_query_and_signs_no_body():
    contract = pool_override_contract(
        "DELETE", [("site_id", "a"), ("pool_id", "gpu"), ("offering_mode", "vm")], EMPTY_BODY
    )

    assert (contract.operation, contract.resource) == ("admin_delete_pool_override", "a/gpu/vm")
    assert contract.body is EMPTY_BODY


@pytest.mark.parametrize(
    ("query", "operation", "resource"),
    [
        ([("offering_mode", "vm"), ("pool_id", "gpu"), ("site_id", "a")],
         "admin_get_pool_override", "pool-overrides?offering_mode=vm&pool_id=gpu&site_id=a"),
        ([("site_id", "a/b")], "admin_list_pool_overrides", "pool-overrides?site_id=a%2Fb"),
        ([("site_id", "a"), ("pool_id", "gpu")], "admin_list_pool_overrides",
         "pool-overrides?pool_id=gpu&site_id=a"),
        # An empty query signs no trailing "?".
        ([], "admin_list_pool_overrides", "pool-overrides"),
    ],
)
def test_a_read_binds_its_sorted_query(query, operation, resource):
    contract = pool_override_contract("GET", query, EMPTY_BODY)

    assert (contract.operation, contract.resource) == (operation, resource)
    assert read_resource(dict(query)) == resource


@pytest.mark.parametrize(
    ("method", "query", "body"),
    [
        ("GET", [("pool_id", "gpu")], EMPTY_BODY),
        ("GET", [("site_id", "a"), ("offering_mode", "vm")], EMPTY_BODY),
        ("GET", [("site_id", "a"), ("site_id", "b")], EMPTY_BODY),
        ("GET", [("site_id", "a"), ("limit", "5")], EMPTY_BODY),
        ("DELETE", [("site_id", "a"), ("pool_id", "gpu")], EMPTY_BODY),
        ("PUT", [], ["not", "an", "object"]),
        ("PUT", [], {"site_id": "a", "pool_id": "gpu"}),
        ("PUT", [], {"site_id": "", "pool_id": "gpu", "offering_mode": "vm"}),
        ("POST", [], {}),
    ],
)
def test_an_unbindable_request_is_refused(method, query, body):
    with pytest.raises(PoolOverrideContractError):
        pool_override_contract(method, query, body)
