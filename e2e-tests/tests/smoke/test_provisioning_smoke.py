"""Smoke tests for the deployed provisioning service.

The provisioning service gates every non-health route on a single
marketplace signature and asserted role, verified per caller. Every check
here is stateless and writes nothing: the Helm smoke hook runs the read-only
checks and the authentication check, and a service's write paths are its
integration suite's to prove.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from market_identity import Identity, TrustedIdentitySet, create_signer
from compute_provisioning_client import SyncComputeProvisioningClient

log = logging.getLogger(__name__)


def _client(
    provisioning_settings: dict,
    seller_settings: dict,
) -> SyncComputeProvisioningClient:
    credential = provisioning_settings.get("admin_credential") or ""
    authority = provisioning_settings.get("authority_identifier") or ""
    if not credential or not authority:
        pytest.skip(
            "provisioning.admin_credential and provisioning.authority_identifier "
            "are required: provisioning authenticates each caller and signs its "
            "responses, so a smoke check needs both halves configured."
        )
    return SyncComputeProvisioningClient(
        provisioning_settings["api_url"],
        create_signer(
            str(provisioning_settings.get("admin_scheme") or "eip191"), str(credential)
        ),
        "admin",
        TrustedIdentitySet(
            identities=(
                Identity(
                    scheme=str(
                        provisioning_settings.get("authority_scheme") or "eip191"
                    ),
                    identifier=str(authority),
                ),
            )
        ),
        timeout=15.0,
    )


@pytest.mark.provisioning
class TestProvisioningSmoke:
    @pytest.mark.provisioning_readonly
    def test_health_returns_ok(
        self, provisioning_settings: dict, seller_settings: dict
    ):
        """GET /health -> a typed liveness body, ok or degraded."""
        with _client(provisioning_settings, seller_settings) as client:
            data = client.get_health()
        assert data.status in ("ok", "degraded"), f"Unexpected status: {data.status}"
        log.info("Health: %s", data)

    @pytest.mark.provisioning_readonly
    def test_status_reports_execution_and_the_ansible_component(
        self, provisioning_settings: dict, seller_settings: dict
    ):
        """GET /api/v1/system/status reports what executes jobs and the
        Ansible readiness component, typed, whether or not it is degraded."""
        with _client(provisioning_settings, seller_settings) as client:
            status = client.get_system_status()
        assert status.execution.executors, f"No composed executors: {status.execution}"
        assert "execution" in status.checks, f"Missing execution check: {status.checks}"
        ansible = status.component("ansible")
        assert ansible is not None, f"Missing ansible component: {status.components}"
        log.info(
            "Status: execution.mocked=%s, ansible ready=%s, version=%s",
            status.execution.mocked,
            ansible.ready,
            ansible.detail.payload.get("ansible_version"),
        )

    @pytest.mark.provisioning_readonly
    def test_list_hosts_returns_200(
        self, provisioning_settings: dict, seller_settings: dict
    ):
        """GET /api/v1/hosts/ returns a hosts list."""
        with _client(provisioning_settings, seller_settings) as client:
            data = client.list_hosts()
        assert isinstance(data.hosts, list), f"Missing hosts list: {data}"
        log.info("Registered hosts: %d", len(data.hosts))

    @pytest.mark.provisioning_readonly
    def test_connectivity_check_on_first_host_if_available(
        self, provisioning_settings: dict, seller_settings: dict
    ):
        """If any hosts are registered, connectivity returns a structured result."""
        with _client(provisioning_settings, seller_settings) as client:
            hosts = client.list_hosts().hosts
            if not hosts:
                pytest.skip("No hosts registered - skipping connectivity check")
            first = hosts[0].host_id
            data = client.check_connectivity(first)
        assert isinstance(data.reachable, bool), f"Missing reachable field: {data}"
        log.info("Connectivity for %s: reachable=%s", first, data.reachable)

    @pytest.mark.provisioning_security
    def test_auth_enforcement_when_enabled(self, provisioning_settings: dict):
        """An unsigned read of a protected route is refused.

        A read, so the check changes nothing even where enforcement is broken.
        The canonical client cannot express this case — it requires a signer at
        construction — so the request goes out raw. That is the point of the
        check: enforcement must not depend on the caller being well-behaved.
        """
        base = str(provisioning_settings["api_url"]).rstrip("/")
        resp = httpx.get(f"{base}/api/v1/hosts/", timeout=15.0)
        assert resp.status_code in (401, 403), (
            f"Unsigned request to a protected provisioning route returned "
            f"{resp.status_code}; expected a refusal. Body: {resp.text[:200]}"
        )
        log.info("Auth enforcement confirmed: %s without a signature", resp.status_code)
