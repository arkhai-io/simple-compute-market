"""API-credit seller stages own verification, admission and continuations."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any
from types import SimpleNamespace

from market_alkahest import AlkahestConditionalEscrowClient, create_alkahest_registration
from market_alkahest.proposals import accepted_escrow_artifacts_from_proposal
from market_alkahest.escrow_verification import verify_escrow_for_settlement
from market_alkahest.txlock import chain_tx_lock
from market_arkhai_payments import (
    ARKHAI_PAYMENTS_CONFIG_KEY,
    PaymentsPollTimeout, PaymentsOptionParams, create_arkhai_payments_registration,
    derive_mandate, transaction_id, payments_client_for_owner, verify_receipt,
)
from market_core import SettlementEvidence
from market_core.schemas import Agreement, EscrowProposal, SettlementOption, SettlementSelection, derive_settlement_option_id
from domains.apicredits.settlement.payments import validate_payment_publication_clause
import apicredits_storefront.container as container
from market_identity import Identity
from market_negotiation_runtime import OfferUnfulfillableError
from market_settlement_runtime import PreparedSettlement, FulfillmentOutcome, derive_obligation_ref
from core_storefront.stage_log import stage_event

from apicredits_storefront.services.capacity_client import build_capacity_runtime, capacity_binding_from_offer
from apicredits_storefront.services.issuance_evidence import ApiCreditPrivateResultRepository
from apicredits_storefront.utils.config import CHAINS, settings
from domains.apicredits.domain_runtime import market_domain
from domains.apicredits.listings.models import coerce_resource_dict
from domains.apicredits.negotiation.terms import ApiCreditsProvisionTerms, provision_quantity
from domains.apicredits.settlement import mandate_policy_from_agreement, validate_payer_account
from domains.apicredits.settlement.fulfillment import credit_delivery
from domains.apicredits.settlement.issuance_evidence import ApiCreditsIssuanceEvidenceBodyV1

logger = logging.getLogger(__name__)


def accepted_agreement(thread: Mapping[str, Any]) -> tuple[Agreement, bytes]:
    raw = thread.get("agreement_bytes")
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if thread.get("terminal_state") != "success" or not isinstance(raw, bytes):
        raise ValueError("accepted Agreement is unavailable")
    agreement = Agreement.model_validate_json(raw)
    if agreement.settlement is None:
        raise ValueError("accepted Agreement has no selected settlement option")
    if Identity.model_validate(agreement.buyer) != Identity.model_validate(thread["buyer_principal"]):
        raise ValueError("accepted Agreement buyer differs from negotiation")
    if Identity.model_validate(agreement.seller) != Identity.model_validate(thread["seller_principal"]):
        raise ValueError("accepted Agreement seller differs from negotiation")
    if agreement.negotiation_id != thread["negotiation_id"]:
        raise ValueError("accepted Agreement negotiation binding differs")
    return agreement, raw


def settlement_evidence(
    agreement: Agreement, raw: bytes, *, reference: str, status: str,
    source: Mapping[str, Any], order: Mapping[str, Any],
) -> SettlementEvidence:
    provision = agreement.provision_terms or {}
    terms = ApiCreditsProvisionTerms.model_validate({key: provision[key] for key in ("kind", "version", "payload")})
    delivery = {
        "owner": agreement.buyer,
        "offer_resource": market_domain().codecs.listing({"offer_resource": order.get("offer_resource")}).offer_resource.model_dump(mode="json"),
        "quantity": terms.quantity, "key_mode": terms.key_mode, "key_id": terms.key_id,
        "listing_id": agreement.listing_id,
    }
    evidence = SettlementEvidence(
        agreement.negotiation_id, agreement.settlement.mechanism, reference, status,
        {"kind": "api_credits.settlement-evidence.v1", "schema_version": 1,
         "agreement_digest": hashlib.sha256(raw).hexdigest(),
         "source": dict(source), "delivery": delivery},
    )
    credit_delivery(evidence, require_verified=False)
    return evidence


async def persist_delivery(db: Any, evidence: SettlementEvidence, result: Mapping[str, Any], *, public_ref: str) -> dict[str, Any]:
    private = ApiCreditPrivateResultRepository(db.db_path)
    credentials = result.get("tenant_credentials") or {}
    credentials_ref = None
    issuance = result.get("issuance")
    if credentials.get("secret"):
        if issuance is None:
            raise ValueError("private delivery requires canonical issuance identity")
        stored = await asyncio.to_thread(
            private.store, fulfillment_id=issuance.fulfillment_id,
            owner=credit_delivery(evidence).owner, key_id=credentials["key_id"], secret=credentials["secret"],
        )
        credentials_ref = stored.credentials_ref
    public = {key: value for key, value in credentials.items() if key != "secret"}
    if result.get("connection_details"):
        public["connection_details"] = result["connection_details"]
    return await db.save_issuance_progress(
        negotiation_id=evidence.negotiation_id, public_ref=public_ref,
        status="ready" if result.get("status") == "fulfilled" else ("provisioning" if result.get("status") == "pending" else "failed"),
        fulfillment_uid=result.get("fulfillment_uid"), public_result=public,
        credentials_ref=credentials_ref, reason=result.get("message"),
    )


async def project_progress(db: Any, row: Mapping[str, Any], *, owner: Identity) -> dict[str, Any]:
    evidence = await db.load_settlement_evidence(negotiation_id=row["negotiation_id"])
    if evidence is None:
        raise ValueError("settlement source evidence is missing")
    if credit_delivery(evidence, require_verified=False).owner != owner:
        raise PermissionError("settlement result belongs to another principal")
    public = dict(row["public_result"])
    connection = public.pop("connection_details", None)
    result = {
        "escrow_uid": row["public_ref"], "negotiation_id": row["negotiation_id"],
        "status": row["status"], "settlement_ref": evidence.settlement_ref,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "fulfillment_uid": row.get("fulfillment_uid"), "reason": row.get("reason"),
    }
    if connection:
        result["connection_details"] = connection
    if public:
        result["tenant_credentials"] = public
    if row.get("credentials_ref"):
        private = await asyncio.to_thread(
            ApiCreditPrivateResultRepository(db.db_path).get,
            credentials_ref=row["credentials_ref"], owner=owner,
        )
        if private is not None:
            result.setdefault("tenant_credentials", {})["secret"] = private.secret
    return result


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
    agreed_amount: int,
    uses_scalar_amount: bool = True,
    duration_seconds: int = 0,
    listing: Mapping[str, Any] | None = None,
    **_unused: Any,
) -> dict[str, Any]:
    """Materialize the domain's durationless accepted settlement artifacts."""

    artifacts = accepted_escrow_artifacts_from_proposal(
        proposal=proposal,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        uses_scalar_amount=uses_scalar_amount,
        seller_wallet_address=str(settings.get("wallet.address", "") or ""),
        chain_config_paths={name: chain.alkahest_address_config_path for name, chain in CHAINS.items()},
        heartbeat_interval_seconds=None,
    )
    error = artifacts.pop("accepted_escrow_terms_error", None)
    if error:
        logger.debug("Could not materialize accepted escrow terms: %s", error)
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
            order=dict(order),
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


