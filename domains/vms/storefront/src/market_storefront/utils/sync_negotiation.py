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

import json
import logging
import uuid
from decimal import Decimal
from typing import Any

from arkhai_vms import DIMENSION_KEYS as _DIMENSION_COMPUTE_KEYS
from core_storefront.negotiation_sync import (
    LIVE_LISTING_STATUSES,
    OfferUnfulfillableError,
    StorefrontPausedError,
)
from core_storefront.negotiation_sync import (
    coerce_pinned_proposal as _coerce_pinned_proposal,
)
from core_storefront.negotiation_sync import (
    create_sync_negotiation_thread as _create_sync_negotiation_thread,
)
from core_storefront.negotiation_sync import (
    history_from_messages as _history_from_messages,
)
from core_storefront.negotiation_sync import (
    record_buyer_accept_message as _record_buyer_accept_message,
)
from core_storefront.negotiation_sync import (
    record_buyer_counter_message as _record_buyer_counter_message,
)
from core_storefront.negotiation_sync import (
    record_buyer_exit_message as _record_buyer_exit_message,
)
from core_storefront.negotiation_sync import (
    record_seller_decision_message as _record_seller_decision_message,
)
from domains.vms.listings import extract_compute_from_order
from domains.vms.negotiation import storefront_round as vm_storefront_round
from domains.vms.negotiation.policies import _amount_from_proposal
from domains.vms.negotiation.storefront_round import (
    SellerRoundHook,
    SellerRoundResult,
)
from domains.vms.settlement.proposals import accepted_escrow_artifacts_from_proposal
from market_core.schemas import (
    EscrowProposal,
    SettlementObligation,
    SettlementPlan,
    SettlementSelection,
)
from market_policy.negotiation_middleware import (
    NegotiationDecision,
    NegotiationRound,
)

logger = logging.getLogger(__name__)


def _negotiation_settings() -> Any:
    from market_storefront.utils.config import settings

    return settings.negotiation


def _extra_policy_paths() -> list[str]:
    return list(getattr(_negotiation_settings(), "extra_policy_paths", []) or [])


def _chain_settings() -> dict[str, Any]:
    from market_storefront.utils.config import CHAINS

    return dict(CHAINS)


def _default_min_price() -> Any:
    from market_storefront.utils.config import settings

    return settings.pricing.default_min_price


def _discover_file_policies(force: bool = False) -> None:
    vm_storefront_round._discover_file_policies(
        force=force,
        extra_policy_paths=_extra_policy_paths(),
    )


def _load_storefront_chain():
    return vm_storefront_round._load_storefront_chain(
        negotiation_config=_negotiation_settings(),
        chains=_chain_settings(),
        extra_policy_paths=_extra_policy_paths(),
    )


def _seller_reference_amount(
    listing: Any,
    duration_seconds: int | None,
) -> int:
    return vm_storefront_round._seller_reference_amount(
        listing,
        duration_seconds,
        default_min_price=_default_min_price(),
    )


async def _run_default_seller_round_policy(**kwargs: Any) -> SellerRoundResult:
    kwargs.setdefault("negotiation_config", _negotiation_settings())
    kwargs.setdefault("chains", _chain_settings())
    kwargs.setdefault("extra_policy_paths", _extra_policy_paths())
    kwargs.setdefault("default_min_price", _default_min_price())
    return await vm_storefront_round._run_default_seller_round_policy(**kwargs)


def _default_seller_round_hook(sqlite_client: Any) -> SellerRoundHook:
    # The round hook reads its availability snapshot through the
    # site-authority capacity client; embedded mode wraps the same
    # SQLite handle the rest of this flow uses.
    from market_storefront.domain_runtime import get_market_domain_contract
    from market_storefront.services.capacity_client import build_capacity_client

    policy = get_market_domain_contract().storefront
    assert policy is not None
    return policy.run_negotiation_policy(
        build_capacity_client(lambda: sqlite_client),
        negotiation_config=_negotiation_settings(),
        chains=_chain_settings(),
        extra_policy_paths=_extra_policy_paths(),
        default_min_price=_default_min_price(),
    )


