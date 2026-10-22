"""The configured seed listing, created by the ``listing-seed`` loop step.

A ``[seed]`` table names one quota resource for the storefront to register in
the credits service's ledger and publish a listing from, so a fresh deployment
has something to discover without an out-of-band step. Production operators
omit it and publish through the API or the CLI.

The seed is never created during startup. Each cycle of the step tries once,
and the outcome decides what the next does:

- **waiting** while a dependency has not answered: the credits service could
  not be reached for the quota registration or for the reads the create makes
  of the resource's availability and pool, or a mechanism the seed uses is
  unknown, unready only for reachability (its chain not yet probed, say). A
  listing's options are fixed when it is created, so the seed waits for every
  mechanism it uses rather than publishing without one. Nothing is logged at
  error level; the next cycle tries again.
- **given up** on any other failure, which waiting does not repair: the ledger
  refused the registration, the seed names a chain the storefront does not
  configure, or the create was refused for its configuration, nothing being
  publishable. A mechanism unready for its configuration beside a ready one
  does not stop the seed, which publishes without it, as any create does. The
  cycle that gives up fails, so the loop controller records and logs it once;
  later cycles do nothing.
- **done** once a listing derives from the seed's resource, whether this step
  created it or found it.

A cycle's report names why the seed waits or gave up by a reason code and an
error type, never an error's text, which may carry a dependency's address.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

import httpx
from market_alkahest.alkahest import get_erc20_escrow_obligation_default
from market_identity import Signer
from market_site_client import (
    SiteCapacityAdminClient,
    SiteCapacityAdminClientError,
    SiteCapacityClientError,
)

from apicredits_storefront.services.capacity_client import configured_sites
from apicredits_storefront.services.listing_service import SettlementMechanismUnreachable
from apicredits_storefront.utils.config import CHAINS, settings

logger = logging.getLogger(__name__)

LISTING_SEED = "listing_seed"
LISTING_SEED_ROUTE = "listing-seed"

PENDING = "pending"
WAITING = "waiting"
GIVEN_UP = "given_up"
DONE = "done"

#: Why a seed waits: the credits service did not answer.
CREDITS_SERVICE_UNANSWERED = "credits_service_unanswered"
#: Why a seed waits: a mechanism it uses is unknown; the report names which.
SETTLEMENT_MECHANISM_UNREACHED = "settlement_mechanism_unreached"

# The quota resource belongs to the credits authority's system-created default
# pool; a declaration must name its pool explicitly.
_QUOTA_POOL_ID = "default"


class ListingSeedGivenUp(Exception):
    """The cycle in which the seed gave up; its message is the error's type."""


