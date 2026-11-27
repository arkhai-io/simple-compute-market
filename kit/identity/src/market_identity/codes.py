"""The classifications every verification answers, for any transport.

Its own module because the version 2 verifiers, the version 3 profile, the
evidence verifiers and the capture seam all answer in it, and the capture seam
verifies records through the profile: kept here, none of them imports another
only for the codes.
"""

from __future__ import annotations

from enum import Enum


class VerificationCode(str, Enum):
    """Closed authentication classifications suitable for any transport."""

    VERIFIED = "verified"
    EXACT_RETRY = "exact_retry"
    CHANGED_REUSE = "changed_reuse"
    UNSUPPORTED_VERSION = "unsupported_version"
    UNKNOWN_SCHEME = "unknown_scheme"
    WRONG_PRINCIPAL = "wrong_principal"
    MALFORMED_ENVELOPE = "malformed_envelope"
    CONTEXT_MISMATCH = "context_mismatch"
    BODY_HASH_MISMATCH = "body_hash_mismatch"
    TIMESTAMP_SKEW = "timestamp_skew"
    INVALID_PROOF = "invalid_proof"