def _chain_config_paths() -> dict[str, str | None]:
    from market_storefront.utils.config import CHAINS

    return {name: chain.alkahest_address_config_path for name, chain in CHAINS.items()}


def _normalize_vm_message_terms(provision_terms: Any) -> Any | None:
    """Validate the VM envelope before any negotiation policy runs."""
    if provision_terms is None:
        return None
    raw = (
        provision_terms.model_dump()
        if hasattr(provision_terms, "model_dump")
        else provision_terms
    )
    from market_storefront.domain_runtime import get_market_domain_contract

    return get_market_domain_contract().codecs.message(raw)


def _reject_unsupported_resource_shape_request(
    vm_message_terms: Any,
    *,
    our_order_dict: dict[str, Any],
    listing_id: str,
) -> None:
    """Loudly reject a buyer-requested resource shape that differs from the listing.

    Seller negotiation policy currently prices only the listing's
    advertised shape. It has no way to price, size-check, or refuse an
    oversized ask against anything else. Silently admitting a
    non-matching request (or silently falling back to the listing's shape
    while telling the buyer nothing) risks giving away capacity the seller
    never agreed to price, or letting a buyer believe it negotiated a
    smaller/different deal than what actually gets built. A request that
    names a shape different from the listing's own is therefore refused
    outright, the same way ``listing_not_open``/``no_floor_price`` already
    refuse other requests this negotiation path cannot yet honor.

    A buyer that sends no ``compute_resource`` at all (the ordinary case
    today) is unaffected -- this only rejects a request that actively
    names a shape, and that shape disagrees with the listing on a
    dimension the listing itself declares.
    """
    if vm_message_terms is None:
        return
    requested = getattr(vm_message_terms, "compute_resource", None)
    if not requested:
        return
    listing_compute = extract_compute_from_order(our_order_dict)
    mismatched = {
        key: {"requested": requested[key], "listing": listing_compute.get(key)}
        for key in _DIMENSION_COMPUTE_KEYS
        if requested.get(key) is not None and requested[key] != listing_compute.get(key)
    }
    if mismatched:
        raise OfferUnfulfillableError(
            f"resource_shape_not_negotiable: {mismatched}",
            listing_id=listing_id,
        )


def _accepted_escrow_artifacts(
    *,
    proposal: EscrowProposal | dict[str, Any] | None,
    agreed_amount: int,
    duration_seconds: int,
    uses_scalar_amount: bool = True,
) -> dict[str, Any]:
    from market_storefront.utils.config import settings as _settings

    artifacts = accepted_escrow_artifacts_from_proposal(
        proposal=proposal,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        uses_scalar_amount=uses_scalar_amount,
        seller_wallet_address=None,
        chain_config_paths=_chain_config_paths(),
        heartbeat_interval_seconds=int(
            getattr(_settings, "heartbeat_interval_seconds", 60)
        ),
    )
    error = artifacts.pop("accepted_escrow_terms_error", None)
    if error:
        logger.debug("Could not materialize accepted escrow terms: %s", error)
    return artifacts


def _accepted_hosted_artifacts(
    *,
    selection: dict[str, Any],
    option: dict[str, Any],
    agreed_amount: int,
    buyer_address: str,
) -> dict[str, Any]:
    if agreed_amount < 1:
        raise OfferUnfulfillableError("hosted_amount_below_one_minor_unit")
    accepted = SettlementSelection.model_validate(selection)
    if accepted.option_id != option.get(
        "option_id"
    ) or accepted.mechanism != option.get("mechanism"):
        raise OfferUnfulfillableError("settlement_selection_not_exact")
    from market_storefront.utils.config import settings

    claimant_address = str(settings.wallet.address or "")
    if not claimant_address:
        raise OfferUnfulfillableError("seller_wallet_address_unavailable")
    params = dict(option.get("params") or {})
    condition = params.get("condition")
    if not isinstance(condition, dict):
        raise OfferUnfulfillableError("hosted_condition_unavailable")
    params["payer_address"] = buyer_address
    params["claimant_address"] = claimant_address
    plan = SettlementPlan(
        obligations=[
            SettlementObligation(
                payer="buyer",
                claimant="seller",
                amount=agreed_amount,
                asset=str(option.get("asset") or ""),
                expiration_unix=accepted.expiration_unix,
                conditions=[condition],
                mechanism=accepted.mechanism,
                params=params,
            )
        ]
    )
    return {
        "settlement_selection": accepted.model_dump(),
        "settlement_plan": plan.model_dump(),
    }


