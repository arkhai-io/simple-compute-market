"""VM-domain negotiation middlewares.

These policies interpret the VM market's concrete negotiation message
shape: Alkahest escrow proposals, scalar payment amounts in
``proposal.fields["amount"]``, listing ``accepted_escrows``, and VM
inventory snapshots. The generic middleware chain lives in
``market_policy.negotiation_middleware``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationMiddleware,
    NegotiationRound,
    NegotiationStep,
    load_negotiation_chain,
    register_negotiation_middleware,
    run_negotiation_chain,
    their_last_proposal,
)

logger = logging.getLogger(__name__)

DEFAULT_CONVERGENCE_RATIO = 0.01
DEFAULT_REASONABLE_MULTIPLIER = 1.5

_ZERO_ADDRESS = "0x" + "0" * 40


def _amount_from_proposal(proposal: dict[str, Any] | None) -> Optional[float]:
    """Pull the absolute payment amount out of a VM EscrowProposal dict."""
    if not isinstance(proposal, dict):
        return None
    fields = proposal.get("fields") or {}
    if not isinstance(fields, dict):
        return None
    raw = fields.get("amount")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if s.isdigit():
            return float(int(s))
    return None


def their_proposed_amount(history: list[NegotiationRound]) -> Optional[float]:
    """Most recent absolute amount the other side proposed. None if not yet."""
    for round_ in reversed(history):
        if round_.sender == "them":
            amount = _amount_from_proposal(round_.proposal)
            if amount is not None:
                return amount
    return None


def proposal_escrow_kind(
    proposal: dict[str, Any] | None,
    *,
    chain_config_paths: dict[str, str | None] | None = None,
) -> str | None:
    """Resolve an EscrowProposal-shaped dict to an Alkahest escrow kind."""
    if not isinstance(proposal, dict):
        return None
    chain_name = proposal.get("chain_name")
    escrow_address = proposal.get("escrow_address")
    if not isinstance(chain_name, str) or not chain_name:
        return None
    if not isinstance(escrow_address, str) or not escrow_address:
        return None
    try:
        from market_alkahest.alkahest import address_to_slot

        return address_to_slot(
            chain_name,
            escrow_address,
            config_path=(chain_config_paths or {}).get(chain_name),
        )
    except Exception as exc:
        logger.debug(
            "Could not resolve escrow kind for chain=%r address=%r: %s",
            chain_name,
            escrow_address,
            exc,
        )
        return None


def our_previous_counters(history: list[NegotiationRound]) -> list[float]:
    """Absolute amounts we counter-proposed in earlier rounds, oldest first."""
    out: list[float] = []
    for h in history:
        if h.sender == "us" and h.action == "counter":
            amount = _amount_from_proposal(h.proposal)
            if amount is not None:
                out.append(amount)
    return out


def our_first_proposal(history: list[NegotiationRound]) -> Optional[dict[str, Any]]:
    """Our earliest proposal in the transcript."""
    for h in history:
        if h.sender == "us" and h.proposal is not None:
            return h.proposal
    return None


def _set_proposal_amount(proposal: dict[str, Any], amount: float) -> dict[str, Any]:
    out = dict(proposal)
    fields = dict(out.get("fields") or {})
    fields["amount"] = int(round(amount))
    out["fields"] = fields
    return out


def escrow_shape_uses_scalar_amount(proposal: dict[str, Any] | None) -> bool:
    """Whether this escrow shape is negotiated through a scalar ``amount``.

    The scalar policies' own compatibility knowledge
    (ARCHITECTURE.md, "Buyer negotiation policy surface"): payment escrows carry
    ``fields.amount`` (or a fungible token without a tokenId, or a rate
    on the ``amount`` field); exact escrows (a specific NFT) do not, and
    a scalar policy leaves their fields untouched — take-it-or-leave.
    """
    if not isinstance(proposal, dict):
        return False
    fields = proposal.get("fields") or {}
    if "amount" in fields:
        return True
    if (
        "token" in fields
        and "tokenId" not in fields
        and "token_id" not in fields
    ):
        return True
    return any(
        (r.get("field") if isinstance(r, dict) else getattr(r, "field", None))
        == "amount"
        for r in (proposal.get("rates") or [])
    )


def _opening_amount(context: NegotiationContext) -> float:
    opening = getattr(context, "our_opening_amount", None)
    return opening if opening is not None else context.our_reference_amount


def _opening_proposal(context: NegotiationContext) -> dict[str, Any]:
    """The scalar policies' round-0 proposal from a bare context.

    Injects the opening amount only into scalar-amount shapes; exact
    escrows pass through unchanged (the pinned-shape guard is what
    protects them from seller mutation).
    """
    base = context.our_escrow_proposal or {}
    if escrow_shape_uses_scalar_amount(base):
        return _set_proposal_amount(base, _opening_amount(context))
    return dict(base)


@register_negotiation_middleware("bisection")
def bisection_middleware(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Scalar amount midpoint strategy for VM payment escrow proposals."""
    counters = our_previous_counters(history)

    if len(counters) >= context.max_rounds:
        return NegotiationDecision(action="exit", reason="max_rounds"), context
    if len(counters) >= 2 and counters[-1] == counters[-2]:
        return NegotiationDecision(action="exit", reason="stale_negotiation"), context

    our_amount = context.our_reference_amount
    their_amount = their_proposed_amount(history)
    their_proposal = their_last_proposal(history)

    if their_amount is None:
        return (
            NegotiationDecision(action="counter", proposal=_opening_proposal(context)),
            context,
        )

    conv = DEFAULT_CONVERGENCE_RATIO
    reasonable = DEFAULT_REASONABLE_MULTIPLIER
    skeleton = their_proposal or context.our_escrow_proposal or {}

    if context.direction == "minimize":
        if their_amount <= our_amount * (1 + conv):
            return (
                NegotiationDecision(
                    action="accept",
                    proposal=_set_proposal_amount(skeleton, their_amount),
                    reason="convergence",
                ),
                context,
            )
        if their_amount <= our_amount * reasonable:
            proposed = (our_amount + their_amount) / 2
            if proposed > our_amount:
                proposed = our_amount
            return (
                NegotiationDecision(
                    action="counter",
                    proposal=_set_proposal_amount(skeleton, proposed),
                ),
                context,
            )
        return NegotiationDecision(action="exit", reason="price_unreasonable"), context

    if context.direction == "maximize":
        if their_amount >= our_amount * (1 - conv):
            return (
                NegotiationDecision(
                    action="accept",
                    proposal=_set_proposal_amount(skeleton, their_amount),
                    reason="convergence",
                ),
                context,
            )
        if their_amount >= our_amount / reasonable:
            proposed = (our_amount + their_amount) / 2
            return (
                NegotiationDecision(
                    action="counter",
                    proposal=_set_proposal_amount(skeleton, proposed),
                ),
                context,
            )
        return NegotiationDecision(action="exit", reason="price_unreasonable"), context

    return (
        NegotiationDecision(action="reject", reason=f"unknown_direction:{context.direction!r}"),
        context,
    )


