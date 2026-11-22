"""Request authentication independent of supply publisher admission and replay."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import injected_time
from fastapi import HTTPException
from market_core.rfq import RfqAudience, RfqInvocation, RfqTarget
from market_identity import (
    CanonicalizationError,
    TrustedIdentitySet,
    VerificationCode,
    verify_request,
)
from pydantic import ValidationError

from core_registry.api.market_auth import request_signature_fields
from core_registry.rfq_context import VerifiedRfqRequest


@dataclass(frozen=True)
class RfqTrust:
    audience: RfqAudience
    authorities: Mapping[str, TrustedIdentitySet]

    def __post_init__(self) -> None:
        pins = [identity for trust in self.authorities.values() for identity in trust.identities]
        if len(set(pins)) != len(pins):
            raise ValueError("RFQ authority signer pins must be disjoint across namespaces")

    def verify(
        self,
        *,
        headers: Mapping[str, str],
        method: str,
        target: RfqTarget,
        body: Any,
    ) -> VerifiedRfqRequest:
        try:
            invocation = RfqInvocation.model_validate(body)
        except ValidationError as exc:
            raise HTTPException(422, "invalid_rfq_invocation") from exc
        trusted = self.authorities.get(invocation.account.namespace)
        if trusted is None or invocation.audience != self.audience:
            raise HTTPException(401, "rfq_authority_not_admitted")

        try:
            envelope = request_signature_fields(
                headers, method=method, operation=target.operation.value,
                resource=target.resource, body=body,
            )
        except CanonicalizationError as exc:
            raise HTTPException(400, "invalid_rfq_json") from exc
        result = verify_request(
            envelope, body=body, now=injected_time.now(), max_skew=300,
            expected_role=target.caller_role, expected_method=target.method,
            expected_operation=target.operation.value, expected_resource=target.resource,
            expected_principals=trusted,
        )
        if result.code != VerificationCode.VERIFIED:
            raise HTTPException(401, result.code.value)

        if target.operation.shares_contact:
            if not invocation.account.can_share_contact:
                raise HTTPException(403, "contact_sharing_not_authorized")
            if invocation.inputs.get("consent_to_share") is not True:
                raise HTTPException(400, "contact_sharing_consent_required")

        return VerifiedRfqRequest(target, invocation, envelope["request_id"])
