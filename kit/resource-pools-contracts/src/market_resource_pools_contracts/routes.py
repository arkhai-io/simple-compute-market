"""The signed contracts of the resource-pool administration routes.

Plain data, so a client needs only this package to sign a pool request and a
service hosting the pool authority assembles the same declarations into the
table its request authentication reads: ``method``, ``path`` (a regular
expression the whole path must match), ``operation``, ``roles``, and
``path_resource`` where the path names the pool.

Order is significant: the first declaration whose path fully matches decides,
so the export route precedes the identified pool it would otherwise match.
"""

from __future__ import annotations

_ADMIN = ("admin",)

RESOURCE_POOL_ROUTES = (
    {"method": "GET", "path": r"/api/v1/pools/?", "operation": "provisioning_pools_list", "roles": _ADMIN},
    {"method": "GET", "path": r"/api/v1/pools/export", "operation": "provisioning_pools_export", "roles": _ADMIN},
    {
        "method": "GET",
        "path": r"/api/v1/pools/(?P<pool_id>[^/]+)",
        "operation": "provisioning_pool_get",
        "roles": _ADMIN,
        "path_resource": "pool_id",
    },
    {"method": "POST", "path": r"/api/v1/pools/?", "operation": "provisioning_pool_create", "roles": _ADMIN},
    {
        "method": "PUT",
        "path": r"/api/v1/pools/(?P<pool_id>[^/]+)",
        "operation": "provisioning_pool_replace",
        "roles": _ADMIN,
        "path_resource": "pool_id",
    },
    {
        "method": "PATCH",
        "path": r"/api/v1/pools/(?P<pool_id>[^/]+)",
        "operation": "provisioning_pool_update",
        "roles": _ADMIN,
        "path_resource": "pool_id",
    },
    {
        "method": "DELETE",
        "path": r"/api/v1/pools/(?P<pool_id>[^/]+)",
        "operation": "provisioning_pool_disable",
        "roles": _ADMIN,
        "path_resource": "pool_id",
    },
    {"method": "POST", "path": r"/api/v1/pools/import", "operation": "provisioning_pools_import", "roles": _ADMIN},
    {"method": "POST", "path": r"/api/v1/pools/validate", "operation": "provisioning_pools_validate", "roles": _ADMIN},
)


def pool_route(operation: str) -> dict:
    """The declaration of one pool route, by its signed operation."""

    for declaration in RESOURCE_POOL_ROUTES:
        if declaration["operation"] == operation:
            return declaration
    raise KeyError(operation)


__all__ = ["RESOURCE_POOL_ROUTES", "pool_route"]
