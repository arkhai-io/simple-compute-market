"""Sequential buyer orchestration stages over injected domain hooks.

    result = run_buy(config, constraints, negotiate=..., settle=...)

composes three closed-function stages in order:

    1. discover         — registry query for matching seller orders
    2. negotiate        — aggregation + per-match negotiation hook
    3. settle           — create escrow, submit settlement, poll terminal state

Nothing here runs a server or handles inbound HTTP. The buyer is a
client that drives the deal end to end. Seller HTTP calls use the buyer's
injected marketplace signer. Schema plugins adapt their hooks
(`build_escrow_proposal`, `derive_prices`, `create_escrow`, the unit
count, the provisioning payload) into the top-level `negotiate` /
`settle` surface through the factories here.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from market_core.schemas import SettlementSelection
from market_identity import Identity, Signer, TrustedIdentitySet

from core_buyer.orchestrator import (
    DEFAULT_HTTP_TIMEOUT,
    BuyConfig,
    BuyConstraints,
    BuyResult,
    NegotiateFn,
    NegotiationResult,
    SettleFn,
    fetch_listing_dict,
)

from .negotiation_client import (
    NegotiationOutcome,
    _authenticated_json,
    negotiate_with_seller,
)

DEFAULT_SETTLEMENT_POLL_INTERVAL = 5.0
DEFAULT_SETTLEMENT_TIMEOUT = 600.0  # 10 minutes


# Factory: choose one settlement carrier for a candidate listing. The
# concrete schema plugin returns either an opaque mechanism proposal or a
# mechanism-neutral settlement selection. None skips the candidate.
BuildEscrowProposalFn = Callable[[dict[str, Any]], Any | None]
EncodeEscrowProposalFn = Callable[[Any], dict[str, Any]]
DecodeOpaquePayloadFn = Callable[[dict[str, Any]], Any]
BuildEscrowTermsFn = Callable[[Any, str | None, int, int], list[Any]]
CreateEscrowFn = Callable[[list[Any]], list[str]]
SettlementRecipientFn = Callable[[Any], str | None]
BuildSettlementPayloadFn = Callable[[str, Any], dict[str, Any]]


def _opaque_payload_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    raise TypeError("opaque settlement payload is not dictionary-serializable")


def _seller_principals(match: dict[str, Any]) -> TrustedIdentitySet:
    value = match.get("publisher_principals")
    if not isinstance(value, dict) or set(value) != {"identities"}:
        raise RuntimeError("listing is missing required publisher_principals")
    identities = value["identities"]
    if not isinstance(identities, (list, tuple)):
        raise RuntimeError("listing carries invalid publisher_principals")
    try:
        return TrustedIdentitySet(
            identities=tuple(Identity.model_validate(item) for item in identities)
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("listing carries invalid publisher_principals") from exc


def make_publisher_trust_resolver(
    *,
    config: BuyConfig,
    listing: dict[str, Any],
    on_update: Callable[[str, dict[str, Any]], None] | None = None,
) -> Callable[[], TrustedIdentitySet]:
    """Refresh only a listing's registry-authenticated active publisher set."""

    listing_id = listing.get("listing_id")
    publisher_id = listing.get("publisher_id")
    storefront_url = listing.get("storefront_url")
    source_url = str(listing.get("source_registry_url") or "").rstrip("/")
    source_authority = listing.get("source_registry_authority")
    registry_authority = config.registry_authorities.get(source_url)
    if (
        listing_id is None
        or publisher_id is None
        or not storefront_url
        or registry_authority is None
        or source_authority != registry_authority.authority
    ):
        raise RuntimeError(
            "listing trust refresh requires an exact registry authority subject binding"
        )
    listing_id = str(listing_id)
    current = _seller_principals(listing)

    def resolve() -> TrustedIdentitySet:
        nonlocal current
        refreshed = fetch_listing_dict(
            source_url,
            listing_id,
            timeout=(
                config.discovery_timeout
                if config.discovery_timeout is not None
                else DEFAULT_HTTP_TIMEOUT
            ),
            signer=config.signer,
            registry_authority=registry_authority,
            api_key=config.registry_api_keys.get(source_url),
        )
        if refreshed is None:
            raise RuntimeError(
                f"publisher trust refresh could not find listing {listing_id!r}"
            )
        if (
            str(refreshed.get("listing_id")) != listing_id
            or refreshed.get("publisher_id") != publisher_id
            or refreshed.get("storefront_url") != storefront_url
        ):
            raise RuntimeError(
                "publisher trust refresh changed listing subject binding"
            )
        replacement = _seller_principals(refreshed)
        if replacement != current:
            current = replacement
            if on_update is not None:
                on_update(
                    "publisher_trust_refreshed",
                    {
                        "listing_id": listing_id,
                        "publisher_id": publisher_id,
                        "publisher_principals": current.model_dump(mode="json"),
                        "source_registry_url": source_url,
                        "source_registry_authority": source_authority,
                    },
                )
        return current

    return resolve


