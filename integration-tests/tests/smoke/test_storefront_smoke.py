"""Smoke tests for a deployed seller storefront.

Replaces the legacy test_agents.py, which tested the symmetric two-
storefront flow (one "buyer" storefront posting buy-shaped orders, one
"seller" posting sell-shaped). Buyers no longer host a storefront —
they're a pure HTTP client surfaced via the `market` CLI / domains.vms.buyer
library — so what the helm smoke pod actually wants to confirm is "the
seller storefront is reachable and on-chain registered".

Tagged ``@pytest.mark.storefront`` so the helm test pod's
``pytest -m storefront`` selector still picks them up.
"""

from __future__ import annotations

import logging

import pytest

from storefront_client import SyncStorefrontClient

log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def seller_api_url(seller_settings) -> str:
    url = seller_settings.get("api_url", "")
    if not url:
        pytest.fail(
            "seller.api_url is not configured.\n"
            "Set it via ARKHAI_SELLER__API_URL, config.yml, or --seller-api-url."
        )
    return url.rstrip("/")


@pytest.fixture(scope="module")
def seller_client(seller_api_url: str, seller_settings: dict) -> SyncStorefrontClient:
    client = SyncStorefrontClient(
        base_url=seller_api_url,
        private_key=seller_settings["private_key"],
    )
    yield client
    client.close()


@pytest.mark.storefront
class TestStorefrontRegistration:
    """Verify the deployed seller storefront is reachable and its identity is published."""

    def test_storefront_publishes_agent_wallet(
        self, seller_api_url: str, seller_settings: dict
    ) -> None:
        """GET /.well-known/agent-wallet.json must echo back the configured wallet.

        Post-pluggable-identity the agent-wallet well-known is the only
        identity surface peers consult; it advertises the EVM address
        settlement counterparties verify against.
        """
        import httpx

        try:
            resp = httpx.get(
                f"{seller_api_url}/.well-known/agent-wallet.json", timeout=5.0,
            )
        except Exception as exc:
            pytest.fail(f"Could not reach /.well-known/agent-wallet.json: {exc}")

        assert resp.status_code == 200, (
            f"agent-wallet returned {resp.status_code}: {resp.text[:200]}"
        )
        body = resp.json()
        published = (body.get("agent_wallet_address") or "").lower()
        configured = (seller_settings.get("wallet_address") or "").lower()
        assert published, "agent-wallet returned an empty address."
        assert published == configured, (
            f"agent-wallet address {published!r} != configured {configured!r}"
        )
        log.info("✓ Storefront publishes wallet %s", published)

    def test_storefront_registry_connectivity(
        self,
        seller_api_url: str,
        seller_settings: dict,
    ) -> None:
        """GET /api/v1/system/status must report checks.registry == 'ok'.

        Guards against misconfigured registry.url in config.toml — this
        failure would cause resume_listing to silently return
        registry_status='error' and the e2e deal test to fail at stage 05.
        """
        import httpx
        admin_key = seller_settings.get("admin_api_key", "")
        headers = {"X-Admin-Key": admin_key} if admin_key else {}
        try:
            resp = httpx.get(
                f"{seller_api_url}/api/v1/system/status",
                headers=headers,
                timeout=5.0,
            )
        except Exception as exc:
            pytest.fail(f"Could not reach /api/v1/system/status: {exc}")

        assert resp.status_code == 200, (
            f"GET /api/v1/system/status returned {resp.status_code}: {resp.text[:200]}"
        )
        body = resp.json()
        registry_check = body.get("checks", {}).get("registry", "absent")
        assert registry_check == "ok", (
            f"Storefront cannot reach registry. checks.registry={registry_check!r}.\n"
            f"Verify registry.url in the storefront's config.toml points to a reachable\n"
            f"indexer endpoint from inside the storefront container.\n"
            f"Full status response: {body}"
        )
        log.info("✓ Storefront registry connectivity ok")

    def test_negotiation_strategy_viable(
        self,
        seller_api_url: str,
        seller_settings: dict,
    ) -> None:
        """GET /api/v1/system/status must report a viable negotiation strategy.

        Guards against the rl strategy being configured but torch being
        unavailable in the container — in that case every /negotiate/new call
        returns exit_negotiation at round 0, causing stage 10 of the e2e test
        to fail with a 409 on force-accept.  Catching this here saves the entire
        multi-stage e2e run.
        """
        import httpx
        admin_key = seller_settings.get("admin_api_key", "")
        headers = {"X-Admin-Key": admin_key} if admin_key else {}
        try:
            resp = httpx.get(
                f"{seller_api_url}/api/v1/system/status",
                headers=headers,
                timeout=5.0,
            )
        except Exception as exc:
            pytest.fail(f"Could not reach /api/v1/system/status: {exc}")

        assert resp.status_code in (200, 503), (
            f"Unexpected status {resp.status_code}: {resp.text[:200]}"
        )
        body = resp.json()
        strat = body.get("checks", {}).get("negotiation_strategy", "absent")
        assert strat != "absent", (
            "checks.negotiation_strategy absent from status response. "
            "Ensure the storefront image includes the updated system_controller.py."
        )
        assert "exit_on_probe" not in strat, (
            f"Negotiation strategy would exit on every round: {strat!r}\n"
            "Fix: set [seller.negotiation] policies = ['has_matching_inventory_guard', 'escrow_shape_guard', 'bisection'] in config.toml,\n"
            "or install torch in the container if rl is required."
        )
        log.info("✓ Negotiation strategy viable: %s", strat)

    def test_resource_portfolio_seeded(
        self,
        seller_api_url: str,
        seller_settings: dict,
    ) -> None:
        """GET /api/v1/system/status must report resource_count > 0.

        Guards against the CSV importer writing to a different SQLite path
        than the running server reads — a silent misconfiguration where the
        storefront has no inventory and refuses all /negotiate/new calls with
        409 no_matching_inventory.

        resource_count is a top-level field (not in checks) on the full
        diagnostic status endpoint, populated by querying the resources table
        directly on the server.
        """
        admin_key = seller_settings.get("admin_api_key", "")
        if not admin_key:
            pytest.skip(
                "seller.admin_api_key not configured — cannot call admin-gated "
                "/api/v1/system/status endpoint. Set admin_api_key in config."
            )
        client = SyncStorefrontClient(
            base_url=seller_api_url,
            private_key=seller_settings["private_key"],
            admin_key=admin_key,
        )
        try:
            status = client.get_system_status()
        except Exception as exc:
            pytest.fail(f"Could not reach /api/v1/system/status: {exc}")
        finally:
            client.close()

        resource_count = status.resource_count
        assert resource_count is not None, (
            "resource_count absent from /api/v1/system/status response.\n"
            "Rebuild the storefront image with the updated system_service.py."
        )
        assert resource_count > 0, (
            f"resource_count={resource_count} — storefront has no registered compute resources.\n"
            "The resource CSV importer likely wrote to a different SQLite path than the server reads.\n"
            "Check that the compose command passes --db-path matching [seller].db_path in config.toml.\n"
            "Run the importer manually:\n"
            "  docker exec bob-storefront python scripts/import_resources_csv.py \\\n"
            "    --csv src/market_storefront/data/kvm1-machine.csv \\\n"
            "    --db-path src/market_storefront/data/storefront/agent.db"
        )
        log.info("✓ Resource portfolio seeded: resource_count=%d", resource_count)
