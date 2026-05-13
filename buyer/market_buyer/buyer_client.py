"""Buyer-as-pure-client negotiation library.

The buyer doesn't run a storefront or any HTTP server. They pick a
seller, open a negotiation via HTTP, loop round-by-round until the
thread ends, and return the outcome. Every request is signed by the
buyer's wallet so the seller can verify without any prior
registration.

Public API:
    negotiate_with_seller(...) -> NegotiationOutcome

The per-round decision logic lives in
`market_policy.negotiation_strategy` (BisectionStrategy or the
register-on-import RL strategy). Both sides of a negotiation resolve
their moves through the same package; this module is just the buyer's
HTTP transport + signing.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from market_policy.negotiation_strategy import (
    DEFAULT_MAX_ROUNDS,
    DEFAULT_STRATEGY,
    NegotiationRound,
    NegotiationRoundInput,
    NegotiationStrategy,
    load_strategy,
)
from service.schemas import EscrowTermsProposal, ProvisionTerms


def _maybe_register_rl_strategy() -> None:
    """Trigger self-registration of the torch RL strategy.

    Mirrors the storefront-side helper: imports
    ``domain.compute.agent.app.policy.torch_arkhai_strategy`` so its
    ``register_strategy("rl", ...)`` call fires. The import is best-effort —
    if torch / pufferlib aren't installed, ``load_strategy("rl")`` will
    raise its own actionable KeyError pointing at the [rl] extras.
    """
    try:
        import domain.compute.agent.app.policy.torch_arkhai_strategy  # noqa: F401
    except Exception:
        pass


DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass
class NegotiationOutcome:
    """What came out of a full negotiation run from the buyer's POV.

    ``accepted_provision_terms`` and ``accepted_escrow_terms_proposal``
    are populated when the seller echoed them back in the negotiation
    response (always on non-rejection paths). Settlement-time escrow
    construction reads from these — using the *seller-confirmed* values
    rather than the buyer's local proposal protects against any
    drift between sides.
    """
    status: str                     # "agreed" | "exited"
    negotiation_id: Optional[str]   # None only if /new itself failed
    agreed_price: Optional[int] = None
    duration_seconds: Optional[int] = None  # echoed from buyer's negotiation-init ask
    reason: Optional[str] = None    # populated on exit
    rounds: int = 0
    accepted_provision_terms: Optional[ProvisionTerms] = None
    accepted_escrow_terms_proposal: Optional[EscrowTermsProposal] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": self.status, "rounds": self.rounds}
        if self.negotiation_id is not None:
            d["negotiation_id"] = self.negotiation_id
        if self.agreed_price is not None:
            d["agreed_price"] = self.agreed_price
        if self.duration_seconds is not None:
            d["duration_seconds"] = self.duration_seconds
        if self.reason is not None:
            d["reason"] = self.reason
        if self.accepted_provision_terms is not None:
            d["accepted_provision_terms"] = self.accepted_provision_terms.model_dump()
        if self.accepted_escrow_terms_proposal is not None:
            d["accepted_escrow_terms_proposal"] = self.accepted_escrow_terms_proposal.model_dump()
        return d


def _parse_accepted_terms_from_reply(
    reply: dict[str, Any],
) -> tuple[Optional[ProvisionTerms], Optional[EscrowTermsProposal]]:
    """Extract the seller's echoed accepted terms from a negotiate reply.

    Returns (None, None) if the seller didn't include them — happens on
    exit/reject paths or against legacy sellers that haven't shipped the
    new fields yet.
    """
    raw_prov = reply.get("accepted_provision_terms")
    raw_esc = reply.get("accepted_escrow_terms_proposal")
    prov = ProvisionTerms.model_validate(raw_prov) if isinstance(raw_prov, dict) else None
    esc = EscrowTermsProposal.model_validate(raw_esc) if isinstance(raw_esc, dict) else None
    return prov, esc


def _sign(message: str, private_key: str) -> tuple[str, int]:
    """Produce (X-Signature hex, X-Timestamp int) for a given canonical message.

    Mirrors the seller's _check_buyer_signature verification: timestamp
    is appended to the message, and the full string is EIP-191 signed.
    """
    from eth_account import Account
    from eth_account.messages import encode_defunct

    ts = int(time.time())
    signed_message = f"{message}:{ts}"
    msg_hash = encode_defunct(text=signed_message)
    sig = Account.sign_message(msg_hash, private_key).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    return sig, ts


def _post(
    url: str,
    body: dict[str, Any],
    *,
    signature: str,
    timestamp: int,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Signed POST with JSON body. Raises RuntimeError on non-2xx."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Signature": signature,
            "X-Timestamp": str(timestamp),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(f"POST {url} -> HTTP {exc.code}: {detail[:500]}") from exc
    except Exception as exc:
        raise RuntimeError(f"POST {url} failed: {exc}") from exc

    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError as exc:
        raise RuntimeError(f"POST {url} returned non-JSON: {text[:200]!r}") from exc


@dataclass
class ResumeState:
    """Inputs for resuming an in-flight negotiation thread.

    Built by ``market negotiate --from <run_id>``: the run-log gives
    us the server-assigned ``negotiation_id``, the rounds we've
    observed, and the seller's last-known price. We replay that into
    the strategy and continue the round loop without going through
    ``/api/v1/negotiate/new`` again (the seller has the thread already).
    """
    negotiation_id: str
    transcript: list[NegotiationRound]
    last_seller_price: int | None
    rounds_completed: int


def negotiate_with_seller(
    *,
    seller_url: str,
    buyer_address: str,
    buyer_private_key: str,
    listing_id: str,
    initial_price: int,
    max_price: int,
    provision_terms: Optional[ProvisionTerms] = None,
    escrow_terms_proposal: Optional[EscrowTermsProposal] = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    on_round: Optional[Callable[[int, dict, dict], None]] = None,
    strategy: Optional[NegotiationStrategy] = None,
    resume: Optional[ResumeState] = None,
) -> NegotiationOutcome:
    """Run a synchronous negotiation with one seller, round-by-round.

    `initial_price` is what the buyer opens with (can be lower than max
    to haggle). `max_price` is the buyer's absolute ceiling — any seller
    counter at or below convergence to this gets accepted.

    `provision_terms` describes what the buyer wants the seller to
    deliver (duration, ssh key, compute spec) and `escrow_terms_proposal`
    is the buyer's proposed on-chain escrow shape (escrow_kind +
    arbiter_kind + payment_token + expiration). Both are sent on
    /api/v1/negotiate/new and validated server-side against the
    listing's acceptance set. Required for fresh starts; ignored in
    resume mode (the negotiation thread already has them committed).

    The negotiation_id is server-assigned (returned in the
    /api/v1/negotiate/new response) and threaded through every subsequent
    /negotiate/{neg_id} round; the buyer doesn't supply it.

    `on_round(round_idx, our_msg, their_reply)` is an optional observer
    hook (for CLI rendering, testing).

    Synchronous everything: the seller responds in-line on each POST.
    Returns a NegotiationOutcome describing how it ended; the seller's
    accepted_* echo is parsed back so settlement-time escrow construction
    can use the agreed (not local-proposed) values.
    """
    seller_url = seller_url.rstrip("/")
    our_counters: list[int] = []
    transcript: list[NegotiationRound] = []
    # Captured from the seller's round-0 response and threaded forward.
    # The seller commits to these at /negotiate/new (they're persisted on
    # the negotiation thread); subsequent rounds don't re-echo them.
    accepted_prov: Optional[ProvisionTerms] = None
    accepted_esc: Optional[EscrowTermsProposal] = None
    duration_seconds: Optional[int] = None  # populated from provision_terms or resume
    if strategy is None:
        # Default to the registered default ("rl"); pull the torch
        # module in if installed so its registration fires.
        _maybe_register_rl_strategy()
        strategy = load_strategy()

    if resume is not None:
        # Resume mode: skip /api/v1/negotiate/new and the first counter exchange.
        # We trust the run-log's recorded transcript and the seller's last
        # counter price; the strategy decides our next move from there.
        if resume.last_seller_price is None:
            raise RuntimeError(
                "Cannot resume — no seller counter price recorded in run-log."
            )
        neg_id = resume.negotiation_id
        transcript = list(resume.transcript)
        # Synthesize a `reply` dict shaped like the round-loop expects.
        reply: dict[str, Any] = {
            "negotiation_id": neg_id,
            "action": "counter",
            "price": int(resume.last_seller_price),
        }
        round_idx = max(1, resume.rounds_completed)
    else:
        # --- Round 0: /api/v1/negotiate/new ---------------------------------------
        if provision_terms is None:
            raise RuntimeError(
                "provision_terms is required for fresh negotiations "
                "(what the seller will provision: duration, ssh_key, compute)"
            )
        if escrow_terms_proposal is None:
            raise RuntimeError(
                "escrow_terms_proposal is required for fresh negotiations "
                "(escrow_kind + arbiter_kind + payment_token + expiration_unix)"
            )
        duration_seconds = provision_terms.duration_seconds
        new_body = {
            "listing_id": listing_id,
            "buyer_address": buyer_address,
            "initial_price": int(initial_price),
            "provision_terms": provision_terms.model_dump(),
            "escrow_terms_proposal": escrow_terms_proposal.model_dump(),
        }
        sig, ts = _sign(f"negotiate_new:{listing_id}", buyer_private_key)
        reply = _post(
            f"{seller_url}/api/v1/negotiate/new", new_body,
            signature=sig, timestamp=ts,
        )
        if on_round:
            on_round(0, new_body, reply)

        neg_id = reply.get("negotiation_id")
        seller_action = reply.get("action")
        accepted_prov, accepted_esc = _parse_accepted_terms_from_reply(reply)

        if seller_action == "accept":
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=neg_id,
                agreed_price=int(reply.get("price", initial_price)),
                duration_seconds=duration_seconds,
                rounds=0,
                accepted_provision_terms=accepted_prov,
                accepted_escrow_terms_proposal=accepted_esc,
            )
        # On non-agreed paths we still carry forward what the seller
        # validated — used if the negotiation ends up agreed in later
        # rounds (seller doesn't re-echo accepted_* on /continue).
        if seller_action in ("exit", "reject"):
            return NegotiationOutcome(
                status="exited",
                negotiation_id=neg_id,
                reason=reply.get("reason"),
                duration_seconds=duration_seconds,
                rounds=0,
            )
        # From here on seller_action should be "counter".
        if seller_action != "counter":
            raise RuntimeError(f"Unexpected seller action on /api/v1/negotiate/new: {seller_action!r}")
        if not neg_id:
            raise RuntimeError("/api/v1/negotiate/new returned counter but no negotiation_id")

        our_counters.append(int(initial_price))
        transcript.append(NegotiationRound(
            round_number=0, sender="us", action="initial", price=int(initial_price),
        ))
        transcript.append(NegotiationRound(
            round_number=0, sender="them", action="counter",
            price=int(reply.get("price")) if reply.get("price") is not None else None,
        ))
        round_idx = 1

    # --- Rounds 1..N: /negotiate/{id} ----------------------------------
    while round_idx <= max_rounds:
        seller_counter_price = reply.get("price")
        if seller_counter_price is None:
            raise RuntimeError(f"Seller counter without price: {reply!r}")

        next_move = strategy.decide(NegotiationRoundInput(
            direction="minimize",
            our_reference_price=int(max_price),
            their_proposed_price=int(seller_counter_price),
            history=transcript,
            max_rounds=max_rounds,
        ))

        body: dict[str, Any] = {
            "action": next_move.action,
            "buyer_address": buyer_address,
        }
        if next_move.action == "counter":
            body["price"] = int(next_move.price)
        elif next_move.action == "exit":
            body["reason"] = next_move.reason or "buyer_exit"

        sig, ts = _sign(f"negotiate_continue:{neg_id}", buyer_private_key)
        reply = _post(
            f"{seller_url}/api/v1/negotiate/{neg_id}", body,
            signature=sig, timestamp=ts,
        )
        if on_round:
            on_round(round_idx, body, reply)

        # After we sent our move, the seller has replied with either
        # a matching terminal (accept/exit) or a further counter.
        if next_move.action == "accept":
            # We told the seller we accept; their reply should echo accept.
            if reply.get("action") == "accept":
                return NegotiationOutcome(
                    status="agreed",
                    negotiation_id=neg_id,
                    agreed_price=int(reply.get("price", seller_counter_price)),
                    duration_seconds=duration_seconds,
                    rounds=round_idx,
                    accepted_provision_terms=accepted_prov,
                    accepted_escrow_terms_proposal=accepted_esc,
                )
            # Non-accept reply to our accept is anomalous but treat as terminal.
            return NegotiationOutcome(
                status="exited",
                negotiation_id=neg_id,
                reason=f"seller_non_accept_after_buyer_accept:{reply.get('action')!r}",
                duration_seconds=duration_seconds,
                rounds=round_idx,
            )
        if next_move.action == "exit":
            return NegotiationOutcome(
                status="exited",
                negotiation_id=neg_id,
                reason=next_move.reason or "buyer_exit",
                duration_seconds=duration_seconds,
                rounds=round_idx,
            )

        # next_move was counter → state appended, loop continues.
        our_counters.append(int(next_move.price))
        transcript.append(NegotiationRound(
            round_number=round_idx, sender="us", action="counter", price=int(next_move.price),
        ))
        # Record the seller's reply to this round.
        seller_reply_action = reply.get("action") or "counter"
        seller_reply_price = reply.get("price")
        transcript.append(NegotiationRound(
            round_number=round_idx,
            sender="them",
            action=seller_reply_action if seller_reply_action in ("counter", "accept", "exit", "reject") else "counter",
            price=int(seller_reply_price) if seller_reply_price is not None else None,
        ))

        seller_action = reply.get("action")
        if seller_action == "accept":
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=neg_id,
                agreed_price=int(reply.get("price", next_move.price)),
                duration_seconds=duration_seconds,
                rounds=round_idx,
                accepted_provision_terms=accepted_prov,
                accepted_escrow_terms_proposal=accepted_esc,
            )
        if seller_action in ("exit", "reject"):
            return NegotiationOutcome(
                status="exited",
                negotiation_id=neg_id,
                reason=reply.get("reason"),
                duration_seconds=duration_seconds,
                rounds=round_idx,
            )
        if seller_action != "counter":
            raise RuntimeError(f"Unexpected seller action mid-negotiation: {seller_action!r}")

        round_idx += 1

    # Hit max_rounds without converging.
    return NegotiationOutcome(
        status="exited",
        negotiation_id=neg_id,
        reason="max_rounds",
        duration_seconds=duration_seconds,
        rounds=max_rounds,
    )
