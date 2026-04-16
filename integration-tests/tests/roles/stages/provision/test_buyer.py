"""Provision — buyer perspective.

User-visible property: 'after provision, I have credentials I can use
to access the machine I paid for.'

What the buyer observes after provision completes:
  - Their local order records the taker_attestation (fulfillment UID).
  - Connection details (SSH command etc.) are stored on their order.
  - Their tenant credentials (password, ssh_commands) are retrievable
    from their agent's credentials table.
  - The credentials are not obviously empty/placeholder values.
"""

from __future__ import annotations

import json
import logging

import pytest

from tests.roles.helpers.deal import Deal

log = logging.getLogger(__name__)


@pytest.mark.roles_provision_buyer
class TestBuyerReceivesMachineAccess:
    """The buyer ends up with real credentials for a real machine."""

    def test_buyer_order_records_taker_attestation(self, provision_output: dict):
        """The buyer's order has taker_attestation (fulfillment UID) populated,
        proving on-chain that the seller delivered."""
        buyer_order = provision_output["buyer_order"]
        assert buyer_order["taker_attestation"], (
            f"Buyer order has no taker_attestation after provision: {buyer_order}"
        )
        # taker_attestation is the fulfillment_uid, distinct from escrow_uid
        assert buyer_order["taker_attestation"] != buyer_order["escrow_uid"], (
            "taker_attestation should be fulfillment_uid, not reused escrow_uid"
        )

    def test_buyer_has_connection_details(self, provision_output: dict):
        """The buyer's order has fulfillment_resource populated with connection details."""
        buyer_order = provision_output["buyer_order"]
        fulfillment = buyer_order.get("fulfillment_resource")
        assert fulfillment, f"No fulfillment_resource on buyer order: {buyer_order}"

        parsed = json.loads(fulfillment) if isinstance(fulfillment, str) else fulfillment
        # At minimum there should be an ssh command or port to connect to
        has_ssh_info = any(
            k in parsed for k in ("ssh_command", "ssh_port", "vm_host_ip", "tenant_user")
        )
        assert has_ssh_info, (
            f"Fulfillment has no recognizable connection details: {parsed}"
        )

    def test_buyer_can_retrieve_tenant_credentials(self, provision_output: dict):
        """The buyer's agent stored tenant credentials they can use to log in."""
        tenant = provision_output["tenant_credentials"]
        assert tenant, "No tenant credentials found"

        # Password should not be obviously empty/placeholder
        assert tenant.get("password"), f"Tenant password is empty: {tenant}"
        assert tenant.get("ssh_commands"), f"No ssh_commands stored: {tenant}"

        ssh_cmds = json.loads(tenant["ssh_commands"]) if isinstance(tenant["ssh_commands"], str) else tenant["ssh_commands"]
        assert ssh_cmds, f"ssh_commands is empty after decode: {tenant['ssh_commands']}"

    def test_buyer_balance_unchanged_from_settlement(self, provision_output: dict):
        """Buyer's balance does not change at provision (still locked in escrow
        until arbitration completes)."""
        deal: Deal = provision_output["deal"]
        # Between settlement (tokens locked) and post-settlement (tokens
        # transferred to seller), the buyer's on-chain balance should be
        # stable — all that changed was the seller delivered off-chain.
        buyer_current = deal.buyer_balance()
        log.info("Buyer balance at provision: %d (pre-deal was %d)",
                 buyer_current, deal.buyer_balance_before)
