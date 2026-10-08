"""The route table this service authenticates, assembled from every owner.

The service hosts routes several owners declare: the compute family's, the site
capacity authority's, the resource-pool authority's, the Ansible
implementation's host import, and each domain adapter's. Each owner keeps its
route contracts in its own package, and its typed client signs from them; this
module assembles them into the one table request authentication reads, so the
two sides use the same contract data and cannot diverge.

A site contract admits ``admin`` on every route through its own rule rather than
by naming it, so it is translated here into a contract that names its roles.

Canonicalization follows the owner as well: a site route's signed body is the
site's canonical form, which ``kit/site-client`` signs, and every other route's
is the family's.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from compute_provisioning_ansible.host_import import HOST_IMPORT_ROUTES
from compute_provisioning_contracts import (
    ProvisioningRouteContract,
    ProvisioningRouteTable,
    assemble_provisioning_route_table,
    canonical_provisioning_request_body,
)
from market_identity import EMPTY_BODY
from market_resource_pools_contracts import RESOURCE_POOL_ROUTES
from market_site.auth import (
    ADMIN_ROLE,
    CAPACITY_DEFINITION_ROUTE_CONTRACTS,
    CAPACITY_ROUTE_CONTRACTS,
    SiteRouteContract,
    canonical_site_request_body,
)

_SITE_CONTRACTS: tuple[SiteRouteContract, ...] = (
    CAPACITY_ROUTE_CONTRACTS + CAPACITY_DEFINITION_ROUTE_CONTRACTS
)


def site_route_contracts(
    contracts: Sequence[SiteRouteContract],
) -> tuple[ProvisioningRouteContract, ...]:
    """The site's contracts with their roles named, ``admin`` among them."""

    return tuple(
        ProvisioningRouteContract(
            contract.method,
            contract.pattern,
            contract.operation,
            body_resource=contract.body_resource,
            optional_body_resource=contract.optional_body_resource,
            path_resource=contract.path_resource,
            roles=tuple(sorted(contract.allowed_roles - {ADMIN_ROLE})) + (ADMIN_ROLE,),
        )
        for contract in contracts
    )


def assemble_service_route_table(
    *domain_declarations: Iterable[ProvisioningRouteContract | Mapping[str, Any]],
) -> ProvisioningRouteTable:
    """The family's routes, the hosted capabilities', and each domain's."""

    return assemble_provisioning_route_table(
        site_route_contracts(CAPACITY_ROUTE_CONTRACTS),
        site_route_contracts(CAPACITY_DEFINITION_ROUTE_CONTRACTS),
        RESOURCE_POOL_ROUTES,
        HOST_IMPORT_ROUTES,
        *domain_declarations,
    )


def is_site_route(method: str, path: str) -> bool:
    upper = method.upper()
    return any(
        contract.method == upper and contract.pattern.fullmatch(path) is not None
        for contract in _SITE_CONTRACTS
    )


def canonical_request_body(
    method: str,
    path: str,
    body: Any = EMPTY_BODY,
    *,
    query: Mapping[str, Any] | None = None,
) -> Any:
    """The signed body of one request, in its route owner's canonical form."""

    if is_site_route(method, path):
        return canonical_site_request_body(method, path, body, query=query)
    return canonical_provisioning_request_body(method, path, body, query=query)


__all__ = [
    "assemble_service_route_table",
    "canonical_request_body",
    "is_site_route",
    "site_route_contracts",
]
