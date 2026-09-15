"""Registry publication credentials: exact at the boundary, absent from diagnostics.

Only the HTTP transport is substituted, so the bearer credential, signature
headers and request body are the ones production would send.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from market_identity import Ed25519Signer
from registry_client import ListingRequest, RegistryClientError

from arkhai_bare_metal_storefront import publication_cli

# Obviously synthetic development-only credential and signing key. Both are
# fixture values and must never be used on a public network.
_DEV_WRITE_KEY = "synthetic-dev-write-key"
_SIGNER = Ed25519Signer(bytes.fromhex("22" * 32))


class _Captured(Exception):
    """Stops the exchange once the outgoing request has been observed.

    The registry client verifies the signed response before returning, which a
    transport stub cannot produce; raising here keeps the assertion on the real
    request the client put on the wire.
    """

    def __init__(self, request: httpx.Request) -> None:
        super().__init__("captured")
        self.request = request


def _environment(monkeypatch, api_key: str | None) -> None:
    monkeypatch.setenv(
        "BARE_METAL_STOREFRONT_REGISTRY_PRINCIPALS",
        json.dumps(
            [{"scheme": _SIGNER.identity.scheme.value, "identifier": _SIGNER.identity.identifier}]
        ),
    )
    monkeypatch.setenv("BARE_METAL_STOREFRONT_REGISTRY_URL", "https://registry.example")
    monkeypatch.setenv("BARE_METAL_STOREFRONT_REGISTRY_AUTHORITY", "registry-dev")
    if api_key is None:
        monkeypatch.delenv("BARE_METAL_STOREFRONT_REGISTRY_API_KEY", raising=False)
    else:
        monkeypatch.setenv("BARE_METAL_STOREFRONT_REGISTRY_API_KEY", api_key)


def _registry(handler):
    return publication_cli._registry(
        SimpleNamespace(marketplace_signer=_SIGNER),
        transport=httpx.MockTransport(handler),
    )


def _publish(client) -> dict:
    return publication_cli._publish_registry_listing(
        client,
        listing_id="listing-1",
        listing_resource={"kind": "bare_metal.v1"},
        accepted_escrows=[],
        settlement_options=[],
        demands=[],
        max_duration_seconds=3600,
        storefront_url="https://storefront.example",
    )


def _sent_request(monkeypatch, api_key: str | None) -> httpx.Request:
    _environment(monkeypatch, api_key)

    def handler(request: httpx.Request) -> httpx.Response:
        raise _Captured(request)

    client = _registry(handler)
    try:
        with pytest.raises(_Captured) as captured:
            client.publish_listing(
                ListingRequest(
                    listing_id="listing-1",
                    listing_resource={"kind": "bare_metal.v1"},
                    accepted_escrows=[],
                    settlement_options=[],
                    demands=[],
                    max_duration_seconds=3600,
                    storefront_url="https://storefront.example",
                )
            )
    finally:
        client.close()
    return captured.value.request


def test_publication_sends_the_configured_write_credential(monkeypatch):
    request = _sent_request(monkeypatch, _DEV_WRITE_KEY)

    assert request.headers["Authorization"] == f"Bearer {_DEV_WRITE_KEY}"
    # The credential authenticates the caller; it never replaces the seller's
    # per-request signature, which the registry verifies as well.
    assert request.headers["X-Market-Identity-Scheme"] == "ed25519"


@pytest.mark.parametrize("api_key", [None, ""])
def test_publication_without_a_credential_sends_no_bearer(monkeypatch, api_key):
    request = _sent_request(monkeypatch, api_key)

    assert "authorization" not in request.headers


@pytest.mark.parametrize("api_key", [f"{_DEV_WRITE_KEY}\n", f" {_DEV_WRITE_KEY}"])
def test_unsendable_credential_is_refused_without_echoing_it(monkeypatch, api_key):
    _environment(monkeypatch, api_key)

    with pytest.raises(ValueError) as raised:
        _registry(lambda request: httpx.Response(200, json={}))

    assert _DEV_WRITE_KEY not in str(raised.value)


class _RejectingClient:
    """A registry that rejects the credential and quotes it back."""

    def _reject(self, *_args, **_kwargs):
        raise RegistryClientError(
            "POST",
            f"https://registry.example/listings?key={_DEV_WRITE_KEY}",
            401,
            json.dumps({"detail": f"api key {_DEV_WRITE_KEY} is not valid"}),
        )

    publish_listing = _reject
    update_listing = _reject


def _assert_redacted(exc: BaseException, *expected: str) -> None:
    reason = str(exc)
    for fragment in expected:
        assert fragment in reason
    assert _DEV_WRITE_KEY not in reason
    assert "is not valid" not in reason
    assert "registry.example" not in reason
    # The original exception is the leak; it must not ride along as a cause.
    assert exc.__cause__ is None
    assert exc.__suppress_context__ is True


def test_rejected_publish_is_reported_by_type_and_status_only():
    with pytest.raises(publication_cli.RegistryPublicationError) as raised:
        _publish(_RejectingClient())

    _assert_redacted(raised.value, "RegistryClientError", "401", "listing.publish")


def test_rejected_close_is_reported_by_type_and_status_only():
    with pytest.raises(publication_cli.RegistryPublicationError) as raised:
        publication_cli._close_registry_listing(_RejectingClient(), "listing-1")

    _assert_redacted(raised.value, "RegistryClientError", "401", "listing.update")


def test_transport_rejection_does_not_repeat_the_sent_header(monkeypatch):
    _environment(monkeypatch, _DEV_WRITE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.LocalProtocolError(
            f"Illegal header value {request.headers['Authorization']!r}"
        )

    client = _registry(handler)
    try:
        with pytest.raises(publication_cli.RegistryPublicationError) as raised:
            _publish(client)
    finally:
        client.close()

    _assert_redacted(raised.value, "LocalProtocolError", "listing.publish")
