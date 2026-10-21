"""Site authorities that sign their answers as a principal a test chooses.

A storefront verifies each site's responses against the site's service-peer
principals, so a test that follows a rotation needs a site whose signing
principal it can change between calls. Each :class:`SignedSite` answers the
resource-pool projection and its version, as the capacity client reads them,
and a lease read, as the provisioning client does, each signed as its current
``signer`` over the route's own operation and resource. :class:`SignedSites`
serves several by host through one transport, and builds the storefront's site
clients over it, the production clients with only their transport replaced.

Every signer a caller passes is a development fixture, never for use on a
public network.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import httpx
from compute_provisioning_client import ComputeProvisioningClient
from compute_provisioning_contracts import (
    PROVISIONING_ROUTE_TABLE,
    canonical_provisioning_request_body,
)
from market_identity import (
    EMPTY_BODY,
    ResponseEnvelope,
    Signer,
    canonical_body_hash,
    sign_response,
)
from market_site_client import SiteCapacityClient
from market_site_client.client import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    resolve_capacity_route,
)

from arkhai_bare_metal_storefront.site_clients import SiteClientFactories
from source_sites import listing_source_projection

_CAPACITY_PREFIX = "/api/v1/capacity/"


class SignedSite:
    """One site authority, signing every answer as ``signer``."""

    def __init__(self, signer: Signer, projection: dict[str, Any] | None = None) -> None:
        self.signer = signer
        self.projection = projection if projection is not None else listing_source_projection()

    def answer(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        sent = json.loads(request.content) if request.content else EMPTY_BODY
        if path.startswith(_CAPACITY_PREFIX):
            if path.endswith("/version"):
                body: Any = {
                    "revision": self.projection["revision"],
                    "digest": self.projection["digest"],
                }
            else:
                body = self.projection
            operation, resource = resolve_capacity_route(request.method, path, sent)
        else:
            reservation = path.rstrip("/").rsplit("/", 1)[-1]
            body = {
                "capacity_reservation_id": reservation,
                "deal_ref": {"negotiation_id": "negotiation-1"},
                "offering_mode": "bare_metal",
                "executor_target": "machine-1",
                "lease_end_utc": "2030-01-01T00:00:00+00:00",
                "status": "active",
            }
            contract, resource = PROVISIONING_ROUTE_TABLE.resolve(
                request.method,
                path,
                canonical_provisioning_request_body(request.method, path, sent, query={}),
            )
            operation = contract.operation
        signed = sign_response(
            signer=self.signer,
            envelope=ResponseEnvelope(
                role="service",
                principal=self.signer.identity,
                method=request.method,
                operation=operation,
                resource=resource,
                request_id=request.headers[REQUEST_ID_HEADER],
                timestamp=int(time.time()),
                status=200,
                body_hash=canonical_body_hash(body),
            ),
        )
        return httpx.Response(
            200,
            content=json.dumps(body).encode(),
            headers={
                "content-type": "application/json",
                SIGNATURE_VERSION_HEADER: signed.protocol,
                IDENTITY_SCHEME_HEADER: signed.principal.scheme.value,
                IDENTITY_IDENTIFIER_HEADER: signed.principal.identifier,
                ROLE_HEADER: signed.role,
                REQUEST_ID_HEADER: signed.request_id,
                TIMESTAMP_HEADER: str(signed.timestamp),
                SIGNATURE_HEADER: signed.proof.value,
            },
        )


class SignedSites:
    """Several site authorities, each answering requests to its own host."""

    def __init__(self, sites: Mapping[str, SignedSite]) -> None:
        self.sites = dict(sites)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(lambda request: self.sites[request.url.host].answer(request))

    def factories(self) -> SiteClientFactories:
        """The storefront's production site clients, over this transport."""
        transport = self.transport()
        return SiteClientFactories(
            capacity=lambda url, signer, authorities: SiteCapacityClient(
                url, signer, authorities, transport=transport
            ),
            fulfillment=lambda url, signer, authorities: ComputeProvisioningClient(
                url,
                signer=signer,
                caller_role="seller",
                expected_authorities=authorities,
                transport=transport,
            ),
        )
