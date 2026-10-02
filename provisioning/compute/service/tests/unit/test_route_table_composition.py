"""The provisioning service authenticates every route its adapters contribute.

Each adapter declares the signed contracts of the routes it mounts; assembled
with the family kit's own routes, every declared route must resolve to itself,
with no two contributions claiming one path.
"""

from __future__ import annotations

import re

import pytest
from bare_metal_provisioning_adapter.routers import bare_metal_route_contracts
from compute_provisioning import assemble_provisioning_route_table
from vm_provisioning_adapter.routers import vm_route_contracts

_TABLE = assemble_provisioning_route_table(
    vm_route_contracts(), bare_metal_route_contracts()
)
_CONTRIBUTED = [
    contract
    for contract in _TABLE.contracts
    if contract.operation
    in {
        route["operation"]
        for route in (*vm_route_contracts(), *bare_metal_route_contracts())
    }
]


def _concrete_path(pattern: str) -> str:
    path = re.sub(r"\(\?P<[^>]+>\[\^/\]\+\)", "resource-1", pattern)
    return path.replace("/?", "").removesuffix("$")


def test_every_adapter_route_is_contributed() -> None:
    assert len(_CONTRIBUTED) == len(vm_route_contracts()) + len(
        bare_metal_route_contracts()
    )


@pytest.mark.parametrize("contract", _CONTRIBUTED, ids=lambda contract: contract.operation)
def test_every_contributed_route_resolves_to_itself(contract) -> None:
    path = _concrete_path(contract.pattern.pattern)
    body = {contract.body_resource: "resource-1"} if contract.body_resource else {}

    resolved, resource = _TABLE.resolve(contract.method, path, body)

    assert resolved is contract
    assert resource == contract.match(contract.method, path, body)
