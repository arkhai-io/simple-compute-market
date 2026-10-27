"""A quota-backed storefront's negotiation guards, seller round, and runtime.

Escrow-specific steps are injected by the storefront; this library imports no mechanism kit.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import re
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial
from fractions import Fraction
from typing import Any, Protocol

from core_storefront.stage_log import stage_event
from market_core import MarketDomainContract, SettlementStageTable
from market_core.schemas import (
    Agreement,
    ProvisionTerms,
    SettlementObligation,
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
)
from market_identity import Identity, IdentityScheme
from market_negotiation_runtime import (
    Acceptance,
    AgreementTerms,
    NegotiationDomainHooks,
    NegotiationRuntime,
    NegotiationStateError,
    NegotiationTerms,
    OfferUnfulfillableError,
    OpeningWrite,
    ResolvedNegotiation,
    RoundEvaluation,
    RoundRequest,
)
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationMiddleware,
    NegotiationRound,
    NegotiationStep,
    load_negotiation_chain,
    normalize_policies_by_escrow_kind_config,
    register_negotiation_middleware,
    run_negotiation_chain_with_context,
    their_last_proposal,
)
from market_policy.scalar_policies import (
    _amount_from_proposal,
    _loads_json_list,
    make_escrow_kind_dispatch_middleware,
    proposal_uses_scalar_amount,
)
from market_policy.seller_round import SellerRoundResult

from arkhai_api.purchase import provision_key_id, provision_key_mode, provision_quantity
from arkhai_api_selling.contributions import SellingContributions
from arkhai_api_selling.persistence import write_credit_terms
from arkhai_api_selling.pricing import (
    checked_credit_total,
    determine_strategy,
    domain_listing_resource,
    extract_unit_price_from_order,
)
from arkhai_api_selling.quota_listing import (
    ListingSourceCheck,
    listing_binding,
    record_accepted_listing,
)

logger = logging.getLogger(__name__)

# Refusal vocabulary shared with the authority, whose issuance re-check uses the same names.
KEY_NOT_FOUND = "key_not_found"
KEY_NOT_OWNED = "key_not_owned"
KEY_REVOKED = "key_revoked"
QUOTA_EXHAUSTED = "quota_exhausted"

QUOTA_GUARD = "credit_quota_guard"
KEY_OWNERSHIP_GUARD = "key_owned_by_buyer_principal"
_TERMINAL_POLICY = "listed_price"

EscrowProposalNormalizer = Callable[[Mapping[str, Any], list[Any] | None], dict[str, Any]]
"""Canonicalizes a buyer's escrow proposal against the listing's accepted escrows, raising when it fits none."""

KeyLookup = Callable[[str], Awaitable[dict[str, Any] | None]]
"""Resolves a key ID to its authority record, or None when unknown; captured once per round."""

AcceptedObligationDispatch = Mapping[
    str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None
]


def round_zero_guard_name(contributions: SellingContributions) -> str:
    return f"{contributions.schema_name}_round_zero_guard"


def default_guards(contributions: SellingContributions) -> tuple[str, ...]:
    """The guards every chain runs ahead of its configured policies, in order."""
    return (
        round_zero_guard_name(contributions),
        "buyer_counter_guard",
        QUOTA_GUARD,
        KEY_OWNERSHIP_GUARD,
        "escrow_shape_guard",
    )


def _is_round_zero(history: list[NegotiationRound]) -> bool:
    return (
        len(history) == 1
        and history[0].round_number == 0
        and history[0].sender == "them"
        and history[0].action == "initial"
    )


def _reject(reason: str, context: NegotiationContext) -> NegotiationStep:
    return NegotiationDecision(action="reject", reason=reason), context


def make_round_zero_guard(
    contributions: SellingContributions,
    normalize_escrow_proposal: EscrowProposalNormalizer | None,
) -> NegotiationMiddleware:
    """Validate and canonicalize the opening round; with no normalizer, an escrow proposal is refused."""

    def guard(
        history: list[NegotiationRound], context: NegotiationContext
    ) -> NegotiationStep:
        if not _is_round_zero(history):
            return None, context

        listing = context.listing or {}
        quantity = context.intermediate.get("requested_quantity")
        if quantity is None:
            return _reject(
                "credit_quantity_missing: provision_terms.payload.quantity is required",
                context,
            )
        if int(quantity) < 1:
            return _reject("credit_quantity_invalid: quantity must be >= 1", context)

        key_mode = context.intermediate.get("key_mode") or "new"
        if key_mode not in ("new", "existing"):
            return _reject(f"key_disposition_invalid: mode {key_mode!r}", context)
        if key_mode == "existing" and not context.intermediate.get("key_id"):
            return _reject(
                "key_disposition_invalid: existing mode requires key_id", context
            )

        proposal = their_last_proposal(history)
        accepted_proposal_dict = None
        if isinstance(proposal, dict) and proposal.get("settlement_selection") is not None:
            try:
                selection = proposal["settlement_selection"]
                # `params` carries the buyer's inputs to the mechanism and is optional.
                if (
                    not isinstance(selection, dict)
                    or not {"mechanism", "option_id", "expiration_unix"} <= set(selection)
                    or not set(selection) <= {"mechanism", "option_id", "expiration_unix", "params"}
                    or not isinstance(selection.get("params") or {}, dict)
                ):
                    raise ValueError("selection has invalid fields")
                mechanism = selection["mechanism"]
                option_id = selection["option_id"]
                expiration_unix = selection["expiration_unix"]
                if not isinstance(mechanism, str) or not mechanism:
                    raise ValueError("selection mechanism is required")
                if (
                    not isinstance(option_id, str)
                    or re.fullmatch(r"[0-9a-f]{64}", option_id) is None
                ):
                    raise ValueError("selection option_id is invalid")
                if (
                    isinstance(expiration_unix, bool)
                    or not isinstance(expiration_unix, int)
                    or expiration_unix <= 0
                ):
                    raise ValueError("selection expiration is invalid")
                options = _loads_json_list(listing.get("settlement_options"))
                matches = [
                    option
                    for option in options
                    if isinstance(option, dict)
                    and option.get("option_id") == option_id
                    and option.get("mechanism") == mechanism
                ]
                if len(matches) != 1:
                    raise ValueError("selection does not exact-match one listing option")
                context.intermediate["accepted_settlement_selection"] = dict(selection)
                context.intermediate["accepted_settlement_option"] = matches[0]
            except Exception as exc:
                return _reject(f"invalid_settlement_selection:{exc}", context)
        elif isinstance(proposal, dict):
            accepted = _loads_json_list(listing.get("accepted_escrows"))
            try:
                if normalize_escrow_proposal is None:
                    raise ValueError("this storefront settles no escrow")
                accepted_proposal_dict = normalize_escrow_proposal(
                    proposal, accepted if accepted else None
                )
            except Exception as exc:
                return _reject(f"invalid_escrow_proposal:{exc}", context)
            context.intermediate["accepted_escrow_proposal"] = accepted_proposal_dict

        proposal_for_scalar = (
            proposal
            if context.intermediate.get("accepted_settlement_selection") is not None
            else accepted_proposal_dict
            if accepted_proposal_dict is not None
            else proposal
        )
        uses_scalar_amount = proposal_uses_scalar_amount(listing, proposal_for_scalar)
        context.intermediate["uses_scalar_amount"] = uses_scalar_amount
        if uses_scalar_amount and _amount_from_proposal(proposal_for_scalar) is None:
            return _reject(
                "missing_amount: buyer's escrow proposal has no fields.amount", context
            )
        return None, context

    guard.__name__ = round_zero_guard_name(contributions)
    return guard


def make_quota_guard(contributions: SellingContributions) -> NegotiationMiddleware:
    """Veto a quantity the captured quota snapshot cannot cover; advisory, since issuance re-reserves."""

    def guard(
        history: list[NegotiationRound], context: NegotiationContext
    ) -> NegotiationStep:
        listing_resource = domain_listing_resource(
            contributions, context.listing.get("listing_resource")
        )
        if listing_resource is None:
            return None, context

        quantity = context.intermediate.get("requested_quantity")
        if quantity is None:
            return None, context  # the round-zero guard already rejected fresh threads
        quantity = int(quantity)

        snapshot = context.available_resources or {}
        if "resources" not in snapshot:
            return None, context
        resource_id = contributions.issuance_projection(listing_resource).resource_id
        for row in snapshot.get("resources") or []:
            if resource_id and str(row.get("resource_id")) != str(resource_id):
                continue
            available = row.get("available_units")
            if available is None:
                continue
            if int(available) >= quantity:
                return None, context
        return _reject(
            f"{QUOTA_EXHAUSTED}: requested {quantity} token(s), "
            f"quota resource {resource_id!r} cannot cover it",
            context,
        )

    guard.__name__ = QUOTA_GUARD
    return guard


def key_owned_by_buyer_principal(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Reject an existing-key claim unless its owner is the buyer; advisory, since issuance re-checks."""
    if (context.intermediate.get("key_mode") or "new") != "existing":
        return None, context

    key_id = context.intermediate.get("key_id")
    record = context.intermediate.get("key_record")
    if not isinstance(record, dict):
        return _reject(
            f"{KEY_NOT_FOUND}: key {key_id!r} is not known to this seller", context
        )
    if (record.get("status") or "active") != "active":
        return _reject(
            f"{KEY_REVOKED}: key {key_id!r} is {record.get('status')!r}", context
        )

    owner_scheme = record.get("owner_scheme")
    owner_identifier = record.get("owner_id")
    if owner_scheme is None and owner_identifier is None:
        return None, context
    try:
        owner = Identity(
            scheme=IdentityScheme(str(owner_scheme)),
            identifier=str(owner_identifier),
        )
        buyer = Identity.model_validate(context.intermediate.get("buyer_principal"))
    except (TypeError, ValueError):
        return _reject(
            f"{KEY_NOT_OWNED}: key {key_id!r} has no matching principal", context
        )
    if owner == buyer:
        return None, context
    return _reject(
        f"{KEY_NOT_OWNED}: key {key_id!r} is bound to a different marketplace principal",
        context,
    )


