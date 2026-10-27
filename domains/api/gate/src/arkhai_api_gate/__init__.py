"""The api family's bearer gate (Python).

A seller-side component that gates a downstream HTTP app on prepaid
credits: it extracts the bearer key, verifies it against the family
authority (short-TTL cache), meters each request by consuming credits
(synchronously near exhaustion, optionally batched above a low-balance
threshold), and maps a drained key to a 402 whose body points at the
listing to buy more (the re-purchase loop). The authority alone
verifies keys and keeps the accounts.

The behavioral contract — status codes and machine-readable bodies —
is shared with the TypeScript and Rust gates and pinned by the
conformance fixtures under ``domains/apicredits/middleware/conformance``.
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
