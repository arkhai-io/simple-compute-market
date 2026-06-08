"""Synchronous request-response negotiation.

Buyer drives every round via `POST /negotiate/{id}` (or `/new`); the
seller's decision is returned in the HTTP response body instead of
being pushed back as a separate message.

Shape:

    POST /negotiate/new
      {listing_id, buyer_address, provision_terms, proposal}
      → {neg_id, action: "counter"|"accept"|"exit"|"reject", proposal?, reason?}

    POST /negotiate/{neg_id}
      {action: "counter"|"accept"|"exit", proposal?, reason?, buyer_address}
      → {action, proposal?, reason?}

`action` in the request is what the buyer is proposing *in this round*.
`action` in the response is the seller's resulting decision. Every
round carries a full EscrowProposal dict. Scalar payment escrows negotiate
an absolute payment amount in ``proposal.fields["amount"]``. Amountless exact
escrows, such as some attestation escrow policies, may omit that field.
Per-hour rates are a broadcast-only concept on listings; once a negotiation
starts, the duration is fixed and amounts are absolute.

Per-round decisions go through ``market_policy.negotiation_middleware``:
the configured chain runs at round 0 (including pre-flight guards like
inventory match + escrow shape) and on every subsequent round. The
storefront builds a ``NegotiationContext`` from the listing + portfolio
snapshot once per call; the chain decides.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationMiddleware,
    NegotiationRound,
    NegotiationStep,
    _amount_from_proposal,
    load_negotiation_chain,
    make_escrow_kind_dispatch_middleware,
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


def _validate_escrow_proposal(
    *,
    proposal: EscrowProposal | None,
    listing: dict[str, Any],
) -> EscrowProposal | None:
    """Normalize the buyer's escrow proposal against the listing.

    When the proposal's ``(chain_name, escrow_address)`` resolves to an
    entry in the listing's ``accepted_escrows``, merge the listing's
    advertised literal fields and rates into the proposal the seller will
    echo and persist. Listings without an advertised set pass through
    unchecked (publish-time synthesis couldn't resolve a chain; the
    buyer's strategy is on its own).

    Accepted-set membership and field-by-field equality are *seller
    policy*, not protocol — they live in the ``escrow_shape_guard``
    middleware so operators can swap reject behavior for correction or
    softer matching without code changes.

    Returns the normalized proposal so the caller can echo it back.
    Returns ``None`` when the buyer didn't include a proposal (legacy
    clients) — in that case the seller assumes the canonical shape.
    """
    if proposal is None:
        return None
    matched = _match_accepted_escrow(listing, proposal)
    if not matched:
        return proposal

    literal_fields = dict(matched.get("literal_fields") or {})
    literal_fields.update(dict(proposal.literal_fields or {}))
    rates = proposal.rates
    if rates is None:
        rates = matched.get("rates") or []
    return EscrowProposal(
        chain_name=proposal.chain_name,
        escrow_address=proposal.escrow_address,
        fields=dict(proposal.fields or {}),
        literal_fields=literal_fields,
        rates=rates,
        demands=proposal.demands,
        expiration_unix=proposal.expiration_unix,
    )


_ZERO_ADDRESS = "0x" + "0" * 40


def _match_accepted_escrow(
    listing: dict[str, Any], proposal: "EscrowProposal",
) -> dict[str, Any] | None:
    """Find the listing's ``accepted_escrows`` entry matching the
    proposal's ``(chain_name, escrow_address)``.

    Returns the entry dict on hit. Returns ``None`` to skip the strict
    match when the listing has no ``accepted_escrows`` advertised (the
    seller couldn't synthesise one at publish time), when the buyer sent
    the placeholder zero address (legacy clients), or when no advertised
    entry matches. The out-of-set decision is seller policy and is handled
    by ``escrow_shape_guard`` in the negotiation chain.
    """
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
        # Legacy buyer client sends the placeholder address. Skip the
        # strict (chain, address) match.
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


def _extract_listing_token(listing: dict[str, Any]) -> str | None:
    """Pull the payment-token contract address from a listing's primary
    accepted-escrow entry.

    Returns ``None`` when no entry is advertised (compute-for-compute
    listings, or rows where synthesis at publish time couldn't resolve
    an escrow address).
    """
    import json as _json
    from service.schemas import accepted_token_address

    accepted = listing.get("accepted_escrows")
    if isinstance(accepted, str):
        try:
            accepted = _json.loads(accepted)
        except (ValueError, TypeError):
            return None
    if isinstance(accepted, list) and accepted:
        return accepted_token_address(accepted[0])
    return None


def _materialized_escrow_terms_payload(
    *,
    proposal: EscrowProposal | None,
    seller_wallet_address: str | None,
    agreed_amount: int,
    duration_seconds: int,
) -> list[dict[str, Any]] | None:
    if proposal is None:
        return None
    from service.clients.alkahest import materialize_escrow_terms_from_proposal
    from market_storefront.utils.config import CHAINS

    chain_config = CHAINS.get(proposal.chain_name)
    terms = materialize_escrow_terms_from_proposal(
        proposal=proposal,
        seller_wallet_address=seller_wallet_address,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        addr_config_path=(
            chain_config.alkahest_address_config_path if chain_config else None
        ),
    )
    return [term.model_dump() for term in terms]


class StorefrontPausedError(Exception):
    """Raised when a new negotiation is attempted while the storefront (or the
    specific order) is paused.

    The negotiate endpoints convert this to HTTP 503 with a machine-readable
    body so callers can distinguish a pause from a real server error.
    """

    def __init__(self, reason: str = "paused") -> None:
        super().__init__(reason)
        self.reason = reason


class OfferUnfulfillableError(Exception):
    """Raised when the seller refuses an offer it can't actually fulfill.

    Currently triggers on:
      * ``listing_not_open`` — the listing is in a terminal/in-flight
        status (for example closed); accepting a new
        negotiation against it would race with whatever flow already
        owns the listing.
      * ``no_matching_inventory`` — no available compute resource
        matches the listing's offer (gpu_model + region). The seller
        listed capacity it doesn't currently have; refusing here is
        better than agreeing then failing at fulfillment time.

    The negotiate endpoints map this to HTTP 409 (Conflict) since the
    request shape is valid but the seller's local state can't satisfy
    it; the buyer's right move is to pick a different listing or come
    back later.
    """

    def __init__(self, reason: str, *, listing_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.listing_id = listing_id


_LIVE_LISTING_STATUSES = frozenset({"open"})
"""Statuses that allow a new negotiation. Anything else is in-flight or
terminal and accepting a new negotiation would race with whatever owns
the listing (settlement, refund, etc.)."""


_FILE_POLICIES_DISCOVERED = False


def _default_policy_dir() -> Path:
    """Resolve the XDG-flavoured default policy directory.

    Honours ``$XDG_CONFIG_HOME`` so it lines up with the existing TOML
    config loader; falls back to ``~/.config/arkhai/policies/`` on hosts
    that don't set it. In the docker-compose stack the storefront runs
    with ``XDG_CONFIG_HOME=/etc``, so this resolves to
    ``/etc/arkhai/policies/`` — bind-mount a host directory there to
    drop in custom policies.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "arkhai" / "policies"


def _register_file_policy(folder: Path) -> bool:
    """Load ``folder/policy.py`` and register its ``middleware`` callable
    under the folder name. Returns True on success, False if the folder
    doesn't look like a policy (missing ``policy.py`` or ``middleware``).

    The expected shape::

        # /path/to/policies/my_policy/policy.py
        from market_policy.negotiation_middleware import (
            NegotiationContext, NegotiationDecision, NegotiationStep,
        )

        def middleware(history, context) -> NegotiationStep:
            return NegotiationDecision(...), context
    """
    policy_file = folder / "policy.py"
    if not policy_file.is_file():
        return False

    name = folder.name
    module_id = f"market_storefront._file_policies.{name}"
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
            "[POLICY] %s has no callable 'middleware' — skipping",
            policy_file,
        )
        return False

    register_negotiation_middleware(name)(middleware)
    logger.info("[POLICY] registered file middleware %r from %s", name, policy_file)
    return True


