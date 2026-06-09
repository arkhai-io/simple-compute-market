"""VM storefront seller-round hook implementation."""

from __future__ import annotations

import importlib.util
import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from domains.vms.listings import (
    determine_strategy_from_order,
    extract_initial_price_from_order,
)
from domains.vms.negotiation.policies import (
    make_escrow_kind_dispatch_middleware,
    proposal_uses_scalar_amount,
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


@dataclass(frozen=True)
class SellerRoundResult:
    our_amount: int
    strategy_label: str
    direction: str
    chain_label: str
    decision: NegotiationDecision
    intermediate: dict[str, Any] | None = None


class SellerRoundHook(Protocol):
    async def __call__(
        self,
        *,
        listing: Any,
        history: list[NegotiationRound],
        requested_duration_seconds: int | None = None,
        strategy_label: str | None = None,
    ) -> SellerRoundResult:
        ...


async def _default_seller_policy_inputs(sqlite_client: Any) -> dict[str, Any]:
    return {
        "available_resources": {
            "resources": await sqlite_client.list_resources() or [],
        },
    }


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
    module_id = f"domains.vms.negotiation._file_policies.{name}"
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
        import domains.vms.negotiation.rl.torch_arkhai_strategy  # noqa: F401
    except Exception as exc:
        logger.debug("[NEGOTIATION] torch_arkhai_strategy not available: %s", exc)


_DEFAULT_GUARDS = [
    "round_zero_opening_guard",
    "buyer_counter_guard",
    "has_matching_inventory_guard",
    "escrow_shape_guard",
]
_DEFAULT_TERMINAL = "bisection"
_RL_POLICY_NAMES = {"rl", "erc20_rl", "native_token_rl", "erc1155_rl"}


def _prepend_default_guards(policy_names: list[str]) -> list[str]:
    out = list(policy_names)
    for guard in reversed(_DEFAULT_GUARDS):
        if guard not in out:
            out.insert(0, guard)
    return out


def _policy_names_need_rl(policy_names: list[str]) -> bool:
    return any(name in _RL_POLICY_NAMES for name in policy_names)


def _policy_map_needs_rl(policies_by_kind: dict[str, list[str]]) -> bool:
    return any(_policy_names_need_rl(names) for names in policies_by_kind.values())


def _load_storefront_chain(
    *,
    negotiation_config: Any = None,
    chains: Mapping[str, Any] | None = None,
    extra_policy_paths: Iterable[str | Path] | None = None,
) -> list[NegotiationMiddleware]:
    """Resolve the VM storefront's configured negotiation middleware chain."""
    _discover_file_policies(extra_policy_paths=extra_policy_paths)

    negotiation_cfg = negotiation_config
    raw_policies = getattr(negotiation_cfg, "policies", None)
    policies_by_kind = normalize_policies_by_escrow_kind_config(raw_policies)
    if policies_by_kind:
        if _policy_map_needs_rl(policies_by_kind):
            _maybe_register_rl_middleware()
        chain_config_paths = {
            name: chain.alkahest_address_config_path
            for name, chain in (chains or {}).items()
        }
        return load_negotiation_chain(_DEFAULT_GUARDS) + [
            make_escrow_kind_dispatch_middleware(
                policies_by_kind,
                chain_config_paths=chain_config_paths,
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


def _seller_reference_amount(
    listing: Any,
    duration_seconds: int | None,
    *,
    default_min_price: Any = None,
) -> int:
    """Compute the seller's absolute reference amount in base units."""
    per_hour = Decimal(str(
        extract_initial_price_from_order(
            listing,
            default_min_price=default_min_price,
        )
    ))
    seconds = int(duration_seconds) if duration_seconds is not None else 3600
    return int(per_hour * seconds // Decimal(3600))


async def _run_default_seller_round_policy(
    *,
    listing: Any,
    history: list[NegotiationRound],
    requested_duration_seconds: int | None = None,
    strategy_label: str | None = None,
    policy_inputs: dict[str, Any] | None = None,
    negotiation_config: Any = None,
    chains: Mapping[str, Any] | None = None,
    extra_policy_paths: Iterable[str | Path] | None = None,
    default_min_price: Any = None,
) -> SellerRoundResult:
    """Run the default VM seller per-round policy hook."""
    from domains.vms.listings.models import Listing

    if not strategy_label:
        strategy_label = determine_strategy_from_order(listing)
    if not strategy_label:
        raise ValueError(
            f"Listing {getattr(listing, 'listing_id', repr(listing))} "
            "has no usable strategy for negotiation"
        )

    listing_dict = (
        listing.model_dump(mode="json") if isinstance(listing, Listing) else listing
    )
    their_proposal = None
    for item in reversed(history):
        if item.sender == "them":
            their_proposal = item.proposal
            break
    uses_scalar_amount = proposal_uses_scalar_amount(
        listing_dict if isinstance(listing_dict, dict) else {},
        their_proposal,
    )
    reference_amount = (
        _seller_reference_amount(
            listing,
            requested_duration_seconds,
            default_min_price=default_min_price,
        )
        if uses_scalar_amount else 0
    )
    direction = _direction_from_strategy_label(strategy_label)

    chain = _load_storefront_chain(
        negotiation_config=negotiation_config,
        chains=chains,
        extra_policy_paths=extra_policy_paths,
    )
    context = NegotiationContext(
        direction=direction,
        our_reference_amount=float(reference_amount),
        listing=listing_dict if isinstance(listing_dict, dict) else {},
        our_escrow_proposal=their_proposal,
        available_resources=(
            (policy_inputs or {}).get("available_resources")
            or {"resources": []}
        ),
        intermediate={
            "requested_duration_seconds": requested_duration_seconds,
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
        direction=direction,
        chain_label=chain_label,
        decision=decision,
        intermediate=dict(context.intermediate),
    )


@dataclass
class _DefaultSellerRoundHook:
    sqlite_client: Any
    negotiation_config: Any = None
    chains: Mapping[str, Any] | None = None
    extra_policy_paths: Iterable[str | Path] | None = None
    default_min_price: Any = None

    async def __call__(
        self,
        *,
        listing: Any,
        history: list[NegotiationRound],
        requested_duration_seconds: int | None = None,
        strategy_label: str | None = None,
    ) -> SellerRoundResult:
        policy_inputs = await _default_seller_policy_inputs(self.sqlite_client)
        return await _run_default_seller_round_policy(
            listing=listing,
            history=history,
            requested_duration_seconds=requested_duration_seconds,
            strategy_label=strategy_label,
            policy_inputs=policy_inputs,
            negotiation_config=self.negotiation_config,
            chains=self.chains,
            extra_policy_paths=self.extra_policy_paths,
            default_min_price=self.default_min_price,
        )


def default_seller_round_hook(
    sqlite_client: Any,
    *,
    negotiation_config: Any = None,
    chains: Mapping[str, Any] | None = None,
    extra_policy_paths: Iterable[str | Path] | None = None,
    default_min_price: Any = None,
) -> SellerRoundHook:
    return _DefaultSellerRoundHook(
        sqlite_client=sqlite_client,
        negotiation_config=negotiation_config,
        chains=chains,
        extra_policy_paths=extra_policy_paths,
        default_min_price=default_min_price,
    )
