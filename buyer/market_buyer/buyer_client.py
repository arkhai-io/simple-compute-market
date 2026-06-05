"""Buyer-as-pure-client negotiation library.

The buyer doesn't run a storefront or any HTTP server. They pick a
seller, open a negotiation via HTTP, loop round-by-round until the
thread ends, and return the outcome. Every request is signed by the
buyer's wallet so the seller can verify without any prior
registration.

Public API:
    negotiate_with_seller(...) -> NegotiationOutcome

Per-round decisions go through ``market_policy.negotiation_middleware``
— same chain framework the seller uses. The buyer's default chain is
just the terminal strategy (``bisection`` or ``rl``); guards like
inventory match are seller-side.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationMiddleware,
    NegotiationRound,
    load_negotiation_chain,
    make_escrow_kind_dispatch_middleware,
    normalize_policies_by_escrow_kind_config,
    run_negotiation_chain,
)
from service.schemas import EscrowProposal, EscrowTerms, ProvisionTerms


DEFAULT_MAX_ROUNDS = 10
DEFAULT_TERMINAL = "bisection"
_RL_POLICY_NAMES = {"rl", "erc20_rl", "native_token_rl", "erc1155_rl"}


def _maybe_register_rl_middleware() -> None:
    """Trigger self-registration of the torch RL middleware.

    Mirrors the storefront-side helper: imports
    ``domain.compute.agent.app.policy.torch_arkhai_strategy`` so its
    ``register_negotiation_middleware("rl")`` call fires. Best-effort —
    if torch / pufferlib aren't installed, the chain loader raises its
    own actionable KeyError pointing at the [rl] extras.
    """
    try:
        import domain.compute.agent.app.policy.torch_arkhai_strategy  # noqa: F401
    except Exception:
        pass


def _policy_names_need_rl(policy_names: list[str]) -> bool:
    return any(name in _RL_POLICY_NAMES for name in policy_names)


def _policy_map_needs_rl(policies_by_kind: dict[str, list[str]]) -> bool:
    return any(_policy_names_need_rl(names) for names in policies_by_kind.values())


def _load_buyer_chain(
    *,
    policies: Any = None,
    policy_mode: str | None = None,
) -> list[NegotiationMiddleware]:
    """Load the buyer's negotiation chain.

    If ``policies`` is provided (from `[negotiation] policies = [...]`
    in `buyer.toml`), uses the explicit ordered list. Otherwise
    synthesizes the default chain `[buyer_escrow_shape_guard, <terminal>]`
    — the shape guard vetoes if the seller silently mutates a buyer-pinned
    field of the EscrowProposal (token swap, expiration push, escrow
    contract swap). ``<terminal>`` is `policy_mode` if set, else
    ``DEFAULT_TERMINAL`` (`"bisection"`).
    """
    policies_by_kind = normalize_policies_by_escrow_kind_config(policies)
    if policies_by_kind:
        if _policy_map_needs_rl(policies_by_kind):
            _maybe_register_rl_middleware()
        try:
            from market_buyer.common import buyer_chains
            chains = buyer_chains()
        except Exception:
            chains = {}
        chain_config_paths = {
            name: chain.alkahest_address_config_path
            for name, chain in chains.items()
        }
        return load_negotiation_chain(["buyer_escrow_shape_guard"]) + [
            make_escrow_kind_dispatch_middleware(
                policies_by_kind,
                chain_config_paths=chain_config_paths,
            )
        ]

    if policies:
        names = [str(p).strip() for p in policies if str(p).strip()]
    else:
        terminal = (policy_mode or "").strip() or DEFAULT_TERMINAL
        names = ["buyer_escrow_shape_guard", terminal]
    if _policy_names_need_rl(names):
        _maybe_register_rl_middleware()
    return load_negotiation_chain(names)


DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass
class NegotiationOutcome:
    """What came out of a full negotiation run from the buyer's POV.

    ``accepted_provision_terms`` and ``accepted_escrow_proposal``
    are populated when the seller echoed them back in the negotiation
    response (always on non-rejection paths). Settlement-time escrow
    construction reads from these — using the *seller-confirmed* values
    rather than the buyer's local proposal protects against any
    drift between sides.

    ``agreed_amount`` is the absolute total payment in base units of
    the escrow's payment token (i.e. ``accepted_escrow_proposal.fields
    ["amount"]``). Per-hour rates only exist as listing broadcasts;
    once a negotiation starts everything is absolute.
    """
    status: str                     # "agreed" | "exited"
    negotiation_id: Optional[str]   # None only if /new itself failed
    agreed_amount: Optional[int] = None
    duration_seconds: Optional[float] = None  # echoed from buyer's negotiation-init ask
    reason: Optional[str] = None    # populated on exit
    rounds: int = 0
    accepted_provision_terms: Optional[ProvisionTerms] = None
    accepted_escrow_proposal: Optional[EscrowProposal] = None
    accepted_escrow_terms: Optional[list[EscrowTerms]] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": self.status, "rounds": self.rounds}
        if self.negotiation_id is not None:
            d["negotiation_id"] = self.negotiation_id
        if self.agreed_amount is not None:
            d["agreed_amount"] = self.agreed_amount
        if self.duration_seconds is not None:
            d["duration_seconds"] = self.duration_seconds
        if self.reason is not None:
            d["reason"] = self.reason
        if self.accepted_provision_terms is not None:
            d["accepted_provision_terms"] = self.accepted_provision_terms.model_dump()
        if self.accepted_escrow_proposal is not None:
            d["accepted_escrow_proposal"] = self.accepted_escrow_proposal.model_dump()
        if self.accepted_escrow_terms is not None:
            d["accepted_escrow_terms"] = [
                term.model_dump() for term in self.accepted_escrow_terms
            ]
        return d


def _parse_accepted_terms_from_reply(
    reply: dict[str, Any],
) -> tuple[
    Optional[ProvisionTerms],
    Optional[EscrowProposal],
    Optional[list[EscrowTerms]],
]:
    """Extract the seller's echoed accepted terms from a negotiate reply.

    Returns (None, None) if the seller didn't include them — happens on
    exit/reject paths or against legacy sellers that haven't shipped the
    new fields yet.
    """
    raw_prov = reply.get("accepted_provision_terms")
    raw_esc = reply.get("accepted_escrow_proposal")
    raw_terms = reply.get("accepted_escrow_terms")
    prov = ProvisionTerms.model_validate(raw_prov) if isinstance(raw_prov, dict) else None
    esc = EscrowProposal.model_validate(raw_esc) if isinstance(raw_esc, dict) else None
    terms = (
        [EscrowTerms.model_validate(item) for item in raw_terms]
        if isinstance(raw_terms, list)
        else None
    )
    return prov, esc, terms


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
    identity_scheme: str = "eip191",
    identity_identifier: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Signed POST with JSON body. Raises RuntimeError on non-2xx.

    Emits ``X-Identity-Scheme`` + ``X-Identity`` so storefronts that have
    adopted the pluggable-identity dispatch (Phase 2) can route by scheme.
    Storefronts that haven't yet ignore the headers — back-compat is preserved.
    """
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Signature": signature,
        "X-Timestamp": str(timestamp),
        "X-Identity-Scheme": identity_scheme,
    }
    if identity_identifier:
        headers["X-Identity"] = identity_identifier
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
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
    observed, and the seller's last-known proposal. We replay that
    into the strategy and continue the round loop without going through
    ``/api/v1/negotiate/new`` again (the seller has the thread already).
    """
    negotiation_id: str
    transcript: list[NegotiationRound]
    last_seller_proposal: dict | None
    rounds_completed: int


def negotiate_with_seller(
    *,
    seller_url: str,
    buyer_address: str,
    buyer_private_key: str,
    listing_id: str,
    initial_price: float,
    max_price: float,
    provision_terms: Optional[ProvisionTerms] = None,
    escrow_proposal: Optional[EscrowProposal] = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    on_round: Optional[Callable[[int, dict, dict], None]] = None,
    chain: Optional[list[NegotiationMiddleware]] = None,
    resume: Optional[ResumeState] = None,
) -> NegotiationOutcome:
    """Run a synchronous negotiation with one seller, round-by-round.

    `initial_price` is what the buyer opens with (can be lower than max
    to haggle). `max_price` is the buyer's absolute ceiling — any seller
    counter at or below convergence to this gets accepted.

    `provision_terms` describes what the buyer wants the seller to
    deliver (duration, ssh key, compute spec) and `escrow_proposal`
    is the buyer's proposed on-chain escrow tuple — picks one of the
    listing's ``accepted_escrows`` entries by ``(chain_name,
    escrow_address)`` and supplies the buyer-committable EscrowData
    in ``fields`` plus ``expiration_unix``. Both are sent on
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
    transcript: list[NegotiationRound] = []
    # Captured from the seller's round-0 response and threaded forward.
    # The seller commits to these at /negotiate/new (they're persisted on
    # the negotiation thread); subsequent rounds don't re-echo them.
    accepted_prov: Optional[ProvisionTerms] = None
    accepted_esc: Optional[EscrowProposal] = None
    accepted_terms: Optional[list[EscrowTerms]] = None
    duration_seconds: Optional[float] = None  # populated from provision_terms or resume
    if chain is None:
        chain = _load_buyer_chain()

    # Pinned proposal: the buyer's first-round proposal — every field
    # set here is a buyer commitment the seller may not mutate. Used by
    # ``buyer_escrow_shape_guard`` in the chain.
    pinned_proposal: dict[str, Any] | None = None

    def _amount(p: dict | None) -> int | None:
        if not isinstance(p, dict):
            return None
        v = (p.get("fields") or {}).get("amount")
        return int(v) if v is not None else None

    if resume is not None:
        # Resume mode: skip /api/v1/negotiate/new and the first counter exchange.
        # We trust the run-log's recorded transcript and the seller's last
        # counter proposal; the strategy decides our next move from there.
        if resume.last_seller_proposal is None:
            raise RuntimeError(
                "Cannot resume — no seller counter proposal recorded in run-log."
            )
        neg_id = resume.negotiation_id
        transcript = list(resume.transcript)
        # Synthesize a `reply` dict shaped like the round-loop expects.
        reply: dict[str, Any] = {
            "negotiation_id": neg_id,
            "action": "counter",
            "proposal": resume.last_seller_proposal,
        }
        # Recover the buyer's first-pinned proposal from the transcript.
        for entry in transcript:
            if entry.sender == "us" and entry.proposal is not None:
                pinned_proposal = entry.proposal
                break
        round_idx = max(1, resume.rounds_completed)
    else:
        # --- Round 0: /api/v1/negotiate/new ---------------------------------------
        if provision_terms is None:
            raise RuntimeError(
                "provision_terms is required for fresh negotiations "
                "(what the seller will provision: duration, ssh_key, compute)"
            )
        if escrow_proposal is None:
            raise RuntimeError(
                "escrow_proposal is required for fresh negotiations "
                "(chain_name + escrow_address + fields + expiration_unix)"
            )
        duration_seconds = provision_terms.duration_seconds
        # Translate per-hour bounds → absolute amounts (× duration / 3600).
        # Listings broadcast per-hour rates; once the duration is fixed,
        # the whole negotiation runs on absolute totals.
        if duration_seconds is None or duration_seconds <= 0:
            raise RuntimeError(
                "provision_terms.duration_seconds must be > 0 to translate "
                "per-hour bounds into absolute amounts."
            )
        scale = float(duration_seconds) / 3600.0
        initial_amount = int(round(float(initial_price) * scale))
        ceiling_amount = float(max_price) * scale

        # Pin the buyer's first proposal: chain + escrow contract + token
        # came from the picked accepted_escrows entry; amount is round 0's
        # absolute opening bid.
        pinned_fields = dict(escrow_proposal.fields or {})
        pinned_fields["amount"] = initial_amount
        pinned_proposal = {
            "chain_name": escrow_proposal.chain_name,
            "escrow_address": escrow_proposal.escrow_address,
            "fields": pinned_fields,
            "literal_fields": dict(escrow_proposal.literal_fields or escrow_proposal.fields or {}),
            "rates": [
                r.model_dump() if hasattr(r, "model_dump") else dict(r)
                for r in (escrow_proposal.rates or [])
            ],
            "demands": [
                d.model_dump() if hasattr(d, "model_dump") else dict(d)
                for d in (escrow_proposal.demands or [])
            ],
            "expiration_unix": escrow_proposal.expiration_unix,
        }

        new_body = {
            "listing_id": listing_id,
            "buyer_address": buyer_address,
            "provision_terms": provision_terms.model_dump(),
            "proposal": pinned_proposal,
        }
        sig, ts = _sign(f"negotiate_new:{listing_id}", buyer_private_key)
        reply = _post(
            f"{seller_url}/api/v1/negotiate/new", new_body,
            signature=sig, timestamp=ts,
            identity_identifier=buyer_address,
        )
        if on_round:
            on_round(0, new_body, reply)

        neg_id = reply.get("negotiation_id")
        seller_action = reply.get("action")
        accepted_prov, accepted_esc, accepted_terms = _parse_accepted_terms_from_reply(reply)

        if seller_action == "accept":
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=neg_id,
                agreed_amount=_amount(reply.get("proposal")) or initial_amount,
                duration_seconds=duration_seconds,
                rounds=0,
                accepted_provision_terms=accepted_prov,
                accepted_escrow_proposal=accepted_esc,
                accepted_escrow_terms=accepted_terms,
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

        transcript.append(NegotiationRound(
            round_number=0, sender="us", action="initial",
            proposal=pinned_proposal,
        ))
        seller_round0_proposal = reply.get("proposal")
        transcript.append(NegotiationRound(
            round_number=0, sender="them", action="counter",
            proposal=seller_round0_proposal if isinstance(seller_round0_proposal, dict) else None,
        ))
        round_idx = 1

    # --- Rounds 1..N: /negotiate/{id} ----------------------------------
    while round_idx <= max_rounds:
        seller_counter_proposal = reply.get("proposal")
        if not isinstance(seller_counter_proposal, dict):
            raise RuntimeError(f"Seller counter without proposal: {reply!r}")

        # Append the seller's current counter to history so the chain
        # sees it as their_last_proposal.
        round_history = list(transcript)
        if not round_history or round_history[-1].sender != "them":
            round_history.append(NegotiationRound(
                round_number=len(round_history),
                sender="them",
                action="counter",
                proposal=seller_counter_proposal,
            ))
        ceiling_amount = (
            float(max_price) * float(duration_seconds) / 3600.0
            if duration_seconds is not None
            else float(max_price)
        )
        ctx = NegotiationContext(
            direction="minimize",
            our_reference_amount=ceiling_amount,
            listing={},
            our_escrow_proposal=pinned_proposal,
            available_resources={},
            max_rounds=max_rounds,
        )
        next_move = run_negotiation_chain(chain, round_history, ctx)

        body: dict[str, Any] = {
            "action": next_move.action,
            "buyer_address": buyer_address,
        }
        if next_move.action in ("counter", "accept"):
            if next_move.proposal is None:
                raise RuntimeError(
                    f"chain returned {next_move.action!r} without a proposal"
                )
            body["proposal"] = next_move.proposal
        elif next_move.action in ("exit", "reject"):
            body["reason"] = next_move.reason or "buyer_exit"

        sig, ts = _sign(f"negotiate_continue:{neg_id}", buyer_private_key)
        reply = _post(
            f"{seller_url}/api/v1/negotiate/{neg_id}", body,
            signature=sig, timestamp=ts,
            identity_identifier=buyer_address,
        )
        if on_round:
            on_round(round_idx, body, reply)

        # If our chain rejected (shape guard veto), the buyer terminates
        # locally without trusting any seller reply.
        if next_move.action == "reject":
            return NegotiationOutcome(
                status="exited",
                negotiation_id=neg_id,
                reason=next_move.reason or "buyer_reject",
                duration_seconds=duration_seconds,
                rounds=round_idx,
            )

        # After we sent our move, the seller has replied with either
        # a matching terminal (accept/exit) or a further counter.
        if next_move.action == "accept":
            # We told the seller we accept; their reply should echo accept.
            if reply.get("action") == "accept":
                reply_prov, reply_esc, reply_terms = _parse_accepted_terms_from_reply(reply)
                return NegotiationOutcome(
                    status="agreed",
                    negotiation_id=neg_id,
                    agreed_amount=(
                        _amount(reply.get("proposal"))
                        or _amount(next_move.proposal)
                    ),
                    duration_seconds=duration_seconds,
                    rounds=round_idx,
                    accepted_provision_terms=reply_prov or accepted_prov,
                    accepted_escrow_proposal=reply_esc or accepted_esc,
                    accepted_escrow_terms=reply_terms or accepted_terms,
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

        # next_move was counter → record both sides of this round.
        transcript.append(NegotiationRound(
            round_number=round_idx, sender="us", action="counter",
            proposal=next_move.proposal,
        ))
        seller_reply_action = reply.get("action") or "counter"
        seller_reply_proposal = reply.get("proposal")
        transcript.append(NegotiationRound(
            round_number=round_idx,
            sender="them",
            action=seller_reply_action if seller_reply_action in ("counter", "accept", "exit", "reject") else "counter",
            proposal=seller_reply_proposal if isinstance(seller_reply_proposal, dict) else None,
        ))

        seller_action = reply.get("action")
        if seller_action == "accept":
            reply_prov, reply_esc, reply_terms = _parse_accepted_terms_from_reply(reply)
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=neg_id,
                agreed_amount=(
                    _amount(seller_reply_proposal)
                    or _amount(next_move.proposal)
                ),
                duration_seconds=duration_seconds,
                rounds=round_idx,
                accepted_provision_terms=reply_prov or accepted_prov,
                accepted_escrow_proposal=reply_esc or accepted_esc,
                accepted_escrow_terms=reply_terms or accepted_terms,
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
