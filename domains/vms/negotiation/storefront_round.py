"""VM storefront seller-round hook implementation."""

from __future__ import annotations

import importlib.util
import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from domains.vms.negotiation.policies import make_escrow_kind_dispatch_middleware
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationMiddleware,
    NegotiationRound,
    load_negotiation_chain,
    normalize_policies_by_escrow_kind_config,
    register_negotiation_middleware,
    run_negotiation_chain,
)
from service.schemas import EscrowProposal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SellerRoundResult:
    our_amount: int
    strategy_label: str
    direction: str
    chain_label: str
    decision: NegotiationDecision


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


_ZERO_ADDRESS = "0x" + "0" * 40


def _match_accepted_escrow(
    listing: dict[str, Any], proposal: EscrowProposal,
) -> dict[str, Any] | None:
    """Find the listing accepted-escrow entry matching ``proposal``."""
    import json as _json

    accepted = listing.get("accepted_escrows")
    if isinstance(accepted, str):
        try:
            accepted = _json.loads(accepted)
        except (ValueError, TypeError):
            return None
    if not isinstance(accepted, list) or not accepted:
        return None

    proposal_addr = proposal.escrow_address.lower()
    if proposal_addr == _ZERO_ADDRESS:
        return None

    proposal_chain = proposal.chain_name
    for entry in accepted:
        if not isinstance(entry, dict):
            continue
        entry_chain = entry.get("chain_name")
        entry_addr = entry.get("escrow_address")
        if (
            entry_chain == proposal_chain
            and isinstance(entry_addr, str)
            and entry_addr.lower() == proposal_addr
        ):
            return entry
    return None


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


def _proposal_uses_scalar_amount(
    *,
    listing: dict[str, Any],
    proposal: EscrowProposal | dict[str, Any] | None,
) -> bool:
    if proposal is None:
        return True
    proposal_model = (
        proposal
        if isinstance(proposal, EscrowProposal)
        else EscrowProposal.model_validate(proposal)
    )
    fields = dict(proposal_model.fields or {})
    if "amount" in fields:
        return True
    matched = _match_accepted_escrow(listing, proposal_model)
    return _accepted_entry_uses_scalar_amount(matched)


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


def _discover_file_policies(force: bool = False) -> None:
    """Register middleware from configured policy directories."""
    global _FILE_POLICIES_DISCOVERED
    if _FILE_POLICIES_DISCOVERED and not force:
        return
    _FILE_POLICIES_DISCOVERED = True

    from market_storefront.utils.config import settings

    candidates = [
        _default_policy_dir(),
        *(Path(p) for p in settings.negotiation.extra_policy_paths),
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
        import domains.vms.agent.app.policy.torch_arkhai_strategy  # noqa: F401
    except Exception as exc:
        logger.debug("[NEGOTIATION] torch_arkhai_strategy not available: %s", exc)


_DEFAULT_GUARDS = ["has_matching_inventory_guard", "escrow_shape_guard"]
_DEFAULT_TERMINAL = "bisection"
_RL_POLICY_NAMES = {"rl", "erc20_rl", "native_token_rl", "erc1155_rl"}


def _policy_names_need_rl(policy_names: list[str]) -> bool:
    return any(name in _RL_POLICY_NAMES for name in policy_names)


def _policy_map_needs_rl(policies_by_kind: dict[str, list[str]]) -> bool:
    return any(_policy_names_need_rl(names) for names in policies_by_kind.values())


def _load_storefront_chain() -> list[NegotiationMiddleware]:
    """Resolve the VM storefront's configured negotiation middleware chain."""
    from market_storefront.utils.config import CHAINS, settings

    _discover_file_policies()

    negotiation_cfg = getattr(settings, "negotiation", None)
    raw_policies = getattr(negotiation_cfg, "policies", None)
    policies_by_kind = normalize_policies_by_escrow_kind_config(raw_policies)
    if policies_by_kind:
        if _policy_map_needs_rl(policies_by_kind):
            _maybe_register_rl_middleware()
        chain_config_paths = {
            name: chain.alkahest_address_config_path
            for name, chain in CHAINS.items()
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
        policy_names = _DEFAULT_GUARDS + [policy_mode]

    if _policy_names_need_rl(policy_names):
        _maybe_register_rl_middleware()

    return load_negotiation_chain(policy_names)


def _direction_from_strategy_label(strategy: str) -> str:
    if strategy in ("minimize", "maximize"):
        return strategy
    raise ValueError(f"Unknown order strategy {strategy!r}")


def _seller_reference_amount(
    listing: Any, duration_seconds: int | None,
) -> int:
    """Compute the seller's absolute reference amount in base units."""
    from market_storefront.utils.action_executor import _extract_initial_price_from_order

    per_hour = Decimal(str(_extract_initial_price_from_order(listing)))
    seconds = int(duration_seconds) if duration_seconds is not None else 3600
    return int(per_hour * seconds // Decimal(3600))


async def _run_default_seller_round_policy(
    *,
    listing: Any,
    history: list[NegotiationRound],
    requested_duration_seconds: int | None = None,
    strategy_label: str | None = None,
    policy_inputs: dict[str, Any] | None = None,
) -> SellerRoundResult:
    """Run the default VM seller per-round policy hook."""
    from market_storefront.models.domain_models import Listing
    from market_storefront.utils.action_executor import determine_strategy_from_order

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
    uses_scalar_amount = _proposal_uses_scalar_amount(
        listing=listing_dict if isinstance(listing_dict, dict) else {},
        proposal=their_proposal,
    )
    our_amount = (
        _seller_reference_amount(listing, requested_duration_seconds)
        if uses_scalar_amount else 0
    )
    direction = _direction_from_strategy_label(strategy_label)

    chain = _load_storefront_chain()
    context = NegotiationContext(
        direction=direction,
        our_reference_amount=float(our_amount),
        listing=listing_dict if isinstance(listing_dict, dict) else {},
        our_escrow_proposal=their_proposal,
        available_resources=(
            (policy_inputs or {}).get("available_resources")
            or {"resources": []}
        ),
    )
    decision = run_negotiation_chain(chain, history, context)
    chain_label = ",".join(
        type(mw).__name__ if not hasattr(mw, "__name__") else mw.__name__
        for mw in chain
    )
    return SellerRoundResult(
        our_amount=int(our_amount),
        strategy_label=strategy_label,
        direction=direction,
        chain_label=chain_label,
        decision=decision,
    )


@dataclass
class _DefaultSellerRoundHook:
    sqlite_client: Any

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
        )


def default_seller_round_hook(sqlite_client: Any) -> SellerRoundHook:
    return _DefaultSellerRoundHook(sqlite_client=sqlite_client)
