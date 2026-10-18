"""Trusted multi-site capacity and fulfillment client construction."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from compute_provisioning_client import AuthorityTrust, ComputeProvisioningClient
from compute_provisioning_contracts import (
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    FulfillmentScheduleResponse,
    FulfillmentStatusResponse,
    LeaseTermination,
    LeaseView,
)

from core_storefront.aggregation import (
    PLACEMENT_POLICIES,
    AggregateCapacityClient,
)
from core_storefront.auth import AuthError
from core_storefront.service_peers import (
    SERVICE_PEER_ROLE,
    ServicePeerConfigs,
    ServicePeerTrust,
)
from market_config.setting_types import site_authority_url
from market_identity import Signer
from market_site_client import SiteCapacityClient

_SITE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True, slots=True)
class BareMetalSiteBinding:
    """One public site identity bound to its URL and to its one service peer.

    The binding names the peer, not a principal: the principals the site's
    responses and callbacks verify against are the peer's durable active ones,
    which :class:`ServicePeerTrust` holds, so a rotation reaches them without a
    configuration change or a restart.
    """

    site_id: str
    service_peer: str
    authority_url: str = field(repr=False)

    def diagnostic(self, trust: ServicePeerTrust | None) -> dict[str, Any]:
        """Return only public identity data; routing URLs stay private.

        The authority principals are the peer's active ones now, primary
        first; a site the trust cannot answer for reports none, and why.
        """
        report: dict[str, Any] = {
            "site_id": self.site_id,
            "service_peer": self.service_peer,
            "authority_principals": [],
        }
        if trust is None:
            report["trust_error"] = "service-peer trust is not composed"
            return report
        try:
            trusted = trust.site_trusted_set(self.site_id)
        except AuthError as exc:
            report["trust_error"] = exc.detail
            return report
        report["authority_principals"] = [
            principal.model_dump(mode="json") for principal in trusted.identities
        ]
        return report


def _authority_url(value: Any, *, site_id: str) -> str:
    try:
        return site_authority_url(value)
    except ValueError as exc:
        raise ValueError(f"site {site_id!r} authority_url {exc}") from None


def parse_site_bindings(
    sites: Mapping[str, str],
    peers: ServicePeerConfigs,
) -> tuple[BareMetalSiteBinding, ...]:
    """Bind each configured site to its URL and to its one service peer,
    without ever returning raw configuration.

    ``sites`` is ``[capacity.sites]``, each stable site ID to its authority URL;
    ``peers`` the configured service peers, each bound to one site.
    """
    if not sites:
        raise ValueError("at least one site must be configured")
    bindings: list[BareMetalSiteBinding] = []
    for site_id, url in sites.items():
        if not isinstance(site_id, str) or _SITE_ID.fullmatch(site_id) is None:
            raise ValueError("a configured site has an invalid site ID")
        bound = [
            peer_id
            for peer_id, (role, peer_site, _principals) in peers.items()
            if role == SERVICE_PEER_ROLE and peer_site == site_id
        ]
        if len(bound) != 1:
            raise ValueError(
                f"site {site_id!r} must be bound to exactly one service peer"
            )
        bindings.append(
            BareMetalSiteBinding(
                site_id=site_id,
                service_peer=bound[0],
                authority_url=_authority_url(url, site_id=site_id),
            )
        )
    return tuple(bindings)


class DurableReservationSiteMap(dict[str, str]):
    """Reservation-to-site cache whose site binding survives restart.

    Each reservation is pinned to its site and to the service peer that site is
    bound to: the stable subject, not a principal, so an authorized rotation of
    the peer leaves every reservation bound. The principal recorded beside them
    is the peer's primary when the reservation was made, an audit record that
    is never compared.
    """

    def __init__(
        self,
        db_path: str,
        bindings: Mapping[str, BareMetalSiteBinding],
        trust: ServicePeerTrust,
    ) -> None:
        self._db_path = db_path
        self._bindings = dict(bindings)
        self._trust = trust
        loaded: dict[str, str] = {}
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT capacity_reservation_id, site_id, service_peer "
                "FROM bare_metal_selected_site_bindings"
            ).fetchall()
        finally:
            conn.close()
        for reservation_id, site_id, service_peer in rows:
            binding = self._bindings.get(str(site_id))
            if binding is None:
                raise RuntimeError(
                    "persisted bare-metal reservation references an unconfigured "
                    f"site_id {site_id!r}"
                )
            if binding.service_peer != str(service_peer):
                raise RuntimeError(
                    "persisted bare-metal reservation's site is now bound to another "
                    f"service peer for site_id {site_id!r}"
                )
            loaded[str(reservation_id)] = str(site_id)
        super().__init__(loaded)

    def __setitem__(self, reservation_id: str, site_id: str) -> None:
        binding = self._bindings.get(site_id)
        if binding is None:
            raise KeyError(f"unknown trusted site_id {site_id!r}")
        try:
            audited = self._trust.site_trusted_set(site_id).identities[0]
        except AuthError as exc:
            raise RuntimeError(
                f"site_id {site_id!r} has no trusted service peer to record the "
                "reservation against"
            ) from exc
        reservation_id = str(reservation_id)
        conn = sqlite3.connect(self._db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO bare_metal_selected_site_bindings(
                      capacity_reservation_id, site_id, service_peer,
                      authority_scheme, authority_identifier
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        reservation_id,
                        site_id,
                        binding.service_peer,
                        audited.scheme.value,
                        audited.identifier,
                    ),
                )
                recorded = conn.execute(
                    "SELECT site_id, service_peer "
                    "FROM bare_metal_selected_site_bindings "
                    "WHERE capacity_reservation_id = ?",
                    (reservation_id,),
                ).fetchone()
                if recorded != (site_id, binding.service_peer):
                    raise RuntimeError(
                        "capacity reservation conflicts with its persisted "
                        "trusted site binding"
                    )
        finally:
            conn.close()
        super().__setitem__(reservation_id, site_id)

    def pop(self, reservation_id: str, default: Any = None) -> str | Any:
        reservation_id = str(reservation_id)
        conn = sqlite3.connect(self._db_path)
        try:
            with conn:
                conn.execute(
                    "DELETE FROM bare_metal_selected_site_bindings "
                    "WHERE capacity_reservation_id = ?",
                    (reservation_id,),
                )
        finally:
            conn.close()
        return super().pop(reservation_id, default)


class SelectedSiteFulfillmentClient:
    """Route every lifecycle verb only to the reservation's durable site."""

    def __init__(
        self,
        clients: Mapping[str, ComputeProvisioningClient],
        reservation_sites: Mapping[str, str],
    ) -> None:
        self._clients = dict(clients)
        self._reservation_sites = reservation_sites

    def _client(self, capacity_reservation_id: str) -> ComputeProvisioningClient:
        site_id = self._reservation_sites.get(str(capacity_reservation_id))
        if site_id is None:
            raise RuntimeError(
                "capacity reservation has no persisted trusted site binding"
            )
        try:
            return self._clients[site_id]
        except KeyError as exc:
            raise RuntimeError(
                f"capacity reservation references unconfigured site_id {site_id!r}"
            ) from exc

    async def schedule_resource(
        self,
        request: FulfillmentScheduleRequest,
    ) -> FulfillmentScheduleResponse:
        return await self._client(
            request.capacity_reservation_id
        ).schedule_resource(request)

    async def begin_fulfillment(
        self,
        body: FulfillmentRequestBody,
    ) -> FulfillmentAcceptanceResponse:
        return await self._client(
            body.capacity_reservation_id
        ).begin_fulfillment(body)

    async def get_fulfillment_status(
        self,
        fulfillment_id: str,
        *,
        capacity_reservation_id: str,
    ) -> FulfillmentStatusResponse:
        return await self._client(
            capacity_reservation_id
        ).get_fulfillment_status(fulfillment_id)

    async def get_fulfillment_result(
        self,
        fulfillment_id: str,
        *,
        capacity_reservation_id: str,
    ):
        return await self._client(
            capacity_reservation_id
        ).get_fulfillment_result(fulfillment_id)

    async def begin_fulfillment_teardown(
        self,
        fulfillment_id: str,
        *,
        capacity_reservation_id: str,
    ) -> FulfillmentAcceptanceResponse:
        return await self._client(
            capacity_reservation_id
        ).begin_fulfillment_teardown(fulfillment_id)

    async def get_lease(self, capacity_reservation_id: str) -> LeaseView:
        """The reservation's lease, from the site that holds it."""
        return await self._client(capacity_reservation_id).get_lease(
            capacity_reservation_id
        )

    async def terminate_lease(
        self,
        capacity_reservation_id: str,
        *,
        reason: str | None = None,
    ) -> LeaseView:
        """End the reservation's lease at the site that holds it.

        The site converges teardown through the lease's fulfillment and releases
        the capacity once; terminating a lease already ending returns it as it is.
        """
        return await self._client(capacity_reservation_id).terminate_lease(
            capacity_reservation_id, LeaseTermination(reason=reason)
        )


