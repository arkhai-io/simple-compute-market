"""Sequential buyer orchestrator — the "buyer is a pure client" realization.

    result = run_buy(config, constraints, negotiate=..., settle=...)

composes three closed-function stages in order:

    1. discover         — registry query for matching seller orders
    2. negotiate        — aggregation + per-match negotiation hook
    3. settle           — create escrow, submit settlement, poll terminal state

Nothing here runs a server or handles inbound HTTP. The buyer is a
client that drives the deal end to end. Every HTTP call to the seller
is signed by the buyer's wallet. The current compute buyer still adapts
legacy hooks such as `build_escrow_proposal`, `derive_prices`, and
`create_escrow` into the top-level `negotiate` / `settle` surface.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from market_alkahest.schemas import (
    EscrowTerms,
    EscrowProposal,
    accepted_recipient_address,
)
from market_core.buyer import (
    DEFAULT_HTTP_TIMEOUT,
    BuyConfig,
    BuyConstraints,
    BuyResult,
    NegotiationResult,
    NegotiateFn,
    SettleFn,
    fetch_listing_dict,
    fetch_listing_dict_multi,
    query_registry_for_matches,
    query_registry_for_matches_multi,
    run_buy,
)
from market_core.schemas import ProvisionTerms
from domains.vms.settlement import BuildEscrowTermsFn, CreateEscrowFn

from .buyer_client import (
    NegotiationOutcome,
    negotiate_with_seller,
    _sign,
)


DEFAULT_SETTLEMENT_POLL_INTERVAL = 5.0
DEFAULT_SETTLEMENT_TIMEOUT = 600.0  # 10 minutes


# Factory: build the EscrowProposal for a specific candidate listing.
# Returns None when the listing carries no accepted_escrows entry
# compatible with the buyer's chain + filters — the orchestrator then
# skips that candidate. The caller closes over chain config + selection
# rules; the orchestrator just invokes per match.
BuildEscrowProposalFn = Callable[[dict[str, Any]], Optional["EscrowProposal"]]


def extract_seller_min_price(listing: dict[str, Any]) -> Optional[float]:
    """Pull the seller's per-hour floor out of a registry listing dict.

    Reads the primary rate on ``accepted_escrows[0]`` — the per-hour
    token rate advertised on the seller's first accepted escrow tuple.
    Returns ``None`` for hidden-reserve listings (empty ``rates``).
    """
    from market_alkahest.schemas import primary_rate_value

    accepted = listing.get("accepted_escrows") or []
    if isinstance(accepted, str):
        try:
            accepted = json.loads(accepted)
        except (ValueError, TypeError):
            return None
    if not isinstance(accepted, list) or not accepted:
        return None
    first = accepted[0]
    if not isinstance(first, dict):
        return None
    amount = primary_rate_value(first)
    return float(amount) if amount is not None else None


# ---------------------------------------------------------------------------
# Settlement: signed POST + polling GET
# ---------------------------------------------------------------------------


# Substrings in the seller's 400 detail that indicate the seller couldn't
# yet read the just-created escrow from the chain — public RPC nodes
# (Infura/Alchemy) frequently lag the tx by 5-15s. Retrying the POST
# resolves it without any user action.
_PROPAGATION_LAG_HINTS = (
    "buffer overrun",
    "ABI decoding",
    "Failed to read escrow",
)


def _looks_like_propagation_lag(exc: RuntimeError) -> bool:
    msg = str(exc)
    if "HTTP 400" not in msg:
        return False
    return any(hint in msg for hint in _PROPAGATION_LAG_HINTS)


def submit_settlement(
    *,
    seller_url: str,
    escrow_uid: str,
    negotiation_id: str,
    ssh_public_key: str,
    buyer_address: str,
    buyer_private_key: str,
    chain_name: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    max_attempts: int = 6,
    retry_backoff: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """POST /api/v1/settle/{escrow_uid} with signed body. Returns the initial job state.

    Retries on transient propagation-lag 400s — the seller's
    ``verify_escrow_for_settlement`` reads the escrow from chain, and
    public RPC nodes can lag the just-mined create-escrow tx by 5-15s,
    surfacing as ``"buffer overrun while deserializing"`` / "Failed to
    read escrow" detail. Non-matching errors bubble up immediately.

    ``chain_name`` tells the seller which configured ``[chains.<name>]``
    entry to dispatch the on-chain verify against — required since the
    seller may serve multiple chains.
    """
    url = seller_url.rstrip("/") + f"/api/v1/settle/{escrow_uid}"
    body = {
        "negotiation_id": negotiation_id,
        "ssh_public_key": ssh_public_key,
        "buyer_address": buyer_address,
        "chain_name": chain_name,
    }
    last_exc: RuntimeError | None = None
    for attempt in range(1, max_attempts + 1):
        sig, ts = _sign(f"settle_escrow:{escrow_uid}", buyer_private_key)
        try:
            return _signed_json(
                url, body, sig, ts, method="POST", timeout=timeout,
                identity_identifier=buyer_address,
            )
        except RuntimeError as exc:
            last_exc = exc
            if not _looks_like_propagation_lag(exc) or attempt == max_attempts:
                raise
            sleep(retry_backoff)
    assert last_exc is not None  # unreachable: loop either returns or raises
    raise last_exc


def poll_settlement_status(
    *,
    seller_url: str,
    escrow_uid: str,
    buyer_address: str,
    buyer_private_key: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> dict[str, Any]:
    """GET /api/v1/settle/{escrow_uid}/status with signed query params + headers."""
    sig, ts = _sign(f"settle_status:{escrow_uid}", buyer_private_key)
    url = (
        seller_url.rstrip("/")
        + f"/api/v1/settle/{escrow_uid}/status?buyer_address={buyer_address}"
    )
    return _signed_json(
        url, body=None, signature=sig, timestamp=ts,
        method="GET", timeout=timeout,
        identity_identifier=buyer_address,
    )


def _signed_json(
    url: str,
    body: dict[str, Any] | None,
    signature: str,
    timestamp: int,
    *,
    method: str,
    timeout: float,
    identity_scheme: str = "eip191",
    identity_identifier: str | None = None,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "X-Signature": signature,
        "X-Timestamp": str(timestamp),
        "X-Identity-Scheme": identity_scheme,
    }
    if identity_identifier:
        headers["X-Identity"] = identity_identifier
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(
            f"{method} {url} -> HTTP {exc.code}: {detail[:300]}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc
    return json.loads(text) if text else {}


def wait_for_settlement(
    *,
    seller_url: str,
    escrow_uid: str,
    buyer_address: str,
    buyer_private_key: str,
    poll_interval: float = DEFAULT_SETTLEMENT_POLL_INTERVAL,
    total_timeout: float = DEFAULT_SETTLEMENT_TIMEOUT,
    on_poll: Optional[Callable[[int, dict], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Poll /settle/{uid}/status until status is 'ready' or 'failed'.

    Raises TimeoutError if no terminal status arrives before
    `total_timeout`. `sleep` is injected so tests don't actually wait.
    """
    deadline = time.monotonic() + total_timeout
    attempts = 0
    while True:
        attempts += 1
        status_body = poll_settlement_status(
            seller_url=seller_url,
            escrow_uid=escrow_uid,
            buyer_address=buyer_address,
            buyer_private_key=buyer_private_key,
        )
        if on_poll:
            on_poll(attempts, status_body)
        if status_body.get("status") in ("ready", "failed"):
            return status_body
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Settlement did not reach terminal status within "
                f"{total_timeout}s (last status={status_body.get('status')!r})"
            )
        sleep(poll_interval)


