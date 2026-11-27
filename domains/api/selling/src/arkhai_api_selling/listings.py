"""Creating and publishing a listing over a quota resource, as the domain's mapping of an operator's request."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from core_storefront.sqlite_client import store_timestamp
from market_core import MarketDomainContract
from market_core.schemas import settlement_option_schema
from market_identity import Identity
from market_settlement_runtime import MechanismReadiness

from arkhai_api_selling.capacity import QuotaCapacity
from arkhai_api_selling.contributions import QuotaSource, SellingContributions
from arkhai_api_selling.issuance import issuance_subject
from arkhai_api_selling.publication import publication_refusal
from arkhai_api_selling.quota_listing import QuotaPool, prepare_listing_binding, quota_pool

logger = logging.getLogger(__name__)

ReleaseConditions = Callable[..., list[dict[str, Any]]]
"""The release conditions a listing advertising accepted escrows publishes, given
the ``readiness`` they were published under."""


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


def _ready(readiness: Sequence[MechanismReadiness], mechanism: str | None) -> bool:
    """Whether ``readiness`` reports ``mechanism`` ready."""
    return any(status.mechanism == mechanism and status.ready for status in readiness)


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


def _admitted(pool: QuotaPool, stages: Mapping[str, Any], mechanism: str) -> bool:
    """Whether the pool's backing lets a listing publish ``mechanism``'s options."""
    _, dropped = pool.declaration.backing.admissible_settlement(
        (mechanism,),
        mechanism=str,
        fulfils_through_capacity=lambda name: stages[name].fulfils_through_capacity,
    )
    return not dropped


def admissible_settlement_terms(
    pool: QuotaPool,
    stages: Mapping[str, Any],
    *,
    accepted_escrows: list[dict[str, Any]],
    settlement_options: list[dict[str, Any]],
    escrow_mechanism: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The settlement terms the pool's backing lets a listing publish.

    Without an admission authority, a stage that issues against quota would take funds
    for credits that cannot be reserved, so its terms are dropped.
    """
    backing = pool.declaration.backing

    def fulfils_through_capacity(mechanism: str) -> bool:
        return stages[mechanism].fulfils_through_capacity

    kept_options, dropped = backing.admissible_settlement(
        settlement_options,
        mechanism=lambda option: str(settlement_option_schema(option)),
        fulfils_through_capacity=fulfils_through_capacity,
    )
    if accepted_escrows:
        if escrow_mechanism is None:
            raise ValueError("this storefront publishes no accepted escrows")
        _, escrow_dropped = backing.admissible_settlement(
            (escrow_mechanism,),
            mechanism=str,
            fulfils_through_capacity=fulfils_through_capacity,
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
        contributions: SellingContributions,
        *,
        sqlite_client: Any,
        seller_principal: Identity,
        settlement_composition: Any,
        domain: MarketDomainContract,
        capacity: QuotaCapacity,
        publish: Callable[[Mapping[str, Any]], Awaitable[dict[str, Any]]],
        close: Callable[[str], Awaitable[dict[str, Any]]],
        settlement_defaults: Callable[[], Sequence[Mapping[str, Any]]],
        storefront_url: str | None,
        stage_event: Callable[..., Any],
        escrow_mechanism: str | None = None,
        release_conditions: ReleaseConditions | None = None,
    ) -> None:
        self._contributions = contributions
        self._stage_event = stage_event
        self._db = sqlite_client
        self._seller_principal = seller_principal
        self._settlement_composition = settlement_composition
        self._domain = domain
        self._capacity = capacity
        self._publish = publish
        self._close = close
        self._settlement_defaults = settlement_defaults
        self._storefront_url = storefront_url
        self._escrow_mechanism = escrow_mechanism
        self._release_conditions = release_conditions

    async def publish_from_quota(
        self,
        *,
        resource_id: str,
        accepted_escrows: list[dict[str, Any]],
        settlement_clauses: list[dict[str, Any]] | None = None,
        paused: bool = False,
        wait_for_every_mechanism: bool = False,
        **request: Any,
    ) -> dict[str, Any]:
        """Create and publish a listing over ``resource_id``; ``request`` is what the domain's mapping reads.

        The resource must exist in the quota ledger with sellable units, and its
        pool's declared backing decides which settlement options the listing may
        publish. A listing's options are fixed when it is created. A create that
        publishes no option only because a mechanism it uses is unknown raises
        ``SettlementMechanismUnreachable``; with ``wait_for_every_mechanism``
        it raises whenever any mechanism it uses is unknown, so a caller that
        can retry, as the seed does, never fixes a listing without one. Either
        is raised only once the resource and its pool have been read, and only
        for a mechanism the pool's backing lets the listing publish, so a create
        refused as retryable is one that publishes once the mechanism answers.
        """
        if accepted_escrows and self._escrow_mechanism is None:
            raise ValueError("this storefront publishes no accepted escrows")
        clauses = (
            tuple(self._settlement_defaults())
            if settlement_clauses is None
            else tuple(settlement_clauses)
        )
        configured_escrows, settlement_options, readiness = (
            await self._settlement_composition.publication_artifacts(
                {
                    "claimant_principal": self._seller_principal,
                    "resource_id": resource_id,
                },
                list(clauses) if clauses else None,
            )
            if clauses or not accepted_escrows
            else ([], [], ())
        )
        # Escrows the request supplies are the escrow mechanism's options, so
        # they publish only while it is ready on their own chains, as the
        # escrows the clauses compile do on theirs.
        escrow_readiness = (
            await self._settlement_composition.readiness(
                accepted_escrows=accepted_escrows
            )
            if accepted_escrows
            else ()
        )

        capacity = self._capacity.runtime(lambda: self._db)
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
        pool = quota_pool(
            self._contributions, projection["resource_pools"], resource_id=resource_id
        )

        # Each mechanism the request uses and the pool's backing admits, judged
        # where it is used: a clause's mechanism on the clauses' readiness, the
        # supplied escrows' mechanism on the readiness of their own chains.
        stages = self._settlement_composition.stages
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
                *(s for s in escrow_readiness if s.mechanism == self._escrow_mechanism),
            )
            if _admitted(pool, stages, status.mechanism)
        )
        named_chains = {
            mechanism: tuple(dict.fromkeys(names))
            for mechanism, names in clause_chains.items()
        }
        if accepted_escrows and self._escrow_mechanism is not None:
            named_chains[self._escrow_mechanism] = tuple(
                dict.fromkeys(
                    [
                        *named_chains.get(self._escrow_mechanism, ()),
                        *(str(escrow.get("chain_name")) for escrow in accepted_escrows),
                    ]
                )
            )
        if wait_for_every_mechanism:
            unknown = _unreached_mechanisms(used, every=False)
            if unknown:
                raise SettlementMechanismUnreachable(unknown, chains=named_chains)
        if accepted_escrows and not _ready(escrow_readiness, self._escrow_mechanism):
            accepted_escrows = []
        accepted_escrows = [*accepted_escrows, *configured_escrows]
        # Every escrow left was published under a ready escrow mechanism, judged
        # on its own chains, so either readiness may stand for it below.
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
        accepted_escrows, settlement_options = admissible_settlement_terms(
            pool,
            stages,
            accepted_escrows=accepted_escrows,
            settlement_options=settlement_options,
            escrow_mechanism=self._escrow_mechanism,
        )
        demands = (
            self._release_conditions(accepted_escrows, readiness=readiness)
            if accepted_escrows and self._release_conditions is not None
            else []
        )

        listing = self._domain.codecs.listing(
            {
                "listing_resource": self._contributions.publication_mapping(
                    request,
                    QuotaSource(
                        site_id=capacity_site_id,
                        resource_id=resource_id,
                        offering_mode=self._contributions.offering_mode,
                    ),
                ),
                "accepted_escrows": accepted_escrows,
                "settlement_options": settlement_options,
                "demands": demands,
            }
        )
        listing_resource = listing.listing_resource.model_dump(mode="json")
        reason = publication_refusal(self._contributions, listing_resource)
        if reason is not None:
            raise ValueError(reason)
        listing_id = str(uuid.uuid4())
        binding = prepare_listing_binding(
            self._contributions,
            listing_id=listing_id,
            site_id=capacity_site_id,
            listing_resource=listing_resource,
            pool=pool,
            domain=self._domain,
        )
        now_iso = store_timestamp()
        await self._db.upsert_listing_with_binding(
            binding=binding,
            status="open",
            created_at=now_iso,
            updated_at=now_iso,
            listing_resource=listing_resource,
            accepted_escrows=listing.accepted_escrows,
            settlement_options=[
                option.model_dump(mode="json") for option in listing.settlement_options
            ],
            demands=listing.demands,
            fulfillment_resource=None,
            max_duration_seconds=None,
            storefront_url=self._storefront_url,
            seller_principal=self._seller_principal,
            oracle_address=None,
            paused=paused,
        )
        self._stage_event(
            "discovery",
            "token_listing_created",
            listing_id=listing_id,
            resource_id=resource_id,
            service_name=issuance_subject(
                self._contributions, listing_resource, listing_id=listing_id
            ).service,
            available_units=available,
        )
        if paused:
            return {"status": "created", "listing_id": listing_id}

        row = await self._db.load_listing(listing_id=listing_id)
        publish_result = await self._publish(row or {})
        return {
            "status": "created",
            "listing_id": listing_id,
            "registry_status": publish_result.get("status"),
        }

    async def close_listing(self, listing_id: str) -> dict[str, Any]:
        result = await self._close(listing_id)
        return {
            "status": result.get("status", "closed"),
            "listing_id": listing_id,
        }