def register_guards(
    contributions: SellingContributions,
    *,
    normalize_escrow_proposal: EscrowProposalNormalizer | None = None,
) -> None:
    """Register the domain's guards under the names its chains use."""
    register_negotiation_middleware(round_zero_guard_name(contributions))(
        make_round_zero_guard(contributions, normalize_escrow_proposal)
    )
    register_negotiation_middleware(QUOTA_GUARD)(make_quota_guard(contributions))
    register_negotiation_middleware(KEY_OWNERSHIP_GUARD)(key_owned_by_buyer_principal)


class SellerRoundHook(Protocol):
    async def __call__(
        self,
        *,
        listing: Mapping[str, Any],
        history: list[NegotiationRound],
        buyer_principal: Identity,
        requested_quantity: int | None = None,
        key_mode: str | None = None,
        key_id: str | None = None,
        strategy_label: str | None = None,
    ) -> SellerRoundResult: ...


def load_chain(
    contributions: SellingContributions,
    *,
    negotiation_config: Any = None,
    chain_config_paths: Mapping[str, str | None] | None = None,
    normalize_escrow_proposal: EscrowProposalNormalizer | None = None,
) -> list[NegotiationMiddleware]:
    """The default guards, then the configured policies; registers the guards first so the chain resolves them."""
    register_guards(contributions, normalize_escrow_proposal=normalize_escrow_proposal)
    guards = list(default_guards(contributions))
    raw_policies = getattr(negotiation_config, "policies", None)
    policies_by_kind = normalize_policies_by_escrow_kind_config(raw_policies)
    if policies_by_kind:
        return load_negotiation_chain(guards) + [
            make_escrow_kind_dispatch_middleware(
                policies_by_kind,
                chain_config_paths=dict(chain_config_paths or {}),
            )
        ]

    policy_names = list(raw_policies or [])
    if not policy_names:
        policy_mode = (
            getattr(negotiation_config, "policy_mode", "") or ""
        ).strip() or _TERMINAL_POLICY
        policy_names = [policy_mode]
    for guard in reversed(guards):
        if guard not in policy_names:
            policy_names.insert(0, guard)
    return load_negotiation_chain(policy_names)


