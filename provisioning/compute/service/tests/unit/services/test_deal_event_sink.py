"""The storefront peer's client: how it is built and when it is rebuilt."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet

from compute_provisioning_service.identity import ProvisioningIdentityContext
from compute_provisioning_service.services.deal_event_sink import (
    StorefrontPeer,
    storefront_peer_url,
)


def test_the_peer_s_client_is_rebuilt_when_the_pinned_principals_change():
    principals = [TrustedIdentitySet(identities=(Ed25519Signer(b"\x12" * 32).identity,))]
    authority = SimpleNamespace(active_principals=lambda role: principals[-1])
    identity = ProvisioningIdentityContext(
        signer=Ed25519Signer(b"\x11" * 32),
        storefront_principal=principals[0].identities[0],
        admin_principal=Ed25519Signer(b"\x13" * 32).identity,
        storefront_site_id="site-west",
    )
    peer = StorefrontPeer("https://configured.example", identity, authority)

    first = peer.client()
    assert peer.client() is first
    principals.append(TrustedIdentitySet(identities=(Ed25519Signer(b"\x14" * 32).identity,)))
    assert peer.client() is not first
    peer.close()


def test_no_configured_storefront_is_refused_when_a_delivery_needs_it():
    peer = StorefrontPeer("", MagicMock(), MagicMock())

    with pytest.raises(RuntimeError, match="storefront_url"):
        peer.client()


def test_the_peer_url_drops_a_trailing_slash():
    assert storefront_peer_url(SimpleNamespace(storefront_url="https://configured.example/")) == (
        "https://configured.example"
    )
    assert storefront_peer_url(SimpleNamespace(storefront_url=None)) == ""