@register_negotiation_middleware("erc20_bisection")
@register_negotiation_middleware("native_token_bisection")
@register_negotiation_middleware("erc1155_bisection")
def amount_bisection_middleware(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Escrow-kind named alias for the scalar ``amount`` bisection policy."""
    return bisection_middleware(history, context)


@register_negotiation_middleware("listed_price")
def listed_price_middleware(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Pay the published price: accept within the bound, never haggle.

    The buyer-side default decider (ARCHITECTURE.md, "Buyer negotiation
    policy surface").
    Haggling rounds carry no information today — neither side exchanges
    *reasons* for a new number, so counter-rounds against a seller whose
    floor is already published are wasted traffic. The buyer opens at
    the listing's advertised price (or the caller's explicit bid);
    ``our_reference_amount`` is the bound. Any side that wants actual
    bargaining configures ``bisection`` (or richer) explicitly.

    minimize: accept the counterparty's amount iff it is at or under the
    bound, exit otherwise. maximize mirrors it. An amountless proposal
    from the other side (exact escrows) is accepted as-proposed — the
    pinned-shape guard upstream already vetoed any mutation.
    """
    their_proposal = their_last_proposal(history)
    if their_proposal is None:
        # Round-0 opening (or resume edge with nothing from them yet).
        return (
            NegotiationDecision(action="counter", proposal=_opening_proposal(context)),
            context,
        )

    their_amount = their_proposed_amount(history)
    if their_amount is None:
        return (
            NegotiationDecision(
                action="accept", proposal=dict(their_proposal),
                reason="listed_price_amountless",
            ),
            context,
        )

    bound = context.our_reference_amount
    within = (
        their_amount <= bound
        if context.direction == "minimize"
        else their_amount >= bound
    )
    if within:
        return (
            NegotiationDecision(
                action="accept",
                proposal=_set_proposal_amount(dict(their_proposal), their_amount),
                reason="listed_price",
            ),
            context,
        )
    return (
        NegotiationDecision(action="exit", reason="price_above_bound"),
        context,
    )


def _escrow_kind_lookup_keys(kind: str) -> list[str]:
    keys = [kind]
    for prefix in (
        "erc20",
        "native_token",
        "erc1155",
        "erc721",
        "token_bundle",
        "attestation",
    ):
        if kind.startswith(prefix):
            keys.append(prefix)
            break
    keys.append("default")
    out: list[str] = []
    for key in keys:
        if key not in out:
            out.append(key)
    return out


def make_escrow_kind_dispatch_middleware(
    policies_by_kind: dict[str, list[str]],
    *,
    chain_config_paths: dict[str, str | None] | None = None,
) -> NegotiationMiddleware:
    """Build a terminal middleware that dispatches by selected escrow kind."""
    normalized: dict[str, list[str]] = {
        str(kind).strip(): [str(name).strip() for name in chain if str(name).strip()]
        for kind, chain in policies_by_kind.items()
        if str(kind).strip()
    }
    chain_cache: dict[str, list[NegotiationMiddleware]] = {}

    def _chain_for(kind: str) -> tuple[str, list[NegotiationMiddleware]] | None:
        for key in _escrow_kind_lookup_keys(kind):
            names = normalized.get(key)
            if not names:
                continue
            if any(name == "escrow_kind_dispatch" for name in names):
                raise RuntimeError("escrow_kind_dispatch cannot dispatch to itself")
            if key not in chain_cache:
                chain_cache[key] = load_negotiation_chain(names)
            return key, chain_cache[key]
        return None

    def escrow_kind_dispatch_middleware(
        history: list[NegotiationRound],
        context: NegotiationContext,
    ) -> NegotiationStep:
        proposal = their_last_proposal(history) or context.our_escrow_proposal
        kind = proposal_escrow_kind(
            proposal,
            chain_config_paths=chain_config_paths,
        )
        if not kind:
            return (
                NegotiationDecision(
                    action="reject",
                    reason="escrow_kind_dispatch:unknown_escrow_kind",
                ),
                context,
            )
        selected = _chain_for(kind)
        if selected is None:
            return (
                NegotiationDecision(
                    action="reject",
                    reason=f"escrow_kind_dispatch:no_policy_for:{kind}",
                ),
                context,
            )
        matched_key, chain = selected
        context.intermediate["escrow_kind"] = kind
        context.intermediate["escrow_kind_policy_key"] = matched_key
        decision = run_negotiation_chain(chain, history, context)
        return decision, context

    escrow_kind_dispatch_middleware.__name__ = "escrow_kind_dispatch_middleware"
    return escrow_kind_dispatch_middleware


def _coerce_resource_dict(value: Any) -> dict[str, Any]:
    import json

    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _normalize_escrow_field(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("0x") and len(value) == 42:
        return value.lower()
    return value


def _normalize_exact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize_exact_value(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize_exact_value(v) for v in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("0x"):
            return stripped.lower()
        if stripped.isdigit():
            return int(stripped)
        return value
    return value


def _normalize_rate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {
            "field": getattr(value, "field", None),
            "per": getattr(value, "per", None),
            "value": getattr(value, "value", None),
        }
    if value.get("field") is None or value.get("value") is None:
        raise ValueError("rate requires field and value")
    return {
        "field": value.get("field"),
        "per": value.get("per", "hour"),
        "value": int(value.get("value")),
    }


def _proposal_requires_exact_amount(matched: dict[str, Any]) -> bool:
    literal_fields = matched.get("literal_fields") or {}
    if isinstance(literal_fields, dict) and "amount" in literal_fields:
        return True
    for rate in matched.get("rates") or []:
        field = rate.get("field") if isinstance(rate, dict) else getattr(rate, "field", None)
        if field == "amount":
            return True
    return False


def _loads_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        import json

        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _normalize_demands_for_chain(value: Any, chain_name: Any) -> list[Any]:
    raw = _loads_json_list(value)
    out = []
    for demand in raw:
        if not isinstance(demand, dict):
            continue
        demand_chain = demand.get("chain_name")
        if demand_chain and demand_chain != chain_name:
            continue
        out.append(_normalize_exact_value(demand))
    return out


def _accepted_escrow_for_proposal(
    listing: dict[str, Any],
    proposal: dict[str, Any],
) -> dict[str, Any] | None:
    accepted = _loads_json_list(listing.get("accepted_escrows"))
    proposal_addr_raw = proposal.get("escrow_address")
    if not isinstance(proposal_addr_raw, str) or not proposal_addr_raw:
        return None
    proposal_addr = proposal_addr_raw.lower()
    if proposal_addr == _ZERO_ADDRESS:
        return None
    proposal_chain = proposal.get("chain_name")
    for entry in accepted:
        if not isinstance(entry, dict):
            continue
        entry_addr = entry.get("escrow_address")
        if (
            entry.get("chain_name") == proposal_chain
            and isinstance(entry_addr, str)
            and entry_addr.lower() == proposal_addr
        ):
            return entry
    return None


def _is_round_zero(history: list[NegotiationRound]) -> bool:
    return (
        len(history) == 1
        and history[0].round_number == 0
        and history[0].sender == "them"
        and history[0].action == "initial"
    )


def _accepted_entry_uses_scalar_amount(entry: dict[str, Any] | None) -> bool:
    if not isinstance(entry, dict):
        return True
    literal_fields = entry.get("literal_fields") or {}
    if isinstance(literal_fields, dict) and "amount" in literal_fields:
        return True
    for rate in entry.get("rates") or []:
        field = rate.get("field") if isinstance(rate, dict) else getattr(rate, "field", None)
        if field == "amount":
            return True
    return False


def proposal_uses_scalar_amount(
    listing: dict[str, Any],
    proposal: dict[str, Any] | None,
) -> bool:
    if proposal is None:
        return True
    fields = proposal.get("fields") or {}
    if isinstance(fields, dict) and "amount" in fields:
        return True
    matched = _accepted_escrow_for_proposal(listing, proposal)
    return _accepted_entry_uses_scalar_amount(matched)


@register_negotiation_middleware("round_zero_opening_guard")
def round_zero_opening_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Validate and canonicalize VM opening-round negotiation content."""
    if not _is_round_zero(history):
        return None, context

    listing = context.listing or {}
    requested_duration_seconds = context.intermediate.get(
        "requested_duration_seconds",
    )
    if (
        requested_duration_seconds is not None
        and int(requested_duration_seconds) <= 0
    ):
        return (
            NegotiationDecision(
                action="reject",
                reason="compute_duration_invalid:duration_seconds must be > 0",
            ),
            context,
        )

    raw_listing_max_seconds = listing.get("max_duration_seconds")
    listing_max_seconds = (
        int(raw_listing_max_seconds)
        if raw_listing_max_seconds is not None and int(raw_listing_max_seconds) > 0
        else None
    )
    if (
        requested_duration_seconds is not None
        and listing_max_seconds is not None
        and int(requested_duration_seconds) > int(listing_max_seconds)
    ):
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"compute_duration_exceeds_listing_max:"
                    f"{requested_duration_seconds}>{listing_max_seconds}"
                ),
            ),
            context,
        )

    proposal = _peer_proposal(history)
    accepted = _loads_json_list(listing.get("accepted_escrows"))
    accepted_for_normalization = accepted if accepted else None
    accepted_proposal = None
    if isinstance(proposal, dict):
        try:
            from market_alkahest.schemas import (
                EscrowProposal,
                normalize_proposal_against_accepted_escrows,
            )

            accepted_proposal = normalize_proposal_against_accepted_escrows(
                proposal=EscrowProposal.model_validate(proposal),
                accepted_escrows=accepted_for_normalization,
            )
        except Exception as exc:
            return (
                NegotiationDecision(
                    action="reject",
                    reason=f"invalid_escrow_proposal:{exc}",
                ),
                context,
            )

    accepted_proposal_dict = (
        accepted_proposal.model_dump()
        if accepted_proposal is not None
        else None
    )
    if accepted_proposal_dict is not None:
        context.intermediate["accepted_escrow_proposal"] = accepted_proposal_dict

    proposal_for_scalar = accepted_proposal_dict if accepted_proposal_dict is not None else proposal
    uses_scalar_amount = proposal_uses_scalar_amount(listing, proposal_for_scalar)
    context.intermediate["uses_scalar_amount"] = uses_scalar_amount
    if uses_scalar_amount and _amount_from_proposal(proposal_for_scalar) is None:
        return (
            NegotiationDecision(
                action="reject",
                reason="missing_amount: buyer's escrow proposal has no fields.amount",
            ),
            context,
        )

    return None, context


@register_negotiation_middleware("buyer_counter_guard")
def buyer_counter_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Validate and canonicalize buyer counter-round negotiation content."""
    if not history:
        return None, context
    latest = history[-1]
    if latest.sender != "them" or latest.action != "counter":
        return None, context

    listing = context.listing or {}
    pinned = context.our_escrow_proposal
    proposal = latest.proposal if isinstance(latest.proposal, dict) else None
    proposal_for_scalar = proposal or pinned
    uses_scalar_amount = proposal_uses_scalar_amount(listing, proposal_for_scalar)
    context.intermediate["uses_scalar_amount"] = uses_scalar_amount

    raw_amount = _amount_from_proposal(proposal_for_scalar)
    if raw_amount is None:
        if uses_scalar_amount:
            return (
                NegotiationDecision(
                    action="reject",
                    reason="counter_missing_amount",
                ),
                context,
            )
        buyer_amount = 0
    else:
        buyer_amount = int(raw_amount)

    context.intermediate["buyer_amount"] = buyer_amount
    if uses_scalar_amount:
        context.intermediate["buyer_counter_proposal"] = _set_proposal_amount(
            pinned if isinstance(pinned, dict) else proposal or {},
            buyer_amount,
        )
    elif proposal is not None:
        context.intermediate["buyer_counter_proposal"] = dict(proposal)
    elif isinstance(pinned, dict):
        context.intermediate["buyer_counter_proposal"] = dict(pinned)

    return None, context


@register_negotiation_middleware("has_matching_inventory_guard")
def has_matching_inventory_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Veto when no available VM inventory resource matches the listing."""
    offer = _coerce_resource_dict(context.listing.get("offer_resource"))
    if "gpu_model" not in offer:
        return None, context

    required: dict[str, Any] = {}
    for key in ("region", "gpu_model"):
        v = offer.get(key)
        if v is not None:
            required[key] = v

    portfolio_raw = (context.available_resources or {}).get("resources") or []

    import json

    for row in portfolio_raw:
        if (row.get("state") or "").strip() != "available":
            continue
        attrs = row.get("attributes")
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except (ValueError, TypeError):
                continue
        if not isinstance(attrs, dict):
            continue
        if all(attrs.get(k) == v for k, v in required.items()):
            return None, context

    return (
        NegotiationDecision(action="reject", reason="no_matching_inventory"),
        context,
    )


def _peer_proposal(history: list[NegotiationRound]) -> dict[str, Any] | None:
    return their_last_proposal(history)


@register_negotiation_middleware("escrow_shape_guard")
def escrow_shape_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Veto when the buyer's escrow proposal diverges from the listing."""
    proposal = _peer_proposal(history)
    if not isinstance(proposal, dict):
        return None, context

    listing = context.listing or {}
    accepted = _loads_json_list(listing.get("accepted_escrows"))
    if not accepted:
        return None, context

    proposal_addr_raw = proposal.get("escrow_address")
    if not isinstance(proposal_addr_raw, str) or not proposal_addr_raw:
        return None, context
    proposal_addr = proposal_addr_raw.lower()
    if proposal_addr == _ZERO_ADDRESS:
        return None, context

    proposal_literal = proposal.get("literal_fields") or {}

    matched = _accepted_escrow_for_proposal(listing, proposal)
    if matched is None:
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"escrow_not_in_accepted_set: "
                    f"(chain={proposal.get('chain_name')!r}, "
                    f"address={proposal.get('escrow_address')!r}) not in "
                    "listing's accepted_escrows"
                ),
            ),
            context,
        )

    seller_literal = matched.get("literal_fields") or {}
    if not isinstance(seller_literal, dict):
        return None, context

    for key, seller_value in seller_literal.items():
        buyer_value = proposal_literal.get(key) if isinstance(proposal_literal, dict) else None
        if _normalize_escrow_field(buyer_value) != _normalize_escrow_field(seller_value):
            return (
                NegotiationDecision(
                    action="reject",
                    reason=(
                        f"escrow_field_mismatch: field {key!r} - buyer "
                        f"proposed {buyer_value!r}, listing requires "
                        f"{seller_value!r}"
                    ),
                ),
                context,
            )
    return None, context


