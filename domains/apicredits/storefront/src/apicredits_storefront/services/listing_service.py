"""ListingService — quota-backed listing lifecycle.

A credit listing derives from a quota resource in the credits service's
ledger (ARCHITECTURE.md, "API-credits market domain — Market shape"): ``publish_from_quota``
reads the resource's availability, writes the local listing row with an
``api_credits.v1`` listing_resource naming that resource, and fans out to the
registries. Closing goes through the shared publication path.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from core_storefront.stage_log import stage_event
from market_alkahest import ALKAHEST_MECHANISM_ID
from market_identity import Identity
from market_settlement_runtime import MechanismReadiness

from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.listing_binding import (
    QuotaPool,
    prepare_api_credit_listing_binding,
    quota_pool,
)
from apicredits_storefront.services import capacity_client
from apicredits_storefront.settlement_composition import SELLER_STAGES, alkahest_ready
from apicredits_storefront.utils.config import (
    BASE_URL_OVERRIDE,
    settlement_publication_defaults,
)

logger = logging.getLogger(__name__)


class SettlementMechanismUnreachable(Exception):
    """A create refused because a mechanism it uses has unknown readiness.

    ``mechanisms`` are unready only for reachability: a dependency each needs
    did not answer, or has not been probed yet. Raised for a create that
    publishes nothing, when every unready mechanism it uses is one of these,
    or, for a caller that waits for every mechanism, whenever any is. Either
    way the resource and its pool were read first, so the same create can be
    retried once the mechanisms are reached. ``chains`` names the chains the
    request uses each mechanism on, where it names any; a mechanism's readiness
    covers all of them, so it cannot say which one was not reached.
    """

    def __init__(
        self,
        mechanisms: tuple[str, ...],
        *,
        chains: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.mechanisms = mechanisms
        self.chains = {
            mechanism: tuple(chains.get(mechanism, ()))
            for mechanism in mechanisms
            if chains and chains.get(mechanism)
        }
        named = ", ".join(
            f"{mechanism} (chain {', '.join(self.chains[mechanism])})"
            if mechanism in self.chains
            else mechanism
            for mechanism in mechanisms
        )
        super().__init__(
            f"settlement mechanism {named} cannot be reached yet; "
            "retry the create once it is"
        )


def _clause_name(clause: Any) -> str:
    if isinstance(clause, Mapping):
        return str(clause.get("mechanism") or "")
    return str(getattr(clause, "mechanism", "") or "")


def _clause_chain(clause: Any) -> str | None:
    mechanism_input = (
        clause.get("mechanism_input")
        if isinstance(clause, Mapping)
        else getattr(clause, "mechanism_input", None)
    )
    chain = mechanism_input.get("chain") if isinstance(mechanism_input, Mapping) else None
    return chain if isinstance(chain, str) and chain else None


def _unknown(status: MechanismReadiness) -> bool:
    """Whether an enabled mechanism's readiness could not be determined: it is
    unready, and every blocker it reports is a reachability blocker."""
    return (
        status.enabled
        and not status.ready
        and bool(status.blockers)
        and all(blocker.kind == "reachability" for blocker in status.blockers)
    )


def _unreached_mechanisms(
    used: tuple[MechanismReadiness, ...], *, every: bool
) -> tuple[str, ...]:
    """The unknown mechanisms among ``used``, each the readiness of a mechanism
    the request uses. With ``every``, none unless every unready one is unknown:
    a mechanism unready for its configuration makes the refusal a configuration
    one."""
    unready = [status for status in used if status.enabled and not status.ready]
    unknown = [status for status in unready if _unknown(status)]
    if not unknown or (every and len(unknown) != len(unready)):
        return ()
    return tuple(sorted({status.mechanism for status in unknown}))


def _fulfils_through_capacity(mechanism: str) -> bool:
    return SELLER_STAGES[mechanism].fulfils_through_capacity


def _admitted(pool: QuotaPool, mechanism: str) -> bool:
    """Whether the pool's backing lets a listing publish ``mechanism``'s options."""
    _, dropped = pool.declaration.backing.admissible_settlement(
        (mechanism,), mechanism=str, fulfils_through_capacity=_fulfils_through_capacity
    )
    return not dropped


def _admissible_settlement_terms(
    pool: QuotaPool,
    *,
    accepted_escrows: list[dict[str, Any]],
    settlement_options: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep only the settlement terms the pool's backing lets a listing publish.

    Each seller stage declares whether settling through it issues against
    quota; where no admission authority stands behind the pool, such a stage
    would take a buyer's funds for credits that cannot be reserved, so its
    terms are dropped, and a listing left with none is refused.
    """
    backing = pool.declaration.backing
    kept_options, dropped = backing.admissible_settlement(
        settlement_options,
        mechanism=lambda option: str(option.get("mechanism")),
        fulfils_through_capacity=_fulfils_through_capacity,
    )
    if accepted_escrows:
        # Accepted escrows are the Alkahest publication form.
        _, escrow_dropped = backing.admissible_settlement(
            (ALKAHEST_MECHANISM_ID,),
            mechanism=str,
            fulfils_through_capacity=_fulfils_through_capacity,
        )
        if escrow_dropped:
            accepted_escrows = []
            dropped = (*dropped, *escrow_dropped)
    if not kept_options and not accepted_escrows:
        raise ValueError(
            f"pool {pool.pool_id!r} leaves no settlement option its "
            f"{backing.label} listings may publish"
            + (f" (dropped: {', '.join(dict.fromkeys(dropped))})" if dropped else "")
        )
    return accepted_escrows, list(kept_options)