# ---------------------------------------------------------------------------
# Escrow creation: injected hook (real impl lives in escrow_client.py)
# ---------------------------------------------------------------------------


@dataclass
class AgreedTerms:
    """Human-facing summary of a finalized negotiation.

    Passed to the optional ``confirm_settlement`` callback so the user
    can review what they're about to commit to before any chain write.
    Not used by ``create_escrow`` itself — that hook reads
    ``list[EscrowTerms]`` built by ``build_escrow_terms``.
    """
    seller_url: str
    seller_wallet_address: str
    negotiation_id: str
    listing_id: str
    agreed_amount: int                # base units, absolute payment total
    duration_seconds: int           # buyer's lease ask (negotiation init)


def make_legacy_negotiate_hook(
    *,
    config: BuyConfig,
    constraints: BuyConstraints,
    provision: ProvisionTerms,
    build_escrow_proposal: BuildEscrowProposalFn,
    max_negotiation_rounds: int,
    derive_prices: Optional[Callable[[dict[str, Any]], tuple[int, int]]],
    chain: Optional[list[Any]],
) -> NegotiateFn:
    """Build the current compute-instantiated negotiate hook.

    The returned hook absorbs the old fine-grained negotiation injections:
    accepted-escrow proposal construction, per-listing price derivation,
    buyer policy chain, and aggregation policy execution.
    """

    def _hook(
        matches: list[dict[str, Any]],
        on_event: Callable[[str, dict], None],
    ) -> NegotiationResult:
        return _legacy_negotiate_matches(
            matches=matches,
            config=config,
            constraints=constraints,
            provision=provision,
            build_escrow_proposal=build_escrow_proposal,
            max_negotiation_rounds=max_negotiation_rounds,
            derive_prices=derive_prices,
            chain=chain,
            on_event=on_event,
        )

    return _hook