def _discover_file_policies(force: bool = False) -> None:
    """Scan the default + configured policy directories and register
    each subdirectory as a policy named after the folder.

    Runs at most once per process unless ``force=True`` (used by tests).
    Failures in individual folders are logged but don't block other
    folders. Built-in registrations win on cold start; a file policy
    with the same name overwrites them by design — that's the override
    UX for ad-hoc tuning.
    """
    global _FILE_POLICIES_DISCOVERED
    if _FILE_POLICIES_DISCOVERED and not force:
        return
    _FILE_POLICIES_DISCOVERED = True

    from market_storefront.utils.config import settings, BASE_URL_OVERRIDE
    candidates = [_default_policy_dir(), *(Path(p) for p in settings.negotiation.extra_policy_paths)]

    for root in candidates:
        if not root.is_dir():
            logger.debug("[POLICY] skipping non-existent policy dir %s", root)
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue
            _register_file_policy(entry)


def _maybe_register_rl_middleware() -> None:
    """Trigger self-registration of the torch RL middleware.

    The strategy module registers under name ``"rl"`` at import time. If
    torch / pufferlib aren't installed, the import fails — we swallow it
    and let ``load_negotiation_chain(["rl"])`` raise the actionable
    KeyError so callers get a clear "install with [rl] extras" message.
    """
    try:
        import domain.compute.agent.app.policy.torch_arkhai_strategy  # noqa: F401
    except Exception as exc:
        logger.debug("[NEGOTIATION] torch_arkhai_strategy not available: %s", exc)


