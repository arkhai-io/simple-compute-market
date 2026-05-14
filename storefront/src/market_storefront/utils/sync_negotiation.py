"""Synchronous request-response negotiation.

Buyer drives every round via `POST /negotiate/{id}` (or `/new`); the
seller's decision is returned in the HTTP response body instead of
being pushed back as a separate message.

Shape:

    POST /negotiate/new
      {seller_order_id, buyer_address, initial_price}
      → {neg_id, action: "counter"|"accept"|"exit"|"reject", price?, reason?}

    POST /negotiate/{neg_id}
      {action: "counter"|"accept"|"exit", price?, reason?, buyer_address}
      → {action, price?, reason?}

`action` in the request is what the buyer is proposing *in this round*.
`action` in the response is the seller's resulting decision.

Negotiation state is persisted in the existing `negotiation_threads` +
`negotiation_messages` tables. The per-round decision lives in
`market_policy.negotiation_strategy` so both buyer and storefront drive
rounds through the same engine.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from market_policy.negotiation_strategy import (
    DEFAULT_STRATEGY,
    NegotiationDecision,
    NegotiationRound,
    NegotiationRoundInput,
    load_strategy,
    register_strategy,
)

from service.schemas import EscrowTermsProposal

logger = logging.getLogger(__name__)


# Today's only acceptable escrow shape. Future listings will advertise
# their acceptance set (potentially multiple shapes); the validator
# below interprets the listing-derived expected shape against the
# buyer's proposal.
_SUPPORTED_ESCROW_KIND = "erc20_non_tierable"
_SUPPORTED_ARBITER_KIND = "recipient"


def _validate_escrow_terms_proposal(
    *,
    proposal: EscrowTermsProposal | None,
    listing: dict[str, Any],
) -> EscrowTermsProposal | None:
    """Validate the buyer's escrow proposal against the listing.

    Today's listing implicitly accepts exactly one shape:
    ``erc20_non_tierable`` + ``recipient`` + the
    listing's ``demand_resource.token.contract_address``. Any deviation
    raises ``OfferUnfulfillableError``. Future step: listings advertise
    an explicit acceptance set and this validator picks the matching
    shape (or rejects).

    Returns the validated proposal unchanged so the caller can echo it
    back. Returns None when the buyer didn't include a proposal (legacy
    clients) — in that case the seller assumes the canonical shape.
    """
    if proposal is None:
        # Legacy buyer pre-step-7; we can't echo what they didn't send.
        return None

    if proposal.escrow_kind != _SUPPORTED_ESCROW_KIND:
        raise OfferUnfulfillableError(
            f"escrow_kind_unsupported: got {proposal.escrow_kind!r}, "
            f"expected {_SUPPORTED_ESCROW_KIND!r}",
            listing_id=listing.get("listing_id"),
        )
    if proposal.arbiter_kind != _SUPPORTED_ARBITER_KIND:
        raise OfferUnfulfillableError(
            f"arbiter_kind_unsupported: got {proposal.arbiter_kind!r}, "
            f"expected {_SUPPORTED_ARBITER_KIND!r}",
            listing_id=listing.get("listing_id"),
        )

    # Token must match the listing's demand_resource.token.contract_address.
    expected_token = _extract_listing_payment_token(listing)
    if expected_token is None:
        # Listing has no token to validate against — accept whatever
        # the buyer proposed (relaxed for listings without a typed
        # payment token, e.g. legacy compute listings).
        return proposal
    if proposal.payment_token.lower() != expected_token.lower():
        raise OfferUnfulfillableError(
            f"payment_token_mismatch: buyer proposed {proposal.payment_token}, "
            f"listing demands {expected_token}",
            listing_id=listing.get("listing_id"),
        )
    return proposal


def _extract_listing_payment_token(listing: dict[str, Any]) -> str | None:
    """Pull the payment-token contract address from the listing.

    Prefers ``accepted_escrows[0].fields.payment_token`` — the canonical
    advertisement under the new shape. Falls back to legacy
    ``demand_resource.token.contract_address`` for pre-migration rows.
    Returns ``None`` when neither source has a typed token side (e.g.
    compute-for-compute trades or hidden-reserve listings).
    """
    import json as _json

    accepted = listing.get("accepted_escrows")
    if isinstance(accepted, str):
        try:
            accepted = _json.loads(accepted)
        except (ValueError, TypeError):
            accepted = None
    if isinstance(accepted, list) and accepted:
        first = accepted[0]
        if isinstance(first, dict):
            fields = first.get("fields")
            if isinstance(fields, dict):
                addr = fields.get("payment_token")
                if isinstance(addr, str) and addr:
                    return addr

    raw = listing.get("demand_resource")
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, dict):
        return None
    token = raw.get("token")
    if isinstance(token, dict):
        addr = token.get("contract_address")
        if isinstance(addr, str):
            return addr
    return None


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
        status (accepted, refunded, closed); accepting a new
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
    """Load ``folder/policy.py`` and register its ``factory`` under the
    folder name. Returns True on success, False if the folder doesn't
    look like a policy (missing ``policy.py`` or ``factory``)."""
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

    factory = getattr(module, "factory", None)
    if not callable(factory):
        logger.warning(
            "[POLICY] %s has no callable 'factory' — skipping",
            policy_file,
        )
        return False

    register_strategy(name, factory)
    logger.info("[POLICY] registered file policy %r from %s", name, policy_file)
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

    from market_storefront.utils.config import CONFIG
    candidates = [_default_policy_dir(), *(Path(p) for p in CONFIG.extra_policy_paths)]

    for root in candidates:
        if not root.is_dir():
            logger.debug("[POLICY] skipping non-existent policy dir %s", root)
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue
            _register_file_policy(entry)


def _maybe_register_rl_strategy() -> None:
    """Trigger self-registration of the torch RL strategy.

    The strategy module calls ``register_strategy("rl", ...)`` at import
    time. If torch / pufferlib aren't installed, the import fails — we
    swallow it and let ``load_strategy("rl")`` raise the actionable
    KeyError so callers get a clear "install with [rl] extras" message.
    """
    try:
        import domain.compute.agent.app.policy.torch_arkhai_strategy  # noqa: F401
    except Exception as exc:
        logger.debug("[NEGOTIATION] torch_arkhai_strategy not available: %s", exc)


def _load_storefront_strategy():
    """Resolve the storefront's configured strategy.

    Selected via ``CONFIG.negotiation_policy_mode``; defaults to the
    registered default ("rl") if unset. Triggers the torch strategy's
    self-registration on first call.
    """
    from market_storefront.utils.config import CONFIG
    name = (CONFIG.negotiation_policy_mode or "").strip() or None
    _discover_file_policies()
    if (name or DEFAULT_STRATEGY) == "rl":
        _maybe_register_rl_strategy()
    return load_strategy(name)


def _direction_from_strategy_label(strategy: str) -> str:
    """Translate the storefront's per-order strategy ('minimize'|'maximize')
    into the symmetric negotiation direction. They happen to match
    today; the indirection makes any future schema drift obvious."""
    if strategy in ("minimize", "maximize"):
        return strategy
    raise ValueError(f"Unknown order strategy {strategy!r}")


def _history_from_messages(messages: list[dict[str, Any]], our_sender: str) -> list[NegotiationRound]:
    """Convert the SQLite-flavored thread messages into the symmetric
    NegotiationRound shape strategies consume."""
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
        price = m.get("proposed_price")
        out.append(NegotiationRound(
            round_number=i,
            sender=sender,
            action=action,
            price=int(price) if price is not None else None,
        ))
    return out


# ---------------------------------------------------------------------------
# Pure compute — no DB writes, no events.
# Called by both the real flow and the evaluate-negotiate dry-run endpoint.
# ---------------------------------------------------------------------------


def _compute_round_zero_decision(
    *,
    listing: Any,
    their_proposed_price: int,
) -> tuple[int, str, str, NegotiationDecision]:
    """Determine the seller's round-0 decision for a given buyer price.

    Loads the configured strategy, builds a ``NegotiationRoundInput`` for
    round 0, and calls ``strategy.decide()``.  No SQLite writes and no
    stage events are emitted — those remain the responsibility of the
    real flow in ``start_sync_negotiation``.

    Returns ``(our_price, strategy_label, direction, strategy_name, decision)``
    so callers have all the context needed to emit events or build response
    payloads without duplicating the extraction logic.

    Raises ``ValueError`` if the listing has no usable negotiation strategy
    (e.g. the offer/demand resources don't declare one).
    """
    from market_storefront.utils.action_executor import (
        _extract_initial_price_from_order,
        determine_strategy_from_order,
    )

    strategy_label = determine_strategy_from_order(listing)
    if not strategy_label:
        raise ValueError(
            f"Listing {getattr(listing, 'listing_id', repr(listing))} "
            "has no usable strategy for negotiation"
        )
    our_price = _extract_initial_price_from_order(listing)
    direction = _direction_from_strategy_label(strategy_label)

    strategy_obj = _load_storefront_strategy()
    strategy_name = type(strategy_obj).__name__
    decision = strategy_obj.decide(NegotiationRoundInput(
        direction=direction,
        our_reference_price=our_price,
        their_proposed_price=their_proposed_price,
        history=[],
    ))
    return our_price, strategy_label, direction, strategy_name, decision


# ---------------------------------------------------------------------------
# Stateful wrappers — load/save thread, call the configured strategy.
# ---------------------------------------------------------------------------


async def start_sync_negotiation(
    *,
    sqlite_client: Any,
    our_listing_id: str,
    buyer_address: str,
    their_proposed_price: int,
    provision_terms: Any = None,
    escrow_terms_proposal: Any = None,
    our_base_url: str,
    their_agent_url: str,
    policy_service: Any = None,
) -> dict[str, Any]:
    """Create a new negotiation thread and return the seller's first response.

    Generates a fresh ``negotiation_id`` (uuid4) and returns it to the
    buyer in the response. The buyer captures it from the response and
    uses it for all subsequent ``/negotiate/{neg_id}`` rounds — the
    canonical id is server-assigned, not client-derived.

    ``provision_terms`` carries the buyer's lease duration, ssh key, and
    eventually compute spec. ``escrow_terms_proposal`` is the buyer's
    on-chain escrow shape proposal. Both are validated against the
    listing's acceptance set (today: trivial — only the canonical
    erc20+recipient shape is supported with the listing's
    demand_resource token). Persisted on the negotiation thread (in a
    future step) so settlement reads them back without re-querying
    the buyer; echoed back to the buyer in the response so settlement-
    time escrow construction can use the seller-confirmed values.

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

    # Listing-state-machine invariant — kept as infrastructure rather
    # than policy. Accepting a negotiation against a closed/in-flight
    # listing breaks consistency with whatever flow already owns it
    # (settlement, refund, etc.); operators don't get to opt out.
    listing_status = (our_order_dict.get("status") or "").strip()
    if listing_status not in _LIVE_LISTING_STATUSES:
        raise OfferUnfulfillableError(
            f"listing_not_open (status={listing_status!r})",
            listing_id=our_listing_id,
        )

    # Run the seeded pre-thread guard composite. The default for an
    # immediate-deal seller checks that available portfolio inventory
    # matches the listing's offer; operators running futures or
    # off-chain-matched flows swap the composite's components and the
    # same code path lets non-immediate negotiations through.
    if policy_service is not None:
        rejection_reason = await policy_service.consult_pre_negotiation_guards(
            listing_id=our_listing_id,
            listing=our_order_dict,
            proposed_price=their_proposed_price,
            requested_duration_seconds=requested_duration_seconds,
        )
        if rejection_reason:
            raise OfferUnfulfillableError(
                rejection_reason, listing_id=our_listing_id,
            )

    # Validate the buyer's duration ask against the listing's advertised
    # ceiling. NULL on the listing means "unlimited" — accept any positive
    # duration. A buyer ask exceeding the cap is rejected before any thread
    # state is written.
    listing_max_seconds = our_order_dict.get("max_duration_seconds")
    if (
        requested_duration_seconds is not None
        and listing_max_seconds is not None
        and int(requested_duration_seconds) > int(listing_max_seconds)
    ):
        raise ValueError(
            f"Requested duration {requested_duration_seconds}s exceeds "
            f"listing's max_duration_seconds={listing_max_seconds}s"
        )

    # Validate the buyer's escrow terms proposal against the listing's
    # acceptance set. Today's acceptance set is implicit and trivial:
    # one canonical shape per listing (erc20_non_tierable + recipient +
    # the listing's demand_resource token). Future listings may
    # advertise multiple acceptable proposals; for now any deviation
    # from the canonical shape rejects.
    _accepted_escrow_proposal = _validate_escrow_terms_proposal(
        proposal=escrow_terms_proposal,
        listing=our_order_dict,
    )

    our_order = Listing.model_validate(our_order_dict)

    # Pure compute: resolve strategy and get round-0 decision without writing anything.
    try:
        our_price, strategy, direction, _strategy_name, decision = _compute_round_zero_decision(
            listing=our_order,
            their_proposed_price=their_proposed_price,
        )
    except ValueError as exc:
        # Price-less listing without a configured fallback floor — the
        # operator opted into publishing without a price but never set
        # default_min_price. Surface as an unfulfillable offer (409) so
        # the buyer gets a clean retry hint, not a 404.
        if "price-less" in str(exc) or "default_min_price" in str(exc):
            raise OfferUnfulfillableError(
                "no_floor_price",
                listing_id=our_listing_id,
            ) from exc
        raise

    neg_id = "neg_" + uuid.uuid4().hex

    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_NEW") as txn:
        await txn.ensure_thread(
            negotiation_id=neg_id,
            our_listing_id=our_listing_id,
            their_listing_id="",  # buyer has no listing; engine column kept for symmetric schema
            our_agent_id=our_base_url,
            their_agent_id=their_agent_url,
            our_initial_price=our_price,
            our_strategy=strategy,
            requested_duration_seconds=requested_duration_seconds,
            buyer_escrow_terms_proposal=(
                _accepted_escrow_proposal.model_dump()
                if _accepted_escrow_proposal is not None
                else None
            ),
        )
        # Round-0 record of the buyer's opening proposal.
        await txn.add_message(
            negotiation_id=neg_id,
            sender=their_agent_url or buyer_address,
            our_price=our_price,
            their_price=their_proposed_price,
            proposed_price=their_proposed_price,
            action_taken="make_offer",
            message_type="offer",
        )

    await _record_seller_decision(neg_id=neg_id, our_price=our_price,
                                  their_price=their_proposed_price,
                                  decision=decision)
    stage_event(
        "negotiation", "round_decided",
        negotiation_id=neg_id,
        round=0,
        our_price=our_price,
        their_price=their_proposed_price,
        decision=decision.action,
        decision_price=decision.price,
        decision_reason=decision.reason,
    )
    response: dict[str, Any] = {"negotiation_id": neg_id, **decision.to_dict()}
    # Echo back what the seller validated so settlement-time escrow
    # construction can use the seller-confirmed values. Skipped on
    # rejection paths (which raise before reaching here).
    if provision_terms is not None:
        response["accepted_provision_terms"] = provision_terms.model_dump()
    if _accepted_escrow_proposal is not None:
        response["accepted_escrow_terms_proposal"] = _accepted_escrow_proposal.model_dump()
    return response


