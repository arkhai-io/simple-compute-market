"""VM composition for the kit-owned negotiation lifecycle."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from arkhai_vms import DIMENSION_KEYS as _DIMENSION_COMPUTE_KEYS
from core_storefront import (
    StorefrontDomainBinding,
    StorefrontDomainRegistry,
    StorefrontSettlementBuildContext,
    build_domain_settlement_artifacts,
)
from domains.vms.listings import (
    determine_strategy_from_order,
    extract_compute_from_order,
)
from domains.vms.listings.models import Listing
from domains.vms.negotiation import storefront_round as vm_storefront_round
from domains.vms.negotiation.policies import _amount_from_proposal
from domains.vms.negotiation.storefront_round import SellerRoundHook, SellerRoundResult
from domains.vms.settlement.proposals import accepted_escrow_artifacts_from_proposal
from market_core import MarketDomainContract
from market_core.schemas import (
    EscrowProposal,
    SettlementObligation,
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
)
from market_hosted_settlement import HostedObligationParams
from market_identity import Identity
from market_negotiation_runtime import (
    Acceptance,
    AgreementTerms,
    NegotiationDomainHooks,
    NegotiationRuntime,
    NegotiationStateError,
    NegotiationTerms,
    OfferUnfulfillableError,
    OpeningRecord,
    ResolvedNegotiation,
    RoundEvaluation,
    RoundRequest,
)
from market_policy.negotiation_middleware import NegotiationDecision, NegotiationRound
from market_capacity_publication import CapacityBinding, CapacityRuntime
from market_storefront.services.capacity_client import capacity_binding_for_listing
from market_storefront.utils.config import CHAINS, get_evm_wallet_address, settings

logger = logging.getLogger(__name__)


def _negotiation_settings() -> Any:
    return settings.negotiation


def _extra_policy_paths() -> list[str]:
    return list(getattr(_negotiation_settings(), "extra_policy_paths", []) or [])


def _chain_settings() -> dict[str, Any]:
    return dict(CHAINS)


def _default_min_price() -> Any:
    return settings.pricing.default_min_price


def discover_file_policies(force: bool = False) -> None:
    vm_storefront_round._discover_file_policies(
        force=force,
        extra_policy_paths=_extra_policy_paths(),
    )


def load_storefront_chain() -> Any:
    return vm_storefront_round._load_storefront_chain(
        negotiation_config=_negotiation_settings(),
        chains=_chain_settings(),
        extra_policy_paths=_extra_policy_paths(),
    )


def seller_reference_amount(
    listing: Any,
    duration_seconds: int | None,
) -> int:
    return vm_storefront_round._seller_reference_amount(
        listing,
        duration_seconds,
        default_min_price=_default_min_price(),
    )


def _default_seller_round_hook(
    domain: MarketDomainContract,
    capacity_runtime: CapacityRuntime,
) -> SellerRoundHook:
    policy = domain.storefront
    if policy is None:
        raise RuntimeError(
            f"domain {domain.identity!s} has no storefront negotiation capability"
        )
    return policy.run_negotiation_policy(
        capacity_runtime.client(),
        negotiation_config=_negotiation_settings(),
        chains=_chain_settings(),
        extra_policy_paths=_extra_policy_paths(),
        default_min_price=_default_min_price(),
    )


def _chain_config_paths() -> dict[str, str | None]:
    return {
        name: chain.alkahest_address_config_path for name, chain in CHAINS.items()
    }


def _decode_vm_terms(domain: MarketDomainContract, raw_terms: Any) -> NegotiationTerms:
    if raw_terms is None:
        return NegotiationTerms(decoded=None, wire=None)
    raw = (
        raw_terms.model_dump(mode="json")
        if hasattr(raw_terms, "model_dump")
        else raw_terms
    )
    decoded = domain.codecs.message(raw)
    wire = dict(raw)
    return NegotiationTerms(
        decoded=decoded,
        wire=wire,
        requested_duration_seconds=getattr(decoded, "duration_seconds", None),
        requested_start_utc=getattr(decoded, "start_utc", None),
    )


def _validate_vm_opening(
    _listing: Any,
    listing_record: Mapping[str, Any],
    terms: NegotiationTerms,
) -> None:
    decoded = terms.decoded
    if decoded is None:
        return
    requested = getattr(decoded, "compute_resource", None)
    if not requested:
        return
    listing_compute = extract_compute_from_order(dict(listing_record))
    mismatched = {
        key: {"requested": requested[key], "listing": listing_compute.get(key)}
        for key in _DIMENSION_COMPUTE_KEYS
        if requested.get(key) is not None
        and requested[key] != listing_compute.get(key)
    }
    if mismatched:
        raise OfferUnfulfillableError(
            f"resource_shape_not_negotiable: {mismatched}",
            listing_id=str(listing_record.get("listing_id") or "") or None,
        )


def _proposal_wire(proposal: Any) -> dict[str, Any] | None:
    if proposal is None:
        return None
    if isinstance(proposal, Mapping):
        return dict(proposal)
    if hasattr(proposal, "model_dump"):
        return dict(proposal.model_dump(mode="json"))
    raise NegotiationStateError("VM proposal is not an object")


def _proposal_from_amount(
    pinned: Mapping[str, Any] | None,
    amount: int | None,
) -> dict[str, Any] | None:
    if pinned is None and amount is None:
        return None
    base = dict(pinned) if pinned is not None else {}
    fields = base.get("fields")
    merged = dict(fields) if isinstance(fields, Mapping) else {}
    if amount is not None:
        merged["amount"] = int(amount)
    base["fields"] = merged
    return base


def _amount(proposal: Mapping[str, Any] | None) -> int | None:
    value = _amount_from_proposal(proposal)
    return int(value) if value is not None else None


def _decision_wire(decision: NegotiationDecision) -> dict[str, Any]:
    payload = decision.to_dict()
    proposal = payload.get("proposal")
    if not isinstance(proposal, dict):
        return payload
    fields = proposal.get("fields")
    if not isinstance(fields, dict) or not isinstance(fields.get("amount"), int):
        return payload
    payload["proposal"] = {
        **proposal,
        "fields": {**fields, "amount": str(fields["amount"])},
    }
    return payload


def _agreement(
    _listing: Any,
    listing_record: Mapping[str, Any],
    terms: NegotiationTerms,
) -> AgreementTerms:
    return AgreementTerms(
        duration_seconds=int(
            terms.requested_duration_seconds
            or listing_record.get("max_duration_seconds")
            or 3600
        ),
        start_utc=terms.requested_start_utc,
    )


def build_vm_accepted_artifacts(
    *,
    proposal: Any,
    agreed_amount: int,
    duration_seconds: int,
    buyer_principal: Identity,
    seller_principal: Identity,
    uses_scalar_amount: bool = True,
    seller_wallet_address: str | None = None,
    chain_config_paths: Mapping[str, str | None] | None = None,
    **_unused: Any,
) -> dict[str, Any]:
    """Materialize VM settlement artifacts from domain-owned proposal codecs."""

    artifacts = accepted_escrow_artifacts_from_proposal(
        proposal=proposal,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        uses_scalar_amount=uses_scalar_amount,
        seller_wallet_address=seller_wallet_address,
        chain_config_paths=(
            dict(chain_config_paths)
            if chain_config_paths is not None
            else _chain_config_paths()
        ),
        heartbeat_interval_seconds=int(
            getattr(settings, "heartbeat_interval_seconds", 60)
        ),
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
            if not isinstance(obligation, dict):
                continue
            obligation["payer_principal"] = (
                buyer_wire if obligation.get("payer") == "buyer" else seller_wire
            )
            obligation["claimant_principal"] = (
                buyer_wire
                if obligation.get("claimant") == "buyer"
                else seller_wire
            )
    return artifacts


def _build_accepted_escrow_artifacts(
    *,
    domain: MarketDomainContract,
    capacity_binding: CapacityBinding,
    negotiation_id: str,
    listing_id: str,
    proposal: Mapping[str, Any] | None,
    agreed_amount: int,
    duration_seconds: int,
    buyer_principal: Identity,
    seller_principal: Identity,
    uses_scalar_amount: bool,
) -> dict[str, Any]:
    artifacts = build_domain_settlement_artifacts(
        domain,
        StorefrontSettlementBuildContext(
            binding=StorefrontDomainBinding(
                offering_mode=capacity_binding.offering_mode,
                domain_identity=domain.identity,
                contract_major=domain.contract_version.major,
                contract_minor=domain.contract_version.minor,
            ),
            negotiation_id=negotiation_id,
            listing_id=listing_id,
            site_id=capacity_binding.site_id,
            proposal=proposal,
            agreed_amount=agreed_amount,
            duration_seconds=duration_seconds,
            buyer_principal=buyer_principal,
            seller_principal=seller_principal,
            uses_scalar_amount=uses_scalar_amount,
            seller_wallet_address=get_evm_wallet_address() or None,
            chain_config_paths=_chain_config_paths(),
        ),
    )
    return {
        **dict(artifacts.supplemental),
        "settlement_plan": dict(artifacts.settlement_plan),
    }


def _accepted_vm_service_terms(
    *,
    listing: Mapping[str, Any],
    provision_terms: Any,
) -> dict[str, Any]:
    provision = (
        provision_terms.model_dump(mode="json")
        if hasattr(provision_terms, "model_dump")
        else provision_terms
    )
    if not isinstance(provision, Mapping):
        raise OfferUnfulfillableError("hosted_vm_provision_terms_unavailable")
    listing_id = listing.get("listing_id")
    if not isinstance(listing_id, str) or not listing_id:
        raise OfferUnfulfillableError("hosted_listing_identity_unavailable")
    order = dict(listing)
    offer_resource = order.get("offer_resource")
    if isinstance(offer_resource, str):
        try:
            offer_resource = json.loads(offer_resource)
        except json.JSONDecodeError as exc:
            raise OfferUnfulfillableError(
                "hosted_offer_resource_unavailable"
            ) from exc
        order["offer_resource"] = offer_resource
    if not isinstance(offer_resource, dict):
        raise OfferUnfulfillableError("hosted_offer_resource_unavailable")
    return {
        "vm.v1": {
            "listing_id": listing_id,
            "order": order,
            "provision": dict(provision),
        }
    }


def _accepted_hosted_artifacts(
    *,
    selection: Mapping[str, Any],
    option: Mapping[str, Any],
    agreed_amount: int,
    buyer_principal: Identity,
    seller_principal: Identity,
    listing: Mapping[str, Any],
    provision_terms: Any,
) -> dict[str, Any]:
    if agreed_amount < 1:
        raise OfferUnfulfillableError("hosted_amount_below_one_minor_unit")
    accepted = SettlementSelection.model_validate(selection)
    try:
        advertised_option = SettlementOption.model_validate(option)
    except (TypeError, ValueError) as exc:
        raise OfferUnfulfillableError("hosted_settlement_option_not_exact") from exc
    if (
        accepted.option_id != advertised_option.option_id
        or accepted.mechanism != advertised_option.mechanism
    ):
        raise OfferUnfulfillableError("settlement_selection_not_exact")
    if accepted.mechanism != "fiat.stripe.v1":
        raise OfferUnfulfillableError("hosted_mechanism_not_exact")
    params = dict(advertised_option.params)
    condition = params.get("condition")
    currency = advertised_option.asset
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isalpha()
        or currency != currency.lower()
    ):
        raise OfferUnfulfillableError("hosted_currency_not_exact")
    if not isinstance(condition, dict):
        raise OfferUnfulfillableError("hosted_condition_unavailable")
    advertised_claimant = Identity.model_validate(params.get("claimant_principal"))
    if advertised_claimant != seller_principal:
        raise OfferUnfulfillableError("hosted_claimant_principal_mismatch")
    params["payer_principal"] = buyer_principal.model_dump(mode="json")
    params["claimant_principal"] = seller_principal.model_dump(mode="json")
    if "funding_authorization_ref" in params:
        raise OfferUnfulfillableError(
            "hosted_authorization_not_allowed_before_acceptance"
        )
    try:
        params = HostedObligationParams.model_validate(
            {**params, "funding_authorization_ref": "accepted-plan-validation"}
        ).model_dump(mode="json", exclude={"funding_authorization_ref"})
    except (TypeError, ValueError) as exc:
        raise OfferUnfulfillableError("hosted_settlement_option_not_exact") from exc
    plan = SettlementPlan(
        buyer_principal=buyer_principal.model_dump(mode="json"),
        seller_principal=seller_principal.model_dump(mode="json"),
        service_terms=_accepted_vm_service_terms(
            listing=listing,
            provision_terms=provision_terms,
        ),
        obligations=[
            SettlementObligation(
                payer="buyer",
                claimant="seller",
                payer_principal=buyer_principal.model_dump(mode="json"),
                claimant_principal=seller_principal.model_dump(mode="json"),
                amount=agreed_amount,
                asset=advertised_option.asset,
                expiration_unix=accepted.expiration_unix,
                conditions=[condition],
                mechanism=accepted.mechanism,
                params=params,
            )
        ],
    )
    return {
        "settlement_selection": accepted.model_dump(),
        "settlement_plan": plan.model_dump(),
    }


def _accepted_settlement_artifacts(
    *,
    domain: MarketDomainContract,
    capacity_binding: CapacityBinding,
    negotiation_id: str,
    listing_id: str,
    proposal: Mapping[str, Any] | None,
    listing: Mapping[str, Any],
    agreed_amount: int,
    duration_seconds: int,
    uses_scalar_amount: bool,
    buyer_principal: Identity,
    seller_principal: Identity,
    provision_terms: Any,
) -> dict[str, Any]:
    if isinstance(proposal, Mapping) and isinstance(
        proposal.get("settlement_selection"), Mapping
    ):
        selection = SettlementSelection.model_validate(
            proposal["settlement_selection"]
        )
        options = listing.get("settlement_options") or []
        if isinstance(options, str):
            options = json.loads(options)
        option = next(
            (
                item
                for item in options
                if isinstance(item, Mapping)
                and item.get("option_id") == selection.option_id
                and item.get("mechanism") == selection.mechanism
            ),
            None,
        )
        if option is None:
            raise OfferUnfulfillableError("settlement_selection_not_exact")
        return _accepted_hosted_artifacts(
            selection=selection.model_dump(),
            option=option,
            agreed_amount=agreed_amount,
            listing=listing,
            provision_terms=provision_terms,
            buyer_principal=buyer_principal,
            seller_principal=seller_principal,
        )
    return _build_accepted_escrow_artifacts(
        domain=domain,
        capacity_binding=capacity_binding,
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        proposal=proposal,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        uses_scalar_amount=uses_scalar_amount,
        buyer_principal=buyer_principal,
        seller_principal=seller_principal,
    )


def _build_response_artifacts(
    domain: MarketDomainContract,
    acceptance: Acceptance,
    accepted: bool,
) -> Mapping[str, Any]:
    if not isinstance(acceptance.binding, CapacityBinding):
        raise RuntimeError("VM negotiation has no frozen capacity binding")
    if accepted:
        return _accepted_settlement_artifacts(
            capacity_binding=acceptance.binding,
            negotiation_id=acceptance.negotiation_id,
            listing_id=acceptance.listing_id,
            domain=domain,
            proposal=acceptance.pinned_proposal,
            listing=acceptance.listing_record,
            agreed_amount=acceptance.agreed_amount,
            duration_seconds=acceptance.agreement.duration_seconds,
            uses_scalar_amount=acceptance.uses_scalar_amount,
            buyer_principal=acceptance.buyer_principal,
            seller_principal=acceptance.seller_principal,
            provision_terms=acceptance.terms.decoded,
        )
    state = acceptance.policy_state
    if not isinstance(state, Mapping):
        return {}
    proposal = state.get("accepted_escrow_proposal")
    if isinstance(proposal, Mapping):
        artifacts = _build_accepted_escrow_artifacts(
            domain=domain,
            capacity_binding=acceptance.binding,
            negotiation_id=acceptance.negotiation_id,
            listing_id=acceptance.listing_id,
            proposal=proposal,
            agreed_amount=acceptance.agreed_amount,
            duration_seconds=acceptance.agreement.duration_seconds,
            uses_scalar_amount=acceptance.uses_scalar_amount,
            buyer_principal=acceptance.buyer_principal,
            seller_principal=acceptance.seller_principal,
        )
        accepted_proposal = artifacts.get("accepted_escrow_proposal")
        return (
            {"accepted_escrow_proposal": accepted_proposal}
            if accepted_proposal is not None
            else {}
        )
    selection = state.get("accepted_settlement_selection")
    option = state.get("accepted_settlement_option")
    if isinstance(selection, Mapping) and isinstance(option, Mapping):
        artifacts = _accepted_hosted_artifacts(
            selection=selection,
            option=option,
            agreed_amount=acceptance.agreed_amount,
            buyer_principal=acceptance.buyer_principal,
            seller_principal=acceptance.seller_principal,
            listing=acceptance.listing_record,
            provision_terms=acceptance.terms.decoded,
        )
        return {"settlement_selection": artifacts["settlement_selection"]}
    return {}


async def _persist_artifacts(
    repository: Any,
    acceptance: Acceptance,
    artifacts: Mapping[str, Any],
) -> None:
    plan = artifacts.get("settlement_plan")
    if isinstance(plan, dict):
        await repository.commit_settlement_plan(
            negotiation_id=acceptance.negotiation_id,
            settlement_plan=plan,
            buyer_principal=acceptance.buyer_principal,
            seller_principal=acceptance.seller_principal,
        )


def lookup_pool_policy_tags(
    repository: Any,
    listing_id: str | None,
) -> dict[str, Any]:
    """Return the live policy tags for the pool mapped to a VM listing."""

    if not listing_id:
        return {}
    try:
        from domains.vms.listings.reconciler import (
            pool_id_for_listing,
            site_id_for_listing,
        )
        from market_storefront.services.site_projection_cache import (
            projection_caches,
        )

        site_id = site_id_for_listing(repository.db_path, listing_id)
        pool_id = pool_id_for_listing(repository.db_path, listing_id)
        if not site_id or not pool_id:
            return {}
        caches = projection_caches().get(site_id)
        if caches is None:
            return {}
        pools = caches.resource_pools.view().value or []
        for pool in pools:
            if str(pool.get("resource_pool_id") or "") == pool_id:
                metadata = pool.get("pool_metadata") or {}
                return dict(metadata.get("policy_tags") or {})
    except Exception:
        return {}
    return {}


async def _place_capacity_hold(
    repository: Any,
    acceptance: Acceptance,
    *,
    capacity_runtime: CapacityRuntime,
) -> None:
    """Place the VM domain's best-effort capacity hold after acceptance.

    The binding is resolved by the VM composition root before the negotiation
    lifecycle starts.  Keeping that exact site/offering-mode/source tuple on
    ``Acceptance`` prevents the hold from falling back to an aggregate default
    or escaping the listing's pool-mode validation.
    """

    from core_storefront.stage_log import stage_event
    from market_resource_pools.hints import capped_hold_seconds
    from market_storefront.services.vm_job_spec_service import (
        compute_capacity_claim_from_order,
    )

    ttl = float(
        getattr(getattr(settings, "capacity", None), "hold_ttl_seconds", 0) or 0
    )
    if ttl <= 0:
        return
    try:
        if not isinstance(acceptance.binding, CapacityBinding):
            raise RuntimeError("capacity hold requires a durably bound listing")
        claim = compute_capacity_claim_from_order(dict(acceptance.listing_record))
        capacity = capacity_runtime
        ttl = capped_hold_seconds(
            ttl,
            lookup_pool_policy_tags(repository, acceptance.listing_id),
        )
        held = await capacity.reserve(
            acceptance.binding,
            claim=claim,
            deal_ref={
                "listing_id": acceptance.listing_id,
                "negotiation_id": acceptance.negotiation_id,
            },
            ttl_seconds=ttl,
            lease_start_utc=acceptance.agreement.start_utc,
            lease_duration_seconds=acceptance.agreement.duration_seconds,
        )
    except Exception as exc:
        logger.warning(
            "[NEGOTIATION] Could not place capacity hold for %s: %s",
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


def build_vm_negotiation_runtime(
    domain: MarketDomainContract,
    *,
    registry: StorefrontDomainRegistry,
    binding: StorefrontDomainBinding,
    capacity_runtime: CapacityRuntime,
    seller_round_hook: SellerRoundHook | None = None,
) -> NegotiationRuntime:
    """Compose the shared lifecycle with the exact registered VM contract."""

    if not isinstance(registry, StorefrontDomainRegistry):
        raise TypeError("registry must be a StorefrontDomainRegistry")
    if not isinstance(binding, StorefrontDomainBinding):
        raise TypeError("binding must be a StorefrontDomainBinding")
    if binding.offering_mode != "vm":
        raise RuntimeError(
            "VM negotiation runtime requires offering mode 'vm', "
            f"got {binding.offering_mode!r}"
        )
    if registry.resolve(binding) is not domain:
        raise RuntimeError(
            "VM negotiation runtime requires the exact contract resolved by "
            "its startup registry and binding"
        )
    if registry.registration_for_contract(domain).binding != binding:
        raise RuntimeError(
            "VM negotiation binding does not match its exact startup registration"
        )
    if not isinstance(capacity_runtime, CapacityRuntime):
        raise TypeError("capacity_runtime must be a CapacityRuntime")

    def require_repository_registry(repository: Any) -> None:
        if getattr(repository, "domain_registry", None) is not registry:
            raise RuntimeError(
                "negotiation and repository must share the exact storefront "
                "domain registry object"
            )

    def require_domain_binding(durable_binding: StorefrontDomainBinding) -> None:
        if (
            durable_binding != binding
            or registry.resolve(durable_binding) is not domain
        ):
            raise NegotiationStateError(
                "durable negotiation binding does not select the configured "
                "VM contract"
            )

    def require_capacity_binding(
        capacity_binding: CapacityBinding,
        *,
        site_id: str,
    ) -> None:
        if (
            capacity_binding.site_id != site_id
            or capacity_binding.offering_mode != binding.offering_mode
        ):
            raise NegotiationStateError(
                "capacity binding does not match the durable VM site and mode"
            )

    async def resolve_opening(
        repository: Any,
        listing_id: str,
    ) -> ResolvedNegotiation:
        require_repository_registry(repository)
        listing_binding = await repository.load_listing_binding(
            listing_id=listing_id
        )
        if listing_binding is None:
            raise NegotiationStateError(
                f"listing {listing_id!r} has no durable storefront binding"
            )
        require_domain_binding(listing_binding.binding)
        record = await repository.load_listing(listing_id=listing_id)
        if not record:
            raise NegotiationStateError(
                f"Order {listing_id} not found locally; seller has no matching listing"
            )
        capacity_binding = await capacity_binding_for_listing(repository, listing_id)
        require_capacity_binding(
            capacity_binding,
            site_id=listing_binding.site_id,
        )
        return ResolvedNegotiation(
            listing_id=listing_id,
            listing=Listing.model_validate(record),
            listing_record=record,
            hooks=hooks,
            binding=capacity_binding,
        )

    async def resolve_continuation(
        repository: Any,
        thread: Mapping[str, Any],
    ) -> ResolvedNegotiation:
        require_repository_registry(repository)
        negotiation_id = thread.get("negotiation_id")
        if not isinstance(negotiation_id, str) or not negotiation_id:
            raise NegotiationStateError("negotiation thread has no durable identity")
        listing_id = thread.get("our_listing_id")
        if not isinstance(listing_id, str) or not listing_id:
            raise NegotiationStateError("negotiation has no recorded VM listing")
        thread_binding = await repository.load_thread_binding(
            negotiation_id=negotiation_id
        )
        if thread_binding.listing_id != listing_id:
            raise NegotiationStateError(
                "negotiation binding does not match its recorded VM listing"
            )
        require_domain_binding(thread_binding.binding)
        listing_binding = await repository.load_listing_binding(
            listing_id=listing_id
        )
        if (
            listing_binding is None
            or listing_binding.binding != thread_binding.binding
            or listing_binding.site_id != thread_binding.site_id
        ):
            raise NegotiationStateError(
                "VM listing binding changed after negotiation creation"
            )
        record = await repository.load_listing(listing_id=listing_id)
        if not record:
            raise NegotiationStateError(
                f"Seller's order {listing_id} is gone from local DB"
            )
        capacity_binding = await capacity_binding_for_listing(repository, listing_id)
        require_capacity_binding(
            capacity_binding,
            site_id=thread_binding.site_id,
        )
        return ResolvedNegotiation(
            listing_id=listing_id,
            listing=Listing.model_validate(record),
            listing_record=record,
            hooks=hooks,
            binding=capacity_binding,
        )

    async def evaluate(request: RoundRequest) -> RoundEvaluation:
        policy = seller_round_hook or _default_seller_round_hook(
            domain,
            capacity_runtime,
        )
        result = await policy(
            listing=request.listing,
            history=list(request.history),
            requested_duration_seconds=request.terms.requested_duration_seconds,
            **(
                {"strategy_label": request.strategy_label}
                if request.strategy_label is not None
                else {}
            ),
        )
        state = result.intermediate or {}
        pinned = state.get("accepted_escrow_proposal")
        return RoundEvaluation(
            our_amount=int(result.our_amount),
            strategy_label=result.strategy_label,
            decision=result.decision,
            pinned_proposal=(dict(pinned) if isinstance(pinned, Mapping) else None),
            uses_scalar_amount=bool(state.get("uses_scalar_amount", True)),
            buyer_amount=(
                int(state["buyer_amount"])
                if state.get("buyer_amount") is not None
                else None
            ),
            domain_state=state,
        )

    async def listing_is_paused(repository: Any, listing_id: str) -> bool:
        return bool(await repository.is_listing_paused(listing_id=listing_id))

    async def validate_continuation(
        _repository: Any,
        listing: Any,
        listing_record: Mapping[str, Any],
        terms: NegotiationTerms,
        _thread: Mapping[str, Any],
    ) -> None:
        _validate_vm_opening(listing, listing_record, terms)

    async def persist_opening(
        repository: Any,
        opening: OpeningRecord,
    ) -> None:
        copied = await repository.copy_listing_binding_to_thread(
            negotiation_id=opening.negotiation_id,
            listing_id=opening.listing_id,
        )
        require_domain_binding(copied.binding)
        if not isinstance(opening.binding, CapacityBinding):
            raise NegotiationStateError(
                "VM negotiation opening has no capacity binding"
            )
        require_capacity_binding(
            opening.binding,
            site_id=copied.site_id,
        )

    def storefront_is_paused() -> bool:
        from market_storefront.server import is_globally_paused

        return bool(is_globally_paused())

    async def place_hold(
        repository: Any,
        acceptance: Acceptance,
    ) -> None:
        await _place_capacity_hold(
            repository,
            acceptance,
            capacity_runtime=capacity_runtime,
        )

    from core_storefront.stage_log import stage_event

    hooks = NegotiationDomainHooks(
        decode_terms=lambda raw: _decode_vm_terms(domain, raw),
        validate_opening=_validate_vm_opening,
        validate_continuation=validate_continuation,
        evaluate_round=evaluate,
        determine_strategy=lambda listing, _record: determine_strategy_from_order(
            listing
        ),
        reference_amount=lambda _listing, record, terms, scalar: (
            seller_reference_amount(record, terms.requested_duration_seconds)
            if scalar
            else 0
        ),
        amount_from_proposal=_amount,
        proposal_from_amount=_proposal_from_amount,
        agreement_terms=_agreement,
        build_artifacts=lambda acceptance, accepted: _build_response_artifacts(
            domain,
            acceptance,
            accepted,
        ),
        decision_wire=_decision_wire,
        listing_is_live=lambda record: str(record.get("status") or "").strip()
        == "open",
        listing_is_paused=listing_is_paused,
        storefront_is_paused=storefront_is_paused,
        stage_event=stage_event,
        place_hold=place_hold,
        persist_artifacts=_persist_artifacts,
        persist_opening=persist_opening,
    )
    return NegotiationRuntime(
        resolve_opening=resolve_opening,
        resolve_continuation=resolve_continuation,
    )


async def compute_round_zero_decision(
    *,
    repository: Any,
    registry: StorefrontDomainRegistry,
    binding: StorefrontDomainBinding,
    domain: MarketDomainContract,
    capacity_runtime: CapacityRuntime,
    listing: Any,
    proposal: Mapping[str, Any] | None,
    requested_duration_seconds: int | None = None,
) -> tuple[int, str, str, str, NegotiationDecision]:
    """Run the VM policy adapter against the exact durable capacity binding."""

    if getattr(repository, "domain_registry", None) is not registry:
        raise RuntimeError(
            "round-zero evaluation and repository must share the exact registry"
        )
    if registry.resolve(binding) is not domain:
        raise RuntimeError(
            "round-zero evaluation requires the exact registry-owned VM contract"
        )
    if not isinstance(capacity_runtime, CapacityRuntime):
        raise TypeError("capacity_runtime must be a CapacityRuntime")
    listing_id = str(getattr(listing, "listing_id", "") or "")
    listing_binding = await repository.load_listing_binding(listing_id=listing_id)
    if listing_binding is None or listing_binding.binding != binding:
        raise NegotiationStateError(
            "round-zero evaluation requires the selected durable VM binding"
        )
    capacity_binding = await capacity_binding_for_listing(repository, listing_id)
    if (
        capacity_binding.site_id != listing_binding.site_id
        or capacity_binding.offering_mode != binding.offering_mode
    ):
        raise NegotiationStateError(
            "round-zero capacity binding does not match the durable VM site and mode"
        )
    result: SellerRoundResult = await _default_seller_round_hook(
        domain,
        capacity_runtime,
    )(
        listing=listing,
        history=[
            NegotiationRound(
                round_number=0,
                sender="them",
                action="initial",
                proposal=dict(proposal) if proposal is not None else None,
            )
        ],
        requested_duration_seconds=requested_duration_seconds,
    )
    return (
        result.our_amount,
        result.strategy_label,
        result.direction,
        result.chain_label,
        result.decision,
    )