_DEFAULT_GUARDS = ["has_matching_inventory_guard", "escrow_shape_guard"]
_DEFAULT_TERMINAL = "bisection"
_RL_POLICY_NAMES = {"rl", "erc20_rl", "native_token_rl", "erc1155_rl"}


def _policy_names_need_rl(policy_names: list[str]) -> bool:
    return any(name in _RL_POLICY_NAMES for name in policy_names)


def _policy_map_needs_rl(policies_by_kind: dict[str, list[str]]) -> bool:
    return any(_policy_names_need_rl(names) for names in policies_by_kind.values())


def _load_storefront_chain():
    """Resolve the storefront's configured negotiation middleware chain.

    Reads ``[negotiation].policies`` from TOML. Back-compat fallback: if
    ``policies`` is absent, synthesize one from the legacy ``policy_mode``
    key — `["has_matching_inventory_guard", "escrow_shape_guard", policy_mode]`.
    """
    from market_storefront.utils.config import settings

    _discover_file_policies()

    negotiation_cfg = getattr(settings, "negotiation", None)
    raw_policies = getattr(negotiation_cfg, "policies", None)
    policies_by_kind = normalize_policies_by_escrow_kind_config(raw_policies)
    if policies_by_kind:
        if _policy_map_needs_rl(policies_by_kind):
            _maybe_register_rl_middleware()
        from market_storefront.utils.config import CHAINS
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
        policy_mode = (getattr(negotiation_cfg, "policy_mode", "") or "").strip() or _DEFAULT_TERMINAL
        policy_names = _DEFAULT_GUARDS + [policy_mode]

    if _policy_names_need_rl(policy_names):
        _maybe_register_rl_middleware()

    return load_negotiation_chain(policy_names)


def _direction_from_strategy_label(strategy: str) -> str:
    """Translate the storefront's per-order strategy ('minimize'|'maximize')
    into the symmetric negotiation direction. They happen to match
    today; the indirection makes any future schema drift obvious."""
    if strategy in ("minimize", "maximize"):
        return strategy
    raise ValueError(f"Unknown order strategy {strategy!r}")


def _proposal_with_amount(
    pinned: dict[str, Any] | None, amount: int | float | None,
) -> dict[str, Any] | None:
    """Build a full EscrowProposal dict by overlaying ``amount`` onto the
    buyer's pinned skeleton.

    The buyer pins ``(chain_name, escrow_address, fields)`` at round 0;
    every subsequent round only varies ``fields["amount"]``. This helper
    reconstructs the per-round proposal from the thread's pinned skeleton
    plus the per-row amount stored in the messages table.

    Returns ``None`` when both pinned skeleton and amount are missing
    (legacy rows pre-refactor); the strategies handle absent proposals
    by falling back to the reference amount.
    """
    if pinned is None and amount is None:
        return None
    pinned_fields = (pinned or {}).get("fields") if isinstance(pinned, dict) else None
    merged_fields: dict[str, Any] = (
        dict(pinned_fields) if isinstance(pinned_fields, dict) else {}
    )
    if amount is not None:
        merged_fields["amount"] = int(amount)
    if pinned is None:
        return {"fields": merged_fields}
    return {**pinned, "fields": merged_fields}