def seller_reference_amount(
    listing: Mapping[str, Any],
    quantity: int | None,
    *,
    noun: str,
    floor_key: str,
    default_min_price: Any = None,
    proposal: Mapping[str, Any] | None = None,
) -> int:
    """quantity × the per-credit rate of the option ``proposal`` selects, exact for a rational floor."""
    unit = extract_unit_price_from_order(
        dict(listing),
        noun=noun,
        floor_key=floor_key,
        default_min_price=default_min_price,
        proposal=dict(proposal) if isinstance(proposal, Mapping) else None,
    )
    count = int(quantity) if quantity is not None else 1
    if isinstance(unit, int):
        return checked_credit_total(unit, count, noun=noun)
    return math.floor(Fraction(unit) * count)


class _DefaultSellerRoundHook:
    def __init__(
        self,
        contributions: SellingContributions,
        capacity: Any,
        key_lookup: KeyLookup | None,
        *,
        negotiation_config: Any,
        chain_config_paths: Mapping[str, str | None] | None,
        default_min_price: Any,
        floor_key: str,
        normalize_escrow_proposal: EscrowProposalNormalizer | None,
    ) -> None:
        self._contributions = contributions
        self._capacity = capacity
        self._key_lookup = key_lookup
        self._negotiation_config = negotiation_config
        self._chain_config_paths = chain_config_paths
        self._default_min_price = default_min_price
        self._floor_key = floor_key
        self._normalize_escrow_proposal = normalize_escrow_proposal

    async def __call__(
        self,
        *,
        listing: Mapping[str, Any],
        history: list[NegotiationRound],
        buyer_principal: Identity,
        requested_quantity: int | None = None,
        key_mode: str | None = None,
        key_id: str | None = None,
        strategy_label: str | None = None,
    ) -> SellerRoundResult:
        policy_inputs: dict[str, Any] = {}
        snapshot = await self._capacity.snapshot()
        if snapshot is not None:
            policy_inputs["available_resources"] = {"resources": snapshot}
        if (key_mode or "new") == "existing" and key_id and self._key_lookup:
            try:
                policy_inputs["key_record"] = await self._key_lookup(key_id)
            except Exception as exc:
                # An unreachable authority admits no claim: the guard sees no record.
                logger.warning("[NEGOTIATION] key lookup failed for %r: %s", key_id, exc)
                policy_inputs["key_record"] = None

        listing_dict = dict(listing)
        if not strategy_label:
            strategy_label = determine_strategy(self._contributions, listing_dict)
        if not strategy_label:
            raise ValueError(
                f"Listing {listing_dict.get('listing_id')!r} has no usable "
                "strategy for negotiation"
            )

        their_proposal = None
        for item in reversed(history):
            if item.sender == "them":
                their_proposal = item.proposal
                break
        uses_scalar_amount = proposal_uses_scalar_amount(listing_dict, their_proposal)
        reference_amount = (
            seller_reference_amount(
                listing_dict,
                requested_quantity,
                noun=self._contributions.refusal_noun,
                floor_key=self._floor_key,
                default_min_price=self._default_min_price,
                proposal=their_proposal if isinstance(their_proposal, Mapping) else None,
            )
            if uses_scalar_amount
            else 0
        )

        chain = load_chain(
            self._contributions,
            negotiation_config=self._negotiation_config,
            chain_config_paths=self._chain_config_paths,
            normalize_escrow_proposal=self._normalize_escrow_proposal,
        )
        context = NegotiationContext(
            direction="maximize",
            our_reference_amount=int(reference_amount),
            listing=listing_dict,
            our_escrow_proposal=their_proposal,
            available_resources=policy_inputs.get("available_resources") or {},
            intermediate={
                "requested_quantity": requested_quantity,
                "key_mode": key_mode or "new",
                "key_id": key_id,
                "key_record": policy_inputs.get("key_record"),
                "buyer_principal": buyer_principal.model_dump(mode="json"),
                "seller_reference_amount": int(reference_amount),
                "uses_scalar_amount": uses_scalar_amount,
            },
        )
        decision, context = run_negotiation_chain_with_context(chain, history, context)
        chain_label = ",".join(
            type(mw).__name__ if not hasattr(mw, "__name__") else mw.__name__
            for mw in chain
        )
        uses_scalar_amount = context.intermediate.get("uses_scalar_amount", True)
        return SellerRoundResult(
            our_amount=int(reference_amount) if uses_scalar_amount else 0,
            strategy_label=strategy_label,
            direction="maximize",
            chain_label=chain_label,
            decision=decision,
            intermediate=dict(context.intermediate),
        )


