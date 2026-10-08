"""Publish fulfillment evidence as an Alkahest string obligation.

An Alkahest string obligation has no operation identity the chain
deduplicates: submitting the same data twice creates two attestations. So a
caller that may retry must know, after a failure, whether the chain can hold
an attestation it did not see. ``AlkahestFulfillmentPublisher`` answers that
with one of four outcomes rather than an exception:

- ``published``: the attestation exists, and its UID is returned;
- ``not_submitted``: the failure provably preceded the submission;
- ``rejected``: the node refused the transaction or it reverted, so no
  attestation exists and a retry cannot duplicate one;
- ``outcome_unknown``: the transaction may have reached the chain.

The pinned client reports failures only as messages. A failure it does not let
the publisher place is ``outcome_unknown``, the one outcome that never permits
a blind retry. See ``openspec/specs/settlement-servicing/spec.md``, "A
fulfillment submission with an unknown outcome is never repeated".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .txlock import chain_tx_lock

PublicationOutcome = Literal[
    "published", "not_submitted", "rejected", "outcome_unknown"
]

# Messages with which a node refuses a transaction it never accepted, or with
# which a mined transaction reverted. Either way no attestation was created.
# A message that names a transaction the node already holds ("already known")
# is deliberately absent: that transaction may still be mined.
_REFUSALS = (
    "revert",
    "insufficient funds",
    "nonce too low",
    "intrinsic gas too low",
    "gas required exceeds allowance",
)


@dataclass(frozen=True)
class FulfillmentPublication:
    """What one publication attempt established about the chain."""

    outcome: PublicationOutcome
    reference: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if (self.outcome == "published") != bool(self.reference):
            raise ValueError("a reference is reported exactly when published")


class AlkahestFulfillmentPublisher:
    """Submit evidence data as a string obligation referencing an escrow."""

    def __init__(self, client: Any, *, chain_name: str | None = None) -> None:
        self._client = client
        self._chain_name = chain_name

    async def publish(
        self, *, condition_anchor: str, data: str
    ) -> FulfillmentPublication:
        """Publish ``data`` against the escrow named by ``condition_anchor``."""

        if not isinstance(condition_anchor, str) or not condition_anchor.strip():
            return FulfillmentPublication(
                "not_submitted", reason="condition_anchor_missing"
            )
        if not isinstance(data, str) or not data:
            return FulfillmentPublication("not_submitted", reason="data_missing")
        submit = getattr(
            getattr(self._client, "string_obligation", None), "do_obligation", None
        )
        if submit is None:
            return FulfillmentPublication(
                "not_submitted", reason="client_has_no_string_obligation"
            )
        try:
            async with chain_tx_lock(self._chain_name):
                uid = await submit(data, condition_anchor)
        except Exception as exc:  # the pinned client raises untyped errors
            return _classify(exc)
        reference = str(uid or "").strip()
        if not reference:
            # The call returned, so the transaction may have been mined; an
            # empty answer says nothing about which attestation it created.
            return FulfillmentPublication(
                "outcome_unknown", reason="empty_attestation_uid"
            )
        return FulfillmentPublication("published", reference=reference)


def _classify(exc: Exception) -> FulfillmentPublication:
    message = str(exc).lower()
    if any(refusal in message for refusal in _REFUSALS):
        return FulfillmentPublication("rejected", reason=type(exc).__name__)
    return FulfillmentPublication("outcome_unknown", reason=type(exc).__name__)
