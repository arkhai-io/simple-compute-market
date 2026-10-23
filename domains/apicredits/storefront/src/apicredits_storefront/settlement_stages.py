"""API-credit seller stages own verification, admission and continuations."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from arkhai_api_selling.issuance import (
    SettlementRefusal,
    SettleResult,
    accepted_agreement,
    delivery,
    persist_delivery,
    progress_result,
    settlement_evidence,
)
from arkhai_api_selling.quota_listing import accepted_listing_resource, listing_binding

from market_alkahest import AlkahestConditionalEscrowClient, create_alkahest_registration
from market_alkahest.proposals import accepted_escrow_artifacts_from_proposal
from market_alkahest.escrow_verification import verify_escrow_for_settlement
from market_alkahest.txlock import chain_tx_lock
from market_arkhai_payments import create_arkhai_payments_registration
from market_core import SettlementEvidence
from market_core.schemas import EscrowProposal, SettlementOption, SettlementSelection, derive_settlement_option_id
from arkhai_apicredits.settlement import validate_payer_account
from arkhai_apicredits.settlement.payments import validate_payment_publication_clause
import apicredits_storefront.container as container
from market_identity import Identity
from market_negotiation_runtime import OfferUnfulfillableError
from market_settlement_runtime import PreparedSettlement, FulfillmentOutcome, derive_obligation_ref
from core_storefront.stage_log import stage_event

from apicredits_storefront.services.capacity_client import build_capacity_runtime
from apicredits_storefront.utils.config import CHAINS, settings
from arkhai_apicredits.negotiation.terms import provision_quantity
from arkhai_apicredits.schema import ApiCreditsListing

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiCreditsFulfillmentInput:
    """Private-to-domain inputs retained only by the in-process job."""

    chain_name: str
    order: dict[str, Any]
    quantity: int
    key_mode: str
    key_id: str | None
    buyer_principal: Identity
    listing_id: str | None
    negotiation_id: str
    sqlite_client: Any = None
    composition: Any = None


@dataclass(frozen=True)
class ApiCreditsSettlementProjection:
    """Public legacy-row metadata for the accepted settlement."""

    chain_name: str
    escrow_address: str | None



def build_api_credit_accepted_artifacts(
    *,
    buyer_principal: Identity,
    seller_principal: Identity,
    proposal: Any,
    listing: Mapping[str, Any],
    agreed_amount: int,
    uses_scalar_amount: bool = True,
    duration_seconds: int = 0,
    **_unused: Any,
) -> dict[str, Any]:
    """Materialize the domain's durationless accepted settlement artifacts.

    The escrow settles under the release condition ``listing`` authorizes on
    its chain, which a condition the proposal selects must be; the kit refuses
    any other, and a listing authorizing none, with
    ``market_alkahest.proposals.ReleaseConditionError``, and an escrow whose
    plan cannot be materialized with ``SettlementPlanMaterializationError``.
    """

    artifacts = accepted_escrow_artifacts_from_proposal(
        proposal=proposal,
        listing=listing,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        uses_scalar_amount=uses_scalar_amount,
        chain_config_paths={name: chain.alkahest_address_config_path for name, chain in CHAINS.items()},
        heartbeat_interval_seconds=None,
    )
    plan = artifacts.get("settlement_plan")
    if isinstance(plan, dict):
        buyer_wire = buyer_principal.model_dump(mode="json")
        seller_wire = seller_principal.model_dump(mode="json")
        plan["buyer_principal"] = buyer_wire
        plan["seller_principal"] = seller_wire
        for obligation in plan.get("obligations") or []:
            if isinstance(obligation, dict):
                obligation["payer_principal"] = buyer_wire
                obligation["claimant_principal"] = seller_wire
    accepted = artifacts.get("accepted_escrow_proposal")
    if isinstance(accepted, Mapping):
        params = {"accepted_escrow": dict(accepted)}
        asset = str((accepted.get("fields") or {}).get("token") or "")
        option = SettlementOption(
            option_id=derive_settlement_option_id(mechanism="alkahest.v1", asset=asset, rates=[], params=params),
            mechanism="alkahest.v1", asset=asset, rates=[], params=params,
        )
        artifacts["_agreement_settlement_option"] = option.model_dump(mode="json")
        artifacts["settlement_selection"] = SettlementSelection(
            mechanism=option.mechanism, option_id=option.option_id,
            expiration_unix=accepted.get("expiration_unix"),
        ).model_dump(mode="json", exclude_none=True)
    return artifacts


def _domain_order(row: Any) -> dict[str, Any]:
    """Project a stored listing row onto the domain listing's own fields.

    `order` here is whatever `load_listing` returned -- this storefront's
    own database row, carrying its bookkeeping columns (`paused`,
    `publication_clauses`, `seller_principal`, `oracle_address`, the agent
    URL, and so on). The domain's `normalize_listing` hook validates against
    `ApiCreditsListing`, which sets `extra="forbid"`, so a raw row fails
    with `extra_forbidden` errors.

    Narrowed here rather than by relaxing the model. `ApiCreditsListing`
    describes the domain payload *carried by a registry listing*, which is
    untrusted wire input, and forbidding extras there is the guard that
    makes it a contract. A local row passed where a wire payload belongs is
    the local side's to project.

    Field names are read off the model, so a field added to the domain
    listing is carried without editing this.
    """
    fields = frozenset(ApiCreditsListing.model_fields)
    return {key: value for key, value in dict(row).items() if key in fields}


async def _prepare_alkahest_settlement(
    *,
    sqlite_client: Any,
    local_principal: Identity,
    escrow_uid: str,
    negotiation_id: str,
    mechanism_client: Any,
    chain_name: str,
    request: Any = None,
) -> Any:
    """Verify and snapshot the exact durationless API-credit obligation."""
    if request is None:
        raise ValueError("settlement request is required")

    chain = CHAINS.get(chain_name)
    if chain is None:
        raise ValueError(f"chain {chain_name!r} is not configured on this storefront")

    thread = await sqlite_client.load_negotiation_thread_row(
        negotiation_id=negotiation_id,
    )
    if not thread:
        raise ValueError(f"Unknown negotiation {negotiation_id}")
    if thread.get("terminal_state") != "success":
        raise ValueError(
            f"Negotiation {negotiation_id} is not terminal-success "
            f"(terminal_state={thread.get('terminal_state')!r})"
        )
    if thread.get("agreed_price") is None:
        raise ValueError(f"Negotiation {negotiation_id} has no agreed_price committed")
    buyer_principal = Identity.model_validate(thread.get("buyer_principal"))
    seller_principal = Identity.model_validate(thread.get("seller_principal"))
    if request.buyer_principal != buyer_principal:
        raise ValueError("settlement buyer principal does not match negotiation")
    if seller_principal != local_principal:
        raise ValueError("settlement seller principal does not match local identity")

    listing_id = thread.get("our_listing_id")
    order = (
        await sqlite_client.load_listing(listing_id=listing_id) if listing_id else None
    )
    if not order:
        raise ValueError(
            f"Seller's order {listing_id!r} (from negotiation "
            f"{negotiation_id}) is gone from the local DB"
        )
    terms = await sqlite_client.load_credit_terms(negotiation_id=negotiation_id)
    if not terms:
        raise ValueError(
            f"Negotiation {negotiation_id} has no token terms recorded — "
            "cannot issue without a quantity"
        )

    proposal_raw = thread.get("buyer_escrow_proposal")
    proposal = (
        EscrowProposal.model_validate(proposal_raw)
        if isinstance(proposal_raw, dict)
        else None
    )
    # Verification and the plan below materialize the escrow under the release
    # condition the listing authorizes; the kit refuses any other.
    matched_index = await verify_escrow_for_settlement(
        escrow_uid=escrow_uid,
        seller_wallet=settings.wallet.address or "",
        agreed_price=int(thread["agreed_price"]),
        agreed_duration_seconds=0,
        listing=order,
        alkahest_client=mechanism_client,
        chain_name=chain_name,
        alkahest_address_config_path=chain.alkahest_address_config_path,
        escrow_proposal=proposal,
    )

    accepted = build_api_credit_accepted_artifacts(
        proposal=proposal,
        agreed_amount=int(thread["agreed_price"]),
        buyer_principal=buyer_principal,
        seller_principal=seller_principal,
        listing=order,
    )
    plan = accepted.get("settlement_plan")
    obligations_raw = plan.get("obligations") if isinstance(plan, dict) else None
    if not isinstance(obligations_raw, list) or not obligations_raw:
        raise ValueError(
            f"Negotiation {negotiation_id} has no accepted settlement obligations"
        )
    obligations = tuple(dict(obligation) for obligation in obligations_raw)
    expected_payer = buyer_principal.model_dump(mode="json")
    expected_claimant = seller_principal.model_dump(mode="json")
    for obligation in obligations:
        if obligation.get("payer_principal") != expected_payer:
            raise ValueError("settlement obligation payer principal mismatch")
        if obligation.get("claimant_principal") != expected_claimant:
            raise ValueError("settlement obligation claimant principal mismatch")
    if not isinstance(matched_index, int) or not 0 <= matched_index < len(obligations):
        raise ValueError(
            f"Verified obligation index {matched_index!r} is outside the accepted plan"
        )

    proposal_chain = proposal.chain_name if proposal is not None else None
    escrow_address = proposal.escrow_address if proposal is not None else None
    if proposal_chain is None or escrow_address is None:
        accepted_escrows = order.get("accepted_escrows") or []
        if accepted_escrows and isinstance(accepted_escrows[0], dict):
            proposal_chain = proposal_chain or accepted_escrows[0].get("chain_name")
            escrow_address = escrow_address or accepted_escrows[0].get("escrow_address")

    return PreparedSettlement(
        agreement_ref=negotiation_id,
        local_principal=local_principal,
        obligations=obligations,
        selected_obligation_index=matched_index,
        mechanism_ref=escrow_uid,
        mechanism_receipt={"escrow_uid": escrow_uid},
        fulfillment_input=ApiCreditsFulfillmentInput(
            chain_name=proposal_chain or chain_name,
            order=_domain_order(order),
            quantity=int(terms["quantity"]),
            key_mode=str(terms.get("key_mode") or "new"),
            key_id=terms.get("key_id"),
            buyer_principal=buyer_principal,
            listing_id=listing_id,
            negotiation_id=negotiation_id,
        ),
        projection_context=ApiCreditsSettlementProjection(
            chain_name=proposal_chain or chain_name,
            escrow_address=escrow_address,
        ),
    )


class ArkhaiPaymentsSellerStage:
    """Charge-first payment entry; receipt checks and reversal are the kit's.

    Settlement, status, refund and reconciliation run through the composition's
    payment settlement service, which records state in the domain evidence and
    issuance-progress tables rather than in escrow rows.
    """

    registration = staticmethod(create_arkhai_payments_registration)
    # A payment deal settles from the Agreement's mandate and receipt, so its
    # exact selection is accepted without a settlement plan.
    settles_from_agreement = True

    def __init__(self, *, fulfils_through_capacity: bool) -> None:
        # Whether settling through this stage issues credits against quota.
        # Required of every stage, with no default, because publication drops
        # such a stage's options from a listing no admission authority backs.
        self.fulfils_through_capacity = fulfils_through_capacity

    def validate_selection(self, selection: Any) -> None:
        params = selection.params
        if not isinstance(params, Mapping) or set(params) != {"payer_account"}:
            raise OfferUnfulfillableError("payments_payer_account_missing")
        try:
            validate_payer_account(params["payer_account"])
        except ValueError as exc:
            raise OfferUnfulfillableError("payments_payer_account_invalid") from exc

    def agreement_artifacts(self, agreement: Mapping[str, Any], composition: Any) -> dict[str, Any]:
        stage = getattr(composition, "arkhai_payments_stage", None)
        if stage is None:
            raise ValueError("Arkhai payments is not enabled for API credits")
        return stage.settlement_data(agreement).to_wire()

    def readiness_resources(self, clauses: Any, resources: Mapping[str, Any]) -> dict[str, Any]:
        return {}

    def client(self, resources: Mapping[str, Any]) -> Any:
        return None

    def validate_publication(self, resources: Mapping[str, Any]) -> None:
        validate_payment_publication_clause(resources.get("publication_clause"))

    async def place_hold(self, repository: Any, acceptance: Any) -> None:
        quantity = provision_quantity(acceptance.terms.decoded)
        ttl = float(settings.get("capacity.hold_ttl_seconds", 0) or 0)
        if ttl <= 0 or not quantity:
            return
        try:
            binding = await listing_binding(repository, acceptance.listing_id)
            if binding is None:
                raise RuntimeError("API-credit listing has no durable binding")
            claim: dict[str, Any] = {
                "offering_mode": "api_credits",
                "units": int(quantity),
                "resource_id": binding.source_id,
            }
            capacity = build_capacity_runtime(lambda: repository)

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
            stage_event(
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
        stage_event(
            "negotiation",
            "capacity_hold_placed",
            negotiation_id=acceptance.negotiation_id,
            listing_id=acceptance.listing_id,
            capacity_reservation_id=held.get("capacity_reservation_id"),
            resource_id=held.get("resource_id"),
            site=held.get("site"),
            hold_expires_at=held.get("hold_expires_at"),
        )

    @staticmethod
    def _service(db: Any, composition: Any) -> Any:
        service = composition.payment_service(db) if composition is not None else None
        if service is None:
            raise SettlementRefusal(503, "Arkhai payments is not enabled")
        return service

    async def settle(self, *, db: Any, composition: Any, reference: str, body: Any, signer: Any, **_context: Any) -> SettleResult:
        if reference != body.negotiation_id:
            raise SettlementRefusal(400, "payments settlement is keyed by negotiation ID")
        return await self._service(db, composition).settle(
            body.negotiation_id,
            buyer_principal=body.buyer_principal,
            seller_principal=signer.identity,
        )

    async def status(self, *, db: Any, composition: Any, body: Any, signer: Any, **_context: Any) -> SettleResult | None:
        return await self._service(db, composition).status(
            body.negotiation_id,
            buyer_principal=body.buyer_principal,
            seller_principal=signer.identity,
        )

    async def refund(self, *, db: Any, composition: Any, negotiation_id: str) -> SettleResult:
        return await self._service(db, composition).refund(negotiation_id)

    async def refund_before_delivery(self, *, db: Any, composition: Any, negotiation_id: str) -> dict[str, Any]:
        service = composition.payment_service(db) if composition is not None else None
        if service is None:
            return {"action": "refund", "status": "skipped", "reason": "payments_unavailable"}
        return await service.refund_before_delivery(negotiation_id)


class AlkahestSellerStage:
    _delivery_locks: dict[str, asyncio.Lock] = {}
    registration = staticmethod(create_alkahest_registration)
    retry_uncertain = False
    # An escrow is verified against the plan its escrow proposal materializes
    # under the listing's release condition, which an exact selection cannot
    # build, so a selection of it is refused.
    settles_from_agreement = False

    def __init__(
        self, *, fulfils_through_capacity: bool, release_models: frozenset[str]
    ) -> None:
        # As for the payment stage: required, with no default.
        self.fulfils_through_capacity = fulfils_through_capacity
        # The Alkahest release models, from market_alkahest.RELEASE_MODELS, a
        # credit deal may be released under. Composition refuses a configured
        # [Settlement.alkahest] model outside them, so a listing never
        # advertises a condition its deal could not honour.
        self.release_models = release_models

    def validate_selection(self, selection: Any) -> None:
        if selection.expiration_unix is None:
            raise OfferUnfulfillableError("settlement_expiration_required")

    def agreement_artifacts(self, agreement: Mapping[str, Any], composition: Any) -> dict[str, Any]:
        return {}

    def readiness_resources(self, clauses: Any, resources: Mapping[str, Any]) -> dict[str, Any]:
        chains = tuple(dict.fromkeys(str(clause.mechanism_input["chain"]) for clause in clauses
                                    if isinstance(clause.mechanism_input.get("chain"), str)))
        return {"accepted_escrows": [{"chain_name": chain} for chain in chains]} if chains else {}

    def client(self, resources: Mapping[str, Any]) -> Any:
        return AlkahestConditionalEscrowClient(
            get_client=resources["get_client"],
            chain_config_paths={name: chain.alkahest_address_config_path for name, chain in resources["chains"].items()},
            default_chain=resources["default_chain"],
        )

    def validate_publication(self, resources: Mapping[str, Any]) -> None:
        pass

    async def place_hold(self, repository: Any, acceptance: Any) -> None:
        pass

    async def prepare(self, **context: Any) -> Any:
        composition = context.pop("composition", None) or container.resolved_settlement_composition
        if composition is None:
            raise ValueError("settlement composition is unavailable")
        prepared = await _prepare_alkahest_settlement(**context)
        db = context["sqlite_client"]
        thread = await db.load_negotiation_thread_row(negotiation_id=context["negotiation_id"])
        agreement, raw = accepted_agreement(thread)
        accepted = await accepted_listing_resource(
            composition.contributions, db, domain=composition.domain,
            negotiation_id=agreement.negotiation_id, listing_id=agreement.listing_id,
        )
        evidence = settlement_evidence(
            composition.contributions,
            agreement, raw, reference=prepared.mechanism_ref, status="verified",
            source={"chain_name": context["chain_name"], "escrow_uid": prepared.mechanism_ref,
                    "obligation_index": prepared.selected_obligation_index,
                    "obligation_ref": derive_obligation_ref(prepared.agreement_ref, prepared.selected_obligation_index,
                                                           prepared.obligations[prepared.selected_obligation_index]),
                    "funding_expiration_unix": prepared.obligations[prepared.selected_obligation_index]["expiration_unix"]},
            order={"listing_resource": accepted},
        )
        await db.save_settlement_evidence(evidence)
        return replace(prepared, fulfillment_input=replace(
            prepared.fulfillment_input, sqlite_client=db, composition=composition,
        ))

    async def _start(self, *, db: Any, composition: Any, coordinator: Any, reference: str, body: Any) -> dict[str, Any] | None:
        if not body.chain_name:
            raise ValueError("chain_name is required for Alkahest")
        client = composition.mechanism_resources["get_client"](body.chain_name)
        if client is None:
            raise ValueError("Alkahest chain client is unavailable")
        await coordinator.start(
            escrow_uid=reference, negotiation_id=body.negotiation_id,
            mechanism_client=client, chain_name=body.chain_name, request=body,
        )
        return await db.load_issuance_progress(reference=reference)

    async def settle(self, *, db: Any, composition: Any, coordinator: Any, reference: str, body: Any, signer: Any, **_context: Any) -> SettleResult:
        row = await self._start(db=db, composition=composition, coordinator=coordinator, reference=reference, body=body)
        if row is None:
            raise SettlementRefusal(409, "settlement progress is unavailable")
        return await progress_result(
            container.SELLING_CONTRIBUTIONS, db, row, buyer=body.buyer_principal, seller=signer.identity
        )

    async def status(self, *, db: Any, composition: Any, coordinator: Any, reference: str, body: Any, signer: Any, **_context: Any) -> SettleResult | None:
        row = await db.load_issuance_progress(reference=reference)
        if row is None:
            return None
        if row["status"] not in {"ready", "failed"}:
            try:
                evidence = await db.load_settlement_evidence(negotiation_id=body.negotiation_id)
                if evidence is None:
                    raise ValueError("Alkahest settlement source evidence is unavailable")
                redriven = body.model_copy(update={"chain_name": evidence.evidence["source"]["chain_name"]})
                row = await self._start(
                    db=db, composition=composition, coordinator=coordinator,
                    reference=reference, body=redriven,
                ) or row
            except ValueError as exc:
                raise SettlementRefusal(409, str(exc)) from exc
            except Exception:
                logger.exception("Settlement re-drive remains pending for %s", body.negotiation_id)
        return await progress_result(
            container.SELLING_CONTRIBUTIONS, db, row, buyer=body.buyer_principal, seller=signer.identity
        )

    async def refund(self, *, db: Any, composition: Any, negotiation_id: str) -> SettleResult:
        raise SettlementRefusal(409, "this settlement mechanism refunds through its own path")

    async def refund_before_delivery(self, *, db: Any, composition: Any, negotiation_id: str) -> dict[str, Any]:
        return {"action": "refund", "status": "skipped", "reason": "refund_not_supported"}

    async def deliver_prepared(self, prepared: Any, *, mechanism_client: Any) -> Any:
        # One storefront process owns this SQLite authority. Concurrent retries
        # may queue, but only the holder may issue or attest; restart reconstructs
        # the continuation from accepted state and durable progress.
        lock = self._delivery_locks.setdefault(prepared.agreement_ref, asyncio.Lock())
        async with lock:
            params = prepared.fulfillment_input
            db = params.sqlite_client
            if db is None:
                raise ValueError("settlement repository is unavailable")
            evidence = await db.load_settlement_evidence(negotiation_id=params.negotiation_id)
            if evidence is None:
                raise ValueError("settlement source evidence is unavailable")
            delivery(container.SELLING_CONTRIBUTIONS, evidence)
            thread = await db.load_negotiation_thread_row(negotiation_id=params.negotiation_id)
            agreement, raw = accepted_agreement(thread)
            evidence.validate_identity(
                negotiation_id=prepared.agreement_ref, mechanism=agreement.settlement.mechanism,
                settlement_ref=prepared.mechanism_ref,
            )
            if evidence.evidence["agreement_digest"] != hashlib.sha256(raw).hexdigest():
                raise ValueError("settlement evidence differs from accepted Agreement")
            progress = await db.load_issuance_progress(reference=prepared.mechanism_ref)
            if progress is not None and progress["status"] == "ready":
                return FulfillmentOutcome(
                    status="fulfilled", fulfillment_ref=progress["fulfillment_uid"],
                    public_result={"connection_details": progress["public_result"].get("connection_details")},
                )
            try:
                composition = params.composition
                fulfillment = composition.domain.fulfillment
                result = await fulfillment.fulfill(
                    evidence=evidence, retry_uncertain=self.retry_uncertain, db=db, credits_client=composition.credits_client,
                )
                result = await self.continue_delivery(
                    result, evidence=evidence, client=mechanism_client, composition=composition,
                )
            except Exception as exc:
                return FulfillmentOutcome(status="failed", reason=f"issuance_error: {exc}")
            if result.get("status") != "fulfilled":
                return FulfillmentOutcome(status="failed", reason=result.get("message") or "credit issuance failed")
            await persist_delivery(
                container.SELLING_CONTRIBUTIONS, db, evidence, result, public_ref=prepared.mechanism_ref
            )
            return FulfillmentOutcome(
                status="fulfilled",
                fulfillment_ref=result.get("fulfillment_uid"),
                public_result={
                    key: result[key]
                    for key in ("connection_details",)
                    if result.get(key) is not None
                },
                private_result=result.get("tenant_credentials"),
            )


    async def continue_delivery(self, result: dict[str, Any], *, evidence: SettlementEvidence, client: Any, composition: Any) -> dict[str, Any]:
        if result.get("status") != "fulfilled":
            return result
        issuance = result["issuance"]
        try:
            if client is None:
                raise ValueError("Alkahest attestation client is unavailable")
            source = evidence.evidence["source"]
            if issuance.committed_at_unix > int(source["funding_expiration_unix"]):
                raise ValueError("credit grant committed after accepted funding expiry")
            body = composition.evidence_service.body(
                condition_anchor=evidence.settlement_ref, obligation_ref=source["obligation_ref"],
                fulfillment_id=issuance.fulfillment_id, grant_id=issuance.grant_id,
                service=issuance.service, resource_id=issuance.resource_id,
                quantity=issuance.quantity, key_mode=issuance.key_mode, key_id=issuance.key_id,
                owner=issuance.owner, buyer=delivery(composition.contributions, evidence).owner,
                claimant=composition.local_principal, issuer=composition.local_principal,
                committed_at_unix=issuance.committed_at_unix, request_digest=issuance.request_digest,
            )
            publication = await asyncio.to_thread(composition.evidence_service.publish, body)
            async with chain_tx_lock(None):
                fulfillment_uid = await client.string_obligation.do_obligation(
                    publication.canonical_evidence, evidence.settlement_ref,
                )
            return {**result, "fulfillment_uid": fulfillment_uid}
        except Exception as exc:
            rollback = await composition.credits_client.rollback_issuance(
                settlement_ref=evidence.settlement_ref,
                issuance={"key_id": issuance.key_id, "quantity": issuance.quantity},
                key_mode=issuance.key_mode,
            )
            stage_event("settlement", "failed_after_issuance", settlement_ref=evidence.settlement_ref,
                        key_id=issuance.key_id, rollback=rollback, error=str(exc))
            return {"status": "error", "message": f"On-chain fulfillment failed after issuance: {exc}"}