def default_seller_round_hook(
    contributions: SellingContributions,
    capacity: Any,
    key_lookup: KeyLookup | None = None,
    *,
    negotiation_config: Any = None,
    chain_config_paths: Mapping[str, str | None] | None = None,
    default_min_price: Any = None,
    floor_key: str,
    normalize_escrow_proposal: EscrowProposalNormalizer | None = None,
) -> SellerRoundHook:
    """The seller's round: capture the quota snapshot and key record, then run the synchronous chain."""
    return _DefaultSellerRoundHook(
        contributions,
        capacity,
        key_lookup,
        negotiation_config=negotiation_config,
        chain_config_paths=chain_config_paths,
        default_min_price=default_min_price,
        floor_key=floor_key,
        normalize_escrow_proposal=normalize_escrow_proposal,
    )


@dataclass(frozen=True)
class RoundSettings:
    """What the seller's round reads from configuration, read once per round.

    ``floor_key`` is the floor setting as the composing storefront spells it,
    which the pricing refusals name; the library reads no configuration itself.
    """

    floor_key: str
    negotiation_config: Any = None
    chain_config_paths: Mapping[str, str | None] | None = None
    default_min_price: Any = None


class EscrowAcceptance(Protocol):
    """The escrow path of an acceptance; each method raises ``OfferUnfulfillableError`` before anything is recorded."""

    def offer(self, acceptance: Acceptance) -> dict[str, Any]:
        """The escrow proposal a round that does not accept offers back at its amount."""

    def accept(self, acceptance: Acceptance) -> dict[str, Any]:
        """The accepted escrow's artifacts, its settlement plan among them."""


class _QuotaSnapshot:
    """One listing's quota snapshot, read only at its bound site and only where its backing bounds availability."""

    def __init__(
        self, repository: Any, listing_id: str, capacity_client: Callable[[Any], Any]
    ) -> None:
        self._repository = repository
        self._listing_id = listing_id
        self._capacity_client = capacity_client

    async def snapshot(self) -> list[dict[str, Any]] | None:
        binding = await listing_binding(self._repository, self._listing_id)
        if binding is None:
            raise NegotiationStateError(
                f"listing {self._listing_id!r} has no durable capacity binding"
            )
        try:
            site = self._capacity_client(self._repository).site(binding.site_id)
        except KeyError:
            raise NegotiationStateError(
                f"listing {self._listing_id!r} is bound to unconfigured site "
                f"{binding.site_id!r}"
            ) from None

        async def declared() -> None:
            return None

        async def available() -> list[dict[str, Any]]:
            return list(await site.snapshot() or [])

        return await binding.backing.judge_async(declared, available)


_PROVISION_TERMS_FIELDS = frozenset(ProvisionTerms.model_fields)


def decode_terms(domain: MarketDomainContract, raw_terms: Any) -> NegotiationTerms:
    """The domain's message, and its wire form narrowed to ``ProvisionTerms``' fields, which forbid extras."""
    if raw_terms is None:
        return NegotiationTerms(decoded=None, wire=None)
    raw = raw_terms.model_dump(mode="json") if hasattr(raw_terms, "model_dump") else raw_terms
    decoded = domain.codecs.message(raw)
    if not hasattr(decoded, "model_dump"):
        return NegotiationTerms(decoded=decoded, wire=dict(raw))
    dumped = decoded.model_dump(mode="json")
    wire = {key: value for key, value in dumped.items() if key in _PROVISION_TERMS_FIELDS}
    return NegotiationTerms(decoded=decoded, wire=wire)


def _validate_opening(
    noun: str,
    _listing: Any,
    _listing_record: Mapping[str, Any],
    terms: NegotiationTerms,
) -> None:
    if terms.decoded is None or provision_quantity(terms.decoded) is None:
        raise NegotiationStateError(
            f"{noun} negotiation requires domain-valid provision terms"
        )


def _agreement(
    _listing: Any,
    _listing_record: Mapping[str, Any],
    _terms: NegotiationTerms,
) -> AgreementTerms:
    return AgreementTerms(0)


def _amount(proposal: Mapping[str, Any] | None) -> int | None:
    value = _amount_from_proposal(proposal)
    return int(value) if value is not None else None


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