def _seller_reference_amount(
    listing: Any, duration_seconds: int | None,
) -> int:
    """Compute the seller's absolute reference amount in base units.

    Reads the primary rate from ``accepted_escrows[0]`` (the per-hour
    broadcast rate from the listing) and scales it by the buyer-requested
    duration: ``rate * duration_seconds / 3600``. Falls back to 1 hour
    when no duration was provided.

    Per-hour rates only live on the listing as a broadcast; once
    negotiation begins, both sides reason in absolute base units, so
    we convert at the boundary.
    """
    from market_storefront.utils.action_executor import _extract_initial_price_from_order

    per_hour = Decimal(str(_extract_initial_price_from_order(listing)))
    seconds = int(duration_seconds) if duration_seconds is not None else 3600
    return int(per_hour * seconds // Decimal(3600))


def _coerce_pinned_proposal(value: Any) -> dict[str, Any] | None:
    """Parse a stored buyer_escrow_proposal value (dict or JSON string)
    into a dict. Returns ``None`` on missing/unparseable values.
    """
    import json as _json

    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = _json.loads(value)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _history_from_messages(
    messages: list[dict[str, Any]],
    our_sender: str,
    *,
    buyer_pinned_proposal: dict[str, Any] | None,
) -> list[NegotiationRound]:
    """Convert the SQLite-flavored thread messages into the symmetric
    NegotiationRound shape strategies consume.

    Per-round proposals are reconstructed from the buyer's pinned
    skeleton (``thread.buyer_escrow_proposal``) overlaid with the
    per-message amount stored in ``proposed_price``. The column name
    is retained for migration symmetry; semantically it now holds the
    absolute amount in base units.
    """
    out: list[NegotiationRound] = []
    for i, m in enumerate(messages):
        sender = "us" if m.get("sender") == our_sender else "them"
        action_taken = m.get("action_taken", "")
        if action_taken == "make_offer":
            action = "initial"
        elif action_taken == "counter_offer":
            action = "counter"
        elif action_taken == "accept_offer":
            action = "accept"
        elif action_taken in ("exit_negotiation",):
            action = "exit"
        else:
            action = "counter"
        amount_raw = m.get("proposed_price")
        try:
            amount: int | None = int(Decimal(str(amount_raw))) if amount_raw is not None else None
        except (InvalidOperation, TypeError, ValueError):
            amount = None
        proposal = (
            _proposal_with_amount(buyer_pinned_proposal, amount)
            if amount is not None or buyer_pinned_proposal is not None
            else None
        )
        out.append(NegotiationRound(
            round_number=i,
            sender=sender,
            action=action,
            proposal=proposal,
        ))
    return out


# ---------------------------------------------------------------------------
# Pure compute — no DB writes, no events.
# Called by both the real flow and the evaluate-negotiate dry-run endpoint.
# ---------------------------------------------------------------------------


async def _run_default_seller_round_policy(
    *,
    listing: Any,
    history: list[NegotiationRound],
    requested_duration_seconds: int | None = None,
    strategy_label: str | None = None,
    policy_inputs: dict[str, Any] | None = None,
) -> SellerRoundResult:
    """Run the default seller per-round policy hook.

    This is the current compute storefront instantiation: determine the
    listing strategy, derive the seller reference amount, load the configured
    middleware chain, interpret the explicit policy input bundle supplied by
    the caller, and return the chain's decision. The stateful HTTP wrappers
    own protocol persistence/events around this hook; policy implementations
    own any private decision state they need behind their callable.
    """
    from market_storefront.models.domain_models import Listing
    from market_storefront.utils.action_executor import determine_strategy_from_order

    if not strategy_label:
        strategy_label = determine_strategy_from_order(listing)
    if not strategy_label:
        raise ValueError(
            f"Listing {getattr(listing, 'listing_id', repr(listing))} "
            "has no usable strategy for negotiation"
        )

    # Compute the seller reference from the Listing model (or original
    # dict) BEFORE dumping. The model_dump'd dict is consumed by the
    # chain's context and shouldn't be passed back through
    # ``_extract_initial_price_from_order`` — that helper re-validates
    # dicts as Listings, and the ``parse_resources`` model_validator
    # mutates the input dict in place (replaces offer_resource with a
    # ComputeDomainResource object). Mutating the listing_dict here
    # would break downstream guards that expect plain dicts.
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


def _default_seller_round_hook(sqlite_client: Any) -> SellerRoundHook:
    return _DefaultSellerRoundHook(sqlite_client=sqlite_client)


async def _compute_round_zero_decision(
    *,
    sqlite_client: Any,
    listing: Any,
    their_proposal: dict[str, Any] | None,
    requested_duration_seconds: int | None = None,
) -> tuple[int, str, str, str, NegotiationDecision]:
    """Determine the seller's round-0 decision for a given buyer proposal.

    Builds a ``NegotiationContext`` (listing snapshot + portfolio for the
    inventory guard + buyer escrow proposal for the shape guard), constructs
    a single-element history representing the buyer's opening proposal,
    and runs the configured middleware chain. No SQLite writes and no
    stage events are emitted — those remain the responsibility of the real
    flow in ``start_sync_negotiation``.

    Returns ``(our_amount, strategy_label, direction, chain_label, decision)``
    where ``our_amount`` is the seller's absolute reference (per-hour rate
    scaled by the requested duration). Callers have everything they need
    to emit events or build response payloads without duplicating extraction.

    Raises ``ValueError`` if the listing has no usable negotiation strategy
    (e.g. the offer/demand resources don't declare one).
    """
    history = [NegotiationRound(
        round_number=0,
        sender="them",
        action="initial",
        proposal=their_proposal,
    )]
    result = await _default_seller_round_hook(sqlite_client)(
        listing=listing,
        history=history,
        requested_duration_seconds=requested_duration_seconds,
    )
    return (
        result.our_amount,
        result.strategy_label,
        result.direction,
        result.chain_label,
        result.decision,
    )


# ---------------------------------------------------------------------------
# Stateful wrappers — load/save thread, call the configured strategy.
# ---------------------------------------------------------------------------


async def start_sync_negotiation(
    *,
    sqlite_client: Any,
    our_listing_id: str,
    buyer_address: str,
    proposal: EscrowProposal | None = None,
    provision_terms: Any = None,
    our_base_url: str,
    their_agent_url: str,
    seller_round_hook: SellerRoundHook | None = None,
) -> dict[str, Any]:
    """Create a new negotiation thread and return the seller's first response.

    Generates a fresh ``negotiation_id`` (uuid4) and returns it to the
    buyer in the response. The buyer captures it from the response and
    uses it for all subsequent ``/negotiate/{neg_id}`` rounds — the
    canonical id is server-assigned, not client-derived.

    ``provision_terms`` carries the buyer's lease duration, ssh key, and
    eventually compute spec. ``proposal`` is the buyer's full
    EscrowProposal — picks a ``(chain_name, escrow_address)`` entry from
    the listing's ``accepted_escrows``, supplies the buyer-committable
    fields, and for scalar payment escrows carries the absolute opening
    amount in ``fields["amount"]``. Both artifacts are validated against
    the listing's acceptance set; the seller-confirmed values are persisted
    on the negotiation thread and echoed back so settlement-time escrow
    construction can use them.

    Raises ``ValueError`` if ``our_listing_id`` isn't in the local DB
    (seller must have published; no ad-hoc negotiations without a
    listing) or if the buyer's duration / proposal doesn't match what
    the listing accepts.
    """
    requested_duration_seconds = (
        provision_terms.duration_seconds if provision_terms is not None else None
    )
    # Imports deferred so unit tests can patch the registry / thread store
    # without paying for the whole import graph.
    from market_policy.negotiation_thread import NegotiationThreadTransaction
    from market_storefront.models.domain_models import Listing
    from market_storefront.utils.stage_log import stage_event

    # Check global pause flag and per-order pause flag before doing any work.
    from market_storefront.server import is_globally_paused
    if is_globally_paused():
        raise StorefrontPausedError("global")

    if await sqlite_client.is_listing_paused(listing_id=our_listing_id):
        raise StorefrontPausedError(f"order:{our_listing_id}")

    our_order_dict = await sqlite_client.load_listing(listing_id=our_listing_id)
    if not our_order_dict:
        raise ValueError(f"Order {our_listing_id} not found locally; seller has no matching listing")

    listing_status = (our_order_dict.get("status") or "").strip()
    if listing_status not in _LIVE_LISTING_STATUSES:
        raise OfferUnfulfillableError(
            f"listing_not_open (status={listing_status!r})",
            listing_id=our_listing_id,
        )

    raw_listing_max_seconds = our_order_dict.get("max_duration_seconds")
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
        raise ValueError(
            f"Requested duration {requested_duration_seconds}s exceeds "
            f"listing's max_duration_seconds={listing_max_seconds}s"
        )

    accepted_proposal = _validate_escrow_proposal(
        proposal=proposal,
        listing=our_order_dict,
    )

    proposal_dict = (
        proposal.model_dump()
        if proposal is not None and hasattr(proposal, "model_dump")
        else proposal
    )
    uses_scalar_amount = _proposal_uses_scalar_amount(
        listing=our_order_dict,
        proposal=accepted_proposal,
    )
    their_amount = _amount_from_proposal(proposal_dict)
    if their_amount is None:
        if uses_scalar_amount:
            raise OfferUnfulfillableError(
                "missing_amount: buyer's escrow proposal has no fields.amount",
                listing_id=our_listing_id,
            )
        their_amount = 0
    their_amount = int(their_amount)

    our_order = Listing.model_validate(our_order_dict)

    history = [NegotiationRound(
        round_number=0,
        sender="them",
        action="initial",
        proposal=proposal_dict,
    )]
    try:
        round_hook = seller_round_hook or _default_seller_round_hook(sqlite_client)
        round_result = await round_hook(
            listing=our_order,
            history=history,
            requested_duration_seconds=requested_duration_seconds,
        )
        our_amount = round_result.our_amount
        strategy = round_result.strategy_label
        decision = round_result.decision
    except ValueError as exc:
        if "price-less" in str(exc) or "default_min_price" in str(exc):
            raise OfferUnfulfillableError(
                "no_floor_price",
                listing_id=our_listing_id,
            ) from exc
        raise

    if decision.action == "reject":
        raise OfferUnfulfillableError(
            decision.reason or "rejected",
            listing_id=our_listing_id,
        )

    neg_id = "neg_" + uuid.uuid4().hex

    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_NEW") as txn:
        await txn.ensure_thread(
            negotiation_id=neg_id,
            our_listing_id=our_listing_id,
            their_listing_id="",  # buyer has no listing; engine column kept for symmetric schema
            our_agent_id=our_base_url,
            their_agent_id=their_agent_url,
            our_initial_price=our_amount,  # column name retained; stores absolute amount
            our_strategy=strategy,
            requested_duration_seconds=requested_duration_seconds,
            buyer_escrow_proposal=(
                accepted_proposal.model_dump()
                if accepted_proposal is not None
                else None
            ),
        )
        await txn.add_message(
            negotiation_id=neg_id,
            sender=their_agent_url or buyer_address,
            our_price=our_amount,
            their_price=their_amount,
            proposed_price=their_amount,
            action_taken="make_offer",
            message_type="offer",
        )

    await _record_seller_decision(
        neg_id=neg_id,
        our_amount=our_amount,
        their_amount=their_amount,
        decision=decision,
    )
    decision_amount = _amount_from_proposal(decision.proposal)
    if decision.action == "accept":
        agreed_duration_seconds = (
            requested_duration_seconds
            or our_order_dict.get("max_duration_seconds")
            or 3600
        )
        agreed_amount = decision_amount if decision_amount is not None else our_amount
        await sqlite_client.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=int(agreed_amount),
            agreed_duration_seconds=int(agreed_duration_seconds),
        )
    stage_event(
        "negotiation", "round_decided",
        negotiation_id=neg_id,
        round=0,
        our_amount=our_amount,
        their_amount=their_amount,
        decision=decision.action,
        decision_amount=int(decision_amount) if decision_amount is not None else None,
        decision_reason=decision.reason,
    )
    response: dict[str, Any] = {"negotiation_id": neg_id, **decision.to_dict()}
    if provision_terms is not None:
        response["accepted_provision_terms"] = provision_terms.model_dump()
    if accepted_proposal is not None:
        response["accepted_escrow_proposal"] = accepted_proposal.model_dump()
        if decision.action == "accept":
            try:
                response["accepted_escrow_terms"] = _materialized_escrow_terms_payload(
                    proposal=accepted_proposal,
                    seller_wallet_address=None,
                    agreed_amount=int(agreed_amount),
                    duration_seconds=int(agreed_duration_seconds),
                )
            except Exception as exc:
                logger.debug("Could not materialize accepted escrow terms: %s", exc)
    return response


