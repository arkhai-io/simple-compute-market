"""The seller's Arkhai payments stage: charge-first settlement, its quota hold, and its reconciliation loop.

Receipt checks and reversal are the payments kit's; settlement, status, refund,
and reconciliation run through ``PaymentSettlementService``, which records state
in the family's evidence and issuance-progress tables rather than in escrow rows.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from arkhai_api.purchase import provision_quantity
from arkhai_api_selling.capacity import QuotaCapacity
from arkhai_api_selling.contributions import SellingContributions
from arkhai_api_selling.issuance import SettlementRefusal, SettleResult
from arkhai_api_selling.lifecycle import ContributedLoop
from arkhai_api_selling.quota_listing import listing_binding
from market_arkhai_payments import (
    ARKHAI_PAYMENTS_CONFIG_KEY,
    ARKHAI_PAYMENTS_MECHANISM,
    ClientForOwner,
    PaymentSellerStage,
    create_arkhai_payments_registration,
    servicing_stage,
)
from market_negotiation_runtime import OfferUnfulfillableError
from market_storefront_kit import LifecycleRouteError

from arkhai_api_selling_arkhai_payments.service import PaymentSettlementService
from arkhai_api_selling_arkhai_payments.validators import (
    validate_payer_account,
    validate_payment_publication_clause,
)

logger = logging.getLogger(__name__)

StageEventFn = Callable[..., Any]

PAYMENT_RECONCILIATION = "payment_reconciliation"


class ArkhaiPaymentsSellerStage:
    """The seller's Arkhai payments entry, over the collaborators its storefront injects.

    ``capacity`` and ``hold_ttl_seconds`` place the acceptance's quota hold;
    ``composition`` and ``sqlite_client`` are the storefront lifespan's
    settlement composition and persistence, which reconciliation reads.
    """

    mechanism = ARKHAI_PAYMENTS_MECHANISM
    registration = staticmethod(create_arkhai_payments_registration)
    # A payment deal settles from the Agreement's mandate and receipt, so its
    # exact selection is accepted without a settlement plan.
    settles_from_agreement = True

    def __init__(
        self,
        contributions: SellingContributions,
        *,
        fulfils_through_capacity: bool,
        capacity: QuotaCapacity,
        hold_ttl_seconds: Callable[[], float],
        composition: Callable[[], Any | None],
        sqlite_client: Callable[[], Any | None],
        reconciliation_interval: Callable[[], float],
        stage_event: StageEventFn,
        client_for_owner: ClientForOwner | None = None,
    ) -> None:
        self._contributions = contributions
        # Whether settling through this stage issues credits against quota.
        # Required, with no default, because publication drops such a stage's
        # options from a listing no admission authority backs.
        self.fulfils_through_capacity = fulfils_through_capacity
        self._capacity = capacity
        self._hold_ttl_seconds = hold_ttl_seconds
        self._composition = composition
        self._sqlite_client = sqlite_client
        self._reconciliation_interval = reconciliation_interval
        self._stage_event = stage_event
        self._client_for_owner = client_for_owner

    # Composition-time contributions.

    def servicing(self, settlement_config: Any) -> PaymentSellerStage | None:
        """The kit's servicing of accepted deals.

        It follows the section's servicing fields, not ``enabled``: accepted
        payment deals are serviced whether or not new options are published.
        """
        return servicing_stage(
            settlement_config.mechanism_config(ARKHAI_PAYMENTS_CONFIG_KEY),
            client_for_owner=self._client_for_owner,
        )

    def validate_configuration(self, settlement_config: Any) -> None:
        pass

    def service(self, db: Any, composition: Any) -> PaymentSettlementService | None:
        """The deal-scoped payment settlement service, or None when payments is not serviced."""
        servicing = (composition.servicing if composition is not None else {}).get(self.mechanism)
        if servicing is None:
            return None
        return PaymentSettlementService(
            db=db, composition=composition, stage=servicing, mechanism=self.mechanism
        )

    def contributed_loops(self) -> tuple[ContributedLoop, ...]:
        """Payment reconciliation, a loop only while payments is serviced."""
        if self._reconciling_service() is None:
            return ()
        return (
            ContributedLoop(
                PAYMENT_RECONCILIATION,
                route="payment-reconciliation",
                step=self.reconciliation_step,
                interval_seconds=self._reconciliation_interval(),
            ),
        )

    def startup_steps(self) -> tuple[Callable[[], Awaitable[None]], ...]:
        return ()

    def health_checks(self) -> dict[str, str]:
        return {}

    def _reconciling_service(self) -> PaymentSettlementService | None:
        composition = self._composition()
        if composition is None:
            return None
        db = self._sqlite_client()
        if db is None:
            raise LifecycleRouteError(503, "storefront persistence is not initialized")
        return self.service(db, composition)

    async def reconciliation_step(self) -> Mapping[str, Any]:
        service = self._reconciling_service()
        if service is None:
            return {"loop": PAYMENT_RECONCILIATION, "attempted": 0, "failed": 0}
        done = await service.reconcile_once()
        return {"loop": PAYMENT_RECONCILIATION, "attempted": done.attempted, "failed": done.failed}

    # The stage table's entry.

    def validate_selection(self, selection: Any) -> None:
        params = selection.params
        if not isinstance(params, Mapping) or set(params) != {"payer_account"}:
            raise OfferUnfulfillableError("payments_payer_account_missing")
        try:
            validate_payer_account(params["payer_account"])
        except ValueError as exc:
            raise OfferUnfulfillableError("payments_payer_account_invalid") from exc

    def agreement_artifacts(self, agreement: Mapping[str, Any], composition: Any) -> dict[str, Any]:
        servicing = composition.servicing.get(self.mechanism)
        if servicing is None:
            raise ValueError("Arkhai payments is not enabled")
        return servicing.settlement_data(agreement).to_wire()

    def readiness_resources(self, clauses: Any, resources: Mapping[str, Any]) -> dict[str, Any]:
        return {}

    def client(self, resources: Mapping[str, Any]) -> Any:
        return None

    def validate_publication(self, resources: Mapping[str, Any]) -> None:
        validate_payment_publication_clause(
            resources.get("publication_clause"), noun=self._contributions.refusal_noun
        )

    async def place_hold(self, repository: Any, acceptance: Any) -> None:
        quantity = provision_quantity(acceptance.terms.decoded)
        ttl = float(self._hold_ttl_seconds() or 0)
        if ttl <= 0 or not quantity:
            return
        try:
            binding = await listing_binding(repository, acceptance.listing_id)
            if binding is None:
                raise RuntimeError(f"{self._contributions.refusal_noun} listing has no durable binding")
            claim: dict[str, Any] = {
                "offering_mode": self._contributions.offering_mode,
                "units": int(quantity),
                "resource_id": binding.source_id,
            }
            capacity = self._capacity.runtime(lambda: repository)

            async def reserve() -> Any:
                return await capacity.reserve(
                    binding,
                    claim=claim,
                    deal_ref={
                        "listing_id": acceptance.listing_id,
                        "negotiation_id": acceptance.negotiation_id,
                    },
                    ttl_seconds=ttl,
                )

            # A hold stands only where an admission authority backs the listing.
            held = await binding.backing.place_hold(reserve)
        except Exception as exc:
            logger.warning(
                "[NEGOTIATION] Could not place quota hold for %s: %s",
                acceptance.negotiation_id,
                exc,
            )
            return
        if not held:
            self._stage_event(
                "negotiation",
                "capacity_hold_unavailable",
                negotiation_id=acceptance.negotiation_id,
                listing_id=acceptance.listing_id,
            )
            return
        await repository.save_capacity_hold(
            negotiation_id=acceptance.negotiation_id,
            listing_id=acceptance.listing_id,
            capacity_reservation_id=str(held["capacity_reservation_id"]),
            payload=held,
            expires_at=held.get("hold_expires_at"),
        )
        self._stage_event(
            "negotiation",
            "capacity_hold_placed",
            negotiation_id=acceptance.negotiation_id,
            listing_id=acceptance.listing_id,
            capacity_reservation_id=held.get("capacity_reservation_id"),
            resource_id=held.get("resource_id"),
            site=held.get("site"),
            hold_expires_at=held.get("hold_expires_at"),
        )

    def _required_service(self, db: Any, composition: Any) -> PaymentSettlementService:
        service = self.service(db, composition)
        if service is None:
            raise SettlementRefusal(503, "Arkhai payments is not enabled")
        return service

    async def settle(self, *, db: Any, composition: Any, reference: str, body: Any, signer: Any, **_context: Any) -> SettleResult:
        if reference != body.negotiation_id:
            raise SettlementRefusal(400, "payments settlement is keyed by negotiation ID")
        return await self._required_service(db, composition).settle(
            body.negotiation_id,
            buyer_principal=body.buyer_principal,
            seller_principal=signer.identity,
        )

    async def status(self, *, db: Any, composition: Any, body: Any, signer: Any, **_context: Any) -> SettleResult | None:
        return await self._required_service(db, composition).status(
            body.negotiation_id,
            buyer_principal=body.buyer_principal,
            seller_principal=signer.identity,
        )

    async def refund(self, *, db: Any, composition: Any, negotiation_id: str) -> SettleResult:
        return await self._required_service(db, composition).refund(negotiation_id)

    async def refund_before_delivery(self, *, db: Any, composition: Any, negotiation_id: str) -> dict[str, Any]:
        service = self.service(db, composition)
        if service is None:
            return {"action": "refund", "status": "skipped", "reason": "payments_unavailable"}
        return await service.refund_before_delivery(negotiation_id)


__all__ = ["PAYMENT_RECONCILIATION", "ArkhaiPaymentsSellerStage"]