def _selected_policy_state(
    listing: Mapping[str, Any],
    proposal: Mapping[str, Any] | None,
    admitted_mechanisms: Collection[str],
) -> dict[str, Any] | None:
    if not isinstance(proposal, Mapping):
        return None
    raw_selection = proposal.get("settlement_selection")
    if raw_selection is None:
        return None
    if not isinstance(raw_selection, Mapping):
        raise NegotiationStateError("selected settlement selection is not exact")
    required = {"mechanism", "option_id", "expiration_unix"}
    if not required <= set(raw_selection) or set(raw_selection) - required - {"params"}:
        raise NegotiationStateError("selected settlement selection is not exact")
    try:
        selection = SettlementSelection.model_validate(raw_selection)
    except (TypeError, ValueError) as exc:
        raise NegotiationStateError("selected settlement selection is invalid") from exc
    if selection.mechanism not in admitted_mechanisms:
        raise NegotiationStateError(
            "exact settlement selection uses an unsupported mechanism"
        )
    raw_options = listing.get("settlement_options", ())
    if isinstance(raw_options, str):
        try:
            raw_options = json.loads(raw_options)
        except (TypeError, ValueError) as exc:
            raise NegotiationStateError(
                "trusted listing settlement options are invalid"
            ) from exc
    if not isinstance(raw_options, Sequence) or isinstance(
        raw_options, (str, bytes, bytearray)
    ):
        raise NegotiationStateError("trusted listing settlement options are invalid")
    matches: list[SettlementOption] = []
    for raw_option in raw_options:
        if not isinstance(raw_option, Mapping):
            continue
        if (
            raw_option.get("option_id") == selection.option_id
            and raw_option.get("mechanism") == selection.mechanism
        ):
            try:
                matches.append(SettlementOption.model_validate(raw_option))
            except (TypeError, ValueError) as exc:
                raise NegotiationStateError(
                    "selected trusted settlement option is invalid"
                ) from exc
    if len(matches) != 1:
        raise NegotiationStateError(
            "selected settlement selection no longer exact-matches the trusted listing"
        )
    return {
        "accepted_settlement_selection": selection.model_dump(mode="json"),
        "accepted_settlement_option": matches[0].model_dump(mode="json"),
    }


def _preserve_selected_round_selection(
    listing: Mapping[str, Any],
    history: Sequence[Any],
    admitted_mechanisms: Collection[str],
) -> tuple[tuple[Any, ...], dict[str, Any] | None]:
    opening_proposal = (
        history[0].proposal
        if history and isinstance(history[0].proposal, Mapping)
        else None
    )
    state = _selected_policy_state(listing, opening_proposal, admitted_mechanisms)
    pinned = state["accepted_settlement_selection"] if state is not None else None
    buyer_rounds = [
        (index, item)
        for index, item in enumerate(history)
        if item.sender == "them" and isinstance(item.proposal, Mapping)
    ]
    for _index, item in buyer_rounds:
        candidate = item.proposal.get("settlement_selection")
        if candidate is None:
            continue
        if pinned is None or dict(candidate) != pinned:
            raise NegotiationStateError(
                "opening settlement selection cannot change during negotiation"
            )
    if pinned is None or not buyer_rounds:
        return tuple(history), state
    last_index, last_buyer = buyer_rounds[-1]
    if last_buyer.proposal.get("settlement_selection") is not None:
        return tuple(history), state
    if {"chain_name", "escrow_address"} & set(last_buyer.proposal):
        raise NegotiationStateError(
            "opening settlement mechanism cannot change during negotiation"
        )
    proposal = dict(last_buyer.proposal)
    proposal["settlement_selection"] = dict(pinned)
    preserved = list(history)
    preserved[last_index] = replace(last_buyer, proposal=proposal)
    return tuple(preserved), state


def _acceptance_policy_state(
    acceptance: Acceptance,
    admitted_mechanisms: Collection[str],
) -> Mapping[str, Any]:
    pinned = _selected_policy_state(
        acceptance.listing_record,
        acceptance.pinned_proposal,
        admitted_mechanisms,
    )
    if pinned is None:
        return (
            acceptance.policy_state
            if isinstance(acceptance.policy_state, Mapping)
            else {}
        )
    for candidate in (acceptance.policy_state, acceptance.binding):
        if not isinstance(candidate, Mapping):
            continue
        selected = candidate.get("accepted_settlement_selection")
        if selected is not None and selected != pinned["accepted_settlement_selection"]:
            raise NegotiationStateError(
                "selected settlement policy state changed after opening"
            )
    return pinned


