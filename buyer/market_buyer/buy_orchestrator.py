"""Sequential buyer orchestrator — the "buyer is a pure client" realization.

    result = run_buy(config, constraints, create_escrow=...)

composes five closed-function stages in order:

    1. discover         — registry query for matching seller orders
    2. negotiate        — buyer_client.negotiate_with_seller per match
    3. create_escrow    — on-chain escrow creation (injected; see escrow_client)
    4. submit_settlement — POST seller's /settle/{escrow_uid}
    5. poll_settlement  — GET seller's /settle/{escrow_uid}/status until terminal

Nothing here runs a server or handles inbound HTTP. The buyer is a
client that drives the deal end to end. Every HTTP call to the seller
is signed by the buyer's wallet; `create_escrow` is injected so the
orchestrator itself can be unit-tested without alkahest-py.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .buyer_client import NegotiationOutcome, negotiate_with_seller, _sign


DEFAULT_HTTP_TIMEOUT = 30.0
DEFAULT_SETTLEMENT_POLL_INTERVAL = 5.0
DEFAULT_SETTLEMENT_TIMEOUT = 600.0  # 10 minutes


@dataclass
class BuyConfig:
    """Buyer identity + how to reach the world. Immutable per `run_buy` call."""
    registry_url: str
    buyer_address: str
    buyer_private_key: str
    ssh_public_key: str


@dataclass
class BuyConstraints:
    """What the buyer wants, enforced locally during negotiation."""
    max_price: int          # ceiling per order (raw token units)
    initial_price: int      # opening bid per order


@dataclass
class BuyResult:
    status: str
    negotiation_id: Optional[str] = None
    seller_url: Optional[str] = None
    agreed_price: Optional[int] = None
    escrow_uid: Optional[str] = None
    attestation_uid: Optional[str] = None
    connection_details: Optional[str] = None
    tenant_credentials: Optional[dict[str, Any]] = None
    reason: Optional[str] = None
    rounds: int = 0
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "rounds": self.rounds}
        for k in (
            "negotiation_id", "seller_url", "agreed_price", "escrow_uid",
            "attestation_uid", "connection_details", "tenant_credentials",
            "reason",
        ):
            v = getattr(self, k)
            if v is not None:
                out[k] = v
        if self.attempts:
            out["attempts"] = self.attempts
        return out


# ---------------------------------------------------------------------------
# Discovery: direct registry query
# ---------------------------------------------------------------------------


def query_registry_for_matches(
    registry_url: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> list[dict[str, Any]]:
    """Ask the registry for open seller offers.

    Returns the raw list of order dicts the registry gave us. Buyers
    don't have anything in the registry to filter against — they pick
    one (or several) offers to negotiate with.
    """
    url = registry_url.rstrip("/") + "/orders?status=open"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(f"Registry GET {url} -> HTTP {exc.code}: {detail[:200]}") from exc
    except Exception as exc:
        raise RuntimeError(f"Registry GET {url} failed: {exc}") from exc

    try:
        payload = json.loads(text) if text else []
    except ValueError as exc:
        raise RuntimeError(f"Registry returned non-JSON: {text[:200]!r}") from exc

    # Registry may wrap the list or return it raw; normalize.
    if isinstance(payload, dict):
        orders = payload.get("orders") or payload.get("data") or []
    else:
        orders = payload
    if not isinstance(orders, list):
        return []

    return orders


# ---------------------------------------------------------------------------
# Settlement: signed POST + polling GET
# ---------------------------------------------------------------------------


def submit_settlement(
    *,
    seller_url: str,
    escrow_uid: str,
    negotiation_id: str,
    ssh_public_key: str,
    buyer_address: str,
    buyer_private_key: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> dict[str, Any]:
    """POST /settle/{escrow_uid} with signed body. Returns the initial job state."""
    url = seller_url.rstrip("/") + f"/settle/{escrow_uid}"
    body = {
        "negotiation_id": negotiation_id,
        "ssh_public_key": ssh_public_key,
        "buyer_address": buyer_address,
    }
    sig, ts = _sign(f"settle_escrow:{escrow_uid}", buyer_private_key)
    return _signed_json(url, body, sig, ts, method="POST", timeout=timeout)


def poll_settlement_status(
    *,
    seller_url: str,
    escrow_uid: str,
    buyer_address: str,
    buyer_private_key: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> dict[str, Any]:
    """GET /settle/{escrow_uid}/status with signed query params + headers."""
    sig, ts = _sign(f"settle_status:{escrow_uid}", buyer_private_key)
    url = (
        seller_url.rstrip("/")
        + f"/settle/{escrow_uid}/status?buyer_address={buyer_address}"
    )
    return _signed_json(url, body=None, signature=sig, timestamp=ts,
                        method="GET", timeout=timeout)


def _signed_json(
    url: str,
    body: dict[str, Any] | None,
    signature: str,
    timestamp: int,
    *,
    method: str,
    timeout: float,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "X-Signature": signature,
        "X-Timestamp": str(timestamp),
    }
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
    """What the buyer needs to turn an agreement into an on-chain escrow.

    Passed into the `create_escrow` hook. The hook is responsible for
    knowing the chain / token / arbiter details (those are config in
    the buyer's environment) and returning the on-chain escrow UID.
    """
    seller_url: str
    seller_wallet_address: str
    negotiation_id: str
    listing_id: str
    agreed_price: int               # raw token units
    duration_hours: int


CreateEscrowFn = Callable[[AgreedTerms], str]
"""A function `terms -> escrow_uid`. Synchronous; on-chain call may block."""


# ---------------------------------------------------------------------------
# The orchestrator
# ---------------------------------------------------------------------------


def _resolve_seller_wallet(seller_url: str, timeout: float = 5.0) -> str:
    """Fetch seller's wallet from /.well-known/agent-wallet.json.

    Needed to construct the RecipientArbiter demand on the buyer side —
    we want the escrow to release only on attestations where the
    seller's address is the recipient.
    """
    url = seller_url.rstrip("/") + "/.well-known/agent-wallet.json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Could not fetch seller wallet from {url}: {exc}") from exc
    wallet = body.get("agent_wallet_address")
    if not isinstance(wallet, str) or not wallet.startswith("0x") or len(wallet) != 42:
        raise RuntimeError(
            f"{url} returned malformed agent_wallet_address: {wallet!r}"
        )
    return wallet


def run_buy(
    *,
    config: BuyConfig,
    constraints: BuyConstraints,
    create_escrow: CreateEscrowFn,
    matches: Optional[list[dict[str, Any]]] = None,
    max_matches_to_try: int = 5,
    max_negotiation_rounds: int = 10,
    settlement_poll_interval: float = DEFAULT_SETTLEMENT_POLL_INTERVAL,
    settlement_total_timeout: float = DEFAULT_SETTLEMENT_TIMEOUT,
    on_event: Optional[Callable[[str, dict], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> BuyResult:
    """Run one buy attempt end-to-end. Sequential; every dependency is explicit.

    Parameters
    ----------
    config, constraints
        Buyer identity + what we want. Immutable for this call.
    create_escrow
        Hook that takes AgreedTerms and returns an on-chain escrow UID.
        Injected so the orchestrator itself is testable without alkahest-py.
    matches
        Pre-computed match list. If None, queries the registry directly.
    on_event
        Optional observer: called as `on_event(stage_name, payload)` at
        each stage transition. Good for CLI progress UI.

    Returns
    -------
    BuyResult with status ∈
      - "ready"        — escrow collected and seller posted attestation
      - "failed"       — provisioning failed on seller side
      - "exited"       — no match agreed to terms
      - "no_matches"   — registry returned nothing
      - "timeout"      — settlement polling timed out
    """
    def _event(stage: str, payload: dict) -> None:
        if on_event:
            on_event(stage, payload)

    # --- 1. Discover ---------------------------------------------------
    if matches is None:
        matches = query_registry_for_matches(config.registry_url)
    _event("discover", {"match_count": len(matches)})

    if not matches:
        return BuyResult(status="no_matches")

    attempts: list[dict[str, Any]] = []

    # --- 2. Try each match ---------------------------------------------
    # Each negotiation attempt is its own sub-stream of events: emitted
    # with sticky `listing_id` (known up-front) plus `negotiation_id`
    # (server-assigned, captured from round 0). Consumers (run-log
    # readers, observers) group on those keys.
    for match in matches[:max_matches_to_try]:
        seller_url = match.get("order_maker") or match.get("seller_url") or ""
        listing_id = match.get("order_id") or match.get("listing_id") or ""
        if not seller_url or not listing_id:
            attempts.append({"match": match, "error": "missing_seller_url_or_listing_id"})
            continue

        # Mutable context: starts with listing_id, gets negotiation_id
        # added once round 0 returns.
        neg_ctx: dict[str, Any] = {"listing_id": listing_id}

        def _emit_neg(stage: str, **fields: Any) -> None:
            _event(stage, {**neg_ctx, **fields})

        _emit_neg("negotiation_started", seller_url=seller_url)

        def _on_round(round_idx: int, our_msg: dict, their_reply: dict) -> None:
            # Capture the server-assigned negotiation_id from round 0.
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

        try:
            outcome = negotiate_with_seller(
                seller_url=seller_url,
                buyer_address=config.buyer_address,
                buyer_private_key=config.buyer_private_key,
                listing_id=listing_id,
                initial_price=constraints.initial_price,
                max_price=constraints.max_price,
                max_rounds=max_negotiation_rounds,
                on_round=_on_round,
            )
        except RuntimeError as exc:
            _emit_neg("negotiation_failed", error=f"http_error: {exc}")
            attempts.append({
                "seller_url": seller_url,
                "listing_id": listing_id,
                "error": f"negotiation_http_error: {exc}",
            })
            continue

        if outcome.negotiation_id and "negotiation_id" not in neg_ctx:
            neg_ctx["negotiation_id"] = outcome.negotiation_id

        _emit_neg(
            "negotiation_completed",
            seller_url=seller_url,
            status=outcome.status,
            agreed_price=outcome.agreed_price,
            rounds=outcome.rounds,
            reason=outcome.reason,
        )
        attempts.append({
            "seller_url": seller_url,
            "listing_id": listing_id,
            "outcome": outcome.to_dict(),
        })

        if outcome.status != "agreed" or outcome.agreed_price is None:
            continue

        # --- 3. Create escrow on-chain --------------------------------
        try:
            seller_wallet = _resolve_seller_wallet(seller_url)
        except RuntimeError as exc:
            _event("escrow_resolve_wallet_failed", {"seller_url": seller_url, "error": str(exc)})
            continue

        terms = AgreedTerms(
            seller_url=seller_url,
            seller_wallet_address=seller_wallet,
            negotiation_id=outcome.negotiation_id or "",
            listing_id=listing_id,
            agreed_price=outcome.agreed_price,
            duration_hours=int(match.get("duration_hours") or 1),
        )
        _event("escrow_create_start", {"terms": terms.__dict__})
        try:
            escrow_uid = create_escrow(terms)
        except Exception as exc:
            _event("escrow_create_failed", {"error": str(exc)})
            return BuyResult(
                status="exited",
                negotiation_id=outcome.negotiation_id,
                seller_url=seller_url,
                agreed_price=outcome.agreed_price,
                reason=f"escrow_create_failed: {exc}",
                rounds=outcome.rounds,
                attempts=attempts,
            )
        _event("escrow_created", {"escrow_uid": escrow_uid})

        # --- 4. Submit settlement -------------------------------------
        submit_settlement(
            seller_url=seller_url,
            escrow_uid=escrow_uid,
            negotiation_id=outcome.negotiation_id or "",
            ssh_public_key=config.ssh_public_key,
            buyer_address=config.buyer_address,
            buyer_private_key=config.buyer_private_key,
        )
        _event("settlement_submitted", {"escrow_uid": escrow_uid})

        # --- 5. Poll status until terminal ----------------------------
        try:
            final = wait_for_settlement(
                seller_url=seller_url,
                escrow_uid=escrow_uid,
                buyer_address=config.buyer_address,
                buyer_private_key=config.buyer_private_key,
                poll_interval=settlement_poll_interval,
                total_timeout=settlement_total_timeout,
                on_poll=lambda i, body: _event("settlement_poll",
                                               {"attempt": i, "body": body}),
                sleep=sleep,
            )
        except TimeoutError as exc:
            return BuyResult(
                status="timeout",
                negotiation_id=outcome.negotiation_id,
                seller_url=seller_url,
                agreed_price=outcome.agreed_price,
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
                agreed_price=outcome.agreed_price,
                escrow_uid=escrow_uid,
                attestation_uid=final.get("attestation_uid"),
                connection_details=final.get("connection_details"),
                tenant_credentials=final.get("tenant_credentials"),
                rounds=outcome.rounds,
                attempts=attempts,
            )
        # status == 'failed' — escrow is stuck on-chain; return the
        # details so the caller can kick off refund/reclaim.
        return BuyResult(
            status="failed",
            negotiation_id=outcome.negotiation_id,
            seller_url=seller_url,
            agreed_price=outcome.agreed_price,
            escrow_uid=escrow_uid,
            reason=final.get("reason") or "provisioning_failed",
            rounds=outcome.rounds,
            attempts=attempts,
        )

    # Exhausted all matches without an agreement.
    return BuyResult(
        status="exited",
        reason="no_match_agreed_to_terms",
        attempts=attempts,
    )