# ---------------------------------------------------------------------------
# Settlement: signed POST + polling GET
# ---------------------------------------------------------------------------


def _never_retry(_exc: RuntimeError) -> bool:
    return False


def submit_settlement_request(
    *,
    seller_url: str,
    escrow_uid: str,
    payload: dict[str, Any],
    principal: Identity,
    signer: Signer,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    max_attempts: int = 1,
    retry_backoff: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
    retryable: Callable[[RuntimeError], bool] = _never_retry,
    resolve_seller_principals: Callable[[], TrustedIdentitySet],
) -> dict[str, Any]:
    """Submit one domain-built settlement payload with marketplace authentication."""
    if "buyer_principal" in payload:
        raise ValueError("settlement payload must not override buyer_principal")
    url = seller_url.rstrip("/") + f"/api/v1/settle/{escrow_uid}"
    body = {
        **payload,
        "buyer_principal": principal.model_dump(mode="json"),
    }
    request_id = uuid.uuid4().hex
    timestamp = int(time.time())
    last_exc: RuntimeError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return _signed_json(
                url,
                body,
                signer=signer,
                principal=principal,
                method="POST",
                operation="settle_escrow",
                resource=escrow_uid,
                timeout=timeout,
                request_id=request_id,
                timestamp=timestamp,
                resolve_response_principals=resolve_seller_principals,
            )
        except RuntimeError as exc:
            last_exc = exc
            if not retryable(exc) or attempt == max_attempts:
                raise
            sleep(retry_backoff)
    assert last_exc is not None
    raise last_exc


def poll_settlement_status(
    *,
    seller_url: str,
    escrow_uid: str,
    principal: Identity,
    signer: Signer,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    resolve_seller_principals: Callable[[], TrustedIdentitySet],
) -> dict[str, Any]:
    """Read an EVM settlement status through v2 marketplace authentication."""

    return _signed_json(
        seller_url.rstrip("/") + f"/api/v1/settle/{escrow_uid}/status",
        body=None,
        signer=signer,
        principal=principal,
        method="GET",
        operation="settle_status",
        resource=escrow_uid,
        timeout=timeout,
        resolve_response_principals=resolve_seller_principals,
    )


def _signed_json(
    url: str,
    body: dict[str, Any] | None,
    *,
    signer: Signer,
    principal: Identity,
    method: str,
    operation: str,
    resource: str,
    timeout: float,
    request_id: str | None = None,
    timestamp: int | None = None,
    resolve_response_principals: Callable[[], TrustedIdentitySet],
) -> dict[str, Any]:
    return _authenticated_json(
        url,
        body,
        signer=signer,
        principal=principal,
        method=method,
        operation=operation,
        resource=resource,
        timeout=timeout,
        request_id=request_id,
        timestamp=timestamp,
        expected_response_principals=resolve_response_principals(),
    )


