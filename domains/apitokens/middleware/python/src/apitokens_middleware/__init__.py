"""API-tokens gating middleware (Python).

A seller-side component that gates a downstream HTTP app on prepaid API
credits: it extracts the bearer key, verifies it against the tokens
service (short-TTL cache), meters each request by consuming credits
(synchronously near exhaustion, optionally batched above a low-balance
threshold), and maps a drained key to a 402 whose body points at the
listing to buy more (the re-purchase loop). All verification and
accounting authority stays in the service.

The behavioral contract — status codes and machine-readable bodies —
is shared with the TypeScript and Rust middlewares and pinned by the
conformance fixtures under ``domains/apitokens/middleware/conformance``.
"""

from .asgi import TokenGateMiddleware
from .client import ConsumeResult, TokensClient, VerifyResult
from .config import GateConfig, PurchasePointer
from .gate import (
    INVALID_API_KEY,
    MISSING_API_KEY,
    GateDecision,
    TokenGate,
    key_id_from_secret,
    parse_bearer,
)

__all__ = [
    "ConsumeResult",
    "GateConfig",
    "GateDecision",
    "INVALID_API_KEY",
    "MISSING_API_KEY",
    "PurchasePointer",
    "TokenGate",
    "TokenGateMiddleware",
    "TokensClient",
    "VerifyResult",
    "key_id_from_secret",
    "parse_bearer",
]
