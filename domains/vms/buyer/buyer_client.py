"""VM shim over the core buyer negotiation client.

The round loop, chain loading, and outcome parsing moved to
``core_buyer.negotiation_client`` when the API-credits domain became the
second schema plugin. The seam that moved with it: listings broadcast
**per-unit** rates and the core client scales them to absolute amounts
by ``unit_count`` — this module supplies the VM unit, the lease hour
(``duration_seconds / 3600``), and re-attaches ``duration_seconds`` to
the outcome for VM callers and run-log compatibility.

``rl``-named policies in buyer.toml resolve through the VM domain's declared
negotiation capability: the buyer role composes a catalogue from installed
domain contracts, and this domain offers its torch strategy when the requested
policy set names it. Importing this module installs nothing.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from arkhai_vms import VmProvisionTerms
from core_buyer.negotiation_client import (  # noqa: F401 — re-exports
    DEFAULT_MAX_ROUNDS,
    DEFAULT_TIMEOUT_SECONDS,
    ResumeState,
    _load_buyer_chain,
    _parse_accepted_terms_from_reply,
    _post,
    _sign,
)
from core_buyer.negotiation_client import (
    NegotiationOutcome as CoreNegotiationOutcome,
)
from core_buyer.negotiation_client import (
    negotiate_with_seller as _core_negotiate_with_seller,
)
from market_alkahest.schemas import EscrowProposal
from market_policy.negotiation_middleware import NegotiationMiddleware


@dataclass
class NegotiationOutcome(CoreNegotiationOutcome):
    """Core outcome plus the VM domain's ``duration_seconds`` echo.

    ``duration_seconds`` is the buyer's lease ask from negotiation init
    (None on resume) — the VM reading of the core ``unit_count``
    (hours × 3600).
    """

    duration_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        if self.duration_seconds is not None:
            d["duration_seconds"] = self.duration_seconds
        return d


def negotiate_with_seller(
    *,
    seller_url: str,
    buyer_address: str,
    buyer_private_key: str,
    listing_id: str,
    initial_price: float,
    max_price: float,
    provision_terms: VmProvisionTerms | None = None,
    escrow_proposal: EscrowProposal | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    on_round: Callable[[int, dict, dict], None] | None = None,
    chain: list[NegotiationMiddleware] | None = None,
    resume: ResumeState | None = None,
    policy_params: dict[str, Any] | None = None,
) -> NegotiationOutcome:
    """Run a synchronous negotiation with one seller, round-by-round.

    VM instantiation of ``core_buyer.negotiation_client
    .negotiate_with_seller``: prices are per-hour rates, scaled to
    absolute amounts by the lease duration fixed in
    ``provision_terms.duration_seconds``.
    """
    duration_seconds: float | None = None
    if resume is None:
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

    core_outcome = _core_negotiate_with_seller(
        seller_url=seller_url,
        buyer_address=buyer_address,
        buyer_private_key=buyer_private_key,
        listing_id=listing_id,
        initial_price=initial_price,
        max_price=max_price,
        unit_count=(
            float(duration_seconds) / 3600.0 if duration_seconds is not None else None
        ),
        provision_terms=provision_terms,
        escrow_proposal=escrow_proposal,
        max_rounds=max_rounds,
        on_round=on_round,
        chain=chain,
        resume=resume,
        policy_params=policy_params,
    )
    return NegotiationOutcome(
        **{
            f.name: getattr(core_outcome, f.name)
            for f in dataclasses.fields(CoreNegotiationOutcome)
        },
        duration_seconds=duration_seconds,
    )
