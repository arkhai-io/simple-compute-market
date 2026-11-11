"""VM storefront seller-round hook implementation."""

from __future__ import annotations

import importlib.util
import logging
import math
import os
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from arkhai_vms import vm_listing_resource_shape
from arkhai_vms_listings.models import Listing

from arkhai_vms_listings import (
    determine_strategy_from_order,
    extract_initial_price_from_order,
    extract_compute_from_order,
)
from arkhai_vms_negotiation.amounts import (
    BASIS_POINTS, has_rate_structure, multiplier_floor, quote_from_multiplier, shape_hourly_amount,
)
from arkhai_vms_negotiation.policies import (
    make_escrow_kind_dispatch_middleware,
    proposal_uses_scalar_amount,
)
from market_policy.listing_source import ListingSourceVerdict
from market_policy.seller_round import SellerRoundResult
from market_policy.scalar_policies import (
    pinned_proposal,
    amount_from_proposal,
    set_proposal_amount,
    selected_settlement_artifact,
)
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationMiddleware,
    NegotiationRound,
    load_negotiation_chain,
    normalize_policies_by_escrow_kind_config,
    register_negotiation_middleware,
    run_negotiation_chain_with_context,
)

logger = logging.getLogger(__name__)


class SellerRoundHook(Protocol):
    """VM seller policy input includes the effective requested capability shape."""

    async def __call__(
        self,
        *,
        listing: Any,
        history: list[NegotiationRound],
        requested_duration_seconds: int | None = None,
        requested_shape: Mapping[str, Mapping[str, Any]] | None = None,
        strategy_label: str | None = None,
        listing_source: ListingSourceVerdict | None = None,
    ) -> SellerRoundResult: ...


_FILE_POLICIES_DISCOVERED = False


def _default_policy_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "arkhai" / "policies"


def _register_file_policy(folder: Path) -> bool:
    """Load ``folder/policy.py`` and register its ``middleware`` callable."""
    policy_file = folder / "policy.py"
    if not policy_file.is_file():
        return False

    name = folder.name
    module_id = f"arkhai_vms_negotiation._file_policies.{name}"
    try:
        spec = importlib.util.spec_from_file_location(module_id, policy_file)
        if spec is None or spec.loader is None:
            logger.warning("[POLICY] couldn't build spec for %s", policy_file)
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        logger.warning(
            "[POLICY] failed to import file policy %s from %s: %s",
            name, policy_file, exc,
        )
        return False

    middleware = getattr(module, "middleware", None)
    if not callable(middleware):
        logger.warning(
            "[POLICY] %s has no callable 'middleware' - skipping",
            policy_file,
        )
        return False

    register_negotiation_middleware(name)(middleware)
    logger.info("[POLICY] registered file middleware %r from %s", name, policy_file)
    return True


def _discover_file_policies(
    force: bool = False,
    *,
    extra_policy_paths: Iterable[str | Path] | None = None,
) -> None:
    """Register middleware from configured policy directories."""
    global _FILE_POLICIES_DISCOVERED
    if _FILE_POLICIES_DISCOVERED and not force:
        return
    _FILE_POLICIES_DISCOVERED = True

    candidates = [
        _default_policy_dir(),
        *(Path(p) for p in (extra_policy_paths or ())),
    ]

    for root in candidates:
        if not root.is_dir():
            logger.debug("[POLICY] skipping non-existent policy dir %s", root)
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue
            _register_file_policy(entry)


def _maybe_register_rl_middleware() -> None:
    """Trigger self-registration of the torch RL middleware if available."""
    try:
        import arkhai_vms_negotiation.rl.torch_arkhai_strategy  # noqa: F401
    except Exception as exc:
        logger.debug("[NEGOTIATION] torch_arkhai_strategy not available: %s", exc)


_DEFAULT_GUARDS = [
    "round_zero_opening_guard",
    "buyer_counter_guard",
    "has_matching_inventory_guard",
    "escrow_shape_guard",
    # Last, so an unpriced option is accepted only once the selection and the
    # inventory behind it have passed every guard above.
    "accept_unpriced_selection",
]
_DEFAULT_TERMINAL = "bisection"
_RL_POLICY_NAMES = {"rl", "erc20_rl", "native_token_rl", "erc1155_rl"}


def _prepend_default_guards(policy_names: list[str]) -> list[str]:
    # The default guards run first, in their own order, wherever an operator
    # names one: an opening selecting nothing the listing offers is priced at
    # zero, and only these guards refuse it before a decider could accept it.
    return [
        *_DEFAULT_GUARDS,
        *(name for name in policy_names if name not in _DEFAULT_GUARDS),
    ]


def _policy_names_need_rl(policy_names: list[str]) -> bool:
    return any(name in _RL_POLICY_NAMES for name in policy_names)


def _policy_map_needs_rl(policies_by_kind: dict[str, list[str]]) -> bool:
    return any(_policy_names_need_rl(names) for names in policies_by_kind.values())