def _accepted_settlement_artifacts(
    *,
    proposal: EscrowProposal | dict[str, Any] | None,
    listing: dict[str, Any],
    agreed_amount: int,
    duration_seconds: int,
    uses_scalar_amount: bool,
    buyer_address: str,
) -> dict[str, Any]:
    proposal_dict = (
        proposal.model_dump() if isinstance(proposal, EscrowProposal) else proposal
    )
    if isinstance(proposal_dict, dict) and isinstance(
        proposal_dict.get("settlement_selection"), dict
    ):
        selection = SettlementSelection.model_validate(
            proposal_dict["settlement_selection"]
        )
        options = listing.get("settlement_options") or []
        if isinstance(options, str):
            options = json.loads(options)
        option = next(
            (
                item
                for item in options
                if isinstance(item, dict)
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
            buyer_address=buyer_address,
        )
    return _accepted_escrow_artifacts(
        proposal=proposal,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        uses_scalar_amount=uses_scalar_amount,
    )


def lookup_pool_policy_tags(
    sqlite_client: Any,
    listing_id: str | None,
) -> dict[str, Any]:
    """A listing's mapped pool's currently cached ``policy_tags``, or ``{}``.

    Two steps, not one opaque call: (1) resolve the listing's mapped
    ``pool_id`` from the existing ``derived_compute_listings`` table (the
    same table a mapped listing's ``site_id`` is already resolved from,
    no new column or table needed); (2) read that pool's ``policy_tags``
    live from the in-memory projection cache. ``policy_tags`` has no
    durable local persistence, so it can only ever be read fresh from the
    cache, never from a table -- see
    openspec/specs/storefront-publication/spec.md#domain-owned-publication-and-hold-hints.

    Always returns a plain ``dict`` (never ``None``), including on any
    resolution failure (unmapped listing, pool absent from the cache, its
    site's projection not yet loaded) -- ``capped_hold_seconds({}, ...)``
    already treats an empty/missing preference as "leave the caller's
    requested TTL unchanged," so callers need no separate None-handling
    branch, matching this function's own fail-open posture.
    """
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

        site_id = site_id_for_listing(sqlite_client.db_path, listing_id)
        pool_id = pool_id_for_listing(sqlite_client.db_path, listing_id)
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
        return {}
    except Exception:
        return {}


async def _place_capacity_hold(
    sqlite_client: Any,
    *,
    negotiation_id: str,
    listing_id: str | None,
    order_dict: dict[str, Any] | None,
    requested_start_utc: str | None = None,
    requested_duration_seconds: int | None = None,
) -> None:
    """Two-phase reserve: a TTL'd soft hold at terms acceptance.

    Always claims capacity from ``order_dict`` (the seller's own listing),
    never from anything a buyer requested during negotiation. This is
    intentional, not an oversight: seller negotiation policy currently
    prices only the listing's advertised shape, and a buyer requesting a
    different one is already rejected loudly at negotiation creation
    (``_reject_unsupported_resource_shape_request``), so by the time a hold
    is placed here, the only shape that could have survived negotiation is
    the listing's own. Do not "fix" this by threading a negotiated shape
    through without first building seller policy that can price it --
    doing so would let a buyer claim capacity the seller never agreed to
    give away.

    Closes the window where the escrow settles but the capacity is gone
    (the capacity design's reservation-protocol step 2) — settlement
    commits this hold instead of racing a fresh reserve. Best-effort by
    design: a hold that can't be placed leaves acceptance untouched
    (settlement then does the plain atomic reserve, exactly as before),
    and a hold whose deal never settles auto-lapses at the ledger.

    The requested TTL is capped by the listing's mapped pool's advisory
    ``max_reservation_hold_seconds`` policy tag, if any (see
    ``lookup_pool_policy_tags``) -- this changes nothing about what the
    site ledger actually enforces (it still enforces only the value this
    function sends), only what value this function chooses to send.
    """
    from core_storefront.stage_log import stage_event

    from market_storefront.utils.config import settings as _settings

    ttl = float(
        getattr(
            getattr(_settings, "capacity", None),
            "hold_ttl_seconds",
            0,
        )
        or 0
    )
    if ttl <= 0:
        return
    try:
        from domains.vms.listings.reconciler import site_id_for_listing
        from market_resource_pools.hints import capped_hold_seconds

        from market_storefront.services.capacity_client import build_capacity_client
        from market_storefront.services.vm_job_spec_service import (
            compute_capacity_claim_from_order,
        )

        claim = compute_capacity_claim_from_order(order_dict)
        capacity = build_capacity_client(lambda: sqlite_client)
        site_id = (
            site_id_for_listing(sqlite_client.db_path, listing_id)
            if listing_id
            else None
        )
        policy_tags = lookup_pool_policy_tags(sqlite_client, listing_id)
        ttl = capped_hold_seconds(ttl, policy_tags)
        held = await capacity.reserve(
            claim=claim or None,
            deal_ref={
                "listing_id": listing_id,
                "negotiation_id": negotiation_id,
            },
            ttl_seconds=ttl,
            lease_start_utc=requested_start_utc,
            lease_duration_seconds=requested_duration_seconds,
            site=site_id,
        )
    except Exception as exc:
        logger.warning(
            "[NEGOTIATION] Could not place capacity hold for %s: %s",
            negotiation_id,
            exc,
        )
        return
    if not held:
        stage_event(
            "negotiation",
            "capacity_hold_unavailable",
            negotiation_id=negotiation_id,
            listing_id=listing_id,
        )
        return
    await sqlite_client.save_capacity_hold(
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        capacity_reservation_id=str(held["capacity_reservation_id"]),
        payload=held,
        expires_at=held.get("hold_expires_at"),
    )
    stage_event(
        "negotiation",
        "capacity_hold_placed",
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        capacity_reservation_id=held.get("capacity_reservation_id"),
        resource_id=held.get("resource_id"),
        site=held.get("site"),
        hold_expires_at=held.get("hold_expires_at"),
    )


_LIVE_LISTING_STATUSES = LIVE_LISTING_STATUSES


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
    history = [
        NegotiationRound(
            round_number=0,
            sender="them",
            action="initial",
            proposal=their_proposal,
        )
    ]
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
    proposal: EscrowProposal | dict[str, Any] | None = None,
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
    optionally a requested compute shape. A requested shape that names a
    dimension differing from the listing's own shape is rejected outright
    (``OfferUnfulfillableError``, ``resource_shape_not_negotiable``) --
    seller negotiation policy cannot yet reason about a non-listing shape,
    so this path only ever admits the listing's own, fixed shape. Omitting
    ``compute_resource`` entirely negotiates normally against the listing's
    shape, exactly as before. ``proposal`` is the buyer's full
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
    vm_message_terms = _normalize_vm_message_terms(provision_terms)
    requested_duration_seconds = (
        vm_message_terms.duration_seconds if vm_message_terms is not None else None
    )
    requested_start_utc = (
        vm_message_terms.start_utc if vm_message_terms is not None else None
    )
    # Imports deferred so unit tests can patch the registry without paying for
    # the whole import graph.
    from core_storefront.stage_log import stage_event
    from domains.vms.listings.models import Listing

    # Check global pause flag and per-order pause flag before doing any work.
    from market_storefront.server import is_globally_paused

    if is_globally_paused():
        raise StorefrontPausedError("global")

    if await sqlite_client.is_listing_paused(listing_id=our_listing_id):
        raise StorefrontPausedError(f"order:{our_listing_id}")

    our_order_dict = await sqlite_client.load_listing(listing_id=our_listing_id)
    if not our_order_dict:
        raise ValueError(
            f"Order {our_listing_id} not found locally; seller has no matching listing"
        )

    listing_status = (our_order_dict.get("status") or "").strip()
    if listing_status not in _LIVE_LISTING_STATUSES:
        raise OfferUnfulfillableError(
            f"listing_not_open (status={listing_status!r})",
            listing_id=our_listing_id,
        )

    _reject_unsupported_resource_shape_request(
        vm_message_terms,
        our_order_dict=our_order_dict,
        listing_id=our_listing_id,
    )

    proposal_dict = (
        proposal.model_dump()
        if proposal is not None and hasattr(proposal, "model_dump")
        else proposal
    )

    our_order = Listing.model_validate(our_order_dict)

    history = [
        NegotiationRound(
            round_number=0,
            sender="them",
            action="initial",
            proposal=proposal_dict,
        )
    ]
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

    policy_intermediate = round_result.intermediate or {}
    accepted_selection = policy_intermediate.get("accepted_settlement_selection")
    accepted_option = policy_intermediate.get("accepted_settlement_option")
    accepted_proposal_dict = policy_intermediate.get("accepted_escrow_proposal")
    accepted_proposal = (
        EscrowProposal.model_validate(accepted_proposal_dict)
        if isinstance(accepted_proposal_dict, dict)
        else proposal
        if isinstance(proposal, EscrowProposal)
        else None
    )
    uses_scalar_amount = bool(policy_intermediate.get("uses_scalar_amount", True))
    their_amount = _amount_from_proposal(proposal_dict)
    if their_amount is None:
        their_amount = 0
    their_amount = int(their_amount)

    neg_id = "neg_" + uuid.uuid4().hex

    await _create_sync_negotiation_thread(
        negotiation_id=neg_id,
        our_listing_id=our_listing_id,
        their_listing_id="",  # buyer has no listing; column kept for symmetry
        our_agent_id=our_base_url,
        their_agent_id=their_agent_url,
        our_initial_amount=our_amount,
        our_strategy=strategy,
        requested_duration_seconds=requested_duration_seconds,
        requested_start_utc=requested_start_utc,
        buyer_escrow_proposal=(
            accepted_proposal.model_dump()
            if accepted_proposal is not None
            else proposal_dict
        ),
        provision_terms=(
            vm_message_terms.model_dump(mode="json")
            if vm_message_terms is not None
            else None
        ),
        opening_sender=their_agent_url or buyer_address,
        opening_amount=their_amount,
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
            agreed_start_utc=requested_start_utc,
        )
        await _place_capacity_hold(
            sqlite_client,
            negotiation_id=neg_id,
            listing_id=our_listing_id,
            order_dict=our_order_dict,
            requested_start_utc=requested_start_utc,
            requested_duration_seconds=int(agreed_duration_seconds),
        )
    stage_event(
        "negotiation",
        "round_decided",
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
        artifacts = _accepted_escrow_artifacts(
            proposal=accepted_proposal,
            agreed_amount=int(
                agreed_amount if decision.action == "accept" else our_amount
            ),
            duration_seconds=int(
                agreed_duration_seconds
                if decision.action == "accept"
                else (
                    requested_duration_seconds
                    or our_order_dict.get("max_duration_seconds")
                    or 3600
                )
            ),
            uses_scalar_amount=uses_scalar_amount,
        )
        if decision.action == "accept":
            response.update(artifacts)
        else:
            response["accepted_escrow_proposal"] = artifacts["accepted_escrow_proposal"]
    elif isinstance(accepted_selection, dict) and isinstance(accepted_option, dict):
        artifacts = _accepted_hosted_artifacts(
            selection=accepted_selection,
            option=accepted_option,
            agreed_amount=int(
                agreed_amount if decision.action == "accept" else our_amount
            ),
            buyer_address=buyer_address,
        )
        response["settlement_selection"] = artifacts["settlement_selection"]
        if decision.action == "accept":
            response["settlement_plan"] = artifacts["settlement_plan"]
            await sqlite_client.commit_settlement_plan(
                negotiation_id=neg_id,
                settlement_plan=artifacts["settlement_plan"],
            )
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
    from core_storefront.stage_log import stage_event
    from domains.vms.listings import determine_strategy_from_order
    from domains.vms.listings.models import Listing

    thread = await sqlite_client.load_negotiation_thread_row(negotiation_id=neg_id)
    if not thread:
        raise ValueError(f"Unknown negotiation {neg_id}")
    if thread.get("terminal_state"):
        raise ValueError(
            f"Negotiation {neg_id} is already in terminal state "
            f"{thread.get('terminal_state')!r}",
        )

    our_listing_id = thread.get("our_listing_id")
    our_order_dict = (
        await sqlite_client.load_listing(listing_id=our_listing_id)
        if our_listing_id
        else None
    )
    if not our_order_dict:
        raise ValueError(f"Seller's order {our_listing_id} is gone from local DB")
    our_order = Listing.model_validate(our_order_dict)
    strategy = determine_strategy_from_order(our_order)
    requested_duration_seconds = thread.get("requested_duration_seconds")
    requested_start_utc = thread.get("requested_start_utc")
    buyer_pinned_proposal = _coerce_pinned_proposal(thread.get("buyer_escrow_proposal"))
    pinned_fields = (
        buyer_pinned_proposal.get("fields")
        if isinstance(buyer_pinned_proposal, dict)
        else None
    )
    uses_scalar_amount = isinstance(pinned_fields, dict) and "amount" in pinned_fields
    our_amount = (
        _seller_reference_amount(our_order_dict, requested_duration_seconds)
        if uses_scalar_amount
        else 0
    )

    messages = await sqlite_client.load_negotiation_thread(negotiation_id=neg_id)
    our_previous_counters = [
        m
        for m in messages
        if m.get("action_taken") == "counter_offer"
        and m.get("proposed_price") is not None
        and m.get("sender") != buyer_address
    ]

    # Buyer-declared action short-circuits (accept / exit). No policy call.
    if buyer_action == "accept":
        last_seller_amount = next(
            (
                int(Decimal(str(m["proposed_price"])))
                for m in reversed(messages)
                if m.get("action_taken") == "counter_offer"
                and m.get("sender") != buyer_address
            ),
            our_amount,
        )
        await _record_buyer_accept_message(
            negotiation_id=neg_id,
            sender=buyer_address,
            our_amount=our_amount,
            accepted_amount=last_seller_amount,
        )
        agreed_duration_seconds = (
            requested_duration_seconds
            or our_order_dict.get("max_duration_seconds")
            or 3600
        )
        await sqlite_client.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=int(last_seller_amount),
            agreed_duration_seconds=int(agreed_duration_seconds),
            agreed_start_utc=requested_start_utc,
        )
        await _place_capacity_hold(
            sqlite_client,
            negotiation_id=neg_id,
            listing_id=our_listing_id,
            order_dict=our_order_dict,
            requested_start_utc=requested_start_utc,
            requested_duration_seconds=int(agreed_duration_seconds),
        )
        stage_event(
            "negotiation",
            "accepted",
            negotiation_id=neg_id,
            agreed_amount=last_seller_amount,
            our_initial_amount=our_amount,
        )
        response = {
            "action": "accept",
        }
        artifacts = _accepted_settlement_artifacts(
            proposal=buyer_pinned_proposal,
            listing=our_order_dict,
            agreed_amount=int(last_seller_amount),
            duration_seconds=int(agreed_duration_seconds),
            uses_scalar_amount=uses_scalar_amount,
            buyer_address=buyer_address,
        )
        response.update(artifacts)
        settlement_plan = artifacts.get("settlement_plan")
        if isinstance(settlement_plan, dict):
            await sqlite_client.commit_settlement_plan(
                negotiation_id=neg_id,
                settlement_plan=settlement_plan,
            )
        return response

    if buyer_action == "exit":
        await _record_buyer_exit_message(
            negotiation_id=neg_id,
            sender=buyer_address,
            our_amount=our_amount,
        )
        stage_event(
            "negotiation",
            "exited",
            negotiation_id=neg_id,
            reason=buyer_reason or "buyer_exit",
        )
        return {"action": "exit", "reason": "buyer_exit"}

    if buyer_action != "counter":
        raise ValueError(f"Unsupported buyer action {buyer_action!r}")

    from market_storefront.utils.config import BASE_URL_OVERRIDE

    our_sender = BASE_URL_OVERRIDE or "seller"
    history = _history_from_messages(
        messages,
        our_sender,
        buyer_pinned_proposal=buyer_pinned_proposal,
    )
    # The buyer's just-recorded counter isn't in `messages` (loaded before
    # the txn) — append it so the chain sees it as their proposal.
    history.append(
        NegotiationRound(
            round_number=len(history),
            sender="them",
            action="counter",
            proposal=buyer_proposal or buyer_pinned_proposal,
        )
    )
    round_hook = seller_round_hook or _default_seller_round_hook(sqlite_client)
    round_result = await round_hook(
        listing=our_order,
        history=history,
        requested_duration_seconds=requested_duration_seconds,
        strategy_label=strategy,
    )
    policy_intermediate = round_result.intermediate or {}
    uses_scalar_amount = bool(
        policy_intermediate.get("uses_scalar_amount", uses_scalar_amount),
    )
    fallback_buyer_amount = _amount_from_proposal(buyer_proposal)
    buyer_amount = int(
        policy_intermediate.get(
            "buyer_amount",
            fallback_buyer_amount if fallback_buyer_amount is not None else 0,
        ),
    )
    buyer_counter_proposal = policy_intermediate.get("buyer_counter_proposal")
    history[-1] = NegotiationRound(
        round_number=history[-1].round_number,
        sender="them",
        action="counter",
        proposal=(
            buyer_counter_proposal
            if isinstance(buyer_counter_proposal, dict)
            else history[-1].proposal
        ),
    )
    our_amount = round_result.our_amount
    await _record_buyer_counter_message(
        negotiation_id=neg_id,
        sender=buyer_address,
        our_amount=our_amount,
        counter_amount=buyer_amount,
    )
    decision = round_result.decision
    await _record_seller_decision(
        neg_id=neg_id,
        our_amount=our_amount,
        their_amount=buyer_amount,
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
            agreed_start_utc=requested_start_utc,
        )
        await _place_capacity_hold(
            sqlite_client,
            negotiation_id=neg_id,
            listing_id=our_listing_id,
            order_dict=our_order_dict,
            requested_start_utc=requested_start_utc,
            requested_duration_seconds=int(agreed_duration_seconds),
        )
    stage_event(
        "negotiation",
        "round_decided",
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
        artifacts = _accepted_settlement_artifacts(
            proposal=buyer_pinned_proposal,
            listing=our_order_dict,
            agreed_amount=(
                int(decision_amount) if decision_amount is not None else int(our_amount)
            ),
            duration_seconds=int(
                requested_duration_seconds
                or our_order_dict.get("max_duration_seconds")
                or 3600
            ),
            uses_scalar_amount=uses_scalar_amount,
            buyer_address=buyer_address,
        )
        response.update(artifacts)
        settlement_plan = artifacts.get("settlement_plan")
        if isinstance(settlement_plan, dict):
            await sqlite_client.commit_settlement_plan(
                negotiation_id=neg_id,
                settlement_plan=settlement_plan,
            )
    return response


async def _record_seller_decision(
    *,
    neg_id: str,
    our_amount: int,
    their_amount: int,
    decision: NegotiationDecision,
) -> None:
    """Persist the seller's decision using VM proposal amount extraction."""
    from market_storefront.utils.config import BASE_URL_OVERRIDE

    sender = BASE_URL_OVERRIDE or "seller"
    decision_amount = _amount_from_proposal(decision.proposal)
    await _record_seller_decision_message(
        negotiation_id=neg_id,
        sender=sender,
        our_amount=our_amount,
        their_amount=their_amount,
        decision=decision,
        decision_amount=(int(decision_amount) if decision_amount is not None else None),
    )
