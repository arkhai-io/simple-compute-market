import pytest

from market_core.registry_descriptor import RegistryPrincipal
from market_core.rfq import RfqAccountClaim, RfqAudience, RfqInvocation, RfqOperation, RfqTarget
from market_identity import (
    Ed25519Signer,
    TrustedIdentitySet,
    VerificationCode,
    verify_request,
)

from registry_client.rfq_auth import sign_rfq_invocation

# Deterministic fixture seeds. Never use these on a public network.
_AUTHORITY = Ed25519Signer(bytes([1]) * 32)
_REGISTRY = Ed25519Signer(bytes([2]) * 32)
_TIME = 1_800_000_000


def _invocation(*, allowed: bool = False, inputs: dict | None = None) -> RfqInvocation:
    return RfqInvocation(
        account=RfqAccountClaim(namespace="test-accounts", subject="buyer-a",
                                can_share_contact=allowed),
        audience=RfqAudience(
            name="registry-test",
            principal=RegistryPrincipal.model_validate(_REGISTRY.identity.model_dump(mode="json")),
        ),
        inputs={} if inputs is None else inputs,
    )


def test_authority_binds_account_and_operation_in_the_v2_proof():
    target = RfqTarget(RfqOperation.CREATE)
    signed = sign_rfq_invocation(
        signer=_AUTHORITY, target=target,
        invocation=_invocation(inputs={"node_count": 100}),
        request_id="request-a", timestamp=_TIME,
    )
    context = {
        "now": _TIME, "max_skew": 300, "expected_role": "service",
        "expected_method": "POST", "expected_resource": target.resource,
        "expected_principals": TrustedIdentitySet(identities=(_AUTHORITY.identity,)),
    }

    assert verify_request(
        signed.request, body=signed.body(), expected_operation=target.operation.value, **context,
    ).code is VerificationCode.VERIFIED
    assert verify_request(
        signed.request, body=signed.body(),
        expected_operation=RfqOperation.SEARCH.value, **context,
    ).code is VerificationCode.CONTEXT_MISMATCH


@pytest.mark.parametrize("allowed,consent", [(False, True), (True, False), (True, 1)])
def test_contact_sharing_requires_permission_and_affirmative_consent(allowed, consent):
    with pytest.raises(ValueError, match="contact sharing"):
        sign_rfq_invocation(
            signer=_AUTHORITY, target=RfqTarget(RfqOperation.RESPOND, "rfq-a"),
            invocation=_invocation(allowed=allowed, inputs={"consent_to_share": consent}),
        )
