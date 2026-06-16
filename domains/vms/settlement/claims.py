"""Compatibility shim — the alkahest.v1 claim hooks moved to
``market_alkahest.claim_hooks`` when the API-tokens domain became the
second domain collecting through the claims engine."""

from market_alkahest.claim_hooks import (  # noqa: F401
    AlkahestClaimHooks,
    _demand_bytes,
)
