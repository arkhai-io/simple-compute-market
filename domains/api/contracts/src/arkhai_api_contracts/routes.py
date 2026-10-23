"""The authority's signed routes as plain data.

Each declaration is what request authentication and the typed client both
read: ``method``, ``path`` (a regular expression the whole path must match),
``operation``, ``roles``, and the resource the signature covers, named by
``path_resource`` or ``body_resource``. ``exact_retry_safe`` is false only
where re-executing a signed request would apply a relative change twice.

Two caller roles: ``seller`` is the storefront, which issues against settled
deals and administers keys; ``service`` is the gated application, which only
spends and checks, so a compromised one cannot mint grants or revoke keys.
"""

from __future__ import annotations

from arkhai_api_contracts import operations

SELLER_ROLE = "seller"
SERVICE_ROLE = "service"

_SELLER = (SELLER_ROLE,)
_GATED = (SERVICE_ROLE,)
_SELLER_OR_GATED = (SELLER_ROLE, SERVICE_ROLE)

AUTHORITY_ROUTES: tuple[dict, ...] = (
    {
        "method": "POST",
        "path": r"/api/v1/issuance",
        "operation": operations.ISSUE,
        "roles": _SELLER,
        "body_resource": "fulfillment_id",
        "optional_body_resource": True,
    },
    {
        "method": "GET",
        "path": r"/api/v1/issuance/(?P<fulfillment_id>[^/]+)",
        "operation": operations.ISSUANCE_GET,
        "roles": _SELLER,
        "path_resource": "fulfillment_id",
    },
    {
        "method": "POST",
        "path": r"/api/v1/keys/consume-batch",
        "operation": operations.KEY_CONSUME_BATCH,
        "roles": _GATED,
    },
    {
        "method": "POST",
        "path": r"/api/v1/keys/(?P<key_id>[^/]+)/consume",
        "operation": operations.KEY_CONSUME,
        "roles": _GATED,
        "path_resource": "key_id",
    },
    {
        "method": "POST",
        "path": r"/api/v1/keys/(?P<key_id>[^/]+)/verify",
        "operation": operations.KEY_VERIFY,
        "roles": _SELLER_OR_GATED,
        "path_resource": "key_id",
    },
    {
        "method": "POST",
        "path": r"/api/v1/keys/(?P<key_id>[^/]+)/revoke",
        "operation": operations.KEY_REVOKE,
        "roles": _SELLER,
        "path_resource": "key_id",
    },
    {
        "method": "POST",
        "path": r"/api/v1/keys/(?P<key_id>[^/]+)/adjust",
        "operation": operations.KEY_ADJUST,
        "roles": _SELLER,
        "path_resource": "key_id",
        # A relative delta with no idempotency key: an exact retry would apply it twice.
        "exact_retry_safe": False,
    },
    {
        "method": "GET",
        "path": r"/api/v1/keys/(?P<key_id>[^/]+)/grants",
        "operation": operations.KEY_GRANTS_LIST,
        "roles": _SELLER,
        "path_resource": "key_id",
    },
    {
        "method": "GET",
        "path": r"/api/v1/keys/(?P<key_id>[^/]+)/usage",
        "operation": operations.KEY_USAGE_LIST,
        "roles": _SELLER,
        "path_resource": "key_id",
    },
    {"method": "GET", "path": r"/api/v1/keys", "operation": operations.KEYS_LIST, "roles": _SELLER},
    {
        "method": "GET",
        "path": r"/api/v1/keys/(?P<key_id>[^/]+)",
        "operation": operations.KEY_GET,
        "roles": _SELLER,
        "path_resource": "key_id",
    },
)


def route(operation: str) -> dict:
    """The declaration of one authority route, by its signed operation."""

    for declaration in AUTHORITY_ROUTES:
        if declaration["operation"] == operation:
            return declaration
    raise KeyError(operation)
