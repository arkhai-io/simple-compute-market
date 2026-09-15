"""Signed-route contracts for this service's own paths.

`kit/site` owns the capacity routes and their contracts, because it defines
those paths. These are the credits service's own: issuance, key administration,
and the consume/verify pair the gated service calls. They live here for the
same reason -- the table belongs beside the router that defines the paths.

Both tables are handed to one `SiteAuthMiddleware`, so every non-health route
on this service is signed and every response is signed, including refusals.
That replaces a shared-secret gate whose refusals were unsigned, which the
kit's own client could not read: it failed on the missing response-auth header
rather than reporting the 401 it had been sent.

Two caller roles, deliberately distinct:

- `seller` is the storefront this service is an internal dependency of. It
  issues credits against settled deals and administers keys.
- `service` is the gated application consuming and verifying credits. It is a
  narrower role on purpose: a compromised sample app should not be able to mint
  grants or revoke keys, which a single shared admin secret could not express
  at all.

`admin` is admitted everywhere by `SiteRouteContract.permits` and is not
enumerated. It is for manual operation, debugging and intervention, and is
held by an operator and the e2e suite -- not by either service component.
"""

from __future__ import annotations

import re

from market_site.auth import SiteRouteContract

_SELLER = frozenset({"seller"})
#: Issuance and the consume/verify pair. The storefront issues against a
#: settled deal; the gated service spends and checks. Both are legitimate
#: callers of the credit balance, from opposite ends.
_SELLER_OR_GATED = frozenset({"seller", "service"})
#: Consume and verify only. The gated service's whole job.
_GATED = frozenset({"service"})


def _contract(
    method: str,
    pattern: str,
    operation: str,
    roles: frozenset[str],
    **kwargs: object,
) -> SiteRouteContract:
    return SiteRouteContract(
        method=method,
        pattern=re.compile(pattern),
        operation=operation,
        allowed_roles=roles,
        **kwargs,  # type: ignore[arg-type]
    )


#: Order matters where patterns prefix one another: `/keys/consume-batch`
#: precedes `/keys/{key_id}` so the batch route is not read as a key id, and
#: the collection `GET /keys` precedes `GET /keys/{key_id}`.
CREDITS_ROUTE_CONTRACTS: tuple[SiteRouteContract, ...] = (
    _contract(
        "POST",
        r"/api/v1/issuance",
        "credits_issue",
        _SELLER,
        body_resource="fulfillment_id",
        optional_body_resource=True,
    ),
    _contract(
        "GET",
        r"/api/v1/issuance/(?P<fulfillment_id>[^/]+)",
        "credits_issuance_get",
        _SELLER,
        path_resource="fulfillment_id",
    ),
    _contract(
        "POST",
        r"/api/v1/keys/consume-batch",
        "credits_key_consume_batch",
        _GATED,
    ),
    _contract(
        "POST",
        r"/api/v1/keys/(?P<key_id>[^/]+)/consume",
        "credits_key_consume",
        _GATED,
        path_resource="key_id",
    ),
    _contract(
        "POST",
        r"/api/v1/keys/(?P<key_id>[^/]+)/verify",
        "credits_key_verify",
        _SELLER_OR_GATED,
        path_resource="key_id",
    ),
    _contract(
        "POST",
        r"/api/v1/keys/(?P<key_id>[^/]+)/revoke",
        "credits_key_revoke",
        _SELLER,
        path_resource="key_id",
    ),
    _contract(
        "POST",
        r"/api/v1/keys/(?P<key_id>[^/]+)/adjust",
        "credits_key_adjust",
        _SELLER,
        path_resource="key_id",
        # The one credit mutation an exact retry cannot be allowed through to.
        # It applies a *relative* delta and records no idempotency key, so
        # re-executing the same signed request applies the adjustment twice.
        # Consume deduplicates on a key inside its signed body, revoke is
        # idempotent, and an issuance is unique per fulfillment id -- each of
        # those resolves an exact retry to the recorded outcome in the handler,
        # which is why they stay safe.
        exact_retry_safe=False,
    ),
    _contract(
        "GET",
        r"/api/v1/keys/(?P<key_id>[^/]+)/grants",
        "credits_key_grants_list",
        _SELLER,
        path_resource="key_id",
    ),
    _contract(
        "GET",
        r"/api/v1/keys/(?P<key_id>[^/]+)/usage",
        "credits_key_usage_list",
        _SELLER,
        path_resource="key_id",
    ),
    _contract("GET", r"/api/v1/keys", "credits_keys_list", _SELLER),
    _contract(
        "GET",
        r"/api/v1/keys/(?P<key_id>[^/]+)",
        "credits_key_get",
        _SELLER,
        path_resource="key_id",
    ),
)