def _load_storefront_chain(
    *,
    negotiation_config: Any = None,
    chain_config_paths: Mapping[str, str | None] | None = None,
    extra_policy_paths: Iterable[str | Path] | None = None,
) -> list[NegotiationMiddleware]:
    """Resolve the VM storefront's configured negotiation middleware chain.

    ``chain_config_paths`` maps each configured chain to its Alkahest address
    book, ``None`` for the SDK's built-in addresses, as the storefront resolved
    it; the escrow-kind dispatch reads each escrow's kind through it.
    """
    _discover_file_policies(extra_policy_paths=extra_policy_paths)

    negotiation_cfg = negotiation_config
    raw_policies = getattr(negotiation_cfg, "policies", None)
    policies_by_kind = normalize_policies_by_escrow_kind_config(raw_policies)
    if policies_by_kind:
        if _policy_map_needs_rl(policies_by_kind):
            _maybe_register_rl_middleware()
        return load_negotiation_chain(_DEFAULT_GUARDS) + [
            make_escrow_kind_dispatch_middleware(
                policies_by_kind,
                chain_config_paths=dict(chain_config_paths or {}),
            )
        ]

    policy_names = list(raw_policies or [])
    if not policy_names:
        policy_mode = (
            (getattr(negotiation_cfg, "policy_mode", "") or "").strip()
            or _DEFAULT_TERMINAL
        )
        policy_names = [policy_mode]
    policy_names = _prepend_default_guards(policy_names)

    if _policy_names_need_rl(policy_names):
        _maybe_register_rl_middleware()

    return load_negotiation_chain(policy_names)


def _direction_from_strategy_label(strategy: str) -> str:
    if strategy in ("minimize", "maximize"):
        return strategy
    raise ValueError(f"Unknown order strategy {strategy!r}")


def _listing_dict(listing: Any) -> dict[str, Any]:
    raw = listing.model_dump(mode="json") if hasattr(listing, "model_dump") else dict(listing)
    record = Listing.model_validate(raw).model_dump(mode="json")
    if raw.get("rate_structure") is not None:
        record["rate_structure"] = raw["rate_structure"]
    return record


def _selected_option(listing: Any, proposal: Any) -> Any:
    """The accepted escrow or settlement option ``proposal`` selects, or None.

    None when there is no buyer proposal to read, or when it selects nothing the
    listing offers: an escrow proposal naming no escrow contract or one the
    listing does not accept, or a selection matching no option.
    """
    if not isinstance(proposal, Mapping):
        return None
    return selected_settlement_artifact(_listing_dict(listing), proposal)


def _seller_reference_amount(
    listing: Any,
    duration_seconds: int | None,
    *,
    default_min_price: Any = None,
    proposal: Any = None,
    requested_shape: Mapping[str, Mapping[str, Any]] | None = None,
) -> int:
    """The multiplier reference, or legacy absolute reference for a flat listing.

    A shape-priced offering uses a shape-independent basis-point bound. A flat
    or hidden-reserve offering retains its selected-option amount semantics and
    exact truncation. An unknown selection is priced from no option, never an
    unrelated asset or the configured hidden reserve.
    """
    if has_rate_structure(listing):
        if _selected_option(listing, proposal) is None:
            return 0
        return BASIS_POINTS
    selected = _selected_option(listing, proposal)
    if selected is None:
        return 0
    per_hour = extract_initial_price_from_order(
        listing, default_min_price=default_min_price, selected_option=selected
    )
    if requested_shape is not None:
        record = _listing_dict(listing)
        advertised = vm_listing_resource_shape(extract_compute_from_order(record))
        if requested_shape != advertised:
            raise ValueError("shape_commercially_infeasible: flat-priced listing is shape-fixed")
    seconds = int(duration_seconds) if duration_seconds is not None else 3600
    return math.floor(Fraction(per_hour) * seconds / 3600)


