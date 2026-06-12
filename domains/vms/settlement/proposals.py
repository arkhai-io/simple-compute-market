"""Compatibility shim — settlement proposal materialization moved to
``market_alkahest.proposals`` when the API-tokens domain became the
second consumer; it is Alkahest escrow vocabulary, not VM vocabulary."""

from market_alkahest.proposals import (  # noqa: F401
    accepted_escrow_artifacts_from_proposal,
    escrow_proposal_from_accepted_entry,
    proposal_is_oracle_gated,
)
