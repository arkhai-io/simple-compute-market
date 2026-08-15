"""Trusted multi-site capacity and fulfillment client construction."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from compute_provisioning import (
    ComputeProvisioningClient,
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    FulfillmentScheduleResponse,
    FulfillmentStatusResponse,
)

from core_storefront.aggregation import (
    PLACEMENT_POLICIES,
    AggregateCapacityClient,
)
from market_identity import Identity, Signer, TrustedIdentitySet
from market_site_client import SiteCapacityClient

_SITE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_BINDING_FIELDS = frozenset({"site_id", "authority_url", "authority_principal"})


@dataclass(frozen=True, slots=True)
class BareMetalSiteBinding:
    """One public site identity bound to one exact signed authority."""

    site_id: str
    authority_principal: Identity
    authority_url: str = field(repr=False)

    def diagnostic(self) -> dict[str, Any]:
        """Return only public identity data; routing URLs stay private."""
        return {
            "site_id": self.site_id,
            "authority_principal": self.authority_principal.model_dump(mode="json"),
        }


def _authority_url(value: Any, *, site_id: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"site {site_id!r} authority_url must be a string")
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"site {site_id!r} authority_url must be an HTTP(S) origin "
            "without credentials, query, or fragment"
        )
    return value.strip().rstrip("/")


def parse_site_bindings(raw_json: str) -> tuple[BareMetalSiteBinding, ...]:
    """Parse exact site bindings without ever returning raw configuration."""
    try:
        raw = json.loads(raw_json)
    except Exception as exc:
        raise ValueError("trusted site bindings must be valid JSON") from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError("trusted site bindings must be a non-empty JSON list")

    bindings: list[BareMetalSiteBinding] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"trusted site binding {index} must be an object")
        unknown = sorted(set(item) - _BINDING_FIELDS)
        missing = sorted(_BINDING_FIELDS - set(item))
        if unknown or missing:
            raise ValueError(
                f"trusted site binding {index} has invalid fields; "
                f"missing={missing}, unknown={unknown}"
            )
        site_id = item["site_id"]
        if not isinstance(site_id, str) or _SITE_ID.fullmatch(site_id) is None:
            raise ValueError(
                f"trusted site binding {index} has an invalid site_id"
            )
        if site_id in seen:
            raise ValueError(f"duplicate trusted site_id {site_id!r}")
        try:
            authority_principal = Identity.model_validate(
                item["authority_principal"]
            )
        except Exception as exc:
            raise ValueError(
                f"site {site_id!r} has an invalid authority principal"
            ) from exc
        bindings.append(
            BareMetalSiteBinding(
                site_id=site_id,
                authority_url=_authority_url(
                    item["authority_url"],
                    site_id=site_id,
                ),
                authority_principal=authority_principal,
            )
        )
        seen.add(site_id)
    return tuple(bindings)


class DurableReservationSiteMap(dict[str, str]):
    """Reservation-to-site cache whose exact authority binding survives restart."""

    def __init__(
        self,
        db_path: str,
        bindings: Mapping[str, BareMetalSiteBinding],
    ) -> None:
        self._db_path = db_path
        self._bindings = dict(bindings)
        loaded: dict[str, str] = {}
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT capacity_reservation_id, site_id, authority_scheme, "
                "authority_identifier FROM bare_metal_selected_site_bindings"
            ).fetchall()
        finally:
            conn.close()
        for reservation_id, site_id, scheme, identifier in rows:
            binding = self._bindings.get(str(site_id))
            if binding is None:
                raise RuntimeError(
                    "persisted bare-metal reservation references an unconfigured "
                    f"site_id {site_id!r}"
                )
            principal = binding.authority_principal
            if (
                principal.scheme.value != str(scheme)
                or principal.identifier != str(identifier)
            ):
                raise RuntimeError(
                    "persisted bare-metal reservation site authority changed for "
                    f"site_id {site_id!r}"
                )
            loaded[str(reservation_id)] = str(site_id)
        super().__init__(loaded)

    def __setitem__(self, reservation_id: str, site_id: str) -> None:
        binding = self._bindings.get(site_id)
        if binding is None:
            raise KeyError(f"unknown trusted site_id {site_id!r}")
        reservation_id = str(reservation_id)
        conn = sqlite3.connect(self._db_path)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO bare_metal_selected_site_bindings(
                      capacity_reservation_id, site_id,
                      authority_scheme, authority_identifier
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        reservation_id,
                        site_id,
                        binding.authority_principal.scheme.value,
                        binding.authority_principal.identifier,
                    ),
                )
                recorded = conn.execute(
                    "SELECT site_id, authority_scheme, authority_identifier "
                    "FROM bare_metal_selected_site_bindings "
                    "WHERE capacity_reservation_id = ?",
                    (reservation_id,),
                ).fetchone()
                expected = (
                    site_id,
                    binding.authority_principal.scheme.value,
                    binding.authority_principal.identifier,
                )
                if recorded != expected:
                    raise RuntimeError(
                        "capacity reservation conflicts with its persisted "
                        "trusted site authority binding"
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


def build_trusted_site_clients(
    *,
    bindings: tuple[BareMetalSiteBinding, ...],
    signer: Signer,
    db_path: str,
    placement: str,
) -> tuple[
    AggregateCapacityClient,
    SelectedSiteFulfillmentClient,
]:
    """Construct exact per-site clients and a shared durable route map."""
    try:
        placement_policy = PLACEMENT_POLICIES[placement]
    except KeyError as exc:
        supported = ", ".join(sorted(PLACEMENT_POLICIES))
        raise ValueError(
            f"unsupported bare-metal site placement {placement!r}; "
            f"expected one of: {supported}"
        ) from exc

    by_site = {binding.site_id: binding for binding in bindings}
    reservation_sites = DurableReservationSiteMap(db_path, by_site)
    capacity_sites = {
        site_id: SiteCapacityClient(
            binding.authority_url,
            signer,
            TrustedIdentitySet(identities=(binding.authority_principal,)),
        )
        for site_id, binding in by_site.items()
    }
    fulfillment_sites = {
        site_id: ComputeProvisioningClient(
            binding.authority_url,
            signer=signer,
            caller_role="seller",
            expected_authorities=TrustedIdentitySet(
                identities=(binding.authority_principal,)
            ),
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
