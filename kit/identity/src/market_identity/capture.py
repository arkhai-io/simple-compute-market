"""Exact signed messages delivered synchronously before commitment can proceed.

A party that keeps its counterparty's signed message as evidence captures it at
the signed transport boundary, where it was verified: the sink runs before the
caller goes on, so a failed durable write keeps the caller from reaching
commitment. A version 3 message is captured as its record and exact body, which
are everything verification needs; a version 2 envelope with the raw headers it
arrived under.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json

from market_identity.canonical import EMPTY_BODY, canonical_body_hash
from market_identity.codes import VerificationCode
from market_identity.evidence import verify_request_evidence, verify_response_evidence
from market_identity.models import AuthenticatedRequest, AuthenticatedResponse, TrustedIdentitySet
from market_identity.records import RequestRecord, ResponseRecord

CapturedMessage = AuthenticatedRequest | AuthenticatedResponse | RequestRecord | ResponseRecord


@dataclass(frozen=True)
class CapturedEnvelope:
    """One verified signed message, its exact body, and the principals it was
    verified against.

    ``envelope`` is a version 3 request or response record, whose ``headers``
    are empty, or a version 2 envelope with its raw headers.
    """

    envelope: CapturedMessage
    body: bytes
    headers: Mapping[str, str]
    verified_at: int
    expected_principals: TrustedIdentitySet


EnvelopeCapture = Callable[[CapturedEnvelope], None]


def capture_envelope(
    sink: EnvelopeCapture | None,
    *,
    envelope: CapturedMessage,
    raw_body: bytes | None,
    headers: Mapping[str, str] | None = None,
    verified_at: int,
    expected_principals: TrustedIdentitySet,
) -> None:
    """Hand a verified message and its exact body to ``sink``, if there is one.

    The body must be the one signed: a version 3 record is verified with it
    against ``expected_principals``, and a version 2 envelope's canonical body hash
    compared, before the sink runs.
    """

    if sink is None:
        return
    if raw_body is None:
        raise ValueError("envelope capture requires the original transport body")
    if isinstance(envelope, (RequestRecord, ResponseRecord)):
        if headers:
            raise ValueError("a captured record carries no headers")
        verification = (
            verify_request_evidence(envelope, body=raw_body, trusted=expected_principals)
            if isinstance(envelope, RequestRecord)
            else verify_response_evidence(envelope, body=raw_body, trusted=expected_principals)
        )
        if verification.code != VerificationCode.VERIFIED:
            raise ValueError(f"captured body or record differs from what was signed: {verification.code.value}")
    else:
        value = json.loads(raw_body) if raw_body else EMPTY_BODY
        if canonical_body_hash(value) != envelope.body_hash:
            raise ValueError("captured body differs from the verified body")
    # A failed durable write must prevent the caller from reaching commitment.
    sink(CapturedEnvelope(envelope, raw_body, dict(headers or {}), verified_at, expected_principals))
