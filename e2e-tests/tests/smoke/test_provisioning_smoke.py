"""Smoke tests for the deployed provisioning service.

The provisioning service gates every non-health route on a single
marketplace signature and asserted role, verified per caller.
Read-only checks are selected by the Helm smoke hook; write-path checks
are kept under a separate marker because they mutate provisioning
state.
"""

from __future__ import annotations

import logging

import pytest

from market_identity import Identity, TrustedIdentitySet, create_signer
from vm_provisioning_operator import ProvisioningError, SyncProvisioningClient
from vm_provisioning_operator import HostCreate, HostUpdate

log = logging.getLogger(__name__)


def _client(
    provisioning_settings: dict,
    seller_settings: dict,
) -> SyncProvisioningClient:
    credential = provisioning_settings.get("admin_credential") or ""
    authority = provisioning_settings.get("authority_identifier") or ""
    if not credential or not authority:
        pytest.skip(
            "provisioning.admin_credential and provisioning.authority_identifier "
            "are required: provisioning authenticates each caller and signs its "
            "responses, so a smoke check needs both halves configured."
        )
    return SyncProvisioningClient(
        provisioning_settings["api_url"],
        create_signer(
            str(provisioning_settings.get("admin_scheme") or "eip191"), str(credential)
        ),
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
        """GET /health -> 200 with status field present."""
        with _client(provisioning_settings, seller_settings) as client:
            data = client.get_health()
        assert "status" in data, f"Missing status field: {data}"
        assert data["status"] in ("ok", "degraded"), f"Unexpected status: {data['status']}"
        log.info("Health: %s", data)

    @pytest.mark.provisioning_readonly
    def test_ansible_readiness_returns_structured_response(
        self, provisioning_settings: dict, seller_settings: dict
    ):
        """GET /api/v1/system/ansible/readiness returns structured diagnostics."""
        with _client(provisioning_settings, seller_settings) as client:
            data = client.get_ansible_readiness()
        assert "inventory" in data, f"Missing inventory field: {data}"
        assert "playbook" in data, f"Missing playbook field: {data}"
        assert "ssh_keys" in data, f"Missing ssh_keys field: {data}"
        inv = data["inventory"]
        assert "source" in inv
        assert "host_count" in inv
        log.info(
            "Readiness: ansible_version=%s, host_count=%s",
            data.get("ansible_version"),
            inv.get("host_count"),
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
            first = hosts[0].name
            data = client.check_connectivity(first)
        assert isinstance(data.reachable, bool), f"Missing reachable field: {data}"
        log.info("Connectivity for %s: reachable=%s", first, data.reachable)

    @pytest.mark.provisioning_write
    def test_host_crud_round_trip(
        self, provisioning_settings: dict, seller_settings: dict
    ):
        """Register -> GET -> disable -> re-enable -> cleanup a transient test host."""
        test_host = HostCreate(
            name="smoke-test-host",
            kvm_host="192.0.2.1",
            ssh_user="ubuntu",
            ssh_key_type="path",
            ssh_key_value="/home/appuser/.ssh/id_ed25519",
            gpu_count=0,
            enabled=True,
        )

        with _client(provisioning_settings, seller_settings) as client:
            try:
                reg = client.register_host(test_host)
            except ProvisioningError as exc:
                if exc.status_code != 409:
                    raise
                log.info("smoke-test-host already exists - updating instead of inserting")
                reg = client.update_host(
                    "smoke-test-host",
                    HostUpdate(kvm_host=test_host.kvm_host, ssh_user=test_host.ssh_user),
                )
                client.enable_host("smoke-test-host")

            assert reg.name == "smoke-test-host"
            assert not hasattr(reg, "ssh_key_value"), "ssh_key_value must never be returned"

            got = client.get_host("smoke-test-host")
            assert got.kvm_host == "192.0.2.1"

            disabled = client.disable_host("smoke-test-host")
            assert disabled.enabled is False

            names = [h.name for h in client.list_hosts().hosts]
            assert "smoke-test-host" not in names

            enabled = client.enable_host("smoke-test-host")
            assert enabled.enabled is True

            client.disable_host("smoke-test-host")

        log.info("Host CRUD round-trip passed")

    @pytest.mark.provisioning_write
    def test_auth_enforcement_when_enabled(
        self, provisioning_settings: dict, seller_settings: dict
    ):
        """An unsigned POST to a protected route is refused.

        The canonical client cannot express this case — it requires a signer at
        construction — so the request goes out raw. That is the point of the
        check: enforcement must not depend on the caller being well-behaved.
        """
        import httpx

        base = str(provisioning_settings["api_url"]).rstrip("/")
        resp = httpx.post(
            f"{base}/api/v1/hosts/kvm1/vms",
            json={"vm_target": "smoke-test-vm"},
            timeout=15.0,
        )
        assert resp.status_code in (401, 403), (
            f"Unsigned request to a protected provisioning route returned "
            f"{resp.status_code}; expected a refusal. Body: {resp.text[:200]}"
        )
        log.info("Auth enforcement confirmed: %s without a signature", resp.status_code)