def _legacy_negotiate_matches(
    *,
    matches: list[dict[str, Any]],
    config: BuyConfig,
    constraints: BuyConstraints,
    provision: ProvisionTerms,
    build_escrow_proposal: BuildEscrowProposalFn,
    max_negotiation_rounds: int,
    derive_prices: Optional[Callable[[dict[str, Any]], tuple[int, int]]],
    chain: Optional[list[Any]],
    on_event: Callable[[str, dict], None],
) -> NegotiationResult:
    attempts: list[dict[str, Any]] = []

    async def _negotiate(match: dict[str, Any]) -> NegotiationOutcome:
        seller_url = match.get("storefront_url") or match.get("seller") or match.get("seller_url") or ""
        listing_id = match.get("listing_id") or match.get("order_id") or ""
        if not seller_url or not listing_id:
            attempts.append({"match": match, "error": "missing_seller_url_or_listing_id"})
            # Translate to a synthetic outcome so the policy can iterate
            # past it — same shape as a seller-side exit.
            return NegotiationOutcome(
                status="exited",
                negotiation_id=None,
                reason="missing_seller_url_or_listing_id",
            )

        # Per-candidate escrow proposal: token, escrow contract, and chain
        # come from the listing's accepted_escrows. None ⇒ no entry on
        # the buyer's chain (or no entry matching --token-contract).
        escrow_proposal = build_escrow_proposal(match)
        if escrow_proposal is None:
            attempts.append({
                "seller_url": seller_url,
                "listing_id": listing_id,
                "error": "no_compatible_accepted_escrow",
            })
            return NegotiationOutcome(
                status="exited",
                negotiation_id=None,
                reason="no_compatible_accepted_escrow",
            )

        neg_ctx: dict[str, Any] = {"listing_id": listing_id}

        def _emit_neg(stage: str, **fields: Any) -> None:
            on_event(stage, {**neg_ctx, **fields})

        _emit_neg("negotiation_started", seller_url=seller_url)

        def _on_round(round_idx: int, our_msg: dict, their_reply: dict) -> None:
            if "negotiation_id" not in neg_ctx:
                nid = their_reply.get("negotiation_id")
                if nid:
                    neg_ctx["negotiation_id"] = nid
            _emit_neg(
                "negotiation_round",
                round=round_idx,
                our_message=our_msg,
                their_reply=their_reply,
            )

        if derive_prices is not None:
            try:
                initial_price, max_price = derive_prices(match)
            except Exception as exc:
                _emit_neg("negotiation_failed", error=f"price_derivation: {exc}")
                attempts.append({
                    "seller_url": seller_url,
                    "listing_id": listing_id,
                    "error": f"price_derivation: {exc}",
                })
                return NegotiationOutcome(
                    status="exited",
                    negotiation_id=None,
                    reason=f"price_derivation: {exc}",
                )
        else:
            if constraints.initial_price is None or constraints.max_price is None:
                _emit_neg(
                    "negotiation_failed",
                    error="missing_prices_no_derive_prices_callback",
                )
                attempts.append({
                    "seller_url": seller_url,
                    "listing_id": listing_id,
                    "error": (
                        "BuyConstraints.initial_price and max_price are None "
                        "but no derive_prices callback was provided"
                    ),
                })
                return NegotiationOutcome(
                    status="exited",
                    negotiation_id=None,
                    reason="missing_prices_no_derive_prices_callback",
                )
            initial_price = constraints.initial_price
            max_price = constraints.max_price

        # negotiate_with_seller is sync (blocking urllib); to_thread lets
        # policies run multiple negotiations in parallel via asyncio.gather.
        try:
            outcome = await asyncio.to_thread(
                negotiate_with_seller,
                seller_url=seller_url,
                buyer_address=config.buyer_address,
                buyer_private_key=config.buyer_private_key,
                listing_id=listing_id,
                initial_price=initial_price,
                max_price=max_price,
                provision_terms=provision,
                escrow_proposal=escrow_proposal,
                max_rounds=max_negotiation_rounds,
                on_round=_on_round,
                chain=chain,
            )
        except RuntimeError as exc:
            _emit_neg("negotiation_failed", error=f"http_error: {exc}")
            attempts.append({
                "seller_url": seller_url,
                "listing_id": listing_id,
                "error": f"negotiation_http_error: {exc}",
            })
            # Reraise so policies that don't catch see the actual error —
            # surface state, don't paper over network failures.
            raise

        if outcome.negotiation_id and "negotiation_id" not in neg_ctx:
            neg_ctx["negotiation_id"] = outcome.negotiation_id

        # Note: the buyer-side ``buyer_escrow_shape_guard`` middleware
        # (default in the buyer's chain) handles seller-pin-mutation
        # vetoes per round — no separate post-agreement audit is needed.

        _emit_neg(
            "negotiation_completed",
            seller_url=seller_url,
            status=outcome.status,
            agreed_amount=outcome.agreed_amount,
            rounds=outcome.rounds,
            reason=outcome.reason,
            accepted_escrow_proposal=(
                outcome.accepted_escrow_proposal.model_dump()
                if outcome.accepted_escrow_proposal is not None
                else None
            ),
            accepted_escrow_terms=(
                [term.model_dump() for term in outcome.accepted_escrow_terms]
                if outcome.accepted_escrow_terms is not None
                else None
            ),
            accepted_provision_terms=(
                outcome.accepted_provision_terms.model_dump()
                if outcome.accepted_provision_terms is not None
                else None
            ),
        )
        attempts.append({
            "seller_url": seller_url,
            "listing_id": listing_id,
            "outcome": outcome.to_dict(),
        })
        return outcome

    from .aggregation import load_aggregation_policy
    policy = load_aggregation_policy(config.aggregation_policy)

    try:
        selected = asyncio.run(policy(matches, _negotiate))
    except RuntimeError as exc:
        return NegotiationResult(
            attempts=attempts,
            reason=f"policy_error: {exc}",
        )

    if selected is None:
        return NegotiationResult(attempts=attempts)

    match, outcome = selected
    return NegotiationResult(match=match, outcome=outcome, attempts=attempts)