class PaymentSellerStage:
    registration = staticmethod(create_arkhai_payments_registration)
    retry_uncertain = True

    def validate_selection(self, selection: Any) -> None:
        params = selection.params
        if not isinstance(params, Mapping) or set(params) != {"payer_account"}:
            raise OfferUnfulfillableError("payments_payer_account_missing")
        try:
            validate_payer_account(params["payer_account"])
        except ValueError as exc:
            raise OfferUnfulfillableError("payments_payer_account_invalid") from exc

    def agreement_artifacts(self, agreement: Mapping[str, Any], config: Any) -> dict[str, Any]:
        section = config.mechanism_config(ARKHAI_PAYMENTS_CONFIG_KEY)
        if section is None:
            raise ValueError("payment trust configuration is unavailable")
        policy = mandate_policy_from_agreement(agreement, fee_bps=section.fee_bps, dispute_authority=section.dispute_authority)
        mandate = derive_mandate(dict(agreement), policy)
        return {"mandate": mandate.model_dump(mode="json", by_alias=True, exclude_none=True),
                "transaction_id": transaction_id(mandate)}

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
            offer = coerce_resource_dict(acceptance.listing_record.get("offer_resource"))
            claim: dict[str, Any] = {
                "executor_kind": "api_credits",
                "units": int(quantity),
            }
            if offer.get("resource_id"):
                claim["resource_id"] = str(offer["resource_id"])
            capacity = build_capacity_runtime(lambda: repository)
            binding = capacity_binding_from_offer(offer)
            held = await capacity.reserve(
                binding,
                claim=claim,
                deal_ref={
                    "listing_id": acceptance.listing_id,
                    "negotiation_id": acceptance.negotiation_id,
                },
                ttl_seconds=ttl,
            )
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


    async def settle(self, *, db: Any, composition: Any, coordinator: Any, reference: str, body: Any, signer: Any, thread: Mapping[str, Any]) -> dict[str, Any]:
        agreement, raw = accepted_agreement(thread)
        if reference != agreement.negotiation_id:
            raise ValueError("payment settlement is keyed by negotiation ID")
        agreement_json = agreement.model_dump(mode="json", exclude_none=True)
        data = self.agreement_artifacts(agreement_json, composition.settlement_config)
        if thread.get("settlement_data") != data:
            raise ValueError("accepted mandate differs from Agreement")
        config = composition.settlement_config.mechanism_config(ARKHAI_PAYMENTS_CONFIG_KEY)
        policy = mandate_policy_from_agreement(agreement_json, fee_bps=config.fee_bps, dispute_authority=config.dispute_authority)
        mandate = derive_mandate(agreement_json, policy)
        payment_ref = data["transaction_id"]
        progress = await db.load_issuance_progress(reference=reference)
        if progress and progress["status"] in {"ready", "failed"}:
            return progress
        old = await db.load_settlement_evidence(negotiation_id=reference)
        order = await db.load_listing(listing_id=agreement.listing_id)
        if not order:
            raise ValueError("accepted credit listing is unavailable")
        evidence = settlement_evidence(agreement, raw, reference=payment_ref, status="pending", source=data, order=order)
        if old:
            evidence = replace(evidence, evidence={**dict(evidence.evidence), "delivery": dict(old.evidence["delivery"])})
        await db.save_settlement_evidence(evidence)
        await db.save_issuance_progress(negotiation_id=reference, public_ref=reference, status="provisioning")
        with payments_client_for_owner(config, policy.option.payee_account) as client:
            try:
                snapshot = await asyncio.to_thread(client.poll, payment_ref, timeout=30.0, interval=0.5)
            except PaymentsPollTimeout:
                return await db.load_issuance_progress(reference=reference)
            receipt = snapshot.snapshot.receipt
            if not verify_receipt(receipt, config.service_identity, mandate=mandate, agreement_json=agreement_json):
                raise ValueError("payments receipt does not prove this Agreement")
            evidence = replace(evidence, status="verified", evidence={
                **dict(evidence.evidence), "source": {**data, "receipt": receipt.model_dump(mode="json") if hasattr(receipt, "model_dump") else receipt},
            })
            await db.save_settlement_evidence(evidence)
            await asyncio.to_thread(client.ensure_agreement_attached, payment_ref, agreement_json,
                                    PaymentsOptionParams.model_validate(agreement.settlement.params))
            result = await composition.domain.fulfillment.fulfill(
                evidence=evidence, retry_uncertain=self.retry_uncertain, db=db, credits_client=composition.credits_client,
            )
            progress = await persist_delivery(db, evidence, result, public_ref=reference)
            if progress["status"] == "failed":
                try:
                    await asyncio.to_thread(client.reverse, payment_ref)
                except Exception:
                    logger.exception("Could not reverse failed API-credit payment %s", payment_ref)
            return progress

    async def redrive(self, **context: Any) -> dict[str, Any]:
        return await self.settle(**context)


