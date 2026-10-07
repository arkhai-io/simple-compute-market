"""Bare-metal negotiation, composed onto the kit's negotiation runtime.

The runtime owns the protocol: its order of checks, the transcript, the
source recheck before every seller decision and acceptance, and writing an
acceptance as successful only once its agreement and plan are recorded. This
module supplies what is bare metal's:

- the closed ``bare_metal.v1`` message as the negotiated terms, the requested
  duration as the agreement's, and no requested start, so a lease begins when
  settlement commits it;
- an exact settlement option, hosted or contact exchange, accepted at round
  zero at its trusted amount without price policy, once its physical facts are
  checked against the trusted listing;
- an escrow proposal decided by the seller chain (``negotiation.py``);
- the settlement plan built from the same seller wallet and chain configuration
  settlement verification uses, and committed at acceptance with the
  ``BareMetalTerms`` that fulfillment reads;
- no capacity hold: capacity is reserved when settlement starts fulfillment.

A refusal the domain owns carries its HTTP status (``BareMetalNegotiationRefusal``).
See openspec/specs/storefront-publication/spec.md, "Complete bare-metal seller
lifecycle".
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from arkhai_bare_metal import (
    BareMetalBuyerDemand,
    BareMetalMessage,
    BareMetalTerms,
    validate_buyer_selection,
)
from core_storefront.stage_log import stage_event
from market_core import MarketDomainContract
from market_core.schemas import (
    AcceptedEscrow,
    EscrowProposal,
    SettlementObligation,
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
    compute_rate_total,
)
from market_identity import Identity
from market_negotiation_runtime import (
    Acceptance,
    AgreementTerms,
    NegotiationDomainHooks,
    NegotiationRuntime,
    NegotiationStateError,
    NegotiationTerms,
    OpeningRecord,
    ResolvedNegotiation,
    RoundEvaluation,
    RoundRequest,
)
from market_policy.listing_source import ListingSourceVerdict
from market_policy.negotiation_middleware import NegotiationDecision
from market_settlement_runtime import AcceptedObligationArtifacts
from market_storefront_kit import TradingPause

from .listing_source_check import ListingSourceCheck
from .negotiation import BareMetalSellerRoundHook
from .settlement import BareMetalSettlementPlanError

PlanBuilder = Callable[..., dict[str, Any]]
# One curried registry dispatch per composed mechanism: the selection resolves
# the mechanism exactly once and every obligation-shaped decision goes through
# the registration; the domain keeps no per-mechanism conditional arm.
AcceptedObligationDispatch = Mapping[
    str, Callable[[Mapping[str, Any], Mapping[str, Any]], AcceptedObligationArtifacts]
]

#: The strategy an exact-option opening is recorded under.
EXACT_SELECTION_STRATEGY = "bare_metal_exact_selection"
#: What an accepted escrow opening answers with, besides the decision.
_ESCROW_RESPONSE_ARTIFACTS = (
    "settlement_plan",
    "accepted_escrow_terms",
    "accepted_escrow_proposal",
)


class BareMetalNegotiationRefusal(ValueError):
    """A refusal the bare-metal domain owns, with the HTTP status it answers."""

    def __init__(self, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def exact_selection(
    proposal: Any, settlement_selection: SettlementSelection | None
) -> SettlementSelection | None:
    """The exact option an opening request selects, from either carrier.

    A request may name its option beside the proposal or inside it; both are
    refused when they differ, and a selection beside an escrow proposal is
    refused as mixing incompatible carriers.
    """

    nested: SettlementSelection | None = None
    if isinstance(proposal, Mapping) and proposal.get("settlement_selection") is not None:
        unknown = sorted(set(proposal).difference({"settlement_selection", "fields"}))
        fields = proposal.get("fields", {})
        if unknown or not isinstance(fields, Mapping):
            raise BareMetalNegotiationRefusal(
                "hosted settlement proposal has invalid fields", status_code=400
            )
        try:
            nested = SettlementSelection.model_validate(proposal.get("settlement_selection"))
        except (TypeError, ValueError) as exc:
            raise BareMetalNegotiationRefusal(
                "hosted settlement proposal has an invalid selection", status_code=400
            ) from exc
    if settlement_selection is not None and isinstance(proposal, Mapping) and nested is None:
        if sorted(set(proposal).difference({"fields"})):
            raise BareMetalNegotiationRefusal(
                "hosted settlement proposal mixes incompatible carriers", status_code=400
            )
    if (
        settlement_selection is not None
        and nested is not None
        and settlement_selection != nested
    ):
        raise BareMetalNegotiationRefusal(
            "hosted settlement proposal contains ambiguous selections", status_code=400
        )
    return settlement_selection or nested


def _amount(value: Any, *, what: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise BareMetalNegotiationRefusal(
            f"{what} must be a non-negative integer", status_code=400
        )
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise BareMetalNegotiationRefusal(
        f"{what} must be a non-negative integer", status_code=400
    )


def _proposal_amount(proposal: Mapping[str, Any] | None) -> int | None:
    if not isinstance(proposal, Mapping):
        return None
    fields = proposal.get("fields")
    if not isinstance(fields, Mapping):
        return None
    return _amount(fields.get("amount"), what="proposal amount")


def _proposal_from_amount(
    pinned: Mapping[str, Any] | None, amount: int | None
) -> dict[str, Any] | None:
    if pinned is None and amount is None:
        return None
    result = dict(pinned or {})
    if amount is not None:
        result["fields"] = {**dict(result.get("fields") or {}), "amount": str(amount)}
    return result


def _decision_wire(decision: NegotiationDecision) -> dict[str, Any]:
    """The decision as the wire carries it: an amount travels as a decimal string."""

    payload = decision.to_dict()
    proposal = payload.get("proposal")
    if isinstance(proposal, dict):
        fields = proposal.get("fields")
        if isinstance(fields, dict) and isinstance(fields.get("amount"), int):
            payload["proposal"] = {
                **proposal,
                "fields": {**fields, "amount": str(fields["amount"])},
            }
    return payload


def _matching_acceptance(
    listing_record: Mapping[str, Any], proposal: EscrowProposal
) -> AcceptedEscrow | None:
    for raw in listing_record.get("accepted_escrows") or []:
        accepted = AcceptedEscrow.model_validate(raw)
        if (
            accepted.chain_name == proposal.chain_name
            and accepted.escrow_address.lower() == proposal.escrow_address.lower()
        ):
            return accepted
    return None


def _escrow_proposal(proposal: Mapping[str, Any] | None) -> EscrowProposal:
    try:
        return EscrowProposal.model_validate(proposal)
    except (TypeError, ValueError) as exc:
        raise BareMetalNegotiationRefusal(
            "proposal is not a valid escrow proposal", status_code=400
        ) from exc


def _seller_reference_amount(
    accepted: AcceptedEscrow | None,
    *,
    duration_seconds: int,
    buyer_amount: int | None,
) -> int:
    """The listed rate of the escrow the buyer proposed, over the requested duration."""

    if accepted is None:
        return 0
    amount_rates = [rate for rate in accepted.rates if rate.field == "amount"]
    if amount_rates:
        return compute_rate_total(amount_rates[0], duration_seconds)
    if buyer_amount is not None:
        raise BareMetalNegotiationRefusal(
            "scalar listing has no advertised amount rate", status_code=409
        )
    return 0


def _escrow_terms(listing: Any, message: BareMetalMessage, listing_id: str) -> BareMetalTerms:
    """What fulfillment provisions for an accepted escrow: the listed host, as asked."""

    return BareMetalTerms(
        host_id=listing.host_id,
        physical_host_id=listing.physical_host_id,
        duration_seconds=message.duration_seconds,
        access_method=message.access_method,
        ssh_public_key=message.ssh_public_key,
        listing_ref=listing_id,
    )


def build_bare_metal_negotiation_runtime(
    *,
    domain: MarketDomainContract,
    seller_principal: Identity,
    round_hook: BareMetalSellerRoundHook,
    listing_source_check: ListingSourceCheck,
    trading_pause: TradingPause,
    plan_builder: PlanBuilder,
    accepted_obligation_dispatch: AcceptedObligationDispatch,
    seller_wallet_address: str | None = None,
    chain_config_paths: Mapping[str, str | None] | None = None,
) -> NegotiationRuntime:
    """Compose bare metal's hooks onto the kit's negotiation runtime.

    ``plan_builder`` is called with ``seller_wallet_address`` and
    ``chain_config_paths``, the inputs settlement verification uses, so the plan
    committed at acceptance is the plan settlement verifies.
    """

    chain_paths = dict(chain_config_paths or {})

    def require_domain(binding: Any) -> None:
        if str(binding.domain_identity) != str(domain.identity):
            raise NegotiationStateError(
                "durable negotiation binding does not select the bare-metal contract"
            )

    def decode_terms(raw: Any) -> NegotiationTerms:
        # The wire is the terms as the buyer sent them, the envelope the
        # response returns and the thread records for continuation.
        envelope = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw
        try:
            message = domain.codecs.message(envelope)
        except Exception as exc:  # noqa: BLE001 - any codec failure is incompatible terms
            raise BareMetalNegotiationRefusal(
                "incompatible bare-metal provision terms", status_code=400
            ) from exc
        assert isinstance(message, BareMetalMessage)
        return NegotiationTerms(
            decoded=message,
            wire=dict(envelope),
            requested_duration_seconds=message.duration_seconds,
        )

    def listing_of(record: Mapping[str, Any]) -> Any:
        raw = record.get("listing_resource")
        try:
            return domain.codecs.listing(json.loads(raw) if isinstance(raw, str) else raw)
        except Exception as exc:  # noqa: BLE001 - an unreadable listing cannot be offered
            raise BareMetalNegotiationRefusal(
                "trusted bare-metal listing is unavailable"
            ) from exc

    async def resolve_opening(repository: Any, listing_id: str) -> ResolvedNegotiation:
        record = await repository.load_listing(listing_id=listing_id)
        if record is None:
            raise BareMetalNegotiationRefusal("listing not found", status_code=404)
        listing_binding = await repository.load_listing_binding(listing_id=listing_id)
        if listing_binding is None:
            raise NegotiationStateError(
                f"listing {listing_id!r} has no immutable storefront binding"
            )
        require_domain(listing_binding.binding)
        return ResolvedNegotiation(
            listing_id=listing_id,
            listing=listing_of(record),
            listing_record=record,
            hooks=hooks,
            binding=listing_binding,
        )

    async def resolve_continuation(
        repository: Any, thread: Mapping[str, Any]
    ) -> ResolvedNegotiation:
        negotiation_id = thread.get("negotiation_id")
        listing_id = thread.get("our_listing_id")
        if not isinstance(negotiation_id, str) or not isinstance(listing_id, str):
            raise NegotiationStateError("negotiation thread has no recorded listing")
        thread_binding = await repository.load_thread_binding(
            negotiation_id=negotiation_id
        )
        if thread_binding.listing_id != listing_id:
            raise NegotiationStateError(
                "negotiation binding does not match its recorded listing"
            )
        require_domain(thread_binding.binding)
        # The negotiation continues on the authority it opened with; a listing
        # since rebound elsewhere is not the listing it negotiated.
        listing_binding = await repository.load_listing_binding(listing_id=listing_id)
        if (
            listing_binding is None
            or listing_binding.binding != thread_binding.binding
            or listing_binding.site_id != thread_binding.site_id
        ):
            raise NegotiationStateError(
                "bare-metal listing binding changed after negotiation creation"
            )
        record = await repository.load_listing(listing_id=listing_id)
        if record is None:
            raise NegotiationStateError(f"listing {listing_id!r} is gone")
        return ResolvedNegotiation(
            listing_id=listing_id,
            listing=listing_of(record),
            listing_record=record,
            hooks=hooks,
            binding=listing_binding,
        )

    async def validate_continuation(
        repository: Any,
        _listing: Any,
        _record: Mapping[str, Any],
        terms: NegotiationTerms,
        thread: Mapping[str, Any],
    ) -> None:
        recorded = await repository.load_bare_metal_message(
            negotiation_id=str(thread["negotiation_id"])
        )
        if recorded is not None and recorded != terms.decoded:
            raise NegotiationStateError(
                "negotiation terms differ from the terms it opened with"
            )

    async def evaluate(request: RoundRequest) -> RoundEvaluation:
        message = request.terms.decoded
        listing_id = str(request.listing_record["listing_id"])
        proposal = request.history[-1].proposal
        if len(request.history) == 1 and isinstance(proposal, Mapping) and (
            proposal.get("settlement_selection") is not None
        ):
            return await evaluate_exact_selection(request, message, listing_id, proposal)
        opening = _escrow_proposal(request.history[0].proposal)
        if not (request.listing_record.get("accepted_escrows") or []):
            raise BareMetalNegotiationRefusal(
                "listing has no accepted escrow contract", status_code=409
            )
        buyer_amount = _proposal_amount(proposal)
        reference = _seller_reference_amount(
            _matching_acceptance(request.listing_record, opening),
            duration_seconds=message.duration_seconds,
            buyer_amount=buyer_amount,
        )
        result = await round_hook(
            listing=request.listing_record,
            message=message,
            history=list(request.history),
            seller_reference_amount=reference,
            listing_ref=listing_id,
            strategy_label=request.strategy_label,
            listing_source=request.listing_source,
        )
        state = dict(result.intermediate or {})
        return RoundEvaluation(
            our_amount=int(result.our_amount),
            strategy_label=result.strategy_label,
            decision=result.decision,
            pinned_proposal=None,
            uses_scalar_amount=bool(state.get("uses_scalar_amount", True)),
            buyer_amount=buyer_amount,
            domain_state=state,
        )

    async def evaluate_exact_selection(
        request: RoundRequest,
        message: BareMetalMessage,
        listing_id: str,
        proposal: Mapping[str, Any],
    ) -> RoundEvaluation:
        """Accept one exact option at its trusted amount, without price policy."""

        selection = exact_selection(proposal, None)
        assert selection is not None
        build_obligation = accepted_obligation_dispatch.get(selection.mechanism)
        if build_obligation is None:
            raise BareMetalNegotiationRefusal(
                "exact settlement selection uses an unsupported mechanism",
                status_code=400,
            )
        record = request.listing_record
        if Identity.model_validate(record.get("seller_principal")) != seller_principal:
            raise BareMetalNegotiationRefusal("listing seller identity changed")
        try:
            options = [
                SettlementOption.model_validate(value)
                for value in record.get("settlement_options") or []
            ]
        except (TypeError, ValueError) as exc:
            raise BareMetalNegotiationRefusal(
                "listing settlement options are invalid", status_code=400
            ) from exc
        selected_option = next(
            (
                option
                for option in options
                if option.option_id == selection.option_id
                and option.mechanism == selection.mechanism
            ),
            None,
        )
        if selected_option is None:
            raise BareMetalNegotiationRefusal(
                "selection does not exact-match one trusted listing option",
                status_code=400,
            )
        terms: BareMetalTerms | None = None
        service_terms: dict[str, Any] = {}
        if "bare_metal" in selected_option.params:
            terms, service_terms = await validate_physical_selection(
                request.repository,
                listing_id=listing_id,
                message=message,
                selection=selection,
                options=options,
                selected_option=selected_option,
            )
        try:
            built = build_obligation(
                selected_option.model_dump(mode="json"),
                {
                    "buyer_principal": request.buyer_principal.model_dump(mode="json"),
                    "seller_principal": seller_principal.model_dump(mode="json"),
                    "expiration_unix": selection.expiration_unix,
                    "duration_seconds": message.duration_seconds,
                    "domain_param_keys": ("bare_metal",),
                    "listing_id": listing_id,
                },
            )
        except (TypeError, ValueError) as exc:
            raise BareMetalNegotiationRefusal(
                "selected listing option cannot produce an exact accepted plan"
            ) from exc
        fields = proposal.get("fields") or {}
        unknown = sorted(set(fields).difference({"amount"}))
        if unknown:
            raise BareMetalNegotiationRefusal(
                "hosted settlement proposal may contain only amount", status_code=400
            )
        proposed_amount = _amount(fields.get("amount"), what="hosted settlement amount")
        if built.amount is not None:
            if proposed_amount is not None and proposed_amount != built.amount:
                raise BareMetalNegotiationRefusal(
                    "settlement amount differs from the trusted accepted amount",
                    status_code=400,
                )
        elif proposed_amount is not None:
            raise BareMetalNegotiationRefusal(
                "selected mechanism does not negotiate a settlement amount",
                status_code=400,
            )
        try:
            plan = SettlementPlan(
                buyer_principal=request.buyer_principal.model_dump(mode="json"),
                seller_principal=seller_principal.model_dump(mode="json"),
                service_terms={**built.service_terms, **service_terms},
                obligations=[SettlementObligation.model_validate(built.obligation)],
            )
        except (TypeError, ValueError) as exc:
            raise BareMetalNegotiationRefusal(
                "selected listing option cannot produce an exact accepted plan"
            ) from exc
        agreed_amount = built.amount if built.amount is not None else 0
        accepted_proposal = {
            "settlement_selection": selection.model_dump(mode="json"),
            "fields": {"amount": str(built.amount)} if built.amount is not None else {},
        }
        return RoundEvaluation(
            our_amount=agreed_amount,
            strategy_label=EXACT_SELECTION_STRATEGY,
            decision=NegotiationDecision(action="accept", proposal=accepted_proposal),
            pinned_proposal=accepted_proposal,
            uses_scalar_amount=built.amount is not None,
            buyer_amount=agreed_amount,
            domain_state={
                "exact_selection": {
                    "settlement_plan": plan.model_dump(mode="json"),
                    "settlement_selection": selection.model_dump(mode="json"),
                    "bare_metal_terms": (
                        terms.model_dump(mode="json", exclude_none=True)
                        if terms is not None
                        else None
                    ),
                }
            },
        )

    async def validate_physical_selection(
        repository: Any,
        *,
        listing_id: str,
        message: BareMetalMessage,
        selection: SettlementSelection,
        options: list[SettlementOption],
        selected_option: SettlementOption,
    ) -> tuple[BareMetalTerms, dict[str, Any]]:
        """Hold a machine-provisioning selection to the trusted physical facts."""

        try:
            demand = BareMetalBuyerDemand(
                duration_seconds=message.duration_seconds,
                access_method=message.access_method,
                ssh_public_key=message.ssh_public_key or "",
                settlement=selection,
                allow_off_session=(
                    selected_option.params.get("interaction") == "saved_instrument"
                ),
            )
            selected = validate_buyer_selection(demand=demand, advertised_options=options)
        except (TypeError, ValueError) as exc:
            raise BareMetalNegotiationRefusal(
                "hosted selection does not exact-match one trusted listing option",
                status_code=400,
            ) from exc
        trusted_listing = await repository.load_bare_metal_listing_payload(
            listing_id=listing_id
        )
        listing_binding = await repository.load_listing_binding(listing_id=listing_id)
        if trusted_listing is None or listing_binding is None:
            raise BareMetalNegotiationRefusal("trusted bare-metal listing is unavailable")
        facts = selected.facts
        if (
            facts.site_id != listing_binding.site_id
            or facts.physical_resource_id != listing_binding.physical_resource_id
            or facts.pool_id != listing_binding.pool_id
            or facts.physical_host_id != trusted_listing.physical_host_id
            or facts.access_method != message.access_method
        ):
            raise BareMetalNegotiationRefusal(
                "hosted selection changes trusted physical listing terms"
            )
        if (
            trusted_listing.min_duration_seconds is not None
            and message.duration_seconds < trusted_listing.min_duration_seconds
        ) or (
            trusted_listing.max_duration_seconds is not None
            and message.duration_seconds > trusted_listing.max_duration_seconds
        ):
            raise BareMetalNegotiationRefusal(
                "hosted selection duration is outside listing bounds"
            )
        if message.access_method not in trusted_listing.access_methods:
            raise BareMetalNegotiationRefusal(
                "hosted selection uses an unadvertised access method"
            )
        if message.access_ref is not None:
            raise BareMetalNegotiationRefusal(
                "buyer cannot supply hosted bare-metal access authority", status_code=400
            )
        terms = _escrow_terms(trusted_listing, message, listing_id)
        physical_terms = {
            "listing_id": listing_id,
            "option_id": selected.option.option_id,
            "option_facts": selected.facts.model_dump(mode="json", exclude_none=True),
            "provision_terms": terms.model_dump(mode="json", exclude_none=True),
        }
        return terms, {"bare_metal.v2": physical_terms}

    def reference_amount(
        _listing: Any,
        record: Mapping[str, Any],
        terms: NegotiationTerms,
        scalar: bool,
        pinned: Mapping[str, Any] | None,
    ) -> int:
        if not scalar or pinned is None or "settlement_selection" in pinned:
            return 0
        return _seller_reference_amount(
            _matching_acceptance(record, _escrow_proposal(pinned)),
            duration_seconds=int(terms.requested_duration_seconds or 0),
            buyer_amount=None,
        )

    def build_artifacts(acceptance: Acceptance, accepted: bool) -> Mapping[str, Any]:
        if not accepted:
            return {}
        state = acceptance.policy_state if isinstance(acceptance.policy_state, Mapping) else {}
        exact = state.get("exact_selection")
        if isinstance(exact, Mapping):
            return {
                "settlement_plan": exact["settlement_plan"],
                "settlement_selection": exact["settlement_selection"],
            }
        if acceptance.pinned_proposal is not None and (
            "settlement_selection" in acceptance.pinned_proposal
        ):
            raise NegotiationStateError(
                "an exact-option negotiation is accepted only when it opens"
            )
        try:
            artifacts = plan_builder(
                proposal=acceptance.pinned_proposal,
                agreed_amount=acceptance.agreed_amount,
                duration_seconds=acceptance.agreement.duration_seconds,
                uses_scalar_amount=acceptance.uses_scalar_amount,
                buyer_principal=acceptance.buyer_principal,
                seller_principal=acceptance.seller_principal,
                seller_wallet_address=seller_wallet_address,
                chain_config_paths=chain_paths,
            )
        except BareMetalSettlementPlanError as exc:
            raise BareMetalNegotiationRefusal(str(exc)) from exc
        response = {
            key: artifacts[key] for key in _ESCROW_RESPONSE_ARTIFACTS if key in artifacts
        }
        response.setdefault("accepted_escrow_proposal", acceptance.pinned_proposal)
        return response

    async def persist_opening(repository: Any, opening: OpeningRecord) -> None:
        copied = await repository.copy_listing_binding_to_thread(
            negotiation_id=opening.negotiation_id,
            listing_id=opening.listing_id,
        )
        require_domain(copied.binding)
        await repository.save_bare_metal_message(
            negotiation_id=opening.negotiation_id, message=opening.terms.decoded
        )

    async def persist_artifacts(
        repository: Any, acceptance: Acceptance, artifacts: Mapping[str, Any]
    ) -> None:
        state = acceptance.policy_state if isinstance(acceptance.policy_state, Mapping) else {}
        exact = state.get("exact_selection")
        if isinstance(exact, Mapping):
            terms = exact.get("bare_metal_terms")
        else:
            listing = await repository.load_bare_metal_listing_payload(
                listing_id=acceptance.listing_id
            )
            if listing is None:
                raise NegotiationStateError("trusted bare-metal listing is unavailable")
            terms = _escrow_terms(listing, acceptance.terms.decoded, acceptance.listing_id)
        if terms is not None:
            await repository.save_bare_metal_terms(
                negotiation_id=acceptance.negotiation_id, terms=terms
            )
        plan = artifacts.get("settlement_plan")
        if isinstance(plan, Mapping):
            await repository.commit_settlement_plan(
                negotiation_id=acceptance.negotiation_id,
                settlement_plan=dict(plan),
                buyer_principal=acceptance.buyer_principal,
                seller_principal=acceptance.seller_principal,
            )

    async def listing_is_paused(repository: Any, listing_id: str) -> bool:
        return bool(await repository.is_listing_paused(listing_id=listing_id))

    async def check_source(
        _repository: Any, resolved: ResolvedNegotiation
    ) -> ListingSourceVerdict:
        return await listing_source_check(resolved.listing_id)

    hooks = NegotiationDomainHooks(
        decode_terms=decode_terms,
        validate_opening=lambda _listing, _record, _terms: None,
        validate_continuation=validate_continuation,
        evaluate_round=evaluate,
        determine_strategy=lambda _listing, _record: None,
        reference_amount=reference_amount,
        amount_from_proposal=_proposal_amount,
        proposal_from_amount=_proposal_from_amount,
        agreement_terms=lambda _listing, _record, terms: AgreementTerms(
            duration_seconds=int(terms.requested_duration_seconds or 0)
        ),
        build_artifacts=build_artifacts,
        decision_wire=_decision_wire,
        listing_is_live=lambda record: str(record.get("status") or "") == "open",
        listing_is_paused=listing_is_paused,
        storefront_is_paused=lambda: trading_pause.paused,
        stage_event=stage_event,
        persist_opening=persist_opening,
        persist_artifacts=persist_artifacts,
        check_listing_source=check_source,
    )
    return NegotiationRuntime(
        resolve_opening=resolve_opening,
        resolve_continuation=resolve_continuation,
    )


__all__ = [
    "BareMetalNegotiationRefusal",
    "EXACT_SELECTION_STRATEGY",
    "build_bare_metal_negotiation_runtime",
    "exact_selection",
]
