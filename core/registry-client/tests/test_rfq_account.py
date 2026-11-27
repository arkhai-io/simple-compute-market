"""The account client refuses invalid admissions and preserves retry identity."""

import httpx
from market_core.rfq import CreateRfq, RfqAudience, RfqInput, RfqOperation, RfqSummary, RfqTarget, ShareContact
from market_identity import Ed25519Signer
import pytest

from registry_client.rfq_account import RfqAccountError, SyncRfqAccountClient

# Deterministic test identity and fake account credential. Never use on a public network.
_REGISTRY = Ed25519Signer(bytes([21]) * 32)
_ACCOUNT_TOKEN = "synthetic-account-credential"
_AUDIENCE = RfqAudience(name="registry-test", principal=_REGISTRY.identity.model_dump(mode="json"))
_CREATE = RfqTarget(RfqOperation.CREATE)
_ORIGIN = "https://account.example.test"


def client(handler):
    return SyncRfqAccountClient(
        _ORIGIN, registry=_AUDIENCE, credential=_ACCOUNT_TOKEN,
        transport=httpx.MockTransport(handler),
    )


def test_malformed_account_origin_is_reported_as_invalid_configuration():
    with pytest.raises(ValueError, match="invalid trusted RFQ account origin"):
        SyncRfqAccountClient("http://localhost:invalid", registry=_AUDIENCE)


def test_unencodable_input_preserves_its_request_id_without_dispatch():
    def account(_request):
        pytest.fail("unencodable operation inputs must not be sent")

    with client(account) as account_client, pytest.raises(RfqAccountError) as refusal:
        account_client.create(
            CreateRfq(kind="compute", requirements={"description": "\ud800"}),
            request_id="unencodable-input",
        )
    assert refusal.value.code == "rfq_invalid_inputs"
    assert refusal.value.request_id == "unencodable-input"


def test_unsigned_success_and_redirect_are_refused():
    def account(request):
        if request.url.path == "/rfqs/create":
            return httpx.Response(307, headers={"Location": "https://elsewhere.example.test/rfqs/create"})
        assert request.url.host == "account.example.test"
        summary = RfqSummary(
            rfq_id="rfq-test", kind="compute", registry=_AUDIENCE,
            version=1, terms_revision=1, state="open", requirements={},
        )
        return httpx.Response(200, json=summary.model_dump(mode="json"))

    with client(account) as account_client:
        with pytest.raises(RfqAccountError, match="rfq_invalid_account_reply") as refusal:
            account_client.exchange(_CREATE, CreateRfq(kind="compute", requirements={}))
        assert refusal.value.status == 307
        with pytest.raises(RfqAccountError, match="rfq_invalid_account_reply"):
            account_client.exchange(RfqTarget(RfqOperation.READ, "rfq-test"), RfqInput())


@pytest.mark.parametrize("failure_type", [httpx.RemoteProtocolError, httpx.DecodingError])
def test_ambiguous_acknowledgement_retries_only_once_and_keeps_the_retry_id(failure_type):
    sent = []

    def account(request):
        sent.append(request.content)
        raise failure_type("acknowledgement lost", request=request)

    with client(account) as account_client, pytest.raises(RfqAccountError) as error:
        account_client.exchange(
            _CREATE, CreateRfq(kind="compute", requirements={}), request_id="one-attempt",
        )
    assert error.value.code == "rfq_account_transport_failed"
    assert error.value.request_id == "one-attempt"
    assert len(sent) == 2 and sent[0] == sent[1]


def test_contact_inputs_cannot_be_sent_to_a_read_operation():
    def account(request):
        pytest.fail("invalid inputs must be rejected before sending an account credential")

    with client(account) as account_client, pytest.raises(TypeError, match="input model"):
        account_client.exchange(
            RfqTarget(RfqOperation.READ, "rfq-test"),
            ShareContact(
                version=1, terms_revision=1, counterparty="recipient", consent_to_share=True,
                contact={"email": "buyer@example.test"},
            ),
        )


@pytest.mark.parametrize(("detail", "expected"), (
    ("rfq_contact_permission_required", "rfq_contact_permission_required"),
    ("sensitive unexpected message", "rfq_account_forbidden"),
))
def test_hosted_refusal_uses_only_known_error_codes(detail, expected):
    def account(_request):
        return httpx.Response(403, json={"detail": detail})

    with client(account) as account_client, pytest.raises(RfqAccountError) as refusal:
        account_client.exchange(_CREATE, CreateRfq(kind="compute", requirements={}), request_id="request-ref")
    assert refusal.value.code == expected
    assert refusal.value.request_id == "request-ref"