def wait_for_settlement(
    *,
    seller_url: str,
    escrow_uid: str,
    principal: Identity,
    signer: Signer,
    poll_interval: float = DEFAULT_SETTLEMENT_POLL_INTERVAL,
    total_timeout: float = DEFAULT_SETTLEMENT_TIMEOUT,
    on_poll: Callable[[int, dict], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    resolve_seller_principals: Callable[[], TrustedIdentitySet],
) -> dict[str, Any]:
    """Poll an EVM settlement until it reaches a terminal public status."""

    deadline = time.monotonic() + total_timeout
    attempts = 0
    while True:
        attempts += 1
        status_body = poll_settlement_status(
            seller_url=seller_url,
            escrow_uid=escrow_uid,
            principal=principal,
            signer=signer,
            resolve_seller_principals=resolve_seller_principals,
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
    Not used by ``create_escrow`` itself — that hook reads the opaque term
    payloads built by ``build_escrow_terms``.
    ``unit_count`` is the deal's priced-unit span (lease hours for
    compute, token quantity for credits); domain shims may re-derive
    their native quantity from it for display.
    """

    seller_url: str
    seller_wallet_address: str
    negotiation_id: str
    listing_id: str
    agreed_amount: int  # base units, absolute payment total
    unit_count: float  # buyer's ask (negotiation init)


def make_negotiate_hook(
    *,
    config: BuyConfig,
    constraints: BuyConstraints,
    provision: Any,
    unit_count: float,
    build_escrow_proposal: BuildEscrowProposalFn,
    encode_escrow_proposal: EncodeEscrowProposalFn,
    decode_provision_terms: DecodeOpaquePayloadFn,
    decode_escrow_proposal: DecodeOpaquePayloadFn,
    decode_escrow_terms: DecodeOpaquePayloadFn,
    max_negotiation_rounds: int,
    derive_prices: Callable[[dict[str, Any]], tuple[int, int]] | None,
    chain: list[Any] | None,
) -> NegotiateFn:
    """Build the schema-instantiated negotiate hook.

    The returned hook absorbs the fine-grained negotiation injections:
    accepted-escrow proposal construction, per-listing price derivation,
    buyer policy chain, and aggregation policy execution. ``provision``
    is the domain's provisioning payload, passed through opaquely;
    ``unit_count`` is the per-unit→absolute scale.
    """

    def _hook(
        matches: list[dict[str, Any]],
        on_event: Callable[[str, dict], None],
    ) -> NegotiationResult:
        return _negotiate_matches(
            matches=matches,
            config=config,
            constraints=constraints,
            provision=provision,
            unit_count=unit_count,
            build_escrow_proposal=build_escrow_proposal,
            encode_escrow_proposal=encode_escrow_proposal,
            decode_provision_terms=decode_provision_terms,
            decode_escrow_proposal=decode_escrow_proposal,
            decode_escrow_terms=decode_escrow_terms,
            max_negotiation_rounds=max_negotiation_rounds,
            derive_prices=derive_prices,
            chain=chain,
            on_event=on_event,
        )

    return _hook


def _negotiate_matches(
    *,
    matches: list[dict[str, Any]],
    config: BuyConfig,
    constraints: BuyConstraints,
    provision: Any,
    unit_count: float,
    build_escrow_proposal: BuildEscrowProposalFn,
    encode_escrow_proposal: EncodeEscrowProposalFn,
    decode_provision_terms: DecodeOpaquePayloadFn,
    decode_escrow_proposal: DecodeOpaquePayloadFn,
    decode_escrow_terms: DecodeOpaquePayloadFn,
    max_negotiation_rounds: int,
    derive_prices: Callable[[dict[str, Any]], tuple[int, int]] | None,
    chain: list[Any] | None,
    on_event: Callable[[str, dict], None],
) -> NegotiationResult:
    attempts: list[dict[str, Any]] = []

    async def _negotiate(match: dict[str, Any]) -> NegotiationOutcome:
        seller_url = (
            match.get("storefront_url")
            or match.get("seller")
            or match.get("seller_url")
            or ""
        )
        listing_id = match.get("listing_id") or match.get("order_id") or ""
        if not seller_url or not listing_id:
            attempts.append(
                {"match": match, "error": "missing_seller_url_or_listing_id"}
            )
            # Translate to a synthetic outcome so the policy can iterate
            # past it — same shape as a seller-side exit.
            return NegotiationOutcome(
                status="exited",
                negotiation_id=None,
                reason="missing_seller_url_or_listing_id",
            )

        settlement_proposal = build_escrow_proposal(match)
        if settlement_proposal is None:
            attempts.append(
                {
                    "seller_url": seller_url,
                    "listing_id": listing_id,
                    "error": "no_compatible_settlement_option",
                }
            )
            return NegotiationOutcome(
                status="exited",
                negotiation_id=None,
                reason="no_compatible_settlement_option",
            )
        if isinstance(settlement_proposal, SettlementSelection):
            escrow_proposal = None
            settlement_selection = settlement_proposal
        else:
            escrow_proposal = settlement_proposal
            settlement_selection = None

        neg_ctx: dict[str, Any] = {
            "listing_id": listing_id,
            "publisher_id": match.get("publisher_id"),
            "source_registry_url": match.get("source_registry_url"),
            "source_registry_authority": match.get("source_registry_authority"),
        }

        def _emit_neg(stage: str, **fields: Any) -> None:
            on_event(stage, {**neg_ctx, **fields})

        resolve_seller_principals = make_publisher_trust_resolver(
            config=config,
            listing=match,
            on_update=lambda stage, payload: _emit_neg(stage, **payload),
        )
        publisher_principals = resolve_seller_principals()
        neg_ctx["publisher_principals"] = publisher_principals.model_dump(mode="json")

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
                attempts.append(
                    {
                        "seller_url": seller_url,
                        "listing_id": listing_id,
                        "error": f"price_derivation: {exc}",
                    }
                )
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
                attempts.append(
                    {
                        "seller_url": seller_url,
                        "listing_id": listing_id,
                        "error": (
                            "BuyConstraints.initial_price and max_price are None "
                            "but no derive_prices callback was provided"
                        ),
                    }
                )
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
                principal=config.principal,
                signer=config.signer,
                listing_id=listing_id,
                initial_price=initial_price,
                max_price=max_price,
                unit_count=unit_count,
                provision_terms=provision,
                escrow_proposal=escrow_proposal,
                encode_escrow_proposal=encode_escrow_proposal,
                decode_provision_terms=decode_provision_terms,
                decode_escrow_proposal=decode_escrow_proposal,
                decode_escrow_terms=decode_escrow_terms,
                settlement_selection=settlement_selection,
                max_rounds=max_negotiation_rounds,
                on_round=_on_round,
                chain=chain,
                policy_params=constraints.policy_params,
                resolve_seller_principals=resolve_seller_principals,
            )
        except RuntimeError as exc:
            _emit_neg("negotiation_failed", error=f"http_error: {exc}")
            attempts.append(
                {
                    "seller_url": seller_url,
                    "listing_id": listing_id,
                    "error": f"negotiation_http_error: {exc}",
                }
            )
            # Reraise so policies that don't catch see the actual error —
            # surface state, don't paper over network failures.
            raise

        if outcome.negotiation_id and "negotiation_id" not in neg_ctx:
            neg_ctx["negotiation_id"] = outcome.negotiation_id

        # Note: the buyer-side ``buyer_escrow_shape_guard`` middleware
        # (default in the buyer's chain) handles seller-pin-mutation
        # vetoes per round — no separate post-agreement audit is needed.

        from .deal_helpers import settlement_acceptance_fields

        accepted_settlement = settlement_acceptance_fields(
            negotiation_id=outcome.negotiation_id or "",
            selection=outcome.settlement_selection,
            plan=outcome.settlement_plan,
        )
        _emit_neg(
            "negotiation_completed",
            seller_url=seller_url,
            status=outcome.status,
            agreed_amount=outcome.agreed_amount,
            rounds=outcome.rounds,
            reason=outcome.reason,
            accepted_escrow_proposal=(
                _opaque_payload_dict(outcome.accepted_escrow_proposal)
                if outcome.accepted_escrow_proposal is not None
                else None
            ),
            **accepted_settlement,
            accepted_escrow_terms=(
                [_opaque_payload_dict(term) for term in outcome.accepted_escrow_terms]
                if outcome.accepted_escrow_terms is not None
                else None
            ),
            accepted_provision_terms=(
                _opaque_payload_dict(outcome.accepted_provision_terms)
                if outcome.accepted_provision_terms is not None
                else None
            ),
        )
        attempts.append(
            {
                "seller_url": seller_url,
                "listing_id": listing_id,
                "outcome": outcome.to_dict(),
            }
        )
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


def make_settle_hook(
    *,
    config: BuyConfig,
    unit_count: float,
    build_escrow_terms: BuildEscrowTermsFn,
    create_escrow: CreateEscrowFn,
    settlement_recipient: SettlementRecipientFn,
    build_settlement_payload: BuildSettlementPayloadFn,
    confirm_settlement: Callable[[AgreedTerms, dict[str, Any]], bool] | None,
    settlement_submit_max_attempts: int,
    settlement_submit_retryable: Callable[[RuntimeError], bool],
    settlement_poll_interval: float,
    settlement_total_timeout: float,
    sleep: Callable[[float], None],
    duration_seconds: int = 0,
) -> SettleFn:
    """Build the schema-instantiated settlement hook.

    Domain ports materialize escrow terms, recipient identity, and the
    mechanism-specific settlement request payload.
    """

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
            unit_count=unit_count,
            duration_seconds=duration_seconds,
            build_escrow_terms=build_escrow_terms,
            create_escrow=create_escrow,
            settlement_recipient=settlement_recipient,
            build_settlement_payload=build_settlement_payload,
            settlement_submit_max_attempts=settlement_submit_max_attempts,
            settlement_submit_retryable=settlement_submit_retryable,
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
    config: BuyConfig,
    unit_count: float,
    duration_seconds: int,
    build_settlement_payload: BuildSettlementPayloadFn,
    settlement_submit_max_attempts: int,
    settlement_submit_retryable: Callable[[RuntimeError], bool],
    build_escrow_terms: BuildEscrowTermsFn,
    create_escrow: CreateEscrowFn,
    settlement_recipient: SettlementRecipientFn,
    confirm_settlement: Callable[[AgreedTerms, dict[str, Any]], bool] | None,
    settlement_poll_interval: float,
    settlement_total_timeout: float,
    sleep: Callable[[float], None],
    on_event: Callable[[str, dict], None],
    attempts: list[dict[str, Any]],
) -> BuyResult:
    """Drive escrow → submit → poll for the policy's chosen winner.

    Lifted out of the run_buy loop so the negotiate-vs-settle split is
    structural, not just visual. Inputs are the policy's
    ``(match, outcome)`` plus the orchestrator's settlement deps.
    """
    seller_url = (
        match.get("storefront_url")
        or match.get("seller")
        or match.get("seller_url")
        or ""
    )
    listing_id = match.get("listing_id") or match.get("order_id") or ""

    # Pass the seller-confirmed opaque proposal through the domain's
    # materialization, recipient-decoding, and submission ports.
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

    escrow_recipient = settlement_recipient(accepted_proposal)

    terms = AgreedTerms(
        seller_url=seller_url,
        seller_wallet_address=escrow_recipient or "",
        negotiation_id=outcome.negotiation_id or "",
        listing_id=listing_id,
        agreed_amount=outcome.agreed_amount or 0,
        unit_count=unit_count,
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
                accepted_proposal,
                terms.seller_wallet_address,
                terms.agreed_amount,
                duration_seconds,
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
        {
            "terms": {**terms.__dict__, "duration_seconds": duration_seconds},
            "escrows": [_opaque_payload_dict(escrow) for escrow in escrows],
        },
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
            {
                "error": f"create_escrow returned {len(escrow_uids)} uids, "
                f"expected {len(buyer_escrows)} for buyer-made entries"
            },
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
        },
    )

    resolve_seller_principals = make_publisher_trust_resolver(
        config=config,
        listing=match,
        on_update=on_event,
    )
    payload = build_settlement_payload(
        outcome.negotiation_id or "",
        accepted_proposal,
    )
    submit_settlement_request(
        seller_url=seller_url,
        escrow_uid=escrow_uid,
        payload=payload,
        principal=config.principal,
        max_attempts=settlement_submit_max_attempts,
        retryable=settlement_submit_retryable,
        signer=config.signer,
        resolve_seller_principals=resolve_seller_principals,
    )
    on_event("settlement_submitted", {"escrow_uid": escrow_uid})

    try:
        final = wait_for_settlement(
            seller_url=seller_url,
            escrow_uid=escrow_uid,
            principal=config.principal,
            signer=config.signer,
            poll_interval=settlement_poll_interval,
            total_timeout=settlement_total_timeout,
            on_poll=lambda i, body: on_event(
                "settlement_poll", {"attempt": i, "body": body}
            ),
            sleep=sleep,
            resolve_seller_principals=resolve_seller_principals,
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