def _accepted_selection_artifacts(
    contributions: SellingContributions,
    stages: SettlementStageTable,
    dispatch: AcceptedObligationDispatch,
    *,
    selection: Mapping[str, Any],
    option: Mapping[str, Any],
    agreed_amount: int,
    buyer_principal: Identity,
    seller_principal: Identity,
    listing: Mapping[str, Any],
    provision_terms: Any,
) -> dict[str, Any]:
    """The accepted plan, built by the selected mechanism's registration.

    A mechanism that builds no obligation is accepted without a plan only when its
    seller entry ``settles_from_agreement``; otherwise nothing could verify its settlement.
    """
    accepted = SettlementSelection.model_validate(selection)
    advertised = SettlementOption.model_validate(option)
    if (
        accepted.option_id != advertised.option_id
        or accepted.mechanism != advertised.mechanism
    ):
        raise OfferUnfulfillableError("settlement_selection_not_exact")
    stage = stages.get(accepted.mechanism)
    if stage is not None:
        stage.validate_selection(accepted)
    if accepted.mechanism not in dispatch:
        raise OfferUnfulfillableError("settlement_mechanism_unsupported")
    build_obligation = dispatch[accepted.mechanism]
    if build_obligation is None:
        if stage is None or not getattr(stage, "settles_from_agreement", False):
            raise OfferUnfulfillableError("settlement_selection_requires_plan")
        return {
            "settlement_selection": accepted.model_dump(mode="json", exclude_none=True),
            "_agreement_settlement_option": advertised.model_dump(
                mode="json", exclude_none=True
            ),
        }
    if accepted.expiration_unix is None:
        raise OfferUnfulfillableError("settlement_expiration_required")
    quantity = provision_quantity(provision_terms)
    if quantity is None:
        raise OfferUnfulfillableError(f"{contributions.table_prefix}_quantity_unavailable")
    listing_id = listing.get("listing_id")
    if not isinstance(listing_id, str) or not listing_id:
        raise OfferUnfulfillableError("selected_listing_identity_unavailable")
    try:
        built = build_obligation(
            advertised.model_dump(mode="json"),
            {
                "buyer_principal": buyer_principal.model_dump(mode="json"),
                "seller_principal": seller_principal.model_dump(mode="json"),
                "expiration_unix": accepted.expiration_unix,
                "unit_quantity": int(quantity),
                "domain_param_keys": (),
                "listing_id": listing_id,
            },
        )
    except (TypeError, ValueError) as exc:
        raise OfferUnfulfillableError("selected_settlement_option_not_exact") from exc
    if built.amount is not None:
        if agreed_amount != built.amount:
            raise OfferUnfulfillableError("selected_amount_not_quantity_scaled")
    elif agreed_amount:
        raise OfferUnfulfillableError("selection_amount_not_negotiable")
    service_terms = {
        **built.service_terms,
        contributions.kind: {
            "listing_id": listing_id,
            "order": dict(listing),
            "quantity": quantity,
            "key_mode": provision_key_mode(provision_terms),
            "key_id": provision_key_id(provision_terms),
        },
    }
    try:
        plan = SettlementPlan(
            buyer_principal=buyer_principal.model_dump(mode="json"),
            seller_principal=seller_principal.model_dump(mode="json"),
            service_terms=service_terms,
            obligations=[SettlementObligation.model_validate(built.obligation)],
        )
    except (TypeError, ValueError) as exc:
        raise OfferUnfulfillableError("selected_settlement_option_not_exact") from exc
    return {
        "settlement_selection": accepted.model_dump(mode="json", exclude_none=True),
        "settlement_plan": plan.model_dump(mode="json"),
        "_agreement_settlement_option": advertised.model_dump(
            mode="json", exclude_none=True
        ),
    }