@register_negotiation_middleware("accept_exact_listing")
def accept_exact_listing_middleware(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Accept only the exact advertised listing escrow (take-it-or-leave).

    With no peer proposal yet (the buyer-side round-0 opening), proposes
    our pinned escrow unchanged — exactly what the listing advertised.
    """
    proposal = _peer_proposal(history)
    if not isinstance(proposal, dict):
        if isinstance(context.our_escrow_proposal, dict):
            return (
                NegotiationDecision(
                    action="counter",
                    proposal=dict(context.our_escrow_proposal),
                ),
                context,
            )
        return (
            NegotiationDecision(action="reject", reason="exact_listing:no_proposal"),
            context,
        )

    listing = context.listing or {}
    matched = _accepted_escrow_for_proposal(listing, proposal)
    if matched is None:
        return (
            NegotiationDecision(
                action="reject",
                reason="exact_listing:escrow_not_in_accepted_set",
            ),
            context,
        )

    expected_literal = _normalize_exact_value(matched.get("literal_fields") or {})
    proposal_literal = _normalize_exact_value(proposal.get("literal_fields") or {})
    if proposal_literal != expected_literal:
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"exact_listing:literal_fields_mismatch:"
                    f"{proposal_literal!r}!={expected_literal!r}"
                ),
            ),
            context,
        )

    proposal_fields = proposal.get("fields") or {}
    if not isinstance(proposal_fields, dict):
        return (
            NegotiationDecision(action="reject", reason="exact_listing:fields_not_object"),
            context,
        )
    expected_amount = int(round(context.our_reference_amount))
    requires_amount = _proposal_requires_exact_amount(matched)
    if requires_amount:
        proposed_amount = _amount_from_proposal(proposal)
        if proposed_amount is None or int(proposed_amount) != expected_amount:
            return (
                NegotiationDecision(
                    action="reject",
                    reason=(
                        f"exact_listing:amount_mismatch:"
                        f"{proposed_amount!r}!={expected_amount!r}"
                    ),
                ),
                context,
            )
    for key, value in proposal_fields.items():
        if key == "amount" and requires_amount:
            continue
        expected = expected_literal.get(key)
        actual = _normalize_exact_value(value)
        if actual != expected:
            return (
                NegotiationDecision(
                    action="reject",
                    reason=(
                        f"exact_listing:field_mismatch:{key!r}:"
                        f"{actual!r}!={expected!r}"
                    ),
                ),
                context,
            )

    try:
        expected_rates = [
            _normalize_rate(rate) for rate in (matched.get("rates") or [])
        ]
        proposal_rates = [
            _normalize_rate(rate) for rate in (proposal.get("rates") or [])
        ]
    except (TypeError, ValueError) as exc:
        return (
            NegotiationDecision(
                action="reject",
                reason=f"exact_listing:invalid_rates:{exc}",
            ),
            context,
        )
    if proposal_rates != expected_rates:
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"exact_listing:rates_mismatch:"
                    f"{proposal_rates!r}!={expected_rates!r}"
                ),
            ),
            context,
        )

    expected_demands = _normalize_demands_for_chain(
        listing.get("demands"),
        proposal.get("chain_name"),
    )
    proposal_demands = _normalize_demands_for_chain(
        proposal.get("demands"),
        proposal.get("chain_name"),
    )
    if proposal_demands != expected_demands:
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"exact_listing:demands_mismatch:"
                    f"{proposal_demands!r}!={expected_demands!r}"
                ),
            ),
            context,
        )

    return (
        NegotiationDecision(
            action="accept",
            proposal=(
                _set_proposal_amount(proposal, expected_amount)
                if requires_amount else dict(proposal)
            ),
            reason="exact_listing",
        ),
        context,
    )


@register_negotiation_middleware("buyer_escrow_shape_guard")
def buyer_escrow_shape_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Buyer-side mirror of ``escrow_shape_guard``."""
    their_proposal = _peer_proposal(history)
    if not isinstance(their_proposal, dict):
        return None, context

    pinned = context.our_escrow_proposal
    if not isinstance(pinned, dict):
        return None, context

    if pinned.get("chain_name") != their_proposal.get("chain_name"):
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"chain_name_changed:{pinned.get('chain_name')!r}"
                    f"->{their_proposal.get('chain_name')!r}"
                ),
            ),
            context,
        )
    pinned_addr = (pinned.get("escrow_address") or "").lower()
    their_addr = (their_proposal.get("escrow_address") or "").lower()
    if pinned_addr and their_addr and pinned_addr != their_addr:
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"escrow_address_changed:{pinned.get('escrow_address')!r}"
                    f"->{their_proposal.get('escrow_address')!r}"
                ),
            ),
            context,
        )
    if (
        pinned.get("expiration_unix") is not None
        and their_proposal.get("expiration_unix") is not None
        and int(pinned["expiration_unix"]) != int(their_proposal["expiration_unix"])
    ):
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"expiration_unix_changed:{pinned['expiration_unix']}"
                    f"->{their_proposal['expiration_unix']}"
                ),
            ),
            context,
        )

    pinned_fields = pinned.get("fields") or {}
    their_fields = their_proposal.get("fields") or {}
    for key, pinned_value in pinned_fields.items():
        if key == "amount":
            continue
        their_value = their_fields.get(key) if isinstance(their_fields, dict) else None
        if _normalize_escrow_field(pinned_value) != _normalize_escrow_field(their_value):
            return (
                NegotiationDecision(
                    action="reject",
                    reason=(
                        f"escrow_field_changed:{key!r}:{pinned_value!r}"
                        f"->{their_value!r}"
                    ),
                ),
                context,
            )
    return None, context


__all__ = [
    "_amount_from_proposal",
    "accept_exact_listing_middleware",
    "amount_bisection_middleware",
    "bisection_middleware",
    "buyer_counter_guard",
    "buyer_escrow_shape_guard",
    "escrow_shape_guard",
    "has_matching_inventory_guard",
    "make_escrow_kind_dispatch_middleware",
    "our_first_proposal",
    "our_previous_counters",
    "proposal_escrow_kind",
    "proposal_uses_scalar_amount",
    "round_zero_opening_guard",
    "their_proposed_amount",
]


def _backfill_market_policy_compat_exports() -> None:
    import market_policy.negotiation_middleware as compat

    for name in __all__:
        setattr(compat, name, globals()[name])


_backfill_market_policy_compat_exports()