class ListingService:
    def __init__(
        self,
        *,
        sqlite_client,
        seller_principal: Identity,
        settlement_composition,
    ) -> None:
        self._db = sqlite_client
        self._seller_principal = seller_principal
        self._settlement_composition = settlement_composition

    async def publish_from_quota(
        self,
        *,
        resource_id: str,
        service_name: str,
        accepted_escrows: list[dict[str, Any]],
        settlement_clauses: list[dict[str, Any]] | None = None,
        description: str | None = None,
        openapi_url: str | None = None,
        base_url: str | None = None,
        paused: bool = False,
        wait_for_every_mechanism: bool = False,
    ) -> dict[str, Any]:
        """Create + publish a listing backed by a quota resource.

        The resource must exist in the quota ledger with sellable units —
        the listing's lifetime is tied to it from here on (capacity
        deltas close it on exhaustion and reopen it on replenishment). Its
        pool's declared backing is recorded on the listing's binding and
        decides which settlement options the listing may publish.

        A listing's options are fixed when it is created. A create that
        publishes no option only because a mechanism it uses is unknown raises
        ``SettlementMechanismUnreachable``; with ``wait_for_every_mechanism``
        it raises whenever any mechanism it uses is unknown, so a caller that
        can retry, as the seed does, never fixes a listing without one. Either
        is raised only once the resource and its pool have been read, and only
        for a mechanism the pool's backing lets the listing publish, so a create
        refused as retryable is one that publishes once the mechanism answers.
        """
        clauses = (
            settlement_publication_defaults()
            if settlement_clauses is None
            else tuple(settlement_clauses)
        )
        configured_escrows, settlement_options, readiness = (
            await self._settlement_composition.publication_artifacts(
                {
                    "claimant_principal": self._seller_principal,
                    "resource_id": resource_id,
                    "service": service_name,
                },
                list(clauses) if clauses else None,
            )
            if clauses or not accepted_escrows
            else ([], [], ())
        )
        # Escrows the request supplies are Alkahest options, so they publish
        # only while Alkahest is ready on their own chains, as the escrows the
        # clauses compile do on theirs.
        escrow_readiness = (
            await self._settlement_composition.readiness(
                accepted_escrows=accepted_escrows
            )
            if accepted_escrows
            else ()
        )

        capacity = capacity_client.build_capacity_runtime(lambda: self._db)
        availability = await capacity.availability()
        matches = [
            (site_id, units)
            for (site_id, rid), units in availability.items()
            if rid == resource_id
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Quota resource {resource_id!r} must resolve to exactly one "
                f"trusted capacity site; found {len(matches)}."
            )
        capacity_site_id, available = matches[0]
        if available < 1:
            raise ValueError(
                f"Quota resource {resource_id!r} has no sellable units "
                f"(available={available})."
            )
        projection = await capacity.site_client(capacity_site_id).resource_pool_projection()
        pool = quota_pool(projection["resource_pools"], resource_id=resource_id)

        # Each mechanism the request uses and the pool's backing admits, judged
        # where it is used: a clause's mechanism on the clauses' readiness, the
        # supplied escrows' Alkahest on the readiness of their own chains.
        clause_chains: dict[str, list[str]] = {}
        for clause in clauses or ():
            mechanism = self._settlement_composition.canonical_mechanism(
                _clause_name(clause)
            )
            chain = _clause_chain(clause)
            clause_chains.setdefault(mechanism, [])
            if chain is not None:
                clause_chains[mechanism].append(chain)
        used = tuple(
            status
            for status in (
                *(s for s in readiness if s.mechanism in clause_chains),
                *(s for s in escrow_readiness if s.mechanism == ALKAHEST_MECHANISM_ID),
            )
            if _admitted(pool, status.mechanism)
        )
        named_chains = {
            mechanism: tuple(dict.fromkeys(names))
            for mechanism, names in clause_chains.items()
        }
        if accepted_escrows:
            named_chains[ALKAHEST_MECHANISM_ID] = tuple(
                dict.fromkeys(
                    [
                        *named_chains.get(ALKAHEST_MECHANISM_ID, ()),
                        *(str(escrow.get("chain_name")) for escrow in accepted_escrows),
                    ]
                )
            )
        if wait_for_every_mechanism:
            unknown = _unreached_mechanisms(used, every=False)
            if unknown:
                raise SettlementMechanismUnreachable(unknown, chains=named_chains)
        if accepted_escrows and not alkahest_ready(escrow_readiness):
            accepted_escrows = []
        accepted_escrows = [*accepted_escrows, *configured_escrows]
        # Every escrow left was published under a ready Alkahest, judged on its
        # own chains, so either readiness may stand for it below.
        readiness = (*readiness, *escrow_readiness)
        if not accepted_escrows and not settlement_options:
            unreached = _unreached_mechanisms(used, every=True)
            if unreached:
                raise SettlementMechanismUnreachable(unreached, chains=named_chains)
            blockers = list(
                dict.fromkeys(
                    blocker.code
                    for status in readiness
                    if status.enabled
                    for blocker in status.blockers
                )
            )
            suffix = f" ({', '.join(blockers)})" if blockers else ""
            raise ValueError(f"no settlement alternative is ready{suffix}")
        accepted_escrows, settlement_options = _admissible_settlement_terms(
            pool, accepted_escrows=accepted_escrows, settlement_options=settlement_options
        )
        demands = self._settlement_composition.release_conditions(
            accepted_escrows, readiness=readiness
        )

        listing = get_market_domain_contract().codecs.listing(
            {
                "listing_resource": {
                    "service_name": service_name,
                    "description": description,
                    "openapi_url": openapi_url,
                    "base_url": base_url,
                    "resource_id": resource_id,
                    "capacity_site_id": capacity_site_id,
                    "offering_mode": "api_credits",
                },
                "accepted_escrows": accepted_escrows,
                "settlement_options": settlement_options,
                "demands": demands,
            }
        )
        listing_id = str(uuid.uuid4())
        now_iso = datetime.now().isoformat()
        await self._db.upsert_listing_with_binding(
            binding=prepare_api_credit_listing_binding(
                listing_id=listing_id,
                site_id=capacity_site_id,
                resource_id=resource_id,
                pool=pool,
                domain=get_market_domain_contract(),
            ),
            status="open",
            created_at=now_iso,
            updated_at=now_iso,
            listing_resource=listing.listing_resource.model_dump(mode="json"),
            accepted_escrows=listing.accepted_escrows,
            settlement_options=[option.model_dump(mode="json") for option in listing.settlement_options],
            demands=listing.demands,
            fulfillment_resource=None,
            max_duration_seconds=None,
            storefront_url=BASE_URL_OVERRIDE,
            seller_principal=self._seller_principal,
            oracle_address=None,
            paused=paused,
        )
        stage_event(
            "discovery",
            "token_listing_created",
            listing_id=listing_id,
            resource_id=resource_id,
            service_name=service_name,
            available_units=available,
        )
        if paused:
            return {"status": "created", "listing_id": listing_id}

        row = await self._db.load_listing(listing_id=listing_id)
        publication = get_market_domain_contract().publication
        assert publication is not None and publication.publish is not None
        publish_result = await publication.publish(row or {})
        return {
            "status": "created",
            "listing_id": listing_id,
            "registry_status": publish_result.get("status"),
        }

    async def close_listing(self, listing_id: str) -> dict[str, Any]:
        from apicredits_storefront.services.publication_service import close_order

        result = await close_order({"listing_id": listing_id})
        return {
            "status": result.get("status", "closed"),
            "listing_id": listing_id,
        }