def _seller_provisioning_client(
    url: str, signer: Signer, authorities: AuthorityTrust
) -> ComputeProvisioningClient:
    return ComputeProvisioningClient(
        url,
        signer=signer,
        caller_role="seller",
        expected_authorities=authorities,
    )


@dataclass(frozen=True, slots=True)
class SiteClientFactories:
    """How each site's two clients are built from its URL, the storefront's
    signer, and the provider of the site's trusted principals.

    The defaults are the production clients; a test serves the sites through
    its own transports by supplying factories that pass one.
    """

    capacity: Callable[[str, Signer, AuthorityTrust], Any] = SiteCapacityClient
    fulfillment: Callable[[str, Signer, AuthorityTrust], Any] = (
        _seller_provisioning_client
    )


def build_trusted_site_clients(
    *,
    bindings: tuple[BareMetalSiteBinding, ...],
    signer: Signer,
    db_path: str,
    placement: str,
    trust: ServicePeerTrust,
    factories: SiteClientFactories = SiteClientFactories(),
) -> tuple[
    AggregateCapacityClient,
    SelectedSiteFulfillmentClient,
]:
    """Construct exact per-site clients and a shared durable route map.

    Each site's capacity and fulfillment clients verify every response against
    the provider of that site's peer's active principals, read at verification
    time, the set its callbacks are verified against too.
    """
    try:
        placement_policy = PLACEMENT_POLICIES[placement]
    except KeyError as exc:
        supported = ", ".join(sorted(PLACEMENT_POLICIES))
        raise ValueError(
            f"unsupported bare-metal site placement {placement!r}; "
            f"expected one of: {supported}"
        ) from exc

    by_site = {binding.site_id: binding for binding in bindings}
    reservation_sites = DurableReservationSiteMap(db_path, by_site, trust)
    capacity_sites = {
        site_id: factories.capacity(
            binding.authority_url, signer, trust.site_authorities(site_id)
        )
        for site_id, binding in by_site.items()
    }
    fulfillment_sites = {
        site_id: factories.fulfillment(
            binding.authority_url, signer, trust.site_authorities(site_id)
        )
        for site_id, binding in by_site.items()
    }
    capacity_client = AggregateCapacityClient(
        capacity_sites,
        placement=placement_policy,
        reservation_sites=reservation_sites,
    )
    return (
        capacity_client,
        SelectedSiteFulfillmentClient(
            fulfillment_sites,
            reservation_sites,
        ),
    )