class AlkahestSellerStage:
    _delivery_locks: dict[str, asyncio.Lock] = {}
    registration = staticmethod(create_alkahest_registration)
    retry_uncertain = False

    def validate_selection(self, selection: Any) -> None:
        if selection.expiration_unix is None:
            raise OfferUnfulfillableError("settlement_expiration_required")

    def agreement_artifacts(self, agreement: Mapping[str, Any], config: Any) -> dict[str, Any]:
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
        composition = context.pop("composition", None)
        prepared = await _prepare_alkahest_settlement(**context)
        db = context["sqlite_client"]
        thread = await db.load_negotiation_thread_row(negotiation_id=context["negotiation_id"])
        agreement, raw = accepted_agreement(thread)
        evidence = settlement_evidence(
            agreement, raw, reference=prepared.mechanism_ref, status="verified",
            source={"chain_name": context["chain_name"], "escrow_uid": prepared.mechanism_ref,
                    "obligation_index": prepared.selected_obligation_index,
                    "obligation_ref": derive_obligation_ref(prepared.agreement_ref, prepared.selected_obligation_index,
                                                           prepared.obligations[prepared.selected_obligation_index]),
                    "funding_expiration_unix": prepared.obligations[prepared.selected_obligation_index]["expiration_unix"]},
            order=prepared.fulfillment_input.order,
        )
        await db.save_settlement_evidence(evidence)
        return replace(prepared, fulfillment_input=replace(
            prepared.fulfillment_input, sqlite_client=db,
            composition=composition or container.resolved_settlement_composition,
        ))

    async def settle(self, *, db: Any, composition: Any, coordinator: Any, reference: str, body: Any, signer: Any, thread: Mapping[str, Any]) -> dict[str, Any]:
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

    async def redrive(self, **context: Any) -> dict[str, Any]:
        db = context["db"]
        evidence = await db.load_settlement_evidence(negotiation_id=context["body"].negotiation_id)
        if evidence is None:
            raise ValueError("Alkahest settlement source evidence is unavailable")
        body = context["body"].model_copy(update={"chain_name": evidence.evidence["source"]["chain_name"]})
        return await self.settle(**{**context, "body": body})

    async def deliver_prepared(self, prepared: Any, *, mechanism_client: Any) -> Any:
        # One storefront process owns this SQLite authority. Concurrent retries
        # may queue, but only the holder may issue or attest; restart reconstructs
        # the continuation from accepted state and durable progress.
        lock = self._delivery_locks.setdefault(prepared.agreement_ref, asyncio.Lock())
        async with lock:
            db = prepared.fulfillment_input.sqlite_client
            progress = await db.load_issuance_progress(reference=prepared.mechanism_ref)
            if progress is not None and progress["status"] == "ready":
                return FulfillmentOutcome(
                    status="fulfilled", fulfillment_ref=progress["fulfillment_uid"],
                    public_result={"connection_details": progress["public_result"].get("connection_details")},
                )
            params = prepared.fulfillment_input
            db = params.sqlite_client
            if db is None:
                raise ValueError("settlement repository is unavailable")
            thread = await db.load_negotiation_thread_row(negotiation_id=params.negotiation_id)
            agreement, _raw = accepted_agreement(thread)
            stage = self
            try:
                await stage.prepare(
                    sqlite_client=db, local_principal=prepared.local_principal,
                    escrow_uid=prepared.mechanism_ref, negotiation_id=params.negotiation_id,
                    mechanism_client=mechanism_client, chain_name=params.chain_name,
                    request=SimpleNamespace(buyer_principal=params.buyer_principal),
                    composition=params.composition,
                )
                evidence = await db.load_settlement_evidence(negotiation_id=params.negotiation_id)
                composition = params.composition
                fulfillment = composition.domain.fulfillment
                result = await fulfillment.fulfill(
                    evidence=evidence, retry_uncertain=stage.retry_uncertain, db=db, credits_client=composition.credits_client,
                )
                result = await stage.continue_delivery(
                    result, evidence=evidence, client=mechanism_client, composition=composition,
                )
            except Exception as exc:
                return FulfillmentOutcome(status="failed", reason=f"issuance_error: {exc}")
            if result.get("status") != "fulfilled":
                return FulfillmentOutcome(status="failed", reason=result.get("message") or "credit issuance failed")
            await persist_delivery(db, evidence, result, public_ref=prepared.mechanism_ref)
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
            body = ApiCreditsIssuanceEvidenceBodyV1(
                condition_anchor=evidence.settlement_ref, obligation_ref=source["obligation_ref"],
                fulfillment_id=issuance.fulfillment_id, grant_id=issuance.grant_id,
                service=issuance.service, resource_id=issuance.resource_id,
                quantity=issuance.quantity, key_mode=issuance.key_mode, key_id=issuance.key_id,
                owner=issuance.owner, buyer=credit_delivery(evidence).owner,
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
                escrow_uid=evidence.settlement_ref,
                issuance={"key_id": issuance.key_id, "quantity": issuance.quantity},
                key_mode=issuance.key_mode,
            )
            stage_event("settlement", "failed_after_issuance", settlement_ref=evidence.settlement_ref,
                        key_id=issuance.key_id, rollback=rollback, error=str(exc))
            return {"status": "error", "message": f"On-chain fulfillment failed after issuance: {exc}"}