def _json_compatible(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _json_compatible(value.model_dump(mode="json", exclude_none=True))
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    return value


def _with_agreement(
    acceptance: Acceptance,
    artifacts: dict[str, Any],
    settlement_artifacts_builder: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    settlement_raw = artifacts.pop("_agreement_settlement_option", None)
    settlement = (
        SettlementOption.model_validate(settlement_raw)
        if settlement_raw is not None
        else None
    )
    plan = artifacts.get("settlement_plan")
    asset = settlement.asset if settlement is not None else None
    if asset is None and isinstance(plan, Mapping):
        obligations = plan.get("obligations")
        if (
            isinstance(obligations, list)
            and obligations
            and isinstance(obligations[0], Mapping)
        ):
            raw_asset = obligations[0].get("asset")
            asset = raw_asset if isinstance(raw_asset, str) else None
    provision = acceptance.terms.wire
    if provision is None and hasattr(acceptance.terms.decoded, "model_dump"):
        provision = acceptance.terms.decoded.model_dump(mode="json", exclude_none=True)
    provision_terms = (
        _json_compatible(provision) if isinstance(provision, Mapping) else None
    )
    listing_bytes = json.dumps(
        _json_compatible(acceptance.listing_record),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    if acceptance.accepted_at is None or acceptance.agreement.start_utc is None:
        raise RuntimeError("accepted Agreement lacks fixed acceptance timestamps")
    agreement = Agreement(
        negotiation_id=acceptance.negotiation_id,
        listing_id=acceptance.listing_id,
        listing_hash=hashlib.sha256(listing_bytes).hexdigest(),
        buyer=acceptance.buyer_principal.model_dump(mode="json"),
        seller=acceptance.seller_principal.model_dump(mode="json"),
        settlement=settlement,
        settlement_params=(
            SettlementSelection.model_validate(artifacts["settlement_selection"]).params
            if isinstance(artifacts.get("settlement_selection"), Mapping)
            else None
        ),
        amount=acceptance.agreed_amount,
        asset=asset,
        duration_seconds=acceptance.agreement.duration_seconds,
        start_utc=acceptance.agreement.start_utc,
        provision_terms=provision_terms,
        accepted_at=acceptance.accepted_at.isoformat().replace("+00:00", "Z"),
    )
    agreement_bytes = agreement.model_dump_json(exclude_none=True).encode("utf-8")
    artifacts["agreement"] = agreement
    if settlement is not None:
        data = settlement_artifacts_builder(agreement.model_dump(mode="json", exclude_none=True))
        if data:
            artifacts["settlement_data"] = data
    artifacts["agreement_bytes"] = base64.b64encode(agreement_bytes).decode("ascii")
    return artifacts


async def open_negotiation(repository: Any, write: OpeningWrite) -> None:
    """Record the opening in one transaction: the thread, its message, its listing's binding, and its purchase terms.

    A failure in any of them leaves none, so no continuation finds a bound
    thread without the terms it validates against.
    """
    decoded = write.opening.terms.decoded
    quantity = provision_quantity(decoded)
    terms = (
        partial(
            write_credit_terms,
            negotiation_id=write.opening.negotiation_id,
            quantity=int(quantity),
            key_mode=provision_key_mode(decoded),
            key_id=provision_key_id(decoded),
        )
        if quantity is not None
        else None
    )
    await repository.open_negotiation(
        thread=write.thread, message=write.message, domain_writes=terms
    )


async def _validate_continuation(
    noun: str,
    repository: Any,
    _listing: Any,
    _listing_record: Mapping[str, Any],
    terms: NegotiationTerms,
    thread: Mapping[str, Any],
) -> None:
    negotiation_id = thread.get("negotiation_id")
    if not isinstance(negotiation_id, str) or not negotiation_id:
        raise NegotiationStateError(f"{noun} thread has no negotiation identity")
    recorded = await repository.load_credit_terms(negotiation_id=negotiation_id)
    quantity = provision_quantity(terms.decoded)
    key_mode = provision_key_mode(terms.decoded)
    key_id = provision_key_id(terms.decoded)
    if quantity is None:
        if recorded is not None:
            raise NegotiationStateError(
                f"recorded {noun} terms do not match the negotiation transcript"
            )
        return
    if not recorded or (
        int(recorded.get("quantity", -1)),
        str(recorded.get("key_mode") or ""),
        recorded.get("key_id"),
    ) != (int(quantity), key_mode, key_id):
        raise NegotiationStateError(
            f"recorded {noun} terms do not match the negotiation transcript"
        )


def reference_amount(
    contributions: SellingContributions,
    round_settings: Callable[[], RoundSettings],
    listing: Any,
    _listing_record: Mapping[str, Any],
    terms: NegotiationTerms,
    uses_scalar_amount: bool,
    pinned_proposal: Mapping[str, Any] | None,
) -> int:
    """quantity × the rate of the option the buyer's pinned proposal selects."""
    if not uses_scalar_amount:
        return 0
    settings = round_settings()
    return seller_reference_amount(
        listing,
        provision_quantity(terms.decoded),
        noun=contributions.refusal_noun,
        floor_key=settings.floor_key,
        default_min_price=settings.default_min_price,
        proposal=pinned_proposal,
    )


async def place_quota_hold(
    stages: SettlementStageTable,
    dispatch: AcceptedObligationDispatch,
    repository: Any,
    acceptance: Acceptance,
) -> None:
    """Place the selected stage's best-effort quota hold after acceptance."""
    state = _acceptance_policy_state(acceptance, dispatch)
    selection = state.get("accepted_settlement_selection")
    if not isinstance(selection, Mapping):
        return
    stage = stages.get(selection.get("mechanism"))
    if stage is None:
        raise OfferUnfulfillableError("settlement_mechanism_unsupported")
    await stage.place_hold(repository, acceptance)


def acceptance_artifacts(
    contributions: SellingContributions,
    stages: SettlementStageTable,
    dispatch: AcceptedObligationDispatch,
    escrow: EscrowAcceptance | None,
    settlement_artifacts_builder: Callable[[Mapping[str, Any]], dict[str, Any]],
    acceptance: Acceptance,
    accepted: bool,
) -> Mapping[str, Any]:
    """A round's artifacts: a selection's Agreement and plan, or an escrow through ``escrow``."""
    state = _acceptance_policy_state(acceptance, dispatch)
    selection = state.get("accepted_settlement_selection")
    option = state.get("accepted_settlement_option")
    if isinstance(selection, Mapping) and isinstance(option, Mapping):
        artifacts = _accepted_selection_artifacts(
            contributions,
            stages,
            dispatch,
            selection=selection,
            option=option,
            agreed_amount=acceptance.agreed_amount,
            buyer_principal=acceptance.buyer_principal,
            seller_principal=acceptance.seller_principal,
            listing=acceptance.listing_record,
            provision_terms=acceptance.terms.decoded,
        )
        if accepted:
            return _with_agreement(acceptance, artifacts, settlement_artifacts_builder)
        return {"settlement_selection": artifacts["settlement_selection"]}
    if not accepted and acceptance.pinned_proposal is None:
        return {}
    if escrow is None:
        raise OfferUnfulfillableError("settlement_selection_required")
    if not accepted:
        return {"accepted_escrow_proposal": escrow.offer(acceptance)}
    return _with_agreement(acceptance, escrow.accept(acceptance), settlement_artifacts_builder)


async def persist_acceptance(
    contributions: SellingContributions,
    domain: MarketDomainContract,
    repository: Any,
    acceptance: Acceptance,
    artifacts: Mapping[str, Any],
) -> None:
    """Before success is recorded: the acceptance hook, then the accepted listing, then any plan."""
    if contributions.acceptance_hook is not None:
        await contributions.acceptance_hook(repository, acceptance)
    await record_accepted_listing(
        contributions,
        repository,
        domain=domain,
        negotiation_id=acceptance.negotiation_id,
        listing_id=acceptance.listing_id,
        listing_record=acceptance.listing_record,
    )
    plan = artifacts.get("settlement_plan")
    if isinstance(plan, dict):
        await repository.commit_settlement_plan(
            negotiation_id=acceptance.negotiation_id,
            settlement_plan=plan,
            buyer_principal=acceptance.buyer_principal,
            seller_principal=acceptance.seller_principal,
        )


def build_negotiation_runtime(
    contributions: SellingContributions,
    domain: MarketDomainContract,
    *,
    stages: SettlementStageTable,
    round_settings: Callable[[], RoundSettings],
    capacity_client: Callable[[Any], Any],
    key_lookup: KeyLookup | None,
    storefront_is_paused: Callable[[], bool],
    listing_source_check: ListingSourceCheck,
    escrow: EscrowAcceptance | None = None,
    seller_round_hook: SellerRoundHook | None = None,
    accepted_obligation_dispatch: AcceptedObligationDispatch | None = None,
    settlement_artifacts_builder: Callable[[Mapping[str, Any]], dict[str, Any]]
    | None = None,
) -> NegotiationRuntime:
    """Compose the shared negotiation lifecycle with the domain's codecs and effects."""
    dispatch = accepted_obligation_dispatch if accepted_obligation_dispatch is not None else {}

    def agreement_artifacts(agreement: Mapping[str, Any]) -> dict[str, Any]:
        mechanism = agreement["settlement"]["mechanism"]
        return stages[mechanism].agreement_artifacts(agreement, None)

    artifacts_builder = settlement_artifacts_builder or agreement_artifacts

    def default_round_hook(repository: Any, listing_id: str) -> SellerRoundHook:
        policy = domain.storefront
        if policy is None:
            raise RuntimeError(
                f"domain {domain.identity!s} has no storefront negotiation capability"
            )
        settings = round_settings()
        return policy.run_negotiation_policy(
            _QuotaSnapshot(repository, listing_id, capacity_client),
            key_lookup,
            negotiation_config=settings.negotiation_config,
            chain_config_paths=settings.chain_config_paths,
            default_min_price=settings.default_min_price,
            floor_key=settings.floor_key,
        )

    async def resolve_opening(repository: Any, listing_id: str) -> ResolvedNegotiation:
        record = await repository.load_listing(listing_id=listing_id)
        if not record:
            raise NegotiationStateError(
                f"Order {listing_id} not found locally; seller has no matching listing"
            )
        return ResolvedNegotiation(
            listing_id=listing_id,
            listing=record,
            listing_record=record,
            hooks=hooks,
        )

    async def resolve_continuation(
        repository: Any, thread: Mapping[str, Any]
    ) -> ResolvedNegotiation:
        listing_id = thread.get("our_listing_id")
        if not isinstance(listing_id, str) or not listing_id:
            raise NegotiationStateError(
                f"negotiation has no recorded {contributions.refusal_noun} listing"
            )
        record = await repository.load_listing(listing_id=listing_id)
        if not record:
            raise NegotiationStateError(f"Seller's order {listing_id} is gone from local DB")
        binding = _selected_policy_state(
            record,
            (
                thread.get("buyer_escrow_proposal")
                if isinstance(thread.get("buyer_escrow_proposal"), Mapping)
                else None
            ),
            dispatch,
        )
        return ResolvedNegotiation(
            listing_id=listing_id,
            listing=record,
            listing_record=record,
            hooks=hooks,
            binding=binding,
        )

    async def evaluate(request: RoundRequest) -> RoundEvaluation:
        history, selected_state = _preserve_selected_round_selection(
            request.listing_record,
            request.history,
            dispatch,
        )
        policy = seller_round_hook or default_round_hook(
            request.repository,
            str(request.listing_record.get("listing_id") or ""),
        )
        decoded = request.terms.decoded
        result = await policy(
            listing=request.listing,
            history=list(history),
            requested_quantity=provision_quantity(decoded),
            key_mode=provision_key_mode(decoded),
            key_id=provision_key_id(decoded),
            buyer_principal=request.buyer_principal,
            **(
                {"strategy_label": request.strategy_label}
                if request.strategy_label is not None
                else {}
            ),
        )
        state = dict(result.intermediate or {})
        if selected_state is not None:
            state.update(selected_state)
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

    hooks = NegotiationDomainHooks(
        decode_terms=lambda raw: decode_terms(domain, raw),
        validate_opening=partial(_validate_opening, contributions.refusal_noun),
        validate_continuation=partial(_validate_continuation, contributions.refusal_noun),
        evaluate_round=evaluate,
        determine_strategy=lambda listing, _record: determine_strategy(contributions, listing),
        reference_amount=partial(reference_amount, contributions, round_settings),
        amount_from_proposal=_amount,
        proposal_from_amount=_proposal_from_amount,
        agreement_terms=_agreement,
        build_artifacts=partial(
            acceptance_artifacts, contributions, stages, dispatch, escrow, artifacts_builder
        ),
        decision_wire=lambda decision: decision.to_dict(),
        listing_is_live=lambda record: str(record.get("status") or "").strip() == "open",
        listing_is_paused=listing_is_paused,
        storefront_is_paused=storefront_is_paused,
        stage_event=stage_event,
        open_negotiation=open_negotiation,
        place_hold=lambda repository, acceptance: place_quota_hold(
            stages, dispatch, repository, acceptance
        ),
        persist_artifacts=partial(persist_acceptance, contributions, domain),
        check_listing_source=lambda repository, resolved: listing_source_check(
            repository, resolved.listing_id
        ),
    )
    return NegotiationRuntime(
        resolve_opening=resolve_opening,
        resolve_continuation=resolve_continuation,
    )
