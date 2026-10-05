"""VM composition over the shared commercial-settlement runtime."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

from arkhai_vms import VmProvisionTerms, normalize_vm_provision_terms
from core_storefront.domain_lifecycle import (
    StorefrontFulfillmentContext,
    StorefrontFulfillmentPorts,
    StorefrontSettlementBuildContext,
    StorefrontSettlementFulfillmentInput,
    build_domain_settlement_artifacts,
    fulfill_domain,
)
from core_storefront.stage_log import stage_event
from market_alkahest import create_alkahest_registration
from market_arkhai_payments import (
    ArkhaiPaymentsConfig,
    create_arkhai_payments_registration,
)
from market_core import MarketDomainContract
from market_core.schemas import (
    EscrowProposal,
)
from market_identity import Identity, Signer
from market_settlement_runtime import (
    FulfillmentOutcome,
    MechanismReadiness,
    PreparedSettlement,
    SettlementConfig,
    SettlementConfigurationRegistry,
    SettlementJobCoordinator,
    SettlementPublicationClause,
    SettlementRuntime,
    SettlementServicingWorker,
    SettlementSQLiteRepository,
    compile_settlement_publication_clause,
    derive_obligation_ref,
)

from market_storefront.arkhai_payments import VmArkhaiPaymentsStage
from market_storefront.payment_settlement import VmPaymentsCoordinator
from market_storefront.services.capacity_client import (
    build_capacity_runtime,
    capacity_binding_for_listing,
)
from market_storefront.settlement_stages import resolve_proposal_stage
from market_storefront.utils import config as storefront_config
from market_storefront.utils import escrow_verification

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VmProjectionContext:
    sqlite_client: Any
    escrow_uid: str
    negotiation_id: str
    chain_name: str
    escrow_address: str | None
    obligation_ref: str
    obligation_index: int
    convergence_owner: str = field(default_factory=lambda: f"alkahest:{uuid.uuid4()}")


@dataclass(frozen=True)
class VmSettlementComposition:
    domain: MarketDomainContract
    repository: SettlementSQLiteRepository
    runtime: SettlementRuntime
    coordinator: SettlementJobCoordinator
    worker: SettlementServicingWorker
    local_principal: Identity
    mechanism_clients: Mapping[str, Any]
    evidence_clients: Mapping[str, Any]
    settlement_config: SettlementConfig
    configuration_registry: SettlementConfigurationRegistry
    mechanism_resources: Mapping[str, Any]
    arkhai_payments_stage: VmArkhaiPaymentsStage | None = None
    payments_coordinator: VmPaymentsCoordinator | None = None

    @property
    def seller_stages(self):
        return self.domain.settlement.seller_stages

    async def readiness(self) -> tuple[MechanismReadiness, ...]:
        statuses = await self.configuration_registry.ordered_readiness(
            self.settlement_config,
            role="seller",
            resources=self.mechanism_resources,
        )
        return tuple(
            status for status in statuses if status.mechanism in self.seller_stages
        )

    def accepted_obligation_dispatch(
        self,
    ) -> dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None]:
        """Curried registry dispatch for every enabled obligation-building mechanism."""

        dispatch: dict[
            str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None
        ] = {}
        for mechanism_id in self.settlement_config.priority:
            if mechanism_id not in self.seller_stages:
                continue
            registration = self.configuration_registry.registration(mechanism_id)
            if registration.accepted_obligation_builder is None:
                dispatch[mechanism_id] = None
                continue

            def build(
                option: Mapping[str, Any],
                context: Mapping[str, Any],
                *,
                _mechanism_id: str = mechanism_id,
            ) -> Any:
                return self.configuration_registry.build_accepted_obligation(
                    _mechanism_id,
                    option,
                    self.settlement_config,
                    role="seller",
                    context=context,
                )

            dispatch[mechanism_id] = build
        return dispatch

    async def publication_artifacts(
        self,
        resources: Mapping[str, Any],
        clauses: list[SettlementPublicationClause] | None = None,
    ) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]], tuple[MechanismReadiness, ...]
    ]:
        merged_resources = {**self.mechanism_resources, **resources}
        compiled = (
            [
                compile_settlement_publication_clause(
                    clause,
                    registry=self.configuration_registry,
                    config=self.settlement_config,
                    role="seller",
                )
                for clause in clauses
            ]
            if clauses is not None
            else None
        )

        readiness_resources = merged_resources
        if compiled is not None:
            for clause in compiled:
                if clause.mechanism not in self.seller_stages:
                    raise ValueError(
                        f"settlement publication mechanism {clause.mechanism!r} is unsupported"
                    )
            for mechanism, stage in self.seller_stages.items():
                readiness_resources = {
                    **readiness_resources,
                    **stage.readiness_inputs(
                        [clause for clause in compiled if clause.mechanism == mechanism]
                    ),
                }

        readiness = await self.configuration_registry.ordered_readiness(
            self.settlement_config,
            role="seller",
            resources=readiness_resources,
        )
        readiness = tuple(
            status for status in readiness if status.mechanism in self.seller_stages
        )
        accepted_escrows: list[dict[str, Any]] = []
        settlement_options: list[dict[str, Any]] = []
        statuses = {status.mechanism: status for status in readiness}
        work = (
            [
                (
                    statuses.get(clause.mechanism),
                    {**merged_resources, "publication_clause": clause},
                )
                for clause in compiled
            ]
            if compiled is not None
            else [(status, merged_resources) for status in readiness]
        )
        for status, option_resources in work:
            if status is None:
                raise RuntimeError(
                    "publication clause mechanism has no readiness status"
                )
            if not status.enabled:
                if compiled is not None:
                    raise ValueError(
                        f"settlement publication mechanism {status.mechanism!r} is disabled"
                    )
                continue
            if not status.ready:
                logger.warning(
                    "[SETTLEMENT] option suppressed mechanism=%s blockers=%s",
                    status.mechanism,
                    ",".join(blocker.code for blocker in status.blockers),
                )
                continue
            envelope = self.configuration_registry.build_option(
                status,
                self.settlement_config,
                role="seller",
                resources=option_resources,
            )
            if not isinstance(envelope, Mapping):
                raise RuntimeError(
                    f"settlement option builder {status.mechanism} returned no envelope"
                )
            accepted_escrows.extend(
                dict(item) for item in envelope.get("accepted_escrows", ())
            )
            settlement_options.extend(
                dict(item) for item in envelope.get("settlement_options", ())
            )
        if not accepted_escrows and not settlement_options:
            raise RuntimeError("no enabled settlement mechanism is ready")
        return accepted_escrows, settlement_options, readiness


def build_storefront_settlement_registry() -> SettlementConfigurationRegistry:
    return SettlementConfigurationRegistry(
        (
            create_alkahest_registration(),
            create_arkhai_payments_registration(),
        )
    )


def build_storefront_publication_clause_compiler() -> Callable[
    [Mapping[str, Any]], SettlementPublicationClause
]:
    registry = build_storefront_settlement_registry()
    config = registry.resolve(
        storefront_config.settlement_config_mapping(),
        role="seller",
    )
    return partial(
        compile_settlement_publication_clause,
        registry=registry,
        config=config,
        role="seller",
    )


def _settlement_plan_obligations(
    *,
    domain: MarketDomainContract,
    context: StorefrontSettlementBuildContext,
) -> tuple[dict[str, Any], ...]:
    stage = resolve_proposal_stage(domain.settlement.seller_stages, context.proposal)
    artifacts = build_domain_settlement_artifacts(
        domain, context, build_plan=stage.build_plan
    )
    obligations = artifacts.settlement_plan["obligations"]
    return tuple(dict(item) for item in obligations)


async def prepare_vm_settlement(
    *,
    domain: MarketDomainContract,
    escrow_uid: str,
    negotiation_id: str,
    local_principal: Identity,
    mechanism_client: Any,
    chain_name: str,
    request: Any = None,
    sqlite_client: Any,
) -> PreparedSettlement:
    """Reload, verify, and pin accepted VM terms before provisioning."""
    del request
    thread_binding = await sqlite_client.load_thread_binding(
        negotiation_id=negotiation_id
    )
    selected_domain = sqlite_client.domain_registry.resolve(thread_binding.binding)
    if selected_domain is not domain:
        raise RuntimeError(
            "settlement preparation contract disagrees with accepted binding"
        )

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

    provision = normalize_vm_provision_terms(thread.get("provision_terms"))
    proposal_raw = thread.get("buyer_escrow_proposal")

    if not isinstance(proposal_raw, dict):
        raise ValueError(
            f"Negotiation {negotiation_id} has no persisted accepted escrow proposal"
        )
    proposal = EscrowProposal.model_validate(proposal_raw)
    accepted_chain = proposal.chain_name
    if chain_name != accepted_chain:
        raise ValueError("settlement chain does not match accepted terms")
    chain = storefront_config.CHAINS.get(accepted_chain)
    if chain is None:
        raise ValueError(
            f"chain {accepted_chain!r} is not configured on this storefront"
        )
    obligation_index = await escrow_verification.verify_escrow_for_settlement(
        escrow_uid=escrow_uid,
        seller_wallet=storefront_config.get_evm_wallet_address(),
        agreed_price=int(thread["agreed_price"]),
        agreed_duration_seconds=provision.duration_seconds,
        listing=order,
        alkahest_client=mechanism_client,
        chain_name=accepted_chain,
        alkahest_address_config_path=chain.alkahest_address_config_path,
        escrow_proposal=proposal,
    )
    if not isinstance(obligation_index, int):
        raise ValueError("escrow verification did not identify an exact obligation")

    buyer_principal = Identity.model_validate(thread.get("buyer_principal"))
    obligations = _settlement_plan_obligations(
        domain=domain,
        context=StorefrontSettlementBuildContext(
            binding=thread_binding.binding,
            negotiation_id=negotiation_id,
            listing_id=str(listing_id),
            site_id=thread_binding.site_id,
            proposal=proposal,
            agreed_amount=int(thread["agreed_price"]),
            duration_seconds=provision.duration_seconds,
            buyer_principal=buyer_principal,
            seller_principal=local_principal,
            seller_wallet_address=storefront_config.get_evm_wallet_address(),
            chain_config_paths={
                name: config.alkahest_address_config_path
                for name, config in storefront_config.CHAINS.items()
            },
        ),
    )
    if obligation_index < 0 or obligation_index >= len(obligations):
        raise ValueError(
            f"verified obligation index {obligation_index} is outside the accepted plan"
        )
    obligation_ref = derive_obligation_ref(
        negotiation_id, obligation_index, obligations[obligation_index]
    )

    proposal_chain = accepted_chain
    raw = thread.get("agreement_bytes")
    if not isinstance(raw, bytes):
        raise ValueError("accepted Agreement bytes are unavailable")
    agreement = json.loads(raw)
    stage = domain.settlement.seller_stages[agreement["settlement"]["mechanism"]]
    evidence = stage.verified_evidence(
        raw=raw,
        order=dict(order),
        chain_configs=storefront_config.CHAINS,
        source={
            "escrow_uid": escrow_uid,
            "chain_name": accepted_chain,
            "escrow_address": proposal.escrow_address,
            "obligation_ref": obligation_ref,
            "obligation_index": obligation_index,
            "expiration_unix": proposal.expiration_unix,
        },
    )
    await sqlite_client.save_vm_settlement_evidence(evidence)

    return PreparedSettlement(
        agreement_ref=negotiation_id,
        obligations=obligations,
        selected_obligation_index=obligation_index,
        mechanism_ref=escrow_uid,
        local_principal=local_principal,
        mechanism_receipt={"verified": True},
        fulfillment_input=StorefrontSettlementFulfillmentInput(
            buyer_principal=buyer_principal,
            thread_binding=thread_binding,
            settlement_evidence=evidence,
            domain_input={
                "provision": provision,
                "listing_id": str(listing_id),
                "order": dict(order),
            },
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
    evidence = prepared.fulfillment_input.settlement_evidence
    if evidence is None or evidence.status != "verified":
        raise ValueError("VM delivery requires verified settlement evidence")
    await context.sqlite_client.save_vm_settlement_evidence(evidence)
    await context.sqlite_client.insert_vm_delivery(negotiation_id=negotiation_id)
    if inserted:
        start_utc = (
            evidence.evidence.get("delivery", {}).get("payload", {}).get("start_utc")
        )
        start = (
            datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
            if start_utc
            else datetime.now(timezone.utc)
        )
        claimed = await context.sqlite_client.claim_vm_delivery(
            negotiation_id=negotiation_id,
            owner=context.convergence_owner,
            lease_until=(
                max(start, datetime.now(timezone.utc))
                + timedelta(
                    seconds=float(storefront_config.settings.provisioning.timeout) + 60,
                )
            ).isoformat(),
        )
        if not claimed:
            return row
    if not inserted:
        logger.info(
            "[SETTLE_JOB] Job already exists for escrow %s: status=%s",
            escrow_uid,
            row.get("status"),
        )
        return row
    return None


async def fulfill_vm_settlement(
    domain: MarketDomainContract,
    prepared: PreparedSettlement,
    *,
    sqlite_client: Any,
    mechanism_client: Any,
    bind_fulfillment_fn: Any = None,
) -> FulfillmentOutcome:
    fulfillment_input = prepared.fulfillment_input
    if not isinstance(fulfillment_input, StorefrontSettlementFulfillmentInput):
        raise TypeError("storefront settlement fulfillment input is missing")
    domain_input = fulfillment_input.domain_input
    provision = domain_input.get("provision")
    listing_id = domain_input.get("listing_id")
    order = domain_input.get("order")
    if not isinstance(provision, VmProvisionTerms):
        raise TypeError("VM settlement provision input is missing")
    if not isinstance(listing_id, str) or not isinstance(order, dict):
        raise TypeError("VM settlement listing input is missing")
    delivery_anchor = prepared.mechanism_ref
    if not delivery_anchor:
        raise ValueError("settlement fulfillment anchor is unavailable")
    if (
        fulfillment_input.settlement_evidence is None
        or fulfillment_input.settlement_evidence.status != "verified"
    ):
        raise ValueError("VM fulfillment requires verified settlement evidence")
    evidence = fulfillment_input.settlement_evidence
    thread = await sqlite_client.load_negotiation_thread_row(
        negotiation_id=evidence.negotiation_id
    )
    agreement = json.loads(thread["agreement_bytes"])
    stage = domain.settlement.seller_stages[agreement["settlement"]["mechanism"]]
    lifecycle = await fulfill_domain(
        domain,
        StorefrontFulfillmentContext(
            thread_binding=fulfillment_input.thread_binding,
            settlement_evidence=fulfillment_input.settlement_evidence,
            buyer_principal=fulfillment_input.buyer_principal,
            ports=StorefrontFulfillmentPorts(
                repository=sqlite_client,
                capacity_client=None,
                fulfillment_client=None,
            ),
            domain_input={
                "failure_policy": partial(
                    stage.delivery_failed, evidence=evidence, db=sqlite_client
                )
            },
        ),
    )
    result = (
        dict(lifecycle.domain_result)
        if isinstance(lifecycle.domain_result, Mapping)
        else {}
    )
    if lifecycle.state != "fulfilled":
        return FulfillmentOutcome(
            status="failed",
            public_result={
                "status": result.get("status"),
                "message": result.get("message"),
            },
            private_result=result,
            reason=result.get("message") or f"status={result.get('status')!r}",
        )
    delivery = await sqlite_client.load_vm_delivery(
        negotiation_id=evidence.negotiation_id
    )
    fulfillment_uid = await stage.continue_delivery(
        evidence=evidence,
        db=sqlite_client,
        delivery=delivery,
        connection_json=result["connection_details"],
        client=mechanism_client,
        bind=bind_fulfillment_fn,
    )
    if not isinstance(fulfillment_uid, str) or not fulfillment_uid.strip():
        return FulfillmentOutcome(
            status="failed",
            public_result={"status": "error", "message": "missing fulfillment UID"},
            private_result=result,
            reason="fulfilled VM did not produce an immutable fulfillment UID",
        )
    fulfillment_ref = fulfillment_uid
    public_result: dict[str, Any] = {
        "status": "fulfilled",
        "fulfillment_uid": fulfillment_uid,
    }
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
    fulfillment_input = prepared.fulfillment_input
    if not isinstance(fulfillment_input, StorefrontSettlementFulfillmentInput):
        raise TypeError("storefront settlement fulfillment input is missing")
    listing_id = fulfillment_input.domain_input.get("listing_id")
    if not isinstance(listing_id, str):
        raise TypeError("VM settlement listing input is missing")
    private = outcome.private_result if isinstance(outcome.private_result, dict) else {}
    await context.sqlite_client.update_vm_delivery(
        negotiation_id=context.negotiation_id,
        status="ready" if outcome.status == "fulfilled" else "failed",
        fulfillment_uid=outcome.fulfillment_ref,
        connection_details=private.get("connection_details"),
        tenant_credentials=json.dumps(private["tenant_credentials"])
        if private.get("tenant_credentials") is not None
        else None,
        reason=outcome.reason,
    )
    await context.sqlite_client.release_vm_delivery(
        negotiation_id=context.negotiation_id, owner=context.convergence_owner
    )
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
            listing_id=listing_id,
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
    for key in (
        "obligation_ref",
        "fulfillment_uid",
        "fulfillment_id",
        "chain_name",
        "escrow_address",
        "provisioning_job_id",
        "connection_details",
        "reason",
    ):
        value = row.get(key)
        if value is not None:
            out[key] = value
    if row.get("is_primary") is not None:
        out["is_primary"] = bool(row["is_primary"])
    tenant_credentials = row.get("tenant_credentials")
    if tenant_credentials:
        try:
            out["tenant_credentials"] = json.loads(tenant_credentials)
        except Exception:
            out["tenant_credentials"] = tenant_credentials
    return out


def _terminal_requires_lease_truncation(record: Any, outcome: str) -> bool:
    """Only uncollected terminal obligations abandon VM capacity service."""

    return (
        outcome != "collected"
        and getattr(record, "collection_state", None) != "succeeded"
    )


async def truncate_lease_for_terminal_settlement(
    *, agreement_ref: str | None, reason: str | None = None, sqlite_client: Any
) -> dict[str, Any] | None:
    """End capacity service through the agreement's durable reservation binding."""
    if not agreement_ref:
        return None

    try:
        escrow = await sqlite_client.load_primary_escrow_for_negotiation(
            negotiation_id=agreement_ref
        )
        reservation_id = (
            str(escrow.get("capacity_reservation_id") or "") if escrow else ""
        )
        if not reservation_id:
            logger.info(
                "[SETTLEMENT] Agreement %s has no bound capacity reservation",
                agreement_ref,
            )
            return None
        thread = await sqlite_client.load_negotiation_thread_row(
            negotiation_id=agreement_ref
        )
        listing_id = str((thread or {}).get("our_listing_id") or "")
        if not listing_id:
            raise RuntimeError("terminal settlement has no durable listing binding")
        binding = await capacity_binding_for_listing(sqlite_client, listing_id)
        capacity = build_capacity_runtime(lambda: sqlite_client)
        lease_end = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        truncated = await capacity.truncate_lease(
            binding,
            capacity_reservation_id=reservation_id,
            lease_end_utc=lease_end,
        )
        if truncated is None:
            logger.info(
                "[SETTLEMENT] Bound reservation %s for agreement %s "
                "has no live lease to truncate",
                reservation_id,
                agreement_ref,
            )
            return None
        stage_event(
            "claims",
            "lease_truncated_after_abandonment",
            agreement_ref=agreement_ref,
            capacity_reservation_id=reservation_id,
            lease_end_utc=lease_end,
            reason=reason,
            site=truncated.get("site"),
        )
        return truncated
    except Exception:
        logger.exception(
            "[SETTLEMENT] Could not truncate lease for agreement %s",
            agreement_ref,
        )
        raise


