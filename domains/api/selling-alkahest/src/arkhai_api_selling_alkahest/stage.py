"""The seller's Alkahest stage: escrow verification, issuance, and the attestation that releases the escrow.

Issuance whose outcome is unknown stays open and is re-driven under the same
fulfillment identity; only a definite refusal is compensated. The attestation
is a string obligation the chain does not deduplicate, so the stage records its
submission in the settlement journal before submitting and the attestation's
UID before completing. An attempt that finds a submission without a UID cannot
tell whether the chain holds one, and parks the obligation for an operator
rather than submitting again. See openspec/specs/settlement-servicing/spec.md,
"A fulfillment submission with an unknown outcome is never repeated".
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from arkhai_api_selling.contributions import SellingContributions
from arkhai_api_selling.issuance import (
    SettlementRefusal,
    SettleResult,
    accepted_agreement,
    delivery,
    persist_delivery,
    progress_result,
    settlement_evidence,
)
from arkhai_api_selling.quota_listing import accepted_listing
from arkhai_api_selling.settlement_composition import SellingSettlementComposition
from market_alkahest import (
    ALKAHEST_CONFIG_KEY,
    ALKAHEST_MECHANISM_ID,
    AlkahestConditionalEscrowClient,
    AlkahestFulfillmentPublisher,
    create_alkahest_registration,
    require_deliverable_release_model,
)
from market_alkahest.escrow_verification import verify_escrow_for_settlement
from market_core import SettlementEvidence
from market_core.schemas import EscrowProposal
from market_identity import Identity
from market_negotiation_runtime import OfferUnfulfillableError
from market_settlement_runtime import (
    FULFILLMENT_REFERENCE_KEY,
    FULFILLMENT_SUBMISSION_KEY,
    FulfillmentOutcome,
    PreparedSettlement,
    SettlementManualRequired,
    derive_obligation_ref,
)

from arkhai_api_selling_alkahest.negotiation import (
    AlkahestEscrowAcceptance,
    accepted_escrow_artifacts,
    accepted_escrow_proposal,
)
from arkhai_api_selling_alkahest.publication import (
    SEED_ESCROW_SETTINGS,
    accepted_escrow,
    release_conditions,
    seed_accepted_escrows,
)

logger = logging.getLogger(__name__)

StageEventFn = Callable[..., Any]
BackfillFn = Callable[..., Awaitable[int]]

OUTCOME_UNKNOWN = "alkahest_submission_outcome_unknown"


@dataclass(frozen=True)
class AlkahestFulfillmentInput:
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
    composition: SellingSettlementComposition | None = None


@dataclass(frozen=True)
class AlkahestSettlementProjection:
    """Public settlement-row metadata for the accepted escrow."""

    chain_name: str
    escrow_address: str | None


class AlkahestSellerStage:
    """The seller's Alkahest entry, over the collaborators its storefront injects.

    ``chains`` and ``seller_wallet`` read the storefront's chain configuration
    and wallet; ``composition`` and ``sqlite_client`` its lifespan's settlement
    composition and persistence; ``backfill_escrows`` the storefront's identity
    backfill for escrows that predate their obligation records. Every other
    collaborator — the delivery callable, the credits client, the evidence
    service, the settlement runtime and its repository, the local principal,
    the mechanism resources, and the settlement configuration — is read from
    the composition, the selling library's ``SellingSettlementComposition``.
    """

    mechanism = ALKAHEST_MECHANISM_ID
    registration = staticmethod(create_alkahest_registration)
    retry_uncertain = True
    # An escrow is verified against the plan its escrow proposal materializes
    # under the listing's release condition, which an exact selection cannot
    # build, so a selection of it is refused.
    settles_from_agreement = False
    escrow_proposal_step = staticmethod(accepted_escrow_proposal)
    accepted_escrow = staticmethod(accepted_escrow)
    seed_escrow_settings = SEED_ESCROW_SETTINGS

    def __init__(
        self,
        contributions: SellingContributions,
        *,
        fulfils_through_capacity: bool,
        release_models: frozenset[str],
        chains: Callable[[], Mapping[str, Any]],
        seller_wallet: Callable[[], str],
        composition: Callable[[], SellingSettlementComposition | None],
        sqlite_client: Callable[[], Any | None],
        backfill_escrows: BackfillFn,
        stage_event: StageEventFn,
        verify_escrow: Callable[..., Awaitable[Any]] = verify_escrow_for_settlement,
        escrow_client: Callable[..., Any] = AlkahestConditionalEscrowClient,
        worker_id: str = "alkahest-attestation",
    ) -> None:
        self._contributions = contributions
        # Required, with no default: publication drops a capacity-fulfilled
        # stage's options from a listing no admission authority backs.
        self.fulfils_through_capacity = fulfils_through_capacity
        # The release models a deal may be released under; a configured
        # section naming another is refused, so a listing never advertises a
        # condition its deal could not honour.
        self.release_models = release_models
        self._chains = chains
        self._seller_wallet = seller_wallet
        self._composition = composition
        self._sqlite_client = sqlite_client
        self._backfill_escrows = backfill_escrows
        self._stage_event = stage_event
        self._verify_escrow = verify_escrow
        self._escrow_client = escrow_client
        self._worker_id = worker_id
        self._delivery_locks: dict[str, asyncio.Lock] = {}
        self.escrow_acceptance = AlkahestEscrowAcceptance(self._chain_config_paths)

    def _chain_config_paths(self) -> dict[str, str | None]:
        return {name: chain.alkahest_address_config_path for name, chain in self._chains().items()}

    # Composition-time contributions.

    def servicing(self, settlement_config: Any) -> None:
        return None

    def validate_configuration(self, settlement_config: Any) -> None:
        """Refuse a configured section's release model this stage cannot deliver.

        A configured section owns the deals accepted under it, enabled or not.
        """
        section = settlement_config.mechanism_config(ALKAHEST_CONFIG_KEY)
        if section is not None:
            require_deliverable_release_model(section, self.release_models)

    def release_conditions(
        self, composition: SellingSettlementComposition, accepted_escrows: list[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        return release_conditions(
            composition.settlement_config,
            chains=composition.mechanism_resources["chains"],
            wallet_address=self._seller_wallet(),
            accepted_escrows=accepted_escrows,
        )

    def seed_accepted_escrows(self, seed: Mapping[str, Any]) -> list[dict[str, Any]]:
        return seed_accepted_escrows(seed, self._chains())

    def contributed_loops(self) -> tuple[Any, ...]:
        return ()

    def startup_steps(self) -> tuple[Callable[[], Awaitable[None]], ...]:
        return (self.backfill_escrow_records,)

    def health_checks(self) -> dict[str, str]:
        composition = self._composition()
        clients = composition.mechanism_resources.get("clients") if composition is not None else None
        return {"alkahest": ",".join(sorted(clients)) if clients else "unconfigured"}

    async def backfill_escrow_records(self) -> None:
        """Give escrows that predate their obligation records the same identity."""
        composition = self._composition()
        if composition is None:
            return
        backfilled = await self._backfill_escrows(
            sqlite_client=self._sqlite_client(),
            settlement_runtime=composition.runtime,
            local_principal=composition.local_principal,
        )
        if backfilled:
            logger.info("[STARTUP] Backfilled %d legacy escrow obligation records", backfilled)

    # The stage table's entry.

    def validate_selection(self, selection: Any) -> None:
        if selection.expiration_unix is None:
            raise OfferUnfulfillableError("settlement_expiration_required")

    def agreement_artifacts(self, agreement: Mapping[str, Any], composition: SellingSettlementComposition) -> dict[str, Any]:
        return {}

    def readiness_resources(self, clauses: Any, resources: Mapping[str, Any]) -> dict[str, Any]:
        chains = tuple(dict.fromkeys(str(clause.mechanism_input["chain"]) for clause in clauses
                                    if isinstance(clause.mechanism_input.get("chain"), str)))
        return {"accepted_escrows": [{"chain_name": chain} for chain in chains]} if chains else {}

    def client(self, resources: Mapping[str, Any]) -> Any:
        return self._escrow_client(
            get_client=resources["get_client"],
            chain_config_paths={name: chain.alkahest_address_config_path for name, chain in resources["chains"].items()},
            default_chain=resources["default_chain"],
        )

    def validate_publication(self, resources: Mapping[str, Any]) -> None:
        pass

    async def place_hold(self, repository: Any, acceptance: Any) -> None:
        pass

    async def prepare(self, **context: Any) -> Any:
        composition = context.pop("composition", None)
        if composition is None:
            raise ValueError("settlement composition is unavailable")
        db = context["sqlite_client"]

        async def load_accepted(listing_id: str) -> Mapping[str, Any]:
            return await accepted_listing(
                composition.contributions, db, domain=composition.domain,
                negotiation_id=context["negotiation_id"], listing_id=listing_id,
            )

        prepared = await self._prepare(**context, load_listing=load_accepted)
        thread = await db.load_negotiation_thread_row(negotiation_id=context["negotiation_id"])
        agreement, raw = accepted_agreement(thread)
        selected = prepared.obligations[prepared.selected_obligation_index]
        evidence = settlement_evidence(
            composition.contributions,
            agreement, raw, reference=prepared.mechanism_ref, status="verified",
            source={"chain_name": context["chain_name"], "escrow_uid": prepared.mechanism_ref,
                    "obligation_index": prepared.selected_obligation_index,
                    "obligation_ref": derive_obligation_ref(
                        prepared.agreement_ref, prepared.selected_obligation_index, selected
                    ),
                    "funding_expiration_unix": selected["expiration_unix"]},
            order=prepared.fulfillment_input.order,
        )
        await db.save_settlement_evidence(evidence)
        return replace(prepared, fulfillment_input=replace(
            prepared.fulfillment_input, sqlite_client=db, composition=composition,
        ))

    async def _prepare(
        self,
        *,
        sqlite_client: Any,
        local_principal: Identity,
        escrow_uid: str,
        negotiation_id: str,
        mechanism_client: Any,
        chain_name: str,
        load_listing: Callable[[str], Awaitable[Mapping[str, Any]]],
        request: Any = None,
    ) -> PreparedSettlement:
        """Verify and snapshot the exact durationless obligation.

        ``load_listing`` returns the listing as the buyer accepted it, which the
        escrow is verified and the plan rebuilt against.
        """
        if request is None:
            raise ValueError("settlement request is required")
        chain = self._chains().get(chain_name)
        if chain is None:
            raise ValueError(f"chain {chain_name!r} is not configured on this storefront")

        thread = await sqlite_client.load_negotiation_thread_row(negotiation_id=negotiation_id)
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
        order = await load_listing(listing_id) if listing_id else None
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
            EscrowProposal.model_validate(proposal_raw) if isinstance(proposal_raw, dict) else None
        )
        # Verification and the plan below materialize the escrow under the
        # release condition the listing authorizes; the kit refuses any other.
        matched_index = await self._verify_escrow(
            escrow_uid=escrow_uid,
            seller_wallet=self._seller_wallet(),
            agreed_price=int(thread["agreed_price"]),
            agreed_duration_seconds=0,
            listing=order,
            alkahest_client=mechanism_client,
            chain_name=chain_name,
            alkahest_address_config_path=chain.alkahest_address_config_path,
            escrow_proposal=proposal,
        )

        accepted = accepted_escrow_artifacts(
            proposal=proposal,
            agreed_amount=int(thread["agreed_price"]),
            buyer_principal=buyer_principal,
            seller_principal=seller_principal,
            listing=order,
            chain_config_paths=self._chain_config_paths(),
        )
        plan = accepted.get("settlement_plan")
        obligations_raw = plan.get("obligations") if isinstance(plan, dict) else None
        if not isinstance(obligations_raw, list) or not obligations_raw:
            raise ValueError(f"Negotiation {negotiation_id} has no accepted settlement obligations")
        obligations = tuple(dict(obligation) for obligation in obligations_raw)
        expected_payer = buyer_principal.model_dump(mode="json")
        expected_claimant = seller_principal.model_dump(mode="json")
        for obligation in obligations:
            if obligation.get("payer_principal") != expected_payer:
                raise ValueError("settlement obligation payer principal mismatch")
            if obligation.get("claimant_principal") != expected_claimant:
                raise ValueError("settlement obligation claimant principal mismatch")
        if not isinstance(matched_index, int) or not 0 <= matched_index < len(obligations):
            raise ValueError(f"Verified obligation index {matched_index!r} is outside the accepted plan")

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
            fulfillment_input=AlkahestFulfillmentInput(
                chain_name=proposal_chain or chain_name,
                order=dict(order),
                quantity=int(terms["quantity"]),
                key_mode=str(terms.get("key_mode") or "new"),
                key_id=terms.get("key_id"),
                buyer_principal=buyer_principal,
                listing_id=listing_id,
                negotiation_id=negotiation_id,
            ),
            projection_context=AlkahestSettlementProjection(
                chain_name=proposal_chain or chain_name,
                escrow_address=escrow_address,
            ),
        )

    async def _start(self, *, db: Any, composition: SellingSettlementComposition, coordinator: Any, reference: str, body: Any) -> dict[str, Any] | None:
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

    async def settle(self, *, db: Any, composition: SellingSettlementComposition, coordinator: Any, reference: str, body: Any, signer: Any, **_context: Any) -> SettleResult:
        row = await self._start(db=db, composition=composition, coordinator=coordinator, reference=reference, body=body)
        if row is None:
            raise SettlementRefusal(409, "settlement progress is unavailable")
        return await progress_result(
            self._contributions, db, row, buyer=body.buyer_principal, seller=signer.identity
        )

    async def status(self, *, db: Any, composition: SellingSettlementComposition, coordinator: Any, reference: str, body: Any, signer: Any, **_context: Any) -> SettleResult | None:
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
            self._contributions, db, row, buyer=body.buyer_principal, seller=signer.identity
        )

    async def refund(self, *, db: Any, composition: SellingSettlementComposition, negotiation_id: str) -> SettleResult:
        raise SettlementRefusal(409, "this settlement mechanism refunds through its own path")

    async def refund_before_delivery(self, *, db: Any, composition: SellingSettlementComposition, negotiation_id: str) -> dict[str, Any]:
        return {"action": "refund", "status": "skipped", "reason": "refund_not_supported"}

    async def deliver_prepared(self, prepared: Any, *, mechanism_client: Any) -> FulfillmentOutcome:
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
            delivery(self._contributions, evidence)
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
            composition = params.composition
            if composition is None:
                raise ValueError("settlement composition is unavailable")
            try:
                parked = await self._parked(composition, evidence)
            except Exception as exc:
                return FulfillmentOutcome(status="deferred", reason=f"Attestation journal is unavailable: {exc}")
            if parked:
                # Issuing again would rotate the credential the buyer holds.
                return FulfillmentOutcome(
                    status="deferred", reason="the attestation waits for an operator"
                )
            try:
                result = await composition.domain.fulfillment.fulfill(
                    evidence=evidence, retry_uncertain=self.retry_uncertain, db=db,
                    credits_client=composition.credits_client,
                )
                issued = result

                async def keep_credential() -> None:
                    # Kept before a park, since a waiting deal is never issued
                    # again; its fulfillment identity is recorded on resolution.
                    await persist_delivery(
                        self._contributions, db, evidence,
                        {**issued, "status": "pending", "fulfillment_uid": None},
                        public_ref=prepared.mechanism_ref,
                    )

                result = await self.continue_delivery(
                    result, evidence=evidence, client=mechanism_client, composition=composition,
                    keep_credential=keep_credential,
                )
            except Exception as exc:
                return FulfillmentOutcome(status="failed", reason=f"issuance_error: {exc}")
            if result.get("status") == "pending":
                return FulfillmentOutcome(status="deferred", reason=result.get("message"))
            if result.get("status") == "parked":
                return FulfillmentOutcome(status="deferred", reason=result.get("message"))
            if result.get("status") != "fulfilled":
                return FulfillmentOutcome(status="failed", reason=result.get("message") or "credit issuance failed")
            await persist_delivery(
                self._contributions, db, evidence, result, public_ref=prepared.mechanism_ref
            )
            return FulfillmentOutcome(
                status="fulfilled",
                fulfillment_ref=result.get("fulfillment_uid"),
                public_result={
                    key: result[key] for key in ("connection_details",) if result.get(key) is not None
                },
                private_result=result.get("tenant_credentials"),
            )

    async def continue_delivery(
        self,
        result: dict[str, Any],
        *,
        evidence: SettlementEvidence,
        client: Any,
        composition: SellingSettlementComposition,
        keep_credential: Callable[[], Awaitable[None]],
    ) -> dict[str, Any]:
        """Attest an issued grant on chain, once.

        Returns the result fulfilled with the attestation's UID; ``pending``
        while the journal or another attempt holds the attestation; ``parked``
        when its outcome is unknown, for an operator, the grant standing and
        ``keep_credential`` having stored it before the park commits; and an
        error, with the grant rolled back, only when nothing reached the chain.
        """
        if result.get("status") != "fulfilled":
            return result
        issuance = result["issuance"]
        source = evidence.evidence["source"]
        obligation_ref = source["obligation_ref"]
        runtime = composition.runtime
        journal = {"local_principal": composition.local_principal, "worker_id": self._worker_id}

        def attested(reference: str) -> dict[str, Any]:
            return {**result, "fulfillment_uid": reference}

        async def roll_back(reason: str) -> dict[str, Any]:
            rollback = await composition.credits_client.rollback_issuance(
                settlement_ref=evidence.settlement_ref,
                issuance={"key_id": issuance.key_id, "quantity": issuance.quantity},
                key_mode=issuance.key_mode,
            )
            self._stage_event("settlement", "failed_after_issuance", settlement_ref=evidence.settlement_ref,
                              key_id=issuance.key_id, rollback=rollback, error=reason)
            return {"status": "error", "message": f"On-chain fulfillment failed after issuance: {reason}"}

        def parked(reason: str) -> dict[str, Any]:
            return {
                **result,
                "status": "parked",
                "message": f"On-chain fulfillment outcome is unknown after issuance ({reason}); "
                "an operator must reconcile it",
            }

        async def park(reason: str) -> dict[str, Any]:
            try:
                await keep_credential()
            except Exception as exc:
                return {"status": "pending", "message": f"The credential could not be kept: {exc}"}
            self._stage_event("settlement", "attestation_outcome_unknown", settlement_ref=evidence.settlement_ref,
                              key_id=issuance.key_id, reason=reason)
            try:
                await runtime.park_fulfillment(
                    obligation_ref, SettlementManualRequired(reason, code=OUTCOME_UNKNOWN), **journal
                )
            except Exception:
                logger.exception("could not park the attestation of %s", evidence.settlement_ref)
            return parked(reason)

        try:
            reserved = await runtime.reserve_fulfillment(obligation_ref, **journal)
        except Exception as exc:
            return {"status": "pending", "message": f"Attestation journal is unavailable: {exc}"}
        if reserved.status == "busy":
            return {"status": "pending", "message": "Another attempt holds the attestation"}
        receipt = reserved.receipt or {}
        if reserved.status == "succeeded":
            return attested(str(receipt["fulfillment_ref"]))
        if reserved.status == "manual_required":
            try:
                await keep_credential()
            except Exception:
                logger.exception("could not keep the credential of %s", evidence.settlement_ref)
            return parked("the attestation waits for an operator")
        if receipt.get(FULFILLMENT_REFERENCE_KEY):
            # Published before the attempt stopped: complete with what the
            # chain already holds, and never publish again.
            reference = str(receipt[FULFILLMENT_REFERENCE_KEY])
            try:
                await runtime.complete_fulfillment(obligation_ref, reference, **journal)
            except Exception:
                # The coordinator binds the reference this returns.
                logger.exception("could not complete the attestation of %s", evidence.settlement_ref)
            return attested(reference)
        if FULFILLMENT_SUBMISSION_KEY in receipt:
            return await park("an earlier submission's outcome is unknown")

        try:
            if client is None:
                raise ValueError("Alkahest attestation client is unavailable")
            if issuance.committed_at_unix > int(source["funding_expiration_unix"]):
                raise ValueError("credit grant committed after accepted funding expiry")
            body = composition.evidence_service.body(
                condition_anchor=evidence.settlement_ref, obligation_ref=obligation_ref,
                fulfillment_id=issuance.fulfillment_id, grant_id=issuance.grant_id,
                service=issuance.service, resource_id=issuance.resource_id,
                quantity=issuance.quantity, key_mode=issuance.key_mode, key_id=issuance.key_id,
                owner=issuance.owner, buyer=delivery(composition.contributions, evidence).owner,
                claimant=composition.local_principal, issuer=composition.local_principal,
                committed_at_unix=issuance.committed_at_unix, request_digest=issuance.request_digest,
            )
            publication = await asyncio.to_thread(composition.evidence_service.publish, body)
            await runtime.record_fulfillment_submission(
                obligation_ref, {"evidence_digest": publication.evidence_digest}, **journal
            )
        except Exception as exc:
            await self._release(runtime, obligation_ref, exc, journal)
            return await roll_back(str(exc))

        attestation = await AlkahestFulfillmentPublisher(client).publish(
            condition_anchor=evidence.settlement_ref, data=publication.canonical_evidence,
        )
        if attestation.outcome == "published" and attestation.reference:
            try:
                await runtime.record_fulfillment_publication(obligation_ref, attestation.reference, **journal)
                await runtime.complete_fulfillment(obligation_ref, attestation.reference, **journal)
            except Exception:
                # The coordinator binds the reference this returns.
                logger.exception("could not record the attestation of %s", evidence.settlement_ref)
            return attested(attestation.reference)
        if attestation.outcome == "outcome_unknown":
            return await park(str(attestation.reason))
        # Not submitted, or rejected: no attestation exists, so the submission
        # is withdrawn and the grant compensated.
        try:
            await runtime.clear_fulfillment_submission(obligation_ref, **journal)
        except Exception:
            logger.exception("could not withdraw the attestation submission of %s", evidence.settlement_ref)
        await self._release(runtime, obligation_ref, RuntimeError(attestation.reason), journal)
        return await roll_back(f"attestation {attestation.outcome} ({attestation.reason})")

    @staticmethod
    async def _parked(composition: SellingSettlementComposition, evidence: SettlementEvidence) -> bool:
        operation = await composition.repository.load_settlement_operation(
            evidence.evidence["source"]["obligation_ref"], "fulfill"
        )
        return operation is not None and operation["state"] == "manual_required"

    @staticmethod
    async def _release(runtime: Any, obligation_ref: str, error: Exception, journal: Mapping[str, Any]) -> None:
        try:
            await runtime.retry_fulfillment(obligation_ref, error, **journal)
        except Exception:
            logger.exception("could not release the attestation lease of %s", obligation_ref)


__all__ = [
    "OUTCOME_UNKNOWN",
    "AlkahestFulfillmentInput",
    "AlkahestSellerStage",
    "AlkahestSettlementProjection",
]
