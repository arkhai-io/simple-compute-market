"""VM composition over the shared commercial-settlement runtime."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
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
from market_core import MarketDomainContract
from market_core.schemas import (
    EscrowProposal,
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
)
from market_hosted_settlement import (
    ConditionDescriptor,
    FundingMode,
    FundingProfile,
    create_stripe_registration,
    hosted_projected_reason,
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

from market_storefront.hosted_evidence import encode_hosted_fulfillment_ref
from market_storefront.services.capacity_client import (
    build_capacity_runtime,
    capacity_binding_for_listing,
)
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

    async def readiness(self) -> tuple[MechanismReadiness, ...]:
        return await self.configuration_registry.ordered_readiness(
            self.settlement_config,
            role="seller",
            resources=self.mechanism_resources,
        )

    def accepted_obligation_dispatch(
        self,
    ) -> dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any]]:
        """Curried registry dispatch for every enabled obligation-building mechanism."""

        dispatch: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any]] = {}
        for mechanism_id in self.settlement_config.priority:
            registration = self.configuration_registry.registration(mechanism_id)
            if registration.accepted_obligation_builder is None:
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
            alkahest_chains = tuple(
                dict.fromkeys(
                    str(clause.mechanism_input["chain"])
                    for clause in compiled
                    if clause.mechanism == "alkahest.v1"
                    and isinstance(clause.mechanism_input.get("chain"), str)
                )
            )
            if alkahest_chains:
                readiness_resources = {
                    **merged_resources,
                    "accepted_escrows": [
                        {"chain_name": chain_name} for chain_name in alkahest_chains
                    ],
                }
            hosted_clauses = [
                clause.model_dump(mode="json")
                for clause in compiled
                if clause.mechanism == "fiat.stripe.v1"
            ]
            if hosted_clauses:
                readiness_resources = {
                    **readiness_resources,
                    "publication_clauses": hosted_clauses,
                }

        readiness = await self.configuration_registry.ordered_readiness(
            self.settlement_config,
            role="seller",
            resources=readiness_resources,
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
            if (
                not envelope.get("accepted_escrows")
                and not envelope.get("settlement_options")
                and status.mechanism == "fiat.stripe.v1"
            ):
                clause = option_resources.get("publication_clause")
                mechanism_input = getattr(clause, "mechanism_input", {})
                profile = (
                    mechanism_input.get("funding_profile")
                    if isinstance(mechanism_input, Mapping)
                    else None
                )
                profile_details = (
                    status.public_details.get("profiles", {}).get(str(profile), {})
                    if isinstance(status.public_details, Mapping)
                    else {}
                )
                blocker_codes = ",".join(
                    str(blocker.get("code"))
                    for blocker in profile_details.get("blockers", ())
                    if isinstance(blocker, Mapping) and blocker.get("code")
                )
                logger.warning(
                    "[SETTLEMENT] option suppressed mechanism=%s profile=%s blockers=%s",
                    status.mechanism,
                    profile,
                    blocker_codes,
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
            create_stripe_registration(),
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
    artifacts = build_domain_settlement_artifacts(domain, context)
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

    if (
        isinstance(proposal_raw, dict)
        and isinstance(proposal_raw.get("settlement_selection"), dict)
        and proposal_raw["settlement_selection"].get("mechanism") == "fiat.stripe.v1"
    ):
        raise ValueError(
            "hosted settlement must start through the accepted settlement endpoint"
        )
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
) -> FulfillmentOutcome:
    fulfillment_input = prepared.fulfillment_input
    if not isinstance(
        fulfillment_input, StorefrontSettlementFulfillmentInput
    ):
        raise TypeError("storefront settlement fulfillment input is missing")
    domain_input = fulfillment_input.domain_input
    provision = domain_input.get("provision")
    listing_id = domain_input.get("listing_id")
    order = domain_input.get("order")
    if not isinstance(provision, VmProvisionTerms):
        raise TypeError("VM settlement provision input is missing")
    if not isinstance(listing_id, str) or not isinstance(order, dict):
        raise TypeError("VM settlement listing input is missing")
    selected_obligation = prepared.obligations[prepared.selected_obligation_index]
    hosted = selected_obligation.get("mechanism") == "fiat.stripe.v1"
    delivery_client = fulfillment_input.evidence_client if hosted else mechanism_client
    delivery_anchor = (
        fulfillment_input.fulfillment_anchor if hosted else prepared.mechanism_ref
    )
    if not delivery_anchor:
        raise ValueError("settlement fulfillment anchor is unavailable")
    lifecycle = await fulfill_domain(
        domain,
        StorefrontFulfillmentContext(
            thread_binding=fulfillment_input.thread_binding,
            escrow_uid=delivery_anchor,
            buyer_principal=fulfillment_input.buyer_principal,
            ports=StorefrontFulfillmentPorts(
                repository=sqlite_client,
                capacity_client=None,
                fulfillment_client=delivery_client,
            ),
            domain_input={
                "ssh_public_key": provision.ssh_public_key,
                "order": order,
                "duration_seconds": provision.duration_seconds,
                "start_utc": provision.start_utc,
                "listing_id": listing_id,
                "settlement_mechanism": str(
                    selected_obligation.get("mechanism") or ""
                ),
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
    fulfillment_uid = lifecycle.fulfillment_id or result.get("fulfillment_uid")
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
        evidence_mode = domain_input.get("evidence_mode")
        resolver_id = domain_input.get("evidence_resolver_id")
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
    fulfillment_input = prepared.fulfillment_input
    if not isinstance(
        fulfillment_input, StorefrontSettlementFulfillmentInput
    ):
        raise TypeError("storefront settlement fulfillment input is missing")
    listing_id = fulfillment_input.domain_input.get("listing_id")
    if not isinstance(listing_id, str):
        raise TypeError("VM settlement listing input is missing")
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
    for field in (
        "obligation_ref",
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


@dataclass(frozen=True)
class HostedAgreement:
    negotiation_id: str
    listing_id: str
    buyer_principal: Identity
    seller_principal: Identity
    obligation: dict[str, Any]
    obligation_ref: str
    funding_profile: FundingProfile
    legacy_recovery: bool
    provision: VmProvisionTerms
    order: dict[str, Any]


def _plain_mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif hasattr(value, "to_dict"):
        value = value.to_dict()
    return dict(value) if isinstance(value, Mapping) else {}



_CURRENCY_CODE = re.compile(r"^[a-z]{3}$")
_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")
_CONTRACT_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_HOSTED_PARAMS = frozenset(
    {
        "payer_profile_ref",
        "instrument_ref",
        "customer_id",
        "payment_method_id",
        "mandate",
        "client_secret",
        "action",
        "url",
        "bank_instructions",
    }
)


def _accepted_hosted_profile(
    obligation: Mapping[str, Any],
    *,
    buyer_principal: Identity,
    seller_principal: Identity,
    allow_legacy_recovery: bool,
) -> tuple[FundingProfile, bool]:
    if obligation.get("payer") != "buyer" or obligation.get("claimant") != "seller":
        raise ValueError("hosted settlement parties do not match the accepted roles")
    if Identity.model_validate(obligation.get("payer_principal")) != buyer_principal:
        raise ValueError("hosted payer principal does not match accepted state")
    if Identity.model_validate(obligation.get("claimant_principal")) != seller_principal:
        raise ValueError("hosted claimant principal does not match accepted state")
    params = _plain_mapping(obligation.get("params"))
    if Identity.model_validate(params.get("payer_principal")) != buyer_principal:
        raise ValueError("hosted payer parameter does not match accepted state")
    if Identity.model_validate(params.get("claimant_principal")) != seller_principal:
        raise ValueError("hosted claimant parameter does not match accepted state")
    if params.get("funds_flow") != "separate_charges_transfers":
        raise ValueError("hosted settlement funds flow does not match the contract")
    condition = ConditionDescriptor.model_validate(params.get("condition"))
    conditions = obligation.get("conditions")
    forbidden = sorted(_FORBIDDEN_HOSTED_PARAMS.intersection(params))
    if forbidden:
        raise ValueError(
            "accepted hosted obligation contains forbidden payer/provider fields: "
            + ", ".join(forbidden)
        )
    account_ref = params.get("account_ref")
    if (
        not isinstance(account_ref, str)
        or not account_ref
        or account_ref != account_ref.strip()
    ):
        raise ValueError("accepted hosted obligation has no exact account reference")
    if "funding_authorization_ref" in params:
        raise ValueError("accepted hosted plan must not contain a funding authorization")
    if not isinstance(conditions, list) or len(conditions) != 1:
        raise ValueError("hosted settlement requires one accepted condition")
    if ConditionDescriptor.model_validate(conditions[0]) != condition:
        raise ValueError("hosted condition does not match the accepted obligation")
    has_legacy_method = "payment_method_types" in params
    has_profile = "funding_profile" in params
    if has_legacy_method:
        if (
            has_profile
            or params.get("payment_method_types") != ["card"]
            or not allow_legacy_recovery
        ):
            raise ValueError("legacy hosted card obligations are recovery-only")
        return FundingProfile.CARD, True
    if not has_profile:
        raise ValueError("accepted hosted obligation has no funding profile")
    for name in ("authority_id", "environment"):
        value = params.get(name)
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"accepted hosted obligation has no exact {name}")
    country = params.get("country")
    if not isinstance(country, str) or not _COUNTRY_CODE.fullmatch(country):
        raise ValueError("accepted hosted obligation has no exact country")
    interaction = params.get("interaction")
    fingerprint = params.get("contract_fingerprint")
    if interaction not in {mode.value for mode in FundingMode}:
        raise ValueError("accepted hosted obligation has no exact interaction mode")
    if not isinstance(fingerprint, str) or not _CONTRACT_FINGERPRINT.fullmatch(
        fingerprint
    ):
        raise ValueError("accepted hosted obligation has no contract fingerprint")
    try:
        return FundingProfile(params["funding_profile"]), False
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "accepted hosted obligation has an unsupported funding profile"
        ) from exc


def _validate_accepted_hosted_option(
    *,
    order: Mapping[str, Any],
    selection: SettlementSelection,
    obligation: Mapping[str, Any],
    buyer_principal: Identity,
    seller_principal: Identity,
) -> None:
    """Bind the accepted selection to its canonical, immutable listing option."""

    raw_options = order.get("settlement_options")
    if isinstance(raw_options, str):
        try:
            raw_options = json.loads(raw_options)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "accepted VM input has no exact immutable hosted option"
            ) from exc
    if not isinstance(raw_options, list):
        raise ValueError("accepted VM input has no exact immutable hosted option")

    selected_option: dict[str, Any] | None = None
    for item in raw_options:
        candidate = _plain_mapping(item)
        if (
            candidate.get("option_id") == selection.option_id
            and candidate.get("mechanism") == selection.mechanism
        ):
            selected_option = candidate
            break
    if selected_option is None:
        raise ValueError(
            "accepted settlement selection does not match the immutable hosted option"
        )
    try:
        option = SettlementOption.model_validate(selected_option)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "accepted settlement selection does not match the immutable hosted option"
        ) from exc

    expected_params = dict(option.params)
    if "payer_principal" in expected_params:
        raise ValueError(
            "accepted settlement selection does not match the immutable hosted option"
        )
    try:
        advertised_claimant = Identity.model_validate(
            expected_params.get("claimant_principal")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "accepted settlement selection does not match the immutable hosted option"
        ) from exc
    if advertised_claimant != seller_principal:
        raise ValueError(
            "accepted settlement selection does not match the immutable hosted option"
        )
    expected_params["payer_principal"] = buyer_principal.model_dump(mode="json")
    expected_params["claimant_principal"] = seller_principal.model_dump(mode="json")
    if (
        option.mechanism != obligation.get("mechanism")
        or option.asset != obligation.get("asset")
        or expected_params != _plain_mapping(obligation.get("params"))
    ):
        raise ValueError(
            "accepted settlement selection does not match the immutable hosted option"
        )




async def load_hosted_agreement(
    *,
    sqlite_client: Any,
    negotiation_id: str,
    expected_claimant: Identity,
    obligation_ref: str | None = None,
    allow_legacy_recovery: bool = False,
) -> HostedAgreement:
    """Reload one exact accepted hosted obligation from marketplace state."""

    thread = await sqlite_client.load_negotiation_thread_row(
        negotiation_id=negotiation_id
    )
    if not thread or thread.get("terminal_state") != "success":
        raise ValueError("hosted settlement negotiation is not accepted")
    buyer_principal = Identity.model_validate(thread.get("buyer_principal"))
    listing_id = str(thread.get("our_listing_id") or "")
    raw_plan = thread.get("settlement_plan")
    if not isinstance(raw_plan, dict):
        raise ValueError("accepted negotiation has no pinned settlement plan")
    plan = SettlementPlan.model_validate(raw_plan)
    if len(plan.obligations) != 1:
        raise ValueError("hosted settlement plan must contain exactly one obligation")
    obligation = plan.obligations[0].model_dump()
    if obligation.get("mechanism") != "fiat.stripe.v1":
        raise ValueError("accepted negotiation did not select hosted settlement")
    derived_ref = derive_obligation_ref(negotiation_id, 0, obligation)
    if plan.buyer_principal is None or (
        Identity.model_validate(plan.buyer_principal) != buyer_principal
    ):
        raise ValueError("accepted plan buyer does not match the marketplace thread")
    if plan.seller_principal is None or (
        Identity.model_validate(plan.seller_principal) != expected_claimant
    ):
        raise ValueError("accepted plan seller does not match the storefront")
    raw_selection = _plain_mapping(
        _plain_mapping(thread.get("buyer_escrow_proposal")).get(
            "settlement_selection"
        )
    )
    selection = SettlementSelection.model_validate(raw_selection)
    if selection.mechanism != "fiat.stripe.v1":
        raise ValueError("accepted settlement selection is not hosted")
    if obligation.get("expiration_unix") != selection.expiration_unix:
        raise ValueError("hosted expiry does not match the accepted selection")
    if obligation_ref is not None and obligation_ref != derived_ref:
        raise ValueError("hosted obligation identifier does not match accepted plan")
    profile, legacy_recovery = _accepted_hosted_profile(
        obligation,
        buyer_principal=buyer_principal,
        seller_principal=expected_claimant,
        allow_legacy_recovery=allow_legacy_recovery,
    )
    agreed_amount = thread.get("agreed_price")
    raw_amount = obligation.get("amount")
    accepted_amount = (
        int(raw_amount)
        if isinstance(raw_amount, str) and raw_amount.isdigit()
        else raw_amount
    )
    if (
        isinstance(agreed_amount, bool)
        or not isinstance(agreed_amount, int)
        or isinstance(accepted_amount, bool)
        or accepted_amount != agreed_amount
    ):
        raise ValueError("hosted amount does not match accepted seller state")
    thread_provision = normalize_vm_provision_terms(thread.get("provision_terms"))
    vm_state = _plain_mapping(plan.service_terms.get("vm.v1"))
    if vm_state:
        accepted_listing_id = vm_state.get("listing_id")
        order = _plain_mapping(vm_state.get("order"))
        provision = normalize_vm_provision_terms(vm_state.get("provision"))
        if accepted_listing_id != listing_id or order.get("listing_id") != listing_id:
            raise ValueError("accepted VM listing identity is inconsistent")
        if provision != thread_provision:
            raise ValueError("accepted VM input does not match the marketplace thread")
        if not legacy_recovery:
            _validate_accepted_hosted_option(
                order=order,
                selection=selection,
                obligation=obligation,
                buyer_principal=buyer_principal,
                seller_principal=expected_claimant,
            )
    elif legacy_recovery:
        order = await sqlite_client.load_listing(listing_id=listing_id)
        if not order:
            raise ValueError("legacy accepted hosted listing is unavailable")
        provision = thread_provision
    else:
        raise ValueError("accepted hosted plan has no immutable VM input")
    return HostedAgreement(
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        buyer_principal=buyer_principal,
        seller_principal=expected_claimant,
        obligation=obligation,
        obligation_ref=derived_ref,
        funding_profile=profile,
        legacy_recovery=legacy_recovery,
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
    stripe_config = composition.settlement_config.mechanism_config("stripe")
    resolvers = _plain_mapping(getattr(stripe_config, "resolvers", {}))
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
        local_principal=composition.local_principal,
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
        expected_claimant=composition.local_principal,
        allow_legacy_recovery=(
            record.mechanism_params.get("legacy_recovery") == "hosted-card.v1"
        ),
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
            local_principal=composition.local_principal,
            worker_id=worker_id,
        )
        raise error
    # Fulfillment identity for a hosted deal is the authority's immutable
    # condition anchor, and every VM surface downstream of here reads the deal
    # through the storefront's own escrow row: provisioning resolves the
    # negotiation binding from it, lease registration writes the capacity
    # reservation onto it, and terminal lease truncation finds the reservation
    # by asking for the negotiation's primary escrow. The EVM lane writes that
    # row when it reserves settlement; the hosted lane's equivalent moment is
    # here -- once the anchor exists, before capacity is committed. Insertion
    # is idempotent by escrow_uid, so a retried fulfillment rebinds rather
    # than duplicating.
    await sqlite_client.insert_escrow(
        escrow_uid=record.condition_anchor,
        negotiation_id=agreement.negotiation_id,
        chain_name=None,
        escrow_address=None,
        is_primary=True,
        status="provisioning",
    )
    await sqlite_client.bind_escrow_obligation(
        escrow_uid=record.condition_anchor,
        obligation_ref=record.obligation_ref,
        obligation_index=record.obligation_index,
    )
    thread_binding = await sqlite_client.load_thread_binding(
        negotiation_id=agreement.negotiation_id
    )
    prepared = PreparedSettlement(
        agreement_ref=agreement.negotiation_id,
        obligations=(agreement.obligation,),
        selected_obligation_index=0,
        local_principal=composition.local_principal,
        mechanism_ref=str(record.mechanism_ref),
        mechanism_receipt=record.status_receipt,
        fulfillment_input=StorefrontSettlementFulfillmentInput(
            buyer_principal=agreement.buyer_principal,
            thread_binding=thread_binding,
            fulfillment_anchor=record.condition_anchor,
            evidence_client=evidence_client,
            domain_input={
                "provision": agreement.provision,
                "listing_id": agreement.listing_id,
                "order": agreement.order,
                "evidence_mode": evidence_mode,
                "evidence_resolver_id": resolver_id,
            },
        ),
    )
    try:
        outcome = await fulfill_vm_settlement(
            composition.domain,
            prepared,
            mechanism_client=composition.mechanism_clients["fiat.stripe.v1"],
            sqlite_client=sqlite_client,
        )
        if outcome.status != "fulfilled" or not outcome.fulfillment_ref:
            raise RuntimeError("hosted VM fulfillment did not succeed")
        completed = await composition.runtime.complete_fulfillment(
            record.obligation_ref,
            outcome.fulfillment_ref,
            local_principal=composition.local_principal,
            worker_id=worker_id,
        )
    except Exception as exc:
        await composition.runtime.retry_fulfillment(
            record.obligation_ref,
            exc,
            local_principal=composition.local_principal,
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
    if (
        record.materialization_state == "manual_required"
        or record.condition_state == "manual_required"
        or record.collection_state == "manual_required"
        or record.reclaim_state == "manual_required"
        or record.mechanism_status == "manual_required"
    ):
        return "manual_required"
    if record.collection_state == "succeeded":
        return "collected"
    if record.condition_state == "failed" or record.mechanism_status == "failed":
        return "failed"
    if record.mechanism_status == "ready":
        return "ready" if record.fulfillment_ref else "funded"
    return record.mechanism_status or "pending"


async def hosted_settlement_projection(
    *,
    composition: VmSettlementComposition,
    record: Any,
    transient_action: Mapping[str, Any] | None = None,
    transient_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project provider-free lifecycle data; transient actions are never reloaded."""

    del composition
    params = {
        **_plain_mapping(record.obligation.get("params")),
        **_plain_mapping(record.mechanism_params),
    }
    legacy = params.get("legacy_recovery") == "hosted-card.v1"
    profile = (
        FundingProfile.CARD
        if legacy
        else FundingProfile(params.get("funding_profile"))
    )
    authorization_ref = params.get("funding_authorization_ref")
    if not legacy and not isinstance(authorization_ref, str):
        raise ValueError("hosted settlement has no immutable funding authorization")
    receipt = dict(
        transient_receipt
        or record.reclaim_receipt
        or record.collection_receipt
        or record.status_receipt
        or record.materialization_receipt
        or {}
    )
    state = _plain_mapping(record.mechanism_state)
    action = dict(transient_action) if transient_action else None
    action_metadata = action or _plain_mapping(record.buyer_action)
    return {
        "settlement_ref": record.mechanism_ref,
        "obligation_ref": record.obligation_ref,
        "funding_authorization_ref": authorization_ref,
        "funding_profile": profile,
        "payer_principal": record.payer_principal,
        "claimant_principal": record.claimant_principal,
        "status": hosted_public_status(record),
        "funding_reason": hosted_projected_reason(receipt, state),
        "funding_deadline_unix": receipt.get("funding_deadline_unix")
        or state.get("funding_deadline_unix"),
        "action": action,
        "action_kind": action_metadata.get("kind"),
        "action_expires_at_unix": action_metadata.get("expires_at_unix"),
        "condition_anchor": record.condition_anchor,
        "fulfillment_ref": record.fulfillment_ref,
        "receipt": receipt or None,
    }


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
    hosted_client = mechanism_clients.get("fiat.stripe.v1")
    if hosted_client is not None:
        mechanism_resources["hosted_client"] = hosted_client
    evidence_clients = dict(alkahest_clients)
    if hosted_client is not None:
        stripe_section = settlement_config.mechanism_config("stripe")
        for resolver in _plain_mapping(
            getattr(stripe_section, "resolvers", {})
        ).values():
            resolver_config = _plain_mapping(resolver)
            if resolver_config.get("evidence_mode") != "portable-remote.v1":
                continue
            client_name = str(resolver_config.get("chain_name") or "")
            if (
                client_name in evidence_clients
                and evidence_clients[client_name] is not hosted_client
            ):
                raise ValueError(
                    "hosted evidence client name conflicts with a chain client"
                )
            evidence_clients[client_name] = hosted_client
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
                local_principal=prepared.local_principal,
            )
            await worker.wake(context.obligation_ref)
        return existing

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
        ),
        persist_outcome=persist_vm_settlement_outcome,
        wake_servicing=wake_servicing,
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
    )
    composition_holder["value"] = composition
    return composition