async def _run_default_seller_round_policy(
    *,
    listing: Any,
    history: list[NegotiationRound],
    requested_duration_seconds: int | None = None,
    requested_shape: Mapping[str, Mapping[str, Any]] | None = None,
    strategy_label: str | None = None,
    listing_source: ListingSourceVerdict | None = None,
    negotiation_config: Any = None,
    chain_config_paths: Mapping[str, str | None] | None = None,
    extra_policy_paths: Iterable[str | Path] | None = None,
    default_min_price: Any = None,
) -> SellerRoundResult:
    """Run the default VM seller per-round policy hook."""
    if not strategy_label:
        strategy_label = determine_strategy_from_order(
            Listing.model_validate(listing) if isinstance(listing, Mapping) else listing
        )
    if not strategy_label:
        raise ValueError(
            f"Listing {getattr(listing, 'listing_id', repr(listing))} "
            "has no usable strategy for negotiation"
        )

    listing_dict = _listing_dict(listing)
    their_proposal = None
    for item in reversed(history):
        if item.sender == "them":
            their_proposal = item.proposal
            break
    # What is priced, and whether it is bargained by amount, is the pinned
    # opening's: an acceptance settles that opening whatever a counter names.
    pinned = pinned_proposal(history)
    direction = _direction_from_strategy_label(strategy_label)
    if (
        pinned is not None
        and any(item.sender == "us" for item in history)
        and _selected_option(listing, pinned) is None
    ):
        # A continuation is resolved against the listing as it now stands, and
        # a publication cycle that repriced the opening's option changed its
        # identity. Pricing it from no option would hand a decider a zero
        # reference, so the round is refused naming why; the opening guards
        # refuse an opening selecting nothing for their own reasons.
        return SellerRoundResult(
            our_amount=0,
            strategy_label=strategy_label,
            direction=direction,
            chain_label="pinned_option_withdrawn",
            decision=NegotiationDecision(
                action="reject",
                reason=(
                    "pinned_option_withdrawn: the listing no longer offers the "
                    "option the opening selected"
                ),
            ),
            intermediate={"uses_scalar_amount": True},
        )
    uses_scalar_amount = proposal_uses_scalar_amount(
        listing_dict if isinstance(listing_dict, dict) else {},
        pinned,
    )
    reference_amount = (
        _seller_reference_amount(
            listing,
            requested_duration_seconds,
            default_min_price=default_min_price,
            proposal=pinned,
            requested_shape=requested_shape,
        )
        if uses_scalar_amount else 0
    )

    floor_bps = multiplier_floor(negotiation_config)
    multiplier_mode = (
        uses_scalar_amount and has_rate_structure(listing)
        and _selected_option(listing, pinned) is not None
    )
    if multiplier_mode:
        reference_amount = floor_bps
        shape_hourly_amount(listing_dict, pinned, requested_shape)

    chain = _load_storefront_chain(
        negotiation_config=negotiation_config,
        chain_config_paths=chain_config_paths,
        extra_policy_paths=extra_policy_paths,
    )
    context = NegotiationContext(
        direction=direction,
        our_reference_amount=int(reference_amount),
        listing=listing_dict if isinstance(listing_dict, dict) else {},
        our_escrow_proposal=their_proposal,
        available_resources={"resources": []},
        listing_source=listing_source,
        intermediate={
            "requested_duration_seconds": requested_duration_seconds,
            "requested_shape": requested_shape,
            "seller_reference_amount": int(reference_amount),
            "uses_scalar_amount": uses_scalar_amount,
        },
    )
    decision, context = run_negotiation_chain_with_context(chain, history, context)
    if multiplier_mode and decision.action in {"counter", "accept"}:
        proposed = amount_from_proposal(decision.proposal)
        if proposed is not None:
            if proposed < floor_bps:
                decision = NegotiationDecision(
                    action="counter", reason="multiplier_floor",
                    proposal=set_proposal_amount(decision.proposal or pinned, floor_bps),
                )
                proposed = floor_bps
            quote_from_multiplier(
                listing_dict, pinned, proposed,
                int(requested_duration_seconds or 3600), requested_shape,
            )
    chain_label = ",".join(
        type(mw).__name__ if not hasattr(mw, "__name__") else mw.__name__
        for mw in chain
    )
    uses_scalar_amount = context.intermediate.get("uses_scalar_amount", True)
    return SellerRoundResult(
        our_amount=int(reference_amount) if uses_scalar_amount else 0,
        strategy_label=strategy_label,
        direction=direction,
        chain_label=chain_label,
        decision=decision,
        intermediate=dict(context.intermediate),
    )


@dataclass
class _DefaultSellerRoundHook:
    negotiation_config: Any = None
    chain_config_paths: Mapping[str, str | None] | None = None
    extra_policy_paths: Iterable[str | Path] | None = None
    default_min_price: Any = None

    async def __call__(
        self,
        *,
        listing: Any,
        history: list[NegotiationRound],
        requested_duration_seconds: int | None = None,
        requested_shape: Mapping[str, Mapping[str, Any]] | None = None,
        strategy_label: str | None = None,
        listing_source: ListingSourceVerdict | None = None,
    ) -> SellerRoundResult:
        return await _run_default_seller_round_policy(
            listing=listing,
            history=history,
            requested_duration_seconds=requested_duration_seconds,
            requested_shape=requested_shape,
            strategy_label=strategy_label,
            listing_source=listing_source,
            negotiation_config=self.negotiation_config,
            chain_config_paths=self.chain_config_paths,
            extra_policy_paths=self.extra_policy_paths,
            default_min_price=self.default_min_price,
        )


def default_seller_round_hook(
    *,
    negotiation_config: Any = None,
    chain_config_paths: Mapping[str, str | None] | None = None,
    extra_policy_paths: Iterable[str | Path] | None = None,
    default_min_price: Any = None,
) -> SellerRoundHook:
    """Build the default VM seller round hook.

    Each call takes the round's ``listing_source``, the negotiation runtime's
    check of the listing against its own source, which the inventory guard reads.
    ``chain_config_paths`` is each chain's Alkahest address book as the
    storefront resolved it.
    """
    return _DefaultSellerRoundHook(
        negotiation_config=negotiation_config,
        chain_config_paths=chain_config_paths,
        extra_policy_paths=extra_policy_paths,
        default_min_price=default_min_price,
    )
