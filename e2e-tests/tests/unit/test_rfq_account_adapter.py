"""Exercise the two account credential forms on the same RFQ routes."""

import httpx
from market_core.rfq import RfqAccountRequest, RfqAudience, RfqInvocation, RfqOperation, RfqTarget
from market_identity import Ed25519Signer
import pytest
from registry_client.rfq_account import RfqAccountError, SyncRfqAccountClient

from tests.e2e.roles.helpers.rfq_account_adapter import AccountAuthority

# Deterministic test signing seeds. Never use on a public network.
_AUTHORITY = Ed25519Signer(bytes([21]) * 32)
_REGISTRY = Ed25519Signer(bytes([22]) * 32)
_OTHER_REGISTRY = Ed25519Signer(bytes([23]) * 32)
_AUDIENCE = RfqAudience(name="registry-test", principal=_REGISTRY.identity.model_dump(mode="json"))
_OTHER_AUDIENCE = RfqAudience(
    name=_AUDIENCE.name, principal=_OTHER_REGISTRY.identity.model_dump(mode="json"),
)
_TARGET = RfqTarget(RfqOperation.RESPOND, "same-rfq-id")
_READ = RfqTarget(RfqOperation.READ, _TARGET.rfq_id)
_ACCOUNT_ORIGIN = "https://account.example.test"
_REQUEST = RfqAccountRequest(
    registry=_AUDIENCE, request_id="test-response",
    inputs={
        "version": 1, "terms_revision": 1, "counterparty": "buyer-reference",
        "consent_to_share": True, "contact": {"email": "seller@example.test"},
    },
)


def account_http(authority):
    def dispatch(request):
        reply = authority.dispatch(request.url.path, request.headers, request.read())
        return httpx.Response(
            reply.status, json=reply.body, headers={"Cache-Control": "no-store", **reply.proof},
        )
    return httpx.MockTransport(dispatch)


@pytest.fixture
def adapter():
    invocations = []

    def registry(request):
        assert "Authorization" not in request.headers
        assert "Cookie" not in request.headers
        invocations.append(request.read())
        # Simulate a registry that has not been upgraded to support RFQs.
        return httpx.Response(404, json={"detail": "Not Found"})

    fixture = AccountAuthority(
        signer=_AUTHORITY, namespace="test-accounts",
        registries=[(_AUDIENCE, "https://registry.example.test")],
        registry_transport=httpx.MockTransport(registry),
    )
    with httpx.Client(base_url=_ACCOUNT_ORIGIN, transport=account_http(fixture)) as client:
        yield fixture, client, invocations


def test_requires_csrf_for_browser_write_and_derives_account_on_both_paths(adapter):
    authority, client, calls = adapter
    session = authority.issue("browser-account", can_share_contact=True, browser=True)
    cli = authority.issue("terminal-account", can_share_contact=True)
    cookie = {"Cookie": f"rfq_session={session.token}"}
    body = _REQUEST.model_dump(mode="json")

    assert client.post(_TARGET.path, headers=cookie, json=body).json()["detail"] == "rfq_csrf_required"
    assert calls == []
    assert session.csrf is not None
    browser = client.post(_TARGET.path, headers=cookie | {"X-CSRF-Token": session.csrf}, json=body)
    terminal = client.post(_TARGET.path, headers={"Authorization": f"Bearer {cli.token}"}, json=body)
    assert browser.status_code == terminal.status_code == 501
    assert browser.json() == terminal.json() == {"detail": "rfq_not_supported"}
    assert browser.headers["Cache-Control"] == terminal.headers["Cache-Control"] == "no-store"
    assert len(calls) == 2 and b"browser-account" in calls[0] and b"terminal-account" in calls[1]
    assert all(session.token.encode() not in call and cli.token.encode() not in call for call in calls)


def test_revocation_wrong_registry_and_injected_subject_stop_before_registry(adapter):
    authority, client, calls = adapter
    browsing = authority.issue("seller", can_share_contact=False)
    sharing = authority.issue("seller", can_share_contact=True)
    browse_headers = {"Authorization": f"Bearer {browsing.token}"}
    share_headers = {"Authorization": f"Bearer {sharing.token}"}
    body = _REQUEST.model_dump(mode="json")

    assert client.post(
        _TARGET.path, json=body, headers=browse_headers,
    ).json()["detail"] == "rfq_contact_permission_required"
    forged = client.post(_TARGET.path, headers=share_headers, json=body | {"subject": "other-account"})
    assert forged.status_code == 422
    wrong_registry = body | {"registry": _OTHER_AUDIENCE.model_dump(mode="json")}
    assert client.post(
        _TARGET.path, headers=share_headers, json=wrong_registry,
    ).json()["detail"] == "rfq_registry_audience_refused"

    authority.revoke_sharing(sharing)
    assert client.post(
        _TARGET.path, json=body, headers=share_headers,
    ).json()["detail"] == "rfq_contact_permission_required"
    read = RfqAccountRequest(registry=_AUDIENCE, request_id="scope-revoked", inputs={})
    assert client.post(_READ.path, json=read.model_dump(mode="json"), headers=share_headers).status_code == 501
    assert len(calls) == 1

    authority.revoke(sharing)
    assert client.post(_TARGET.path, json=body, headers=share_headers).status_code == 401
    assert len(calls) == 1


def test_open_discovery_recognizes_an_unupgraded_registry(adapter):
    _, client, calls = adapter
    read = RfqAccountRequest(registry=_AUDIENCE, request_id="open-unsupported", inputs={})
    reply = client.post(_READ.path, json=read.model_dump(mode="json"))
    assert reply.status_code == 501
    assert reply.json() == {"detail": "rfq_not_supported"}
    assert len(calls) == 1


def test_same_rfq_id_routes_to_the_selected_registry():
    calls = []

    def registry(request):
        assert request.url.path == _READ.path
        invocation = RfqInvocation.model_validate_json(request.read())
        calls.append((request.url.host, invocation.audience))
        return httpx.Response(404, json={"detail": "Not Found"})

    registries = [
        (_AUDIENCE, "https://first.example.test"),
        (_OTHER_AUDIENCE, "https://second.example.test"),
    ]
    authority = AccountAuthority(
        signer=_AUTHORITY, namespace="test-accounts", registries=registries,
        registry_transport=httpx.MockTransport(registry),
    )
    token = authority.issue("fixture-account", can_share_contact=True).token
    for audience, _ in registries:
        with SyncRfqAccountClient(
            _ACCOUNT_ORIGIN, registry=audience, credential=token, transport=account_http(authority),
        ) as client, pytest.raises(RfqAccountError, match="rfq_not_supported"):
            client.read_detail("same-rfq-id")
    assert calls == [("first.example.test", _AUDIENCE), ("second.example.test", _OTHER_AUDIENCE)]
