"""A quota-backed storefront's capacity: its configured sites and the one runtime over them."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from core_storefront.aggregation import PLACEMENT_POLICIES, AggregateCapacityClient
from market_capacity_publication import (
    CapacityReconcileContext,
    CapacityRuntime,
    CapacitySite as KitCapacitySite,
)
from market_identity import Identity, Signer, TrustedIdentitySet

SQLiteClientFactory = Callable[[], Any]
Reconcile = Callable[[CapacityReconcileContext], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CapacitySite:
    url: str
    expected_authorities: TrustedIdentitySet


def read_capacity_sites(
    raw_sites: Any, raw_placement: Any
) -> tuple[dict[str, CapacitySite], str]:
    """Each configured site's URL and trusted authorities, and the placement; refused by key, never by value."""
    placement = str(raw_placement or "fill_first").strip()
    if not raw_sites or not hasattr(raw_sites, "items"):
        raise RuntimeError("[capacity.sites] must define explicit trusted site IDs")
    sites: dict[str, CapacitySite] = {}
    for raw_name, raw_site in dict(raw_sites).items():
        site_id = str(raw_name).strip()
        values = dict(raw_site) if hasattr(raw_site, "items") else {}
        url = str(values.get("url") or "").strip().rstrip("/")
        raw_authorities = dict(values.get("expected_authorities") or {})
        identities = raw_authorities.get("identities")
        if not site_id or not url or not isinstance(identities, (list, tuple)):
            raise RuntimeError(f"capacity site {site_id!r} is incomplete")
        try:
            trusted = TrustedIdentitySet(
                identities=tuple(Identity.model_validate(value) for value in identities)
            )
        except (TypeError, ValueError):
            trusted = None
        if trusted is None:
            # Raised outside the handler: a validation error keeps the value it refused.
            raise RuntimeError(
                f"[capacity.sites.{site_id}.expected_authorities] must list one or two "
                "valid principals"
            )
        sites[site_id] = CapacitySite(url, trusted)
    return sites, placement


class QuotaCapacity:
    """The storefront's one capacity runtime, rebuilt only when its sites, signer, placement, or database change."""

    def __init__(
        self,
        *,
        sites: Callable[[], tuple[Mapping[str, CapacitySite], str]],
        signer: Callable[[], Signer | None],
        reconciler: Callable[[SQLiteClientFactory], Reconcile],
    ) -> None:
        self._sites = sites
        self._signer = signer
        self._reconciler = reconciler
        self._key: Any = None
        self._runtime: CapacityRuntime | None = None

    def configured_site_ids(self) -> tuple[str, ...]:
        """The configured sites' IDs, in configuration order."""
        return tuple(self._sites()[0])

    def runtime(self, sqlite_client_factory: SQLiteClientFactory) -> CapacityRuntime:
        signer = self._signer()
        if signer is None:
            raise RuntimeError("marketplace signer must be resolved before capacity runtime")
        sites, placement_name = self._sites()
        placement = PLACEMENT_POLICIES.get(placement_name)
        if placement is None:
            raise RuntimeError(f"unknown capacity placement policy {placement_name!r}")
        key = (
            tuple((name, site.url, repr(site.expected_authorities)) for name, site in sites.items()),
            repr(signer.identity),
            placement_name,
            str(getattr(sqlite_client_factory(), "db_path", "")),
        )
        if self._key != key or self._runtime is None:
            self._key = key
            self._runtime = CapacityRuntime(
                sites=tuple(
                    KitCapacitySite(name, site.url, site.expected_authorities)
                    for name, site in sites.items()
                ),
                signer=signer,
                placement=placement,
                reconcile=self._reconciler(sqlite_client_factory),
            )
        return self._runtime

    def client(self, sqlite_client_factory: SQLiteClientFactory) -> AggregateCapacityClient:
        return self.runtime(sqlite_client_factory).client()
