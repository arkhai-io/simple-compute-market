"""The names the service's event store keeps its consumers' destinations under."""

from __future__ import annotations

from compute_provisioning_service.event_names import peer_destination


def test_a_peer_s_destination_is_named_for_its_url():
    assert peer_destination("http://storefront:8001/") == "storefront@storefront:8001"
    assert peer_destination("https://shop.example/agents/a") == "storefront@shop.example~agents~a"
    assert peer_destination("https://shop.example/agents/b") != peer_destination(
        "https://shop.example/agents/a"
    )


def test_a_peer_s_credentials_stay_out_of_its_destination_name():
    assert peer_destination("https://user:secret@shop.example:8443") == (
        "storefront@shop.example:8443"
    )
