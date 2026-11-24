"""The account client consumes the registry producer's actual signed replies."""

import httpx
from market_core.rfq import (
    CreateRfq, RfqAccountClaim, RfqAccountRequest, RfqAudience, RfqInput,
    RfqMutationReceipt, RfqOperation, RfqTarget,
)
from market_identity import Ed25519Signer
import pytest
from registry_client.auth import REQUEST_ID_HEADER
from registry_client.rfq_account import RfqAccountError, SyncRfqAccountClient
from registry_client.rfq_registry import SyncRfqRegistryClient

from core_registry.api.market_auth import signed_context_response

# Deterministic fixture signers and fake account credential. Never use on a public network.
_REGISTRY = Ed25519Signer(bytes([21]) * 32)
_AUTHORITY = Ed25519Signer(bytes([22]) * 32)
_OTHER_REGISTRY = Ed25519Signer(bytes([23]) * 32)
_ACCOUNT_TOKEN = "synthetic-account-credential"
_ACCOUNT = RfqAccountClaim(namespace="test-accounts", subject="test-buyer")
_AUDIENCE = RfqAudience(name="registry-test", principal=_REGISTRY.identity.model_dump(mode="json"))
_CREATE = RfqTarget(RfqOperation.CREATE)
_ORIGIN = "https://account.example.test"
_RECEIPT = RfqMutationReceipt(resource_id="rfq-test", state="open", version=1, terms_revision=1)


def reply(target, request_id, *, signer=_REGISTRY, status=200, body=None):
    if body is None:
        body = _RECEIPT.model_dump(mode="json", exclude_none=True)
    emitted = signed_context_response(
        method=target.method, operation=target.operation.value, resource=target.resource,
        request_id=request_id, signer=signer, status=status, body=body,
    )
    return httpx.Response(emitted.status_code, content=emitted.body, headers=emitted.headers)


def client(handler):
    return SyncRfqAccountClient(
        _ORIGIN, registry=_AUDIENCE, credential=_ACCOUNT_TOKEN,
        transport=httpx.MockTransport(handler),
    )


def test_retry_uses_same_serialized_request_and_forwards_only_checked_proof():
    observed = []

    def registry(request):
        assert request.url.host == "registry.example.test"
        assert "Authorization" not in request.headers
        assert _ACCOUNT_TOKEN.encode() not in request.content
        return reply(_CREATE, request.headers[REQUEST_ID_HEADER])

    def account(request):
        assert request.url.host == "account.example.test"
        assert request.headers["Authorization"] == f"Bearer {_ACCOUNT_TOKEN}"
        envelope = RfqAccountRequest.model_validate_json(request.content)
        assert _ACCOUNT.subject.encode() not in request.content
        observed.append(request.content)
        with SyncRfqRegistryClient(
            "https://registry.example.test", signer=_AUTHORITY, audience=_AUDIENCE,
            transport=httpx.MockTransport(registry),
        ) as downstream:
            result = downstream.forward(_CREATE, _ACCOUNT, envelope)
        if len(observed) == 1:
            raise httpx.ReadError("simulated acknowledgement loss", request=request)
        return httpx.Response(result.status, json=result.body, headers=result.proof)

    with client(account) as account_client:
        assert account_client.exchange(_CREATE, CreateRfq(kind="compute", requirements={})) == _RECEIPT
    assert len(observed) == 2 and observed[0] == observed[1]


@pytest.mark.parametrize("mismatch", ["registry", "operation", "request"])
def test_rejects_another_registry_operation_or_request_id(mismatch):
    def account(request):
        envelope = RfqAccountRequest.model_validate_json(request.content)
        return reply(
            _CREATE if mismatch != "operation" else RfqTarget(RfqOperation.EDIT, "rfq-test"),
            envelope.request_id if mismatch != "request" else "previous-request",
            signer=_REGISTRY if mismatch != "registry" else _OTHER_REGISTRY,
        )

    with client(account) as account_client, pytest.raises(RfqAccountError, match="rfq_invalid_registry_reply"):
        account_client.exchange(_CREATE, CreateRfq(kind="compute", requirements={}))


def test_missing_route_is_distinct_from_signed_private_record_refusal():
    target = RfqTarget(RfqOperation.READ_RESPONSE, "rfq-test", "response-test")
    for supports_rfqs in (False, True):
        def account(request):
            if not supports_rfqs:
                return httpx.Response(404, json={"detail": "Not Found"})
            envelope = RfqAccountRequest.model_validate_json(request.content)
            return reply(target, envelope.request_id, status=404, body={"detail": "rfq_not_found"})

        expected = "rfq_not_found" if supports_rfqs else "rfq_not_supported"
        with client(account) as account_client, pytest.raises(RfqAccountError, match=expected):
            account_client.exchange(target, RfqInput())


def test_open_account_entry_lookup_needs_no_bearer_and_private_actions_do():
    target = RfqTarget(RfqOperation.READ, "rfq-test")
    requests = []
    opened = {
        "rfq_id": "rfq-test", "registry": _AUDIENCE.model_dump(mode="json"), "kind": "compute",
        "state": "open", "version": 1, "terms_revision": 1, "requirements": {},
    }

    def account(request):
        requests.append(request.url.path)
        assert "Authorization" not in request.headers
        envelope = RfqAccountRequest.model_validate_json(request.content)
        return reply(target, envelope.request_id, body=opened)

    with SyncRfqAccountClient(_ORIGIN, registry=_AUDIENCE, transport=httpx.MockTransport(account)) as public:
        assert public.exchange(target, RfqInput()).model_dump(mode="json") == opened
        with pytest.raises(RfqAccountError, match="rfq_auth_required"):
            public.exchange(_CREATE, CreateRfq(kind="compute", requirements={}))
    assert requests == [target.path]