async def continue_sync_negotiation(
    *,
    sqlite_client: Any,
    neg_id: str,
    buyer_action: str,
    buyer_proposal: dict[str, Any] | None,
    buyer_reason: str | None,
    buyer_address: str,
    seller_round_hook: SellerRoundHook | None = None,
) -> dict[str, Any]:
    """Drive one further round against an existing thread.

    `buyer_action` is the action the buyer is proposing this round:
      - "counter" with `buyer_proposal`: the buyer's new full EscrowProposal,
        with ``fields["amount"]`` for scalar payment escrows.
      - "accept": the buyer accepts the seller's last counter; we
        commit agreed_terms and return action=accept in response.
      - "exit": the buyer is walking away; we mark the thread terminal.
    """
    from market_policy.negotiation_thread import NegotiationThreadTransaction
    from market_storefront.models.domain_models import Listing
    from market_storefront.utils.action_executor import determine_strategy_from_order
    from market_storefront.utils.stage_log import stage_event

    thread = await sqlite_client.load_negotiation_thread_row(negotiation_id=neg_id)
    if not thread:
        raise ValueError(f"Unknown negotiation {neg_id}")
    if thread.get("terminal_state"):
        raise ValueError(
            f"Negotiation {neg_id} is already in terminal state "
            f"{thread.get('terminal_state')!r}",
        )

    our_listing_id = thread.get("our_listing_id")
    our_order_dict = await sqlite_client.load_listing(listing_id=our_listing_id) if our_listing_id else None
    if not our_order_dict:
        raise ValueError(f"Seller's order {our_listing_id} is gone from local DB")
    our_order = Listing.model_validate(our_order_dict)
    strategy = determine_strategy_from_order(our_order)
    requested_duration_seconds = thread.get("requested_duration_seconds")
    buyer_pinned_proposal = _coerce_pinned_proposal(thread.get("buyer_escrow_proposal"))
    uses_scalar_amount = _proposal_uses_scalar_amount(
        listing=our_order_dict,
        proposal=buyer_pinned_proposal,
    )
    our_amount = (
        _seller_reference_amount(our_order_dict, requested_duration_seconds)
        if uses_scalar_amount else 0
    )

    messages = await sqlite_client.load_negotiation_thread(negotiation_id=neg_id)
    our_previous_counters = [
        m for m in messages
        if m.get("action_taken") == "counter_offer"
        and m.get("proposed_price") is not None
        and m.get("sender") != buyer_address
    ]

    # Buyer-declared action short-circuits (accept / exit). No policy call.
    if buyer_action == "accept":
        last_seller_amount = next(
            (int(Decimal(str(m["proposed_price"]))) for m in reversed(messages)
             if m.get("action_taken") == "counter_offer" and m.get("sender") != buyer_address),
            our_amount,
        )
        async with NegotiationThreadTransaction("SYNC_NEGOTIATE_ACCEPT") as txn:
            await txn.add_message(
                negotiation_id=neg_id,
                sender=buyer_address,
                our_price=our_amount,
                their_price=last_seller_amount,
                proposed_price=last_seller_amount,
                action_taken="accept_offer",
                message_type="accepted",
            )
            await txn.mark_terminal(neg_id, "success")
        agreed_duration_seconds = (
            requested_duration_seconds
            or our_order_dict.get("max_duration_seconds")
            or 3600
        )
        await sqlite_client.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=int(last_seller_amount),
            agreed_duration_seconds=int(agreed_duration_seconds),
        )
        stage_event(
            "negotiation", "accepted",
            negotiation_id=neg_id,
            agreed_amount=last_seller_amount,
            our_initial_amount=our_amount,
        )
        final_proposal = _proposal_with_amount(
            buyer_pinned_proposal,
            last_seller_amount if uses_scalar_amount else None,
        )
        response = {
            "action": "accept",
            "proposal": final_proposal,
        }
        try:
            accepted = EscrowProposal.model_validate(final_proposal)
            response["accepted_escrow_proposal"] = accepted.model_dump()
            response["accepted_escrow_terms"] = _materialized_escrow_terms_payload(
                proposal=accepted,
                seller_wallet_address=None,
                agreed_amount=int(last_seller_amount),
                duration_seconds=int(agreed_duration_seconds),
            )
        except Exception as exc:
            logger.debug("Could not materialize accepted escrow terms: %s", exc)
        return response

    if buyer_action == "exit":
        async with NegotiationThreadTransaction("SYNC_NEGOTIATE_EXIT") as txn:
            await txn.add_message(
                negotiation_id=neg_id,
                sender=buyer_address,
                our_price=our_amount,
                their_price=None,
                proposed_price=None,
                action_taken="exit_negotiation",
                message_type="exit",
            )
            await txn.mark_terminal(neg_id, "failure")
        stage_event(
            "negotiation", "exited",
            negotiation_id=neg_id,
            reason=buyer_reason or "buyer_exit",
        )
        return {"action": "exit", "reason": "buyer_exit"}

    if buyer_action != "counter":
        raise ValueError(f"Unsupported buyer action {buyer_action!r}")
    raw_amount = _amount_from_proposal(buyer_proposal)
    if raw_amount is None:
        if uses_scalar_amount:
            raise ValueError("counter requires 'proposal' with fields.amount")
        buyer_amount = 0
    else:
        buyer_amount = int(raw_amount)

    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_BUYER_COUNTER") as txn:
        await txn.add_message(
            negotiation_id=neg_id,
            sender=buyer_address,
            our_price=our_amount,
            their_price=buyer_amount,
            proposed_price=buyer_amount,
            action_taken="counter_offer",
            message_type="counter_proposal",
        )

    from market_storefront.utils.config import settings, BASE_URL_OVERRIDE
    our_sender = BASE_URL_OVERRIDE or "seller"
    history = _history_from_messages(
        messages, our_sender, buyer_pinned_proposal=buyer_pinned_proposal,
    )
    # The buyer's just-recorded counter isn't in `messages` (loaded before
    # the txn) — append it so the chain sees it as their proposal.
    history.append(NegotiationRound(
        round_number=len(history),
        sender="them",
        action="counter",
        proposal=(
            _proposal_with_amount(buyer_pinned_proposal, buyer_amount)
            if uses_scalar_amount else (buyer_proposal or buyer_pinned_proposal)
        ),
    ))
    round_hook = seller_round_hook or _default_seller_round_hook(sqlite_client)
    round_result = await round_hook(
        listing=our_order,
        history=history,
        requested_duration_seconds=requested_duration_seconds,
        strategy_label=strategy,
    )
    our_amount = round_result.our_amount
    decision = round_result.decision
    await _record_seller_decision(
        neg_id=neg_id, our_amount=our_amount,
        their_amount=buyer_amount, decision=decision,
    )
    decision_amount = _amount_from_proposal(decision.proposal)
    if decision.action == "accept":
        agreed_duration_seconds = (
            requested_duration_seconds
            or our_order_dict.get("max_duration_seconds")
            or 3600
        )
        agreed_amount = decision_amount if decision_amount is not None else our_amount
        await sqlite_client.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=int(agreed_amount),
            agreed_duration_seconds=int(agreed_duration_seconds),
        )
    stage_event(
        "negotiation", "round_decided",
        negotiation_id=neg_id,
        round=len(our_previous_counters) + 1,
        our_amount=our_amount,
        their_amount=buyer_amount,
        decision=decision.action,
        decision_amount=int(decision_amount) if decision_amount is not None else None,
        decision_reason=decision.reason,
    )
    response = decision.to_dict()
    if decision.action == "accept":
        final_proposal = _proposal_with_amount(
            buyer_pinned_proposal,
            (
                int(decision_amount) if decision_amount is not None else int(our_amount)
            ) if uses_scalar_amount else None,
        )
        try:
            accepted = EscrowProposal.model_validate(final_proposal)
            response["accepted_escrow_proposal"] = accepted.model_dump()
            response["accepted_escrow_terms"] = _materialized_escrow_terms_payload(
                proposal=accepted,
                seller_wallet_address=None,
                agreed_amount=int(decision_amount) if decision_amount is not None else int(our_amount),
                duration_seconds=int(
                    requested_duration_seconds
                    or our_order_dict.get("max_duration_seconds")
                    or 3600
                ),
            )
        except Exception as exc:
            logger.debug("Could not materialize accepted escrow terms: %s", exc)
    return response


