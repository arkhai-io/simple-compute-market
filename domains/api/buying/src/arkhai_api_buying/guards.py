"""The family's buyer-side negotiation guards.

``answer_key_challenge`` answers a seller that enforces an asymmetric key
ownership claim by countering with a nonce (``key_challenge`` in its proposal)
and expects the buyer to sign ``(nonce, negotiation_id, terms hash)`` with the
key's registered owner keypair before pricing proceeds. Sellers bind a new key
to the purchasing principal and never challenge, so the guard defers to the
next link on every such negotiation; when a challenge does arrive it exits
with a clear reason, because an unanswerable challenge must not surface as
chain exhaustion. No owner keypair is configurable, so a challenge always exits.
"""

from __future__ import annotations

import logging
from typing import Any

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
    NegotiationStep,
    register_negotiation_middleware,
    their_last_proposal,
)

logger = logging.getLogger(__name__)

#: Default buyer chain guards: the pinned-shape guard every domain uses, plus
#: the key-challenge pass-through. Passed to ``core_buyer.negotiation_client``
#: as ``default_guards``.
BUYER_GUARDS: tuple[str, ...] = (
    "buyer_escrow_shape_guard",
    "answer_key_challenge",
)


def extract_key_challenge(proposal: Any) -> dict[str, Any] | None:
    """The seller's key challenge riding a counter proposal, if any."""
    if not isinstance(proposal, dict):
        return None
    raw = proposal.get("key_challenge")
    return raw if isinstance(raw, dict) else None


@register_negotiation_middleware("answer_key_challenge")
def answer_key_challenge(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Answer (or refuse) a seller key-possession challenge.

    Pass-through unless the seller's last message carries a
    ``key_challenge``. With no owner keypair available the decision is
    a clean exit naming the reason — the buyer either claimed an
    ``ed25519``-owned key without the matching keypair, or hit a seller
    speaking a scheme this CLI doesn't ship yet.
    """
    challenge = extract_key_challenge(their_last_proposal(history))
    if challenge is None:
        return None, context

    logger.info(
        "[NEGOTIATION] seller issued a key possession challenge "
        "(nonce=%r) — no owner keypair support is configured",
        challenge.get("nonce"),
    )
    return (
        NegotiationDecision(
            action="exit",
            reason=(
                "key_challenge_unanswerable: the seller demands a key "
                "possession proof and no owner keypair is configured — "
                "the ed25519 owner scheme is not shipped yet; use a "
                "wallet-bound key (the v1 default) instead"
            ),
        ),
        context,
    )
