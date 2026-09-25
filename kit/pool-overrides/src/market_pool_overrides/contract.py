"""The signed-resource contract for the override routes.

Site, pool, and offering-mode identifiers are operator-chosen strings with no
character restriction, so they travel in the body or query and each is
percent-encoded with no safe characters before joining, which makes every
resource injective. The storefront's identity middleware and the client both
build resources here, so the two cannot disagree byte for byte.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from market_identity import EMPTY_BODY

POOL_OVERRIDES_PATH = "/api/v1/admin/pool-overrides"

PUT_OPERATION = "admin_put_pool_override"
GET_OPERATION = "admin_get_pool_override"
LIST_OPERATION = "admin_list_pool_overrides"
DELETE_OPERATION = "admin_delete_pool_override"

_ADDRESS = ("site_id", "pool_id", "offering_mode")
_READ_PREFIX = "pool-overrides"


class PoolOverrideContractError(ValueError):
    """A request that cannot be bound to one operation and resource."""


@dataclass(frozen=True)
class PoolOverrideContract:
    operation: str
    resource: str
    body: Any


def address_resource(site_id: Any, pool_id: Any, offering_mode: Any) -> str:
    """The resource a write or delete signs: the three address components."""
    components = (site_id, pool_id, offering_mode)
    if not all(isinstance(value, str) and value for value in components):
        raise PoolOverrideContractError(
            "a pool override requires a non-empty site_id, pool_id, and offering_mode"
        )
    return "/".join(quote(value, safe="") for value in components)


def read_resource(query: Mapping[str, str]) -> str:
    """The resource a read signs: the sorted, percent-encoded query, with no
    ``?`` when there is none."""
    if not query:
        return _READ_PREFIX
    return f"{_READ_PREFIX}?" + urlencode(sorted(query.items()), quote_via=quote, safe="")


def read_query(items: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Validate a read's query: only address keys, each at most once, each
    narrowing the one before it."""
    query: dict[str, str] = {}
    for name, value in items:
        if name not in _ADDRESS or name in query:
            raise PoolOverrideContractError(
                "pool override query contains an unauthenticated alias"
            )
        query[name] = value
    if "pool_id" in query and "site_id" not in query:
        raise PoolOverrideContractError("pool_id requires site_id")
    if "offering_mode" in query and "pool_id" not in query:
        raise PoolOverrideContractError("offering_mode requires pool_id")
    return query


def pool_override_contract(
    method: str, query_items: Iterable[tuple[str, str]], body: Any
) -> PoolOverrideContract:
    """Bind one request to its operation, resource, and signed body."""
    method = method.upper()
    if method == "PUT":
        if not isinstance(body, dict):
            raise PoolOverrideContractError("pool override body must be an object")
        return PoolOverrideContract(
            PUT_OPERATION,
            address_resource(*(body.get(name) for name in _ADDRESS)),
            body,
        )
    query = read_query(query_items)
    if method == "DELETE":
        return PoolOverrideContract(
            DELETE_OPERATION,
            address_resource(*(query.get(name) for name in _ADDRESS)),
            EMPTY_BODY,
        )
    if method == "GET":
        operation = GET_OPERATION if "offering_mode" in query else LIST_OPERATION
        return PoolOverrideContract(operation, read_resource(query), EMPTY_BODY)
    raise PoolOverrideContractError(f"unsupported pool override method {method}")


__all__ = [
    "DELETE_OPERATION",
    "GET_OPERATION",
    "LIST_OPERATION",
    "POOL_OVERRIDES_PATH",
    "PUT_OPERATION",
    "PoolOverrideContract",
    "PoolOverrideContractError",
    "address_resource",
    "pool_override_contract",
    "read_query",
    "read_resource",
]
