"""VM composition over the shared commercial-settlement runtime."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from typing import Any

from arkhai_vms import VmProvisionTerms, make_vm_provision_terms
from core_storefront.stage_log import stage_event
from domains.vms.listings import reconciler as listings_reconciler
from hosted_settlement_client import (
    ClientConfig,
    ConditionDescriptor,
    HostedSettlementAsyncClient,
)
from market_alkahest import AlkahestConditionalEscrowClient
from market_core.schemas import EscrowProposal, SettlementPlan
from market_hosted_settlement import HostedConditionalEscrowClient
from market_settlement_runtime import (
    FulfillmentOutcome,
    PreparedSettlement,
    SettlementJobCoordinator,
    SettlementRuntime,
    SettlementServicingWorker,
    SettlementSQLiteRepository,
    derive_obligation_ref,
)

from market_storefront import domain_runtime
from market_storefront.hosted_evidence import encode_hosted_fulfillment_ref
from market_storefront.services.capacity_client import (
    build_capacity_client,
    remote_site_clients,
)
from market_storefront.utils import config as storefront_config
from market_storefront.utils import escrow_verification
from market_storefront.utils.sync_negotiation import _accepted_hosted_artifacts

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VmFulfillmentInput:
    provision: VmProvisionTerms
    listing_id: str
    order: dict[str, Any]
    negotiation_id: str
    site_id: str | None

    fulfillment_anchor: str | None = None
    evidence_mode: str | None = None
    evidence_resolver_id: str | None = None
    evidence_client: Any = None


@dataclass(frozen=True)
class VmProjectionContext:
    sqlite_client: Any
    escrow_uid: str
    negotiation_id: str
    chain_name: str
    escrow_address: str | None
    obligation_ref: str
    obligation_index: int


@dataclass(frozen=True)
class VmSettlementComposition:
    repository: SettlementSQLiteRepository
    runtime: SettlementRuntime
    coordinator: SettlementJobCoordinator
    worker: SettlementServicingWorker
    mechanism_clients: Mapping[str, Any]
    evidence_clients: Mapping[str, Any]


def _resolve_duration_seconds(
    thread: Mapping[str, Any], order: Mapping[str, Any]
) -> int:
    return int(
        thread.get("agreed_duration_seconds")
        or thread.get("requested_duration_seconds")
        or order.get("max_duration_seconds")
        or 3600
    )


def _resolve_start_utc(thread: Mapping[str, Any]) -> str | None:
    raw = thread.get("requested_start_utc")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _resolve_compute_resource(order: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = order.get("offer_resource")
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _settlement_plan_obligations(
    *, proposal: EscrowProposal, agreed_amount: int, duration_seconds: int
) -> tuple[dict[str, Any], ...]:
    settlement = domain_runtime.get_market_domain_contract().settlement
    if settlement is None:
        raise RuntimeError("VM settlement capability is not installed")
    artifacts = settlement.build_plan(
        proposal=proposal,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
    )
    plan = artifacts.get("settlement_plan") if isinstance(artifacts, dict) else None
    obligations = plan.get("obligations") if isinstance(plan, dict) else None
    if not isinstance(obligations, list) or not obligations:
        raise ValueError("accepted negotiation has no canonical settlement obligations")
    return tuple(dict(item) for item in obligations if isinstance(item, dict))


async def _prepare_hosted_settlement(
    *,
    settlement_ref: str,
    negotiation_id: str,
    selection_payload: dict[str, Any],
    order: Mapping[str, Any],
    thread: Mapping[str, Any],
    provision: VmProvisionTerms,
    mechanism_client: Any,
    sqlite_client: Any,
) -> PreparedSettlement:

    options = order.get("settlement_options") or []
    if isinstance(options, str):
        options = json.loads(options)
    selection = selection_payload.get("settlement_selection")
    if not isinstance(selection, dict):
        raise ValueError("hosted negotiation has no settlement selection")
    option = next(
        (
            item
            for item in options
            if isinstance(item, dict)
            and item.get("option_id") == selection.get("option_id")
            and item.get("mechanism") == "fiat.stripe.v1"
        ),
        None,
    )
    if option is None:
        raise ValueError("hosted settlement selection is not listed")
    artifacts = _accepted_hosted_artifacts(
        selection=selection,
        option=option,
        agreed_amount=int(thread["agreed_price"]),
        buyer_address=str(thread.get("buyer") or thread.get("their_agent_id") or ""),
    )
    plan = artifacts["settlement_plan"]
    obligations = tuple(
        dict(item) for item in plan.get("obligations", []) if isinstance(item, dict)
    )
    if len(obligations) != 1:
        raise ValueError("hosted settlement requires exactly one obligation")
    status = await mechanism_client.get_status(
        obligations[0],
        mechanism_ref=settlement_ref,
        operation_ref=f"arkhai:settlement:{negotiation_id}:status",
        mechanism_state={},
    )
    if status.status != "ready":
        raise ValueError(f"hosted settlement is not funded (status={status.status})")
    listing_id = str(thread.get("our_listing_id") or "")

    obligation_ref = derive_obligation_ref(negotiation_id, 0, obligations[0])
    return PreparedSettlement(
        agreement_ref=negotiation_id,
        obligations=obligations,
        selected_obligation_index=0,
        mechanism_ref=settlement_ref,
        local_role="seller",
        mechanism_receipt=status.receipt,
        fulfillment_input=VmFulfillmentInput(
            provision=provision,
            listing_id=listing_id,
            order=dict(order),
            negotiation_id=negotiation_id,
            site_id=listings_reconciler.site_id_for_listing(
                sqlite_client.db_path, listing_id
            ),
        ),
        projection_context=VmProjectionContext(
            sqlite_client=sqlite_client,
            escrow_uid=settlement_ref,
            negotiation_id=negotiation_id,
            chain_name="fiat.stripe.v1",
            escrow_address=None,
            obligation_ref=obligation_ref,
            obligation_index=0,
        ),
    )


async def prepare_vm_settlement(
    *,
    escrow_uid: str,
    negotiation_id: str,
    mechanism_client: Any,
    chain_name: str,
    request: Any = None,
    sqlite_client: Any,
) -> PreparedSettlement:
    """Reload, verify, and pin the accepted VM obligation before provisioning."""

    thread = await sqlite_client.load_negotiation_thread_row(
        negotiation_id=negotiation_id
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

    listing_id = thread.get("our_listing_id")
    order = (
        await sqlite_client.load_listing(listing_id=listing_id) if listing_id else None
    )
    if not order:
        raise ValueError(
            f"Seller's order {listing_id!r} (from negotiation {negotiation_id}) "
            "is gone from the local DB"
        )

    request_data = request if isinstance(request, Mapping) else {}
    ssh_public_key = str(request_data.get("ssh_public_key") or "")
    provision = make_vm_provision_terms(
        duration_seconds=_resolve_duration_seconds(thread, order),
        start_utc=_resolve_start_utc(thread),
        ssh_public_key=ssh_public_key,
        compute_resource=_resolve_compute_resource(order),
    )

    proposal_raw = thread.get("buyer_escrow_proposal")
    if (
        isinstance(proposal_raw, dict)
        and isinstance(proposal_raw.get("settlement_selection"), dict)
        and proposal_raw["settlement_selection"].get("mechanism") == "fiat.stripe.v1"
    ):
        return await _prepare_hosted_settlement(
            settlement_ref=escrow_uid,
            negotiation_id=negotiation_id,
            selection_payload=proposal_raw,
            order=order,
            thread=thread,
            provision=provision,
            mechanism_client=mechanism_client,
            sqlite_client=sqlite_client,
        )
    chain = storefront_config.CHAINS.get(chain_name)
    if chain is None:
        raise ValueError(f"chain {chain_name!r} is not configured on this storefront")

    if not isinstance(proposal_raw, dict):
        raise ValueError(
            f"Negotiation {negotiation_id} has no persisted accepted escrow proposal"
        )
    proposal = EscrowProposal.model_validate(proposal_raw)
    obligation_index = await escrow_verification.verify_escrow_for_settlement(
        escrow_uid=escrow_uid,
        seller_wallet=storefront_config.settings.wallet.address or "",
        agreed_price=int(thread["agreed_price"]),
        agreed_duration_seconds=provision.duration_seconds,
        listing=order,
        alkahest_client=mechanism_client,
        chain_name=chain_name,
        alkahest_address_config_path=chain.alkahest_address_config_path,
        escrow_proposal=proposal,
    )
    if not isinstance(obligation_index, int):
        raise ValueError("escrow verification did not identify an exact obligation")

    obligations = _settlement_plan_obligations(
        proposal=proposal,
        agreed_amount=int(thread["agreed_price"]),
        duration_seconds=provision.duration_seconds,
    )
    if obligation_index < 0 or obligation_index >= len(obligations):
        raise ValueError(
            f"verified obligation index {obligation_index} is outside the accepted plan"
        )
    obligation_ref = derive_obligation_ref(
        negotiation_id, obligation_index, obligations[obligation_index]
    )

    proposal_chain = proposal.chain_name or chain_name
    if proposal_chain != chain_name:
        logger.warning(
            "[SETTLE_JOB] Proposal chain %r diverges from request chain %r; "
            "using proposal chain.",
            proposal_chain,
            chain_name,
        )

    return PreparedSettlement(
        agreement_ref=negotiation_id,
        obligations=obligations,
        selected_obligation_index=obligation_index,
        mechanism_ref=escrow_uid,
        local_role="seller",
        mechanism_receipt={"verified": True},
        fulfillment_input=VmFulfillmentInput(
            provision=provision,
            listing_id=str(listing_id),
            order=dict(order),
            negotiation_id=negotiation_id,
            site_id=listings_reconciler.site_id_for_listing(
                sqlite_client.db_path, str(listing_id)
            ),
        ),
        projection_context=VmProjectionContext(
            sqlite_client=sqlite_client,
            escrow_uid=escrow_uid,
            negotiation_id=negotiation_id,
            chain_name=proposal_chain,
            escrow_address=proposal.escrow_address,
            obligation_ref=obligation_ref,
            obligation_index=obligation_index,
        ),
    )


async def reserve_vm_settlement_start(
    prepared: PreparedSettlement,
    escrow_uid: str,
    negotiation_id: str,
) -> dict[str, Any] | None:
    context = prepared.projection_context
    if not isinstance(context, VmProjectionContext):
        raise TypeError("VM settlement projection context is missing")
    inserted = await context.sqlite_client.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id=negotiation_id,
        chain_name=context.chain_name,
        escrow_address=context.escrow_address,
        is_primary=True,
        status="provisioning",
    )
    row = await context.sqlite_client.bind_escrow_obligation(
        escrow_uid=escrow_uid,
        obligation_ref=context.obligation_ref,
        obligation_index=context.obligation_index,
    )
    if not inserted:
        logger.info(
            "[SETTLE_JOB] Job already exists for escrow %s: status=%s",
            escrow_uid,
            row.get("status"),
        )
        return row
    return None


async def fulfill_vm_settlement(
    prepared: PreparedSettlement,
    *,
    mechanism_client: Any,
) -> FulfillmentOutcome:
    fulfillment_input = prepared.fulfillment_input
    if not isinstance(fulfillment_input, VmFulfillmentInput):
        raise TypeError("VM settlement fulfillment input is missing")
    fulfillment = domain_runtime.get_market_domain_contract().fulfillment
    if fulfillment is None:
        raise RuntimeError("VM fulfillment capability is not installed")
    selected_obligation = prepared.obligations[prepared.selected_obligation_index]
    hosted = selected_obligation.get("mechanism") == "fiat.stripe.v1"
    delivery_client = fulfillment_input.evidence_client if hosted else mechanism_client
    delivery_anchor = (
        fulfillment_input.fulfillment_anchor if hosted else prepared.mechanism_ref
    )
    if not delivery_anchor:
        raise ValueError("settlement fulfillment anchor is unavailable")
    result = await fulfillment.fulfill(
        client=delivery_client,
        escrow_uid=delivery_anchor,
        ssh_public_key=fulfillment_input.provision.ssh_public_key,
        order=fulfillment_input.order,
        duration_seconds=fulfillment_input.provision.duration_seconds,
        start_utc=fulfillment_input.provision.start_utc,
        listing_id=fulfillment_input.listing_id,
        negotiation_id=fulfillment_input.negotiation_id,
        site_id=fulfillment_input.site_id,
    )
    result = dict(result or {})
    if result.get("status") != "fulfilled":
        return FulfillmentOutcome(
            status="failed",
            public_result={
                "status": result.get("status"),
                "message": result.get("message"),
            },
            private_result=result,
            reason=result.get("message") or f"status={result.get('status')!r}",
        )
    fulfillment_uid = result.get("fulfillment_uid")
    if not isinstance(fulfillment_uid, str) or not fulfillment_uid.strip():
        return FulfillmentOutcome(
            status="failed",
            public_result={"status": "error", "message": "missing fulfillment UID"},
            private_result=result,
            reason="fulfilled VM did not produce an immutable fulfillment UID",
        )
    fulfillment_ref = fulfillment_uid
    if hosted:
        raw_condition = selected_obligation.get("params", {}).get("condition")
        condition = ConditionDescriptor.model_validate(raw_condition)
        evidence_mode = fulfillment_input.evidence_mode
        resolver_id = fulfillment_input.evidence_resolver_id
        if evidence_mode not in {"eas.v1", "portable-remote.v1"} or not resolver_id:
            raise ValueError("hosted evidence resolver configuration is unavailable")
        fulfillment_ref = encode_hosted_fulfillment_ref(
            condition=condition,
            fulfillment_uid=fulfillment_uid,
            evidence_mode=evidence_mode,
            resolver_id=resolver_id,
        )
    public_result: dict[str, Any] = {
        "status": "fulfilled",
        "fulfillment_uid": fulfillment_uid,
    }
    if not hosted:
        public_result.update(
            {
                "message": result.get("message"),
                "escrow_uid": prepared.mechanism_ref,
            }
        )
    return FulfillmentOutcome(
        status="fulfilled",
        fulfillment_ref=fulfillment_ref,
        public_result=public_result,
        private_result=result,
    )


async def persist_vm_settlement_outcome(
    prepared: PreparedSettlement,
    outcome: FulfillmentOutcome,
) -> None:
    context = prepared.projection_context
    if not isinstance(context, VmProjectionContext):
        raise TypeError("VM settlement projection context is missing")
    private = outcome.private_result if isinstance(outcome.private_result, dict) else {}
    if outcome.status == "fulfilled":
        await context.sqlite_client.update_escrow(
            escrow_uid=context.escrow_uid,
            status="ready",
            fulfillment_uid=outcome.fulfillment_ref,
            connection_details=private.get("connection_details"),
            tenant_credentials=(
                json.dumps(private.get("tenant_credentials"))
                if private.get("tenant_credentials") is not None
                else None
            ),
        )
        stage_event(
            "claims",
            "claim_submitted",
            claim_ref=context.obligation_ref,
            obligation_ref=context.obligation_ref,
            escrow_uid=context.escrow_uid,
            mechanism=prepared.obligations[context.obligation_index].get("mechanism"),
            negotiation_id=context.negotiation_id,
            listing_id=prepared.fulfillment_input.listing_id,
            obligation_index=context.obligation_index,
        )
        logger.info("[SETTLE_JOB] Escrow %s provisioning complete", context.escrow_uid)
        return
    reason = outcome.reason or private.get("message") or "provisioning failed"
    await context.sqlite_client.update_escrow(
        escrow_uid=context.escrow_uid,
        status="failed",
        reason=str(reason),
    )
    logger.warning(
        "[SETTLE_JOB] Escrow %s provisioning did not succeed: %s",
        context.escrow_uid,
        reason,
    )


def serialize_settlement_job(row: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve the legacy settle route's public/private response projection."""
    out: dict[str, Any] = {
        "escrow_uid": row.get("escrow_uid"),
        "negotiation_id": row.get("negotiation_id"),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    for field in (
        "fulfillment_uid",
        "fulfillment_id",
        "chain_name",
        "escrow_address",
        "provisioning_job_id",
        "connection_details",
        "reason",
    ):
        value = row.get(field)
        if value is not None:
            out[field] = value
    if row.get("is_primary") is not None:
        out["is_primary"] = bool(row["is_primary"])
    tenant_credentials = row.get("tenant_credentials")
    if tenant_credentials:
        try:
            out["tenant_credentials"] = json.loads(tenant_credentials)
        except Exception:
            out["tenant_credentials"] = tenant_credentials
    return out


async def truncate_lease_for_terminal_settlement(
    *, escrow_uid: str | None, reason: str | None = None, sqlite_client: Any
) -> dict[str, Any] | None:
    """End capacity service when the shared runtime abandons settlement."""
    if not escrow_uid:
        return None

    try:
        capacity = build_capacity_client(lambda: sqlite_client)
        reservation_id: str | None = None
        for client in remote_site_clients(capacity).values():
            rows = await client.list_reservations(escrow_uid=escrow_uid)
            held = [
                row
                for row in rows
                if row.get("state")
                in {"reserved", "provisioning", "leased", "releasing"}
            ]
            if held:
                reservation_id = str(held[0]["capacity_reservation_id"])
                break
        if not reservation_id:
            logger.info(
                "[SETTLEMENT] No live reservation to truncate for %s", escrow_uid
            )
            return None
        lease_end = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        truncated = await capacity.truncate_lease(
            capacity_reservation_id=reservation_id,
            lease_end_utc=lease_end,
        )
        stage_event(
            "claims",
            "lease_truncated_after_abandonment",
            escrow_uid=escrow_uid,
            capacity_reservation_id=reservation_id,
            lease_end_utc=lease_end,
            reason=reason,
            site=(truncated or {}).get("site"),
        )
        return truncated
    except Exception as exc:
        logger.warning(
            "[SETTLEMENT] Could not truncate lease for %s: %s", escrow_uid, exc
        )
        return None


@dataclass(frozen=True)
class HostedAgreement:
    negotiation_id: str
    listing_id: str
    buyer_address: str
    obligation: dict[str, Any]
    obligation_ref: str
    provision: VmProvisionTerms
    order: dict[str, Any]


def _plain_mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return dict(value) if isinstance(value, Mapping) else {}


async def load_hosted_agreement(
    *,
    sqlite_client: Any,
    negotiation_id: str,
    obligation_ref: str | None = None,
) -> HostedAgreement:
    """Reload one exact accepted hosted obligation from marketplace state."""
    thread = await sqlite_client.load_negotiation_thread_row(
        negotiation_id=negotiation_id
    )
    if not thread or thread.get("terminal_state") != "success":
        raise ValueError("hosted settlement negotiation is not accepted")
    buyer_address = str(thread.get("buyer") or "")
    if not buyer_address:
        raise ValueError("accepted hosted negotiation has no buyer identity")
    listing_id = str(thread.get("our_listing_id") or "")
    order = await sqlite_client.load_listing(listing_id=listing_id)
    if not order:
        raise ValueError("accepted hosted listing is unavailable")
    raw_plan = thread.get("settlement_plan")
    if not isinstance(raw_plan, dict):
        raise ValueError("accepted negotiation has no pinned settlement plan")
    plan = SettlementPlan.model_validate(raw_plan)
    if len(plan.obligations) != 1:
        raise ValueError("hosted settlement plan must contain exactly one obligation")
    obligation = plan.obligations[0].model_dump(mode="json")
    if obligation.get("mechanism") != "fiat.stripe.v1":
        raise ValueError("accepted negotiation did not select hosted settlement")
    derived_ref = derive_obligation_ref(negotiation_id, 0, obligation)
    if obligation_ref is not None and obligation_ref != derived_ref:
        raise ValueError("hosted obligation identifier does not match accepted plan")
    provision = VmProvisionTerms.model_validate(thread.get("provision_terms"))
    return HostedAgreement(
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        buyer_address=buyer_address,
        obligation=obligation,
        obligation_ref=derived_ref,
        provision=provision,
        order=dict(order),
    )


def _hosted_evidence_input(
    *,
    composition: VmSettlementComposition,
    condition: ConditionDescriptor,
) -> tuple[str, str, Any]:

    resolver_id = condition.evaluator.resolver_id
    if not resolver_id:
        raise ValueError("hosted condition has no configured evidence resolver")
    hosted_config = getattr(storefront_config.settings, "hosted_settlement", None)
    resolvers = _plain_mapping(getattr(hosted_config, "resolvers", {}))
    resolver = _plain_mapping(resolvers.get(resolver_id))
    chain_name = str(resolver.get("chain_name") or "")
    evidence_mode = str(resolver.get("evidence_mode") or "")
    if evidence_mode not in {"eas.v1", "portable-remote.v1"}:
        raise ValueError("hosted evidence mode is not configured")
    client = composition.evidence_clients.get(chain_name)
    if client is None:
        raise ValueError("hosted evidence chain is not configured")
    return resolver_id, evidence_mode, client


async def ensure_hosted_fulfillment(
    *,
    composition: VmSettlementComposition,
    sqlite_client: Any,
    record: Any,
    worker_id: str,
) -> Any:
    """Provision once after authoritative funding, then bind safe evidence."""
    if record.fulfillment_ref:
        await composition.worker.wake(record.obligation_ref)
        return record
    if record.mechanism_status != "ready":
        return record
    reserved = await composition.runtime.reserve_fulfillment(
        record.obligation_ref,
        local_role="seller",
        worker_id=worker_id,
    )
    if reserved.status in {"busy", "succeeded"}:
        row = await composition.repository.load_settlement_obligation(
            record.obligation_ref
        )
        return type(record).model_validate(row)
    agreement = await load_hosted_agreement(
        sqlite_client=sqlite_client,
        negotiation_id=record.agreement_ref,
        obligation_ref=record.obligation_ref,
    )
    condition = ConditionDescriptor.model_validate(
        agreement.obligation.get("params", {}).get("condition")
    )
    resolver_id, evidence_mode, evidence_client = _hosted_evidence_input(
        composition=composition,
        condition=condition,
    )
    if not record.condition_anchor:
        error = ValueError("hosted authority returned no immutable condition anchor")
        await composition.runtime.retry_fulfillment(
            record.obligation_ref,
            error,
            local_role="seller",
            worker_id=worker_id,
        )
        raise error
    prepared = PreparedSettlement(
        agreement_ref=agreement.negotiation_id,
        obligations=(agreement.obligation,),
        selected_obligation_index=0,
        local_role="seller",
        mechanism_ref=str(record.mechanism_ref),
        mechanism_receipt=record.status_receipt,
        fulfillment_input=VmFulfillmentInput(
            provision=agreement.provision,
            listing_id=agreement.listing_id,
            order=agreement.order,
            negotiation_id=agreement.negotiation_id,
            site_id=None,
            fulfillment_anchor=record.condition_anchor,
            evidence_mode=evidence_mode,
            evidence_resolver_id=resolver_id,
            evidence_client=evidence_client,
        ),
    )
    try:
        outcome = await fulfill_vm_settlement(
            prepared,
            mechanism_client=composition.mechanism_clients["fiat.stripe.v1"],
        )
        if outcome.status != "fulfilled" or not outcome.fulfillment_ref:
            raise RuntimeError("hosted VM fulfillment did not succeed")
        completed = await composition.runtime.complete_fulfillment(
            record.obligation_ref,
            outcome.fulfillment_ref,
            local_role="seller",
            worker_id=worker_id,
        )
    except Exception as exc:
        await composition.runtime.retry_fulfillment(
            record.obligation_ref,
            exc,
            local_role="seller",
            worker_id=worker_id,
        )
        raise
    stage_event(
        "claims",
        "hosted_fulfillment_bound",
        obligation_ref=record.obligation_ref,
        settlement_ref=record.mechanism_ref,
    )
    await composition.worker.wake(record.obligation_ref)
    return completed


def hosted_public_status(record: Any) -> str:
    if record.reclaim_state == "succeeded":
        return "reclaimed"
    if record.collection_state == "succeeded":
        return "collected"
    if (
        record.materialization_state == "manual_required"
        or record.condition_state == "manual_required"
        or record.collection_state == "manual_required"
        or record.reclaim_state == "manual_required"
        or record.mechanism_status == "manual_required"
    ):
        return "manual_required"
    if record.condition_state == "failed" or record.mechanism_status == "failed":
        return "failed"
    if record.mechanism_status == "ready":
        return "ready" if record.fulfillment_ref else "funded"
    return record.mechanism_status or "pending"


async def hosted_settlement_projection(
    *,
    composition: VmSettlementComposition,
    record: Any,
) -> dict[str, Any]:
    action = None
    if record.mechanism_ref and hosted_public_status(record) in {
        "requires_action",
        "pending",
    }:
        adapter = composition.mechanism_clients["fiat.stripe.v1"]
        action = await adapter.get_buyer_action(
            record.mechanism_ref,
            operation_ref=f"arkhai:settlement:{record.obligation_ref}:action",
        )
    return {
        "settlement_ref": record.mechanism_ref,
        "obligation_ref": record.obligation_ref,
        "status": hosted_public_status(record),
        "action": action,
        "action_kind": (record.buyer_action or {}).get("kind"),
        "action_expires_at_unix": (record.buyer_action or {}).get("expires_at_unix"),
    }


async def verify_hosted_contract_ready(
    composition: VmSettlementComposition,
) -> None:

    hosted_config = getattr(storefront_config.settings, "hosted_settlement", None)
    if not hosted_config or not bool(getattr(hosted_config, "enabled", False)):
        return
    adapter = composition.mechanism_clients.get("fiat.stripe.v1")
    if adapter is None:
        raise RuntimeError("hosted settlement is enabled without its adapter")
    expected_manifest = str(
        getattr(hosted_config, "expected_manifest_digest", "") or ""
    )
    expected_contract = str(getattr(hosted_config, "contract_version", "") or "")
    expected_schema = int(getattr(hosted_config, "expected_schema_version", 0) or 0)
    if not expected_manifest or expected_contract != "0.1.0" or expected_schema != 3:
        raise RuntimeError("hosted settlement release pin is incomplete")
    required = tuple(
        sorted(
            {
                "conditional-escrow.v1",
                "stripe-connect-separate-charges-transfers.v1",
                "portable-attestation.v1",
                "eas-arbiter.v1",
                *(
                    str(value)
                    for value in (
                        getattr(hosted_config, "required_capabilities", ()) or ()
                    )
                ),
            }
        )
    )
    await adapter.verify_contract_ready(
        expected_manifest_digest=expected_manifest,
        expected_contract_version=expected_contract,
        expected_schema_version=expected_schema,
        required_capabilities=required,
        operation_ref="storefront-startup",
    )


def build_vm_settlement_composition(
    *, sqlite_client: Any, alkahest_clients: Mapping[str, Any]
) -> VmSettlementComposition:
    """Construct the one VM repository, runtime, coordinator, and worker."""

    repository = SettlementSQLiteRepository(
        sqlite_client.db_path,
        apply_migrations=False,
    )
    alkahest = AlkahestConditionalEscrowClient(
        get_client=lambda chain: alkahest_clients.get(chain or ""),
        chain_config_paths={
            name: config.alkahest_address_config_path
            for name, config in storefront_config.CHAINS.items()
        },
        default_chain=getattr(storefront_config.settings, "chain_name", None),
    )
    mechanism_clients: dict[str, Any] = {"alkahest.v1": alkahest}
    hosted_config = getattr(storefront_config.settings, "hosted_settlement", None)
    hosted_enabled = bool(hosted_config and getattr(hosted_config, "enabled", False))
    hosted_base_url = (
        str(getattr(hosted_config, "base_url", "") or "") if hosted_config else ""
    )
    hosted_credential = (
        str(getattr(hosted_config, "request_credential", "") or "")
        if hosted_config
        else ""
    )
    if hosted_enabled:
        required_fields = {
            "base_url": hosted_base_url,
            "authority_id": str(getattr(hosted_config, "authority_id", "") or ""),
            "environment": str(getattr(hosted_config, "environment", "") or ""),
            "expected_authority": str(
                getattr(hosted_config, "expected_authority", "") or ""
            ),
            "expected_manifest_digest": str(
                getattr(hosted_config, "expected_manifest_digest", "") or ""
            ),
            "contract_version": str(
                getattr(hosted_config, "contract_version", "") or ""
            ),
            "expected_schema_version": (
                int(getattr(hosted_config, "expected_schema_version", 0) or 0)
                if int(getattr(hosted_config, "expected_schema_version", 0) or 0) == 3
                else 0
            ),
            "private_key": hosted_credential,
        }
        missing = sorted(name for name, value in required_fields.items() if not value)
        if missing:
            raise RuntimeError(
                "hosted settlement is enabled with incomplete consumer configuration: "
                + ", ".join(missing)
            )

        hosted = HostedConditionalEscrowClient(
            HostedSettlementAsyncClient(
                ClientConfig(
                    base_url=hosted_base_url,
                    private_key=hosted_credential,
                    caller_role="seller",
                    authority_id=str(getattr(hosted_config, "authority_id", "") or ""),
                    environment=str(getattr(hosted_config, "environment", "") or ""),
                    expected_authority=str(
                        getattr(hosted_config, "expected_authority", "") or ""
                    ),
                    timeout_seconds=float(
                        getattr(hosted_config, "timeout_seconds", 10.0)
                    ),
                    allow_insecure_loopback=bool(
                        getattr(hosted_config, "allow_insecure_loopback", False)
                    ),
                )
            )
        )
        mechanism_clients["fiat.stripe.v1"] = hosted
    runtime = SettlementRuntime(repository, mechanism_clients)

    async def on_terminal(
        record: Any,
        _outcome: str,
        reason: str | None,
    ) -> None:
        if _outcome == "collected":
            return
        await truncate_lease_for_terminal_settlement(
            escrow_uid=getattr(record, "mechanism_ref", None),
            reason=reason,
            sqlite_client=sqlite_client,
        )

    def on_event(event: str, fields: dict[str, Any]) -> None:
        stage_event("claims", event, **fields)

    composition_holder: dict[str, VmSettlementComposition] = {}

    async def on_ready(record: Any, worker_id: str) -> None:
        if record.obligation.get("mechanism") != "fiat.stripe.v1":
            return
        await ensure_hosted_fulfillment(
            composition=composition_holder["value"],
            sqlite_client=sqlite_client,
            record=record,
            worker_id=worker_id,
        )

    worker = SettlementServicingWorker(
        runtime,
        repository,
        worker_id=f"vm-storefront:{storefront_config.AGENT_ID}",
        interval_seconds=float(
            getattr(storefront_config.settings, "claims_sweep_interval", 30)
        ),
        on_event=on_event,
        on_terminal=on_terminal,
        on_ready=on_ready,
    )

    async def wake_servicing(obligation_ref: str) -> None:
        await worker.wake(obligation_ref)

    async def reserve_start(
        prepared: PreparedSettlement,
        escrow_uid: str,
        negotiation_id: str,
    ) -> dict[str, Any] | None:
        existing = await reserve_vm_settlement_start(
            prepared,
            escrow_uid,
            negotiation_id,
        )
        if (
            existing is not None
            and existing.get("status") == "ready"
            and existing.get("fulfillment_uid")
        ):
            context = prepared.projection_context
            assert isinstance(context, VmProjectionContext)
            await runtime.bind_fulfillment(
                context.obligation_ref,
                str(existing["fulfillment_uid"]),
                local_role=prepared.local_role,
            )
            await worker.wake(context.obligation_ref)
        return existing

    coordinator = SettlementJobCoordinator(
        runtime,
        prepare=partial(prepare_vm_settlement, sqlite_client=sqlite_client),
        reserve_start=reserve_start,
        fulfill=fulfill_vm_settlement,
        persist_outcome=persist_vm_settlement_outcome,
        wake_servicing=wake_servicing,
    )
    composition = VmSettlementComposition(
        repository=repository,
        runtime=runtime,
        coordinator=coordinator,
        worker=worker,
        mechanism_clients=mechanism_clients,
        evidence_clients=dict(alkahest_clients),
    )
    composition_holder["value"] = composition
    return composition