def make_legacy_settle_hook(
    *,
    config: "BuyConfig",
    provision: ProvisionTerms,
    build_escrow_terms: BuildEscrowTermsFn,
    create_escrow: CreateEscrowFn,
    confirm_settlement: Optional[Callable[["AgreedTerms", dict[str, Any]], bool]],
    settlement_poll_interval: float,
    settlement_total_timeout: float,
    sleep: Callable[[float], None],
) -> SettleFn:
    """Build the current compute-instantiated settlement hook."""

    def _hook(
        negotiation: NegotiationResult,
        on_event: Callable[[str, dict], None],
    ) -> BuyResult:
        if negotiation.match is None or negotiation.outcome is None:
            raise ValueError("settle hook received no selected negotiation")
        return _settle_one(
            match=negotiation.match,
            outcome=negotiation.outcome,
            config=config,
            provision=provision,
            build_escrow_terms=build_escrow_terms,
            create_escrow=create_escrow,
            confirm_settlement=confirm_settlement,
            settlement_poll_interval=settlement_poll_interval,
            settlement_total_timeout=settlement_total_timeout,
            sleep=sleep,
            on_event=on_event,
            attempts=negotiation.attempts,
        )

    return _hook


def _settle_one(
    *,
    match: dict[str, Any],
    outcome: NegotiationOutcome,
    config: "BuyConfig",
    provision: ProvisionTerms,
    build_escrow_terms: BuildEscrowTermsFn,
    create_escrow: CreateEscrowFn,
    confirm_settlement: Optional[Callable[["AgreedTerms", dict[str, Any]], bool]],
    settlement_poll_interval: float,
    settlement_total_timeout: float,
    sleep: Callable[[float], None],
    on_event: Callable[[str, dict], None],
    attempts: list[dict[str, Any]],
) -> "BuyResult":
    """Drive escrow → submit → poll for the policy's chosen winner.

    Lifted out of the run_buy loop so the negotiate-vs-settle split is
    structural, not just visual. Inputs are the policy's
    ``(match, outcome)`` plus the orchestrator's settlement deps.
    """
    seller_url = match.get("storefront_url") or match.get("seller") or match.get("seller_url") or ""
    listing_id = match.get("listing_id") or match.get("order_id") or ""

    # Materialize the negotiated outcome into on-chain-ready EscrowTerms,
    # then submit. The seller echoed the accepted proposal back in the
    # negotiation response — using *that* (not the buyer's locally-built
    # proposal) means any drift between sides surfaces as a runtime
    # error here rather than silently mismatching on-chain.
    accepted_proposal = outcome.accepted_escrow_proposal
    if accepted_proposal is None:
        on_event(
            "escrow_create_failed",
            {"error": "seller did not echo accepted_escrow_proposal"},
        )
        return BuyResult(
            status="exited",
            negotiation_id=outcome.negotiation_id,
            seller_url=seller_url,
            agreed_amount=outcome.agreed_amount,
            reason="missing_accepted_escrow_proposal",
            rounds=outcome.rounds,
            attempts=attempts,
        )

    escrow_recipient = accepted_recipient_address(accepted_proposal)

    terms = AgreedTerms(
        seller_url=seller_url,
        seller_wallet_address=escrow_recipient or "",
        negotiation_id=outcome.negotiation_id or "",
        listing_id=listing_id,
        agreed_amount=outcome.agreed_amount or 0,
        duration_seconds=provision.duration_seconds,
    )

    if confirm_settlement is not None:
        try:
            approved = confirm_settlement(terms, match)
        except Exception as exc:
            on_event("settlement_confirm_failed", {"error": str(exc)})
            return BuyResult(
                status="exited",
                negotiation_id=outcome.negotiation_id,
                seller_url=seller_url,
                agreed_amount=outcome.agreed_amount,
                reason=f"confirm_settlement_callback_raised: {exc}",
                rounds=outcome.rounds,
                attempts=attempts,
            )
        if not approved:
            on_event("settlement_declined", {"terms": terms.__dict__})
            return BuyResult(
                status="exited",
                negotiation_id=outcome.negotiation_id,
                seller_url=seller_url,
                agreed_amount=outcome.agreed_amount,
                reason="user_declined",
                rounds=outcome.rounds,
                attempts=attempts,
            )

    if outcome.accepted_escrow_terms is not None:
        escrows = outcome.accepted_escrow_terms
    else:
        try:
            escrows = build_escrow_terms(
                accepted_proposal, terms.seller_wallet_address,
                terms.agreed_amount, terms.duration_seconds,
            )
        except Exception as exc:
            on_event("escrow_create_failed", {"error": f"build_escrow_terms: {exc}"})
            return BuyResult(
                status="exited",
                negotiation_id=outcome.negotiation_id,
                seller_url=seller_url,
                agreed_amount=outcome.agreed_amount,
                reason=f"build_escrow_terms_failed: {exc}",
                rounds=outcome.rounds,
                attempts=attempts,
            )

    on_event(
        "escrow_create_start",
        {"terms": terms.__dict__, "escrows": [e.model_dump() for e in escrows]},
    )
    try:
        escrow_uids = create_escrow(escrows)
    except Exception as exc:
        on_event("escrow_create_failed", {"error": str(exc)})
        return BuyResult(
            status="exited",
            negotiation_id=outcome.negotiation_id,
            seller_url=seller_url,
            agreed_amount=outcome.agreed_amount,
            reason=f"escrow_create_failed: {exc}",
            rounds=outcome.rounds,
            attempts=attempts,
        )

    # The hook returns uids for buyer-made entries in input order. The
    # primary payment escrow is the first one; that's what carries
    # through to /settle and the seller's verification.
    buyer_escrows = [e for e in escrows if e.maker == "buyer"]
    if len(escrow_uids) != len(buyer_escrows):
        on_event(
            "escrow_create_failed",
            {"error": f"create_escrow returned {len(escrow_uids)} uids, "
                      f"expected {len(buyer_escrows)} for buyer-made entries"},
        )
        return BuyResult(
            status="exited",
            negotiation_id=outcome.negotiation_id,
            seller_url=seller_url,
            agreed_amount=outcome.agreed_amount,
            reason="create_escrow_uid_count_mismatch",
            rounds=outcome.rounds,
            attempts=attempts,
        )
    if not escrow_uids:
        on_event("escrow_create_failed", {"error": "no buyer-made escrows in list"})
        return BuyResult(
            status="exited",
            negotiation_id=outcome.negotiation_id,
            seller_url=seller_url,
            agreed_amount=outcome.agreed_amount,
            reason="no_buyer_made_escrow",
            rounds=outcome.rounds,
            attempts=attempts,
        )
    escrow_uid = escrow_uids[0]
    on_event(
        "escrow_created",
        {
            "escrow_uid": escrow_uid,
            "all_uids": escrow_uids,
            "chain_name": accepted_proposal.chain_name,
        },
    )

    submit_settlement(
        seller_url=seller_url,
        escrow_uid=escrow_uid,
        negotiation_id=outcome.negotiation_id or "",
        ssh_public_key=provision.ssh_public_key,
        buyer_address=config.buyer_address,
        buyer_private_key=config.buyer_private_key,
        chain_name=accepted_proposal.chain_name,
    )
    on_event("settlement_submitted", {"escrow_uid": escrow_uid})

    try:
        final = wait_for_settlement(
            seller_url=seller_url,
            escrow_uid=escrow_uid,
            buyer_address=config.buyer_address,
            buyer_private_key=config.buyer_private_key,
            poll_interval=settlement_poll_interval,
            total_timeout=settlement_total_timeout,
            on_poll=lambda i, body: on_event("settlement_poll",
                                              {"attempt": i, "body": body}),
            sleep=sleep,
        )
    except TimeoutError as exc:
        return BuyResult(
            status="timeout",
            negotiation_id=outcome.negotiation_id,
            seller_url=seller_url,
            agreed_amount=outcome.agreed_amount,
            escrow_uid=escrow_uid,
            reason=str(exc),
            rounds=outcome.rounds,
            attempts=attempts,
        )

    if final.get("status") == "ready":
        return BuyResult(
            status="ready",
            negotiation_id=outcome.negotiation_id,
            seller_url=seller_url,
            agreed_amount=outcome.agreed_amount,
            escrow_uid=escrow_uid,
            fulfillment_uid=final.get("fulfillment_uid"),
            connection_details=final.get("connection_details"),
            tenant_credentials=final.get("tenant_credentials"),
            rounds=outcome.rounds,
            attempts=attempts,
        )
    return BuyResult(
        status="failed",
        negotiation_id=outcome.negotiation_id,
        seller_url=seller_url,
        agreed_amount=outcome.agreed_amount,
        escrow_uid=escrow_uid,
        reason=final.get("reason") or "provisioning_failed",
        rounds=outcome.rounds,
        attempts=attempts,
    )
