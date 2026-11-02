"""Exact transport envelopes delivered synchronously before commitment can proceed."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json

from market_identity.canonical import EMPTY_BODY, canonical_body_hash
from market_identity.models import AuthenticatedRequest, AuthenticatedResponse, TrustedIdentitySet


@dataclass(frozen=True)
class CapturedEnvelope:
    envelope: AuthenticatedRequest | AuthenticatedResponse
    body: bytes
    headers: Mapping[str, str]
    verified_at: int
    expected_principals: TrustedIdentitySet


EnvelopeCapture = Callable[[CapturedEnvelope], None]


def capture_envelope(
    sink: EnvelopeCapture | None,
    *,
    envelope: AuthenticatedRequest | AuthenticatedResponse,
    raw_body: bytes | None,
    headers: Mapping[str, str] | None,
    verified_at: int,
    expected_principals: TrustedIdentitySet,
) -> None:
    if sink is None:
        return
    if raw_body is None:
        raise ValueError("envelope capture requires the original transport body")
    value = json.loads(raw_body) if raw_body else EMPTY_BODY
    if canonical_body_hash(value) != envelope.body_hash:
        raise ValueError("captured body differs from the verified body")
    # A failed durable write must prevent the caller from reaching commitment.
    sink(CapturedEnvelope(envelope, raw_body, dict(headers or {}), verified_at, expected_principals))
