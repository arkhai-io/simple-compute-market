"""Seller layer: what a seller runs on their own machine.

A seller (someone with compute to sell) runs a storefront and a
provisioning service on their machine. They depend on an external chain
and a marketplace registry, but are otherwise independent of any other
seller or the market operator.

Produces the ``seller_node`` fixture: an identifier for the seller's
running storefront and provisioning service. "Node" here means "one
seller's machine", not blockchain node.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

import pytest

from src.settings import settings

log = logging.getLogger(__name__)


def _http_get(url: str, timeout: float = 5) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except urllib.error.URLError as exc:
        return 0, str(exc)


@pytest.fixture(scope="session")
def seller_node(external_world: dict, registry_layer: dict) -> dict:
    """A seller's running machine: storefront + provisioning service.

    This fixture represents "a seller has launched their node and is
    ready to publish offers". Depends on the external chain (to sign
    attestations) and the registry (to publish into).
    """
    url = settings.get("SELLER.API_URL")
    if not url:
        pytest.skip("SELLER.API_URL not configured — skipping seller-dependent tests")

    return {
        "external": external_world,
        "registry": registry_layer,
        "storefront_url": url,
        "wallet_address": external_world["seller"]["wallet_address"],
        "private_key": external_world["seller"]["private_key"],
    }


@pytest.mark.roles_layer_seller
class TestSellerNode:
    """Verify a seller's node (storefront + provisioning) is running."""

    def test_storefront_reachable(self, seller_node: dict):
        """Storefront responds on its HTTP port."""
        status, body = _http_get(f"{seller_node['storefront_url']}/.well-known/agent.json")
        assert status == 200, (
            f"Storefront at {seller_node['storefront_url']} not reachable: "
            f"status={status} body={body[:200]}"
        )
