"""Verified request context shared by registry RFQ services."""

from dataclasses import dataclass

from market_core.rfq import RfqInvocation, RfqTarget


@dataclass(frozen=True)
class VerifiedRfqRequest:
    target: RfqTarget
    invocation: RfqInvocation
    request_id: str