def _plain_mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif hasattr(value, "to_dict"):
        value = value.to_dict()
    return dict(value) if isinstance(value, Mapping) else {}


_CURRENCY_CODE = re.compile(r"^[a-z]{3}$")
_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")
_CONTRACT_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")


async def preflight_settlement_mechanisms(
    composition: VmSettlementComposition,
) -> tuple[MechanismReadiness, ...]:
    """Observe every enabled registration and log only sanitized status."""
    readiness = await composition.readiness()
    for status in readiness:
        logger.log(
            logging.INFO if status.ready or not status.enabled else logging.WARNING,
            "[SETTLEMENT] mechanism=%s configured=%s enabled=%s ready=%s blockers=%s",
            status.mechanism,
            status.configured,
            status.enabled,
            status.ready,
            ",".join(blocker.code for blocker in status.blockers),
        )
    return readiness


def build_vm_settlement_composition(
    *,
    domain: MarketDomainContract,
    sqlite_client: Any,
    alkahest_clients: Mapping[str, Any],
    marketplace_signer: Signer,
) -> VmSettlementComposition:
    """Construct the VM runtime from explicit settlement mechanisms."""
    registry_owner = getattr(sqlite_client, "domain_registry", None)
    if registry_owner is None:
        raise RuntimeError(
            "settlement composition requires a repository-owned domain registry"
        )
    registry_owner.registration_for_contract(domain)

    repository = SettlementSQLiteRepository(
        sqlite_client.db_path,
        apply_migrations=False,
    )
    registry = build_storefront_settlement_registry()
    settlement_config = registry.resolve(
        storefront_config.settlement_config_mapping(),
        role="seller",
    )
    mechanism_resources: dict[str, Any] = {
        "marketplace_signer": marketplace_signer,
        "clients": dict(alkahest_clients),
        "get_client": lambda chain: alkahest_clients.get(chain or ""),
        "chains": storefront_config.CHAINS,
        "default_chain": getattr(storefront_config.settings, "chain_name", None),
    }
    alkahest_section = settlement_config.mechanism_config("alkahest")
    if alkahest_section is not None and (
        bool(getattr(alkahest_section, "enabled", False)) or alkahest_clients
    ):
        mechanism_resources["wallet"] = {
            "address": storefront_config.get_evm_wallet_address(),
            "private_key": storefront_config.get_evm_wallet_private_key(),
        }

    mechanism_clients: dict[str, Any] = {}
    for registration in registry.ordered_registrations(
        settlement_config,
        role="seller",
    ):
        section = settlement_config.mechanism_config(registration.config_key)
        if registration.client_factory is None:
            continue
        if section is None:
            continue
        try:
            mechanism_clients[registration.mechanism_id] = registry.create_client(
                registration.mechanism_id,
                settlement_config,
                role="seller",
                resources=mechanism_resources,
            )
        except (TypeError, ValueError):
            if getattr(section, "enabled", False):
                raise
            logger.debug(
                "[SETTLEMENT] disabled mechanism has no recoverable client: %s",
                registration.mechanism_id,
            )
    evidence_clients = dict(alkahest_clients)
    # A fulfillment attempt provisions a VM, and the storefront gives that its
    # own bound. The operation lease has to outlive it, or the deal is handed to
    # a second worker while the first is still provisioning.
    runtime = SettlementRuntime(
        repository,
        mechanism_clients,
        fulfillment_lease_seconds=max(
            30.0, float(storefront_config.settings.provisioning.timeout)
        ),
    )

    async def on_terminal(
        record: Any,
        _outcome: str,
        reason: str | None,
    ) -> None:
        if not _terminal_requires_lease_truncation(record, _outcome):
            return
        await truncate_lease_for_terminal_settlement(
            agreement_ref=getattr(record, "agreement_ref", None),
            reason=reason,
            sqlite_client=sqlite_client,
        )

    def on_event(event: str, fields: dict[str, Any]) -> None:
        stage_event("claims", event, **fields)

    worker = SettlementServicingWorker(
        runtime,
        repository,
        worker_id=f"vm-storefront:{storefront_config.AGENT_ID}",
        interval_seconds=float(
            getattr(storefront_config.settings, "claims_sweep_interval", 30)
        ),
        on_event=on_event,
        on_terminal=on_terminal,
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
                local_principal=prepared.local_principal,
            )
            await worker.wake(context.obligation_ref)
        return existing

    async def bind_delivery_claim(*, obligation_ref: str, fulfillment_ref: str) -> None:
        await runtime.bind_fulfillment(
            obligation_ref,
            fulfillment_ref,
            local_principal=marketplace_signer.identity,
        )

    coordinator = SettlementJobCoordinator(
        runtime,
        prepare=partial(
            prepare_vm_settlement,
            domain=domain,
            sqlite_client=sqlite_client,
            local_principal=marketplace_signer.identity,
        ),
        reserve_start=reserve_start,
        fulfill=partial(
            fulfill_vm_settlement,
            domain,
            sqlite_client=sqlite_client,
            bind_fulfillment_fn=bind_delivery_claim,
        ),
        persist_outcome=persist_vm_settlement_outcome,
        wake_servicing=wake_servicing,
    )
    payments_config = settlement_config.mechanism_config("arkhai_payments")
    payments_stage = (
        VmArkhaiPaymentsStage(ArkhaiPaymentsConfig.model_validate(payments_config))
        if payments_config is not None
        else None
    )
    composition = VmSettlementComposition(
        domain=domain,
        repository=repository,
        runtime=runtime,
        coordinator=coordinator,
        worker=worker,
        mechanism_clients=mechanism_clients,
        evidence_clients=evidence_clients,
        local_principal=marketplace_signer.identity,
        settlement_config=settlement_config,
        configuration_registry=registry,
        mechanism_resources=mechanism_resources,
        arkhai_payments_stage=payments_stage,
        payments_coordinator=VmPaymentsCoordinator(
            domain=domain, db=sqlite_client, stage=payments_stage
        )
        if payments_stage is not None
        else None,
    )
    return composition
