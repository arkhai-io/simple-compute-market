"""Smoke tests for a deployed seller storefront.

Replaces the legacy test_agents.py, which tested the symmetric two-
storefront flow (one "buyer" storefront posting buy-shaped orders, one
"seller" posting sell-shaped). Buyers no longer host a storefront —
they're a pure HTTP client surfaced via the `market` CLI / arkhai_vms_buyer
library — so what the helm smoke pod actually wants to confirm is "the
seller storefront is reachable and on-chain registered".

Tagged ``@pytest.mark.storefront`` so the helm test pod's
``pytest -m storefront`` selector still picks them up.
"""

from __future__ import annotations

import logging

import pytest

import uuid
from datetime import datetime, timezone

from market_identity import (
    EMPTY_BODY,
    Identity,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    create_signer,
    sign_request,
)
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
    signer = create_signer("eip191", seller_settings["private_key"])
    client = SyncStorefrontClient(
        seller_api_url,
        signer,
        caller_role="seller",
        expected_publishers=TrustedIdentitySet(
            identities=(
                Identity(
                    scheme="eip191", identifier=signer.identity.identifier
                ),
            )
        ),
    )
    yield client
    client.close()



def _signed_status_headers(seller_settings: dict) -> dict[str, str]:
    """v2 headers for GET /api/v1/system/status as the storefront administrator.

    The route is an administrator operation, so a raw probe has to sign like
    any other caller. Kept as a helper because two checks below read the
    response directly rather than through the typed client.
    """
    credential = seller_settings.get("admin_credential", "")
    if not credential:
        pytest.skip(
            "seller.admin_credential not configured — /api/v1/system/status is "
            "an administrator operation."
        )
    signer = create_signer(
        str(seller_settings.get("admin_scheme") or "eip191"), str(credential)
    )
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role="admin",
            principal=signer.identity,
            method="GET",
            operation="admin_system_status",
            resource="system/status",
            request_id=uuid.uuid4().hex,
            timestamp=int(datetime.now(timezone.utc).timestamp()),
            body_hash=canonical_body_hash(EMPTY_BODY),
        ),
    )
    return {
        "X-Market-Signature-Version": authenticated.protocol,
        "X-Market-Identity-Scheme": authenticated.principal.scheme.value,
        "X-Market-Identity-Identifier": authenticated.principal.identifier,
        "X-Market-Role": authenticated.role,
        "X-Market-Request-ID": authenticated.request_id,
        "X-Market-Timestamp": str(authenticated.timestamp),
        "X-Market-Signature": authenticated.proof.value,
    }


@pytest.mark.storefront
class TestStorefrontRegistration:
    """Verify the deployed seller storefront is reachable and its identity is published."""

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
        headers = _signed_status_headers(seller_settings)
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
        headers = _signed_status_headers(seller_settings)
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

    def test_site_projections_loaded(
        self,
        seller_api_url: str,
        seller_settings: dict,
    ) -> None:
        """GET /api/v1/system/status must report every site's projections loaded.

        The storefront holds no inventory of its own: every listing derives
        from the projections it loads from each configured site. A site whose
        projection is not loaded publishes nothing and refuses negotiations
        against its listings, which surfaces several layers away as
        ``409 no_matching_inventory``. ``site_projections`` reports each
        family's load state per site, outside ``checks``.
        """
        credential = seller_settings.get("admin_credential", "")
        if not credential:
            pytest.skip(
                "seller.admin_credential not configured — /api/v1/system/status is "
                "an administrator operation, and the administrator is a separate "
                "principal from the seller."
            )
        publisher = create_signer("eip191", seller_settings["private_key"]).identity
        client = SyncStorefrontClient(
            seller_api_url,
            create_signer(
                str(seller_settings.get("admin_scheme") or "eip191"), str(credential)
            ),
            caller_role="admin",
            expected_publishers=TrustedIdentitySet(
                identities=(
                    Identity(scheme="eip191", identifier=publisher.identifier),
                )
            ),
        )
        try:
            status = client.get_system_status()
        except Exception as exc:
            pytest.fail(f"Could not reach /api/v1/system/status: {exc}")
        finally:
            client.close()

        sites = status.site_projections or {}
        assert sites, (
            "site_projections absent or empty in /api/v1/system/status: the "
            "storefront has no capacity site configured, so it can publish nothing.\n"
            "Check [capacity.sites] in the storefront configuration."
        )
        unloaded = {
            f"{site}/{family}": (view or {}).get("state")
            for site, families in sites.items()
            for family, view in (families or {}).items()
            if (view or {}).get("state") != "loaded"
        }
        assert not unloaded, (
            f"site projections not loaded: {unloaded}.\n"
            "Check that each site's provisioning service is reachable and trusts "
            "this storefront, then refresh with POST /api/v1/admin/capacity/projections/refresh."
        )
        log.info("✓ Site projections loaded: %s", sorted(sites))
