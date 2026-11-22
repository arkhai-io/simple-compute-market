"""Sign RFQ requests after the account entry point has verified its credential."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from market_core.rfq import RfqInvocation, RfqTarget
from market_identity import AuthenticatedRequest, Identity, Signer, TrustedIdentitySet

from registry_client.auth import (
    authenticate_request,
    authentication_headers,
    verify_authenticated_response,
)


@dataclass(frozen=True)
class SignedRfqRequest:
    request: AuthenticatedRequest
    invocation: RfqInvocation

    def headers(self) -> dict[str, str]:
        return authentication_headers(self.request)

    def body(self) -> dict[str, Any]:
        return self.invocation.model_dump(mode="json")

    def verify_response(
        self,
        headers: Mapping[str, str],
        *,
        status: int,
        body: Any,
        now: int | None = None,
    ) -> None:
        expected_principal = Identity.model_validate(
            self.invocation.audience.principal.model_dump(mode="json")
        )
        verify_authenticated_response(
            headers=headers, expected_registries=TrustedIdentitySet(identities=(expected_principal,)),
            request=self.request, status=status, body=body, now=now,
        )


def sign_rfq_invocation(
    *,
    signer: Signer,
    target: RfqTarget,
    invocation: RfqInvocation,
    request_id: str | None = None,
    timestamp: int | None = None,
) -> SignedRfqRequest:
    """Bind the route, admitted subject and exact request inputs."""

    if target.operation.shares_contact:
        if not invocation.account.can_share_contact:
            raise ValueError("contact sharing permission required")
        if invocation.inputs.get("consent_to_share") is not True:
            raise ValueError("explicit contact sharing consent required")
    request = authenticate_request(
        signer=signer, role="service", method=target.method,
        operation=target.operation.value, resource=target.resource,
        body=invocation.model_dump(mode="json"), request_id=request_id,
        timestamp=timestamp,
    )
    return SignedRfqRequest(request, invocation.model_copy(deep=True))