async def continue_sync_negotiation(
    *,
    sqlite_client: Any,
    neg_id: str,
    buyer_action: str,
    buyer_price: int | None,
    buyer_reason: str | None,
    buyer_address: str,
) -> dict[str, Any]:
    """Drive one further round against an existing thread.

    `buyer_action` is the action the buyer is proposing this round:
      - "counter" with `buyer_price`: the buyer's new price offer.
      - "accept": the buyer accepts the seller's last counter; we
        commit agreed_terms and return action=accept in response.
      - "exit": the buyer is walking away; we mark the thread terminal.
    """
    from market_policy.negotiation_thread import NegotiationThreadTransaction
    from market_storefront.models.domain_models import Listing
    from market_storefront.utils.action_executor import (
        _extract_initial_price_from_order,
        determine_strategy_from_order,
    )
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
    our_price = _extract_initial_price_from_order(our_order)

    messages = await sqlite_client.load_negotiation_thread(negotiation_id=neg_id)
    our_previous_counters = [
        int(m["proposed_price"])
        for m in messages
        if m.get("action_taken") == "counter_offer"
        and m.get("proposed_price") is not None
    ]

    # Buyer-declared action short-circuits (accept / exit). No policy call.
    if buyer_action == "accept":
        # The buyer is accepting our last offered price. Commit terms.
        last_seller_price = next(
            (int(m["proposed_price"]) for m in reversed(messages)
             if m.get("action_taken") == "counter_offer" and m.get("sender") != buyer_address),
            our_price,
        )
        async with NegotiationThreadTransaction("SYNC_NEGOTIATE_ACCEPT") as txn:
            await txn.add_message(
                negotiation_id=neg_id,
                sender=buyer_address,
                our_price=our_price,
                their_price=last_seller_price,
                proposed_price=last_seller_price,
                action_taken="accept_offer",
                message_type="accepted",
            )
            await txn.mark_terminal(neg_id, "success")
        # The buyer's lease ask was captured on /negotiate/new and lives on
        # the thread row; echo it as the agreed duration. Falls back to the
        # listing's max ceiling, then 1h, only for legacy threads with no
        # recorded request (would mean a /negotiate/new from before this slice).
        agreed_duration_seconds = (
            thread.get("requested_duration_seconds")
            or our_order_dict.get("max_duration_seconds")
            or 3600
        )
        await sqlite_client.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=last_seller_price,
            agreed_duration_seconds=int(agreed_duration_seconds),
        )
        stage_event(
            "negotiation", "accepted",
            negotiation_id=neg_id,
            agreed_price=last_seller_price,
            our_initial_price=our_price,
        )
        return {"action": "accept", "price": last_seller_price}

    if buyer_action == "exit":
        async with NegotiationThreadTransaction("SYNC_NEGOTIATE_EXIT") as txn:
            await txn.add_message(
                negotiation_id=neg_id,
                sender=buyer_address,
                our_price=our_price,
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

    # Counter: call the policy.
    if buyer_action != "counter":
        raise ValueError(f"Unsupported buyer action {buyer_action!r}")
    if buyer_price is None:
        raise ValueError("counter requires 'price'")

    # Record the buyer's counter before deciding — symmetric with round-0
    # recording in start_sync_negotiation.
    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_BUYER_COUNTER") as txn:
        await txn.add_message(
            negotiation_id=neg_id,
            sender=buyer_address,
            our_price=our_price,
            their_price=int(buyer_price),
            proposed_price=int(buyer_price),
            action_taken="counter_offer",
            message_type="counter_proposal",
        )

    from market_storefront.utils.config import CONFIG as _CONFIG
    our_sender = _CONFIG.base_url_override or "seller"
    strategy_obj = _load_storefront_strategy()
    decision = strategy_obj.decide(NegotiationRoundInput(
        direction=_direction_from_strategy_label(strategy),
        our_reference_price=our_price,
        their_proposed_price=int(buyer_price),
        history=_history_from_messages(messages, our_sender),
    ))
    await _record_seller_decision(
        neg_id=neg_id, our_price=our_price,
        their_price=int(buyer_price), decision=decision,
    )
    if decision.action == "accept":
        agreed_duration_seconds = (
            thread.get("requested_duration_seconds")
            or our_order_dict.get("max_duration_seconds")
            or 3600
        )
        await sqlite_client.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=int(decision.price),
            agreed_duration_seconds=int(agreed_duration_seconds),
        )
    stage_event(
        "negotiation", "round_decided",
        negotiation_id=neg_id,
        round=len(our_previous_counters) + 1,
        our_price=our_price,
        their_price=int(buyer_price),
        decision=decision.action,
        decision_price=decision.price,
        decision_reason=decision.reason,
    )
    return decision.to_dict()


async def _record_seller_decision(
    *,
    neg_id: str,
    our_price: int,
    their_price: int,
    decision: NegotiationDecision,
) -> None:
    """Persist the seller's decision as a message + terminal state if applicable."""
    from market_policy.negotiation_thread import NegotiationThreadTransaction
    from market_storefront.utils.config import CONFIG

    sender = CONFIG.base_url_override or "seller"
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

    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_SELLER_DECISION") as txn:
        await txn.add_message(
            negotiation_id=neg_id,
            sender=sender,
            our_price=our_price,
            their_price=their_price,
            proposed_price=decision.price if decision.price is not None else their_price,
            action_taken=action_taken,
            message_type=message_type_map[decision.action],
        )
        if decision.action in ("accept",):
            await txn.mark_terminal(neg_id, "success")
        elif decision.action in ("exit", "reject"):
            await txn.mark_terminal(neg_id, "failure")