class _Waiting(Exception):
    """A dependency the seed needs has not answered; the next cycle retries."""

    def __init__(self, reason: str, *, mechanisms: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.mechanisms = mechanisms


def _unreachable(exc: SiteCapacityClientError) -> bool:
    """Whether a site-client failure is the authority not answering, rather
    than refusing: no response at all, or a server error."""
    return exc.status_code is None or exc.status_code >= 500


def capacity_authority_site() -> Any:
    """The explicitly pinned site the seed's quota is registered at."""
    sites = configured_sites()
    selected = str(settings.get("capacity.seed_site", "") or "")
    if selected:
        try:
            return sites[selected]
        except KeyError as exc:
            raise RuntimeError(f"unknown capacity.seed_site {selected!r}") from exc
    if len(sites) != 1:
        raise RuntimeError("capacity.seed_site is required with multiple sites")
    return next(iter(sites.values()))


async def register_seed_quota(
    *,
    resource_id: str,
    total_units: int,
    site: Any,
    signer: Signer,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Register the seed's quota resource in the credits-service ledger at ``site``.

    The ledger is the credits service's; the storefront is a client, so
    registration goes through the typed capacity-administration client, signed
    by ``signer`` and over ``transport`` when one is given. A re-registration
    re-asserts the resource. Raises the client's error, which says whether the
    ledger refused or did not answer.
    """
    admin_client = SiteCapacityAdminClient(
        site.url,
        signer=signer,
        expected_authorities=site.expected_authorities,
        timeout=30.0,
        transport=transport,
        max_timestamp_skew=300,
    )
    await admin_client.register_resource(
        resource_id,
        pool_id=_QUOTA_POOL_ID,
        capacity={"units": total_units},
        resource_type="api_credits",
    )


async def _register_at_configured_site(
    signer: Signer,
    *,
    resource_id: str,
    total_units: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """``register_seed_quota`` at the configured site, signed by ``signer``.

    The site is resolved when the seed registers, so a site the configuration
    cannot name gives the seed up rather than stopping startup.
    """
    await register_seed_quota(
        resource_id=resource_id,
        total_units=total_units,
        site=capacity_authority_site(),
        signer=signer,
        transport=transport,
    )


_LISTING_PAGE = 500


async def _listing_for(db: Any, resource_id: str) -> str | None:
    """The open listing in ``db`` that derives from ``resource_id``, if any.

    Every open listing is read, page by page: a seeded listing missed here is
    one the seed would create a second time.
    """
    offset = 0
    while True:
        rows = await db.list_listings(status="open", limit=_LISTING_PAGE, offset=offset) or []
        for row in rows:
            listing_resource = row.get("listing_resource") or {}
            if isinstance(listing_resource, str):
                try:
                    listing_resource = json.loads(listing_resource)
                except (ValueError, TypeError):
                    listing_resource = {}
            if (
                isinstance(listing_resource, dict)
                and listing_resource.get("resource_id") == resource_id
            ):
                return str(row.get("listing_id"))
        if len(rows) < _LISTING_PAGE:
            return None
        offset += _LISTING_PAGE


def _seed_escrows(seed: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The Alkahest escrow the seed offers, on its configured chain."""
    chain = str(seed.get("chain", "anvil"))
    chain_cfg = CHAINS.get(chain)
    if chain_cfg is None:
        raise RuntimeError(f"seed chain {chain!r} is not configured")
    escrow_address = seed.get("escrow_address") or get_erc20_escrow_obligation_default(
        chain, config_path=chain_cfg.alkahest_address_config_path
    )
    return [
        {
            "chain_name": chain,
            "escrow_address": str(escrow_address).lower(),
            "literal_fields": {"token": str(seed["token"])},
            "rates": [
                {
                    "field": "amount",
                    "per": "token",
                    "value": str(seed.get("price_per_token", "1")),
                }
            ],
        }
    ]


@dataclass
class ListingSeed:
    """The seed's progress across the step's cycles.

    ``register_quota``, ``find_listing``, and ``listing_service`` are the
    boundaries the seed acts through: the credits service's ledger, the
    storefront's own listings, and the service that creates a listing.
    """

    seed: Mapping[str, Any]
    register_quota: Callable[..., Awaitable[None]]
    find_listing: Callable[[str], Awaitable[str | None]]
    listing_service: Any
    state: str = PENDING
    reason: str | None = None
    mechanisms: tuple[str, ...] = ()
    listing_id: str | None = None
    attempts: int = 0
    # The ledger re-asserts a registration, so once it has answered there is
    # nothing to send again while the seed waits on a mechanism.
    registered: bool = False

    @property
    def resource_id(self) -> str:
        return str(self.seed["resource_id"])

    def report(self) -> dict[str, Any]:
        return {
            "loop": LISTING_SEED,
            "state": self.state,
            "reason": self.reason,
            "mechanisms": list(self.mechanisms),
            "listing_id": self.listing_id,
            "attempts": self.attempts,
        }

    async def step(self) -> dict[str, Any]:
        """One attempt, unless the seed is done or given up.

        Raises ``ListingSeedGivenUp`` from the cycle that gives up.
        """
        if self.state in (DONE, GIVEN_UP):
            return self.report()
        self.attempts += 1
        try:
            await self._attempt()
        except _Waiting as waiting:
            if (self.state, self.reason, self.mechanisms) != (
                WAITING,
                waiting.reason,
                waiting.mechanisms,
            ):
                logger.info(
                    "[SEED] listing seed for %s waiting: %s %s",
                    self.resource_id,
                    waiting.reason,
                    ",".join(waiting.mechanisms),
                )
            self.state, self.reason, self.mechanisms = (
                WAITING,
                waiting.reason,
                waiting.mechanisms,
            )
        except Exception as exc:
            self.state, self.reason, self.mechanisms = GIVEN_UP, type(exc).__name__, ()
            raise ListingSeedGivenUp(self.reason) from exc
        return self.report()

    async def _attempt(self) -> None:
        existing = await self.find_listing(self.resource_id)
        if existing is not None:
            self.state, self.reason, self.mechanisms = DONE, None, ()
            self.listing_id = existing
            logger.info("[SEED] listing %s already derives from %s", existing, self.resource_id)
            return
        if not self.registered:
            try:
                await self.register_quota(
                    resource_id=self.resource_id,
                    total_units=int(self.seed.get("total_units", 100)),
                )
            except SiteCapacityAdminClientError as exc:
                if _unreachable(exc):
                    raise _Waiting(CREDITS_SERVICE_UNANSWERED) from exc
                raise
            self.registered = True
        try:
            result = await self.listing_service.publish_from_quota(
                resource_id=self.resource_id,
                service_name=str(self.seed.get("service_name", "service")),
                accepted_escrows=_seed_escrows(self.seed),
                description=self.seed.get("description"),
                openapi_url=self.seed.get("openapi_url"),
                base_url=self.seed.get("base_url"),
                wait_for_every_mechanism=True,
            )
        except SettlementMechanismUnreachable as exc:
            raise _Waiting(
                SETTLEMENT_MECHANISM_UNREACHED, mechanisms=exc.mechanisms
            ) from exc
        except SiteCapacityClientError as exc:
            if _unreachable(exc):
                raise _Waiting(CREDITS_SERVICE_UNANSWERED) from exc
            raise
        self.state, self.reason, self.mechanisms = DONE, None, ()
        self.listing_id = str(result.get("listing_id"))
        logger.info(
            "[SEED] published listing %s (registry=%s)",
            self.listing_id,
            result.get("registry_status"),
        )


def configured_listing_seed(
    *, listing_service: Any, signer: Signer, db: Any
) -> ListingSeed | None:
    """The seed the configuration states, or ``None`` without a ``[seed]`` table.

    It registers its quota signed by ``signer``, looks for its listing in
    ``db``, and creates it through ``listing_service``.
    """
    seed = settings.get("seed")
    if not isinstance(seed, Mapping) or not seed.get("resource_id"):
        return None
    return ListingSeed(
        seed=dict(seed),
        register_quota=partial(_register_at_configured_site, signer),
        find_listing=partial(_listing_for, db),
        listing_service=listing_service,
    )


__all__ = [
    "CREDITS_SERVICE_UNANSWERED",
    "DONE",
    "GIVEN_UP",
    "LISTING_SEED",
    "LISTING_SEED_ROUTE",
    "PENDING",
    "SETTLEMENT_MECHANISM_UNREACHED",
    "WAITING",
    "ListingSeed",
    "ListingSeedGivenUp",
    "capacity_authority_site",
    "configured_listing_seed",
    "register_seed_quota",
]