async def _record_seller_decision(
    *,
    neg_id: str,
    our_amount: int,
    their_amount: int,
    decision: NegotiationDecision,
) -> None:
    """Persist the seller's decision as a message + terminal state if applicable.

    ``proposed_price`` column on the messages table stores the absolute
    amount (in base units) — the column name is retained for migration
    symmetry; semantically it now holds the amount, not a per-hour rate.
    """
    from market_policy.negotiation_thread import NegotiationThreadTransaction
    from market_storefront.utils.config import BASE_URL_OVERRIDE

    sender = BASE_URL_OVERRIDE or "seller"
    action_taken_map = {
        "counter": "counter_offer",
        "accept": "accept_offer",
        "exit": "exit_negotiation",
        "reject": "exit_negotiation",  # reject reuses exit terminal state
    }
    action_taken = action_taken_map[decision.action]
    message_type_map = {
        "counter": "counter_proposal",
        "accept": "accepted",
        "exit": "exit",
        "reject": "exit",
    }
    decision_amount = _amount_from_proposal(decision.proposal)
    stored_amount = (
        int(decision_amount) if decision_amount is not None else their_amount
    )

    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_SELLER_DECISION") as txn:
        await txn.add_message(
            negotiation_id=neg_id,
            sender=sender,
            our_price=our_amount,
            their_price=their_amount,
            proposed_price=stored_amount,
            action_taken=action_taken,
            message_type=message_type_map[decision.action],
        )
        if decision.action in ("accept",):
            await txn.mark_terminal(neg_id, "success")
        elif decision.action in ("exit", "reject"):
            await txn.mark_terminal(neg_id, "failure")
