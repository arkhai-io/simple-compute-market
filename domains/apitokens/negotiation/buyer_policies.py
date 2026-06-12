"""API-tokens buyer-side negotiation middlewares.

``answer_key_challenge`` is the buyer mirror of the seller's planned
``key_possession_challenge`` middleware (design-api-tokens-domain.md,
"Key ownership"): a seller enforcing an asymmetric (``ed25519``) key
ownership claim *counters* with a nonce — ``key_challenge`` in the
message; message content is schema vocabulary — and expects the buyer
to sign ``(nonce, negotiation_id, terms hash)`` with the key's
registered owner keypair before pricing proceeds.

This ships in the API-tokens buyer's default chain from day one as a
pass-through: v1 sellers bind keys to the purchasing wallet
(``key_owned_by_buyer_wallet``) and never challenge, so the middleware
defers to the next link on every real v1 negotiation. When a challenge
*does* arrive it exits with a clear reason instead of passing — an
unanswerable challenge must not surface as chain exhaustion. The
signing path lands with the ``ed25519`` identity scheme in
``arkhai-kit-identity`` (today the kit ships only ``eip191``), at which
point a configured owner keypair turns the exit into a signed counter.
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

#: Default buyer chain guards for token deals: the pinned-shape guard
#: every domain uses, plus the key-challenge pass-through. Passed to
#: ``core_buyer.negotiation_client`` as ``default_guards``.
APITOKENS_BUYER_GUARDS: tuple[str, ...] = (
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
