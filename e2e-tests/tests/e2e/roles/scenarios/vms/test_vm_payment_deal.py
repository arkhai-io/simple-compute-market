"""Fixed-term VM payments: receipt-gated mock delivery, replay, refund and release."""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from market_arkhai_payments import ArkhaiPaymentsConfig, payments_client_for_owner
from market_identity import IdentityScheme, TrustedIdentitySet, create_signer
from storefront_client import SyncStorefrontClient

from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import BuyerCli, _toml_quote, create_profiled_buyer_cli
from tests.e2e.roles.helpers.compute_deal import (
    DealLease,
    advance_fulfillment_to,
    advance_storefront,
    convergence_paused,
    delete_mock_rules_if_present,
    pause_storefront,
    wait_for_stage_event,
)
from tests.e2e.roles.helpers.domain_deal import (
    DealStage,
    DomainDealState,
    assert_market_run_succeeded,
    ordered_events,
    require_state,
)
from tests.e2e.roles.helpers.payments import (
    configured_payments,
    payment_config_toml,
    payment_setting,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    provision_e2e_executor,
    refresh_storefront_projections,
)

log = logging.getLogger(__name__)
pytestmark = pytest.mark.e2e_vm_payment_deal

# Public mock-delivery fixtures, never credentials for a real host.
SSH_PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDemoPublicKeyForComputeAccess buyer@example.invalid"
GPU_MODEL = "RTX 4090"


def _lane_setting(name: str) -> str:
    value = str(settings.get(name, "") or "").strip()
    if not value:
        pytest.fail(f"{name} is required for the VM payment lane")
    return value


@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    for name in (
        "REGISTRY.API_URL", "REGISTRY.AUTHORITY_ID", "REGISTRY.IDENTIFIER",
        "SELLER.API_URL", "SELLER.PRIVATE_KEY", "PROVISIONING.API_URL",
    ):
        _lane_setting(name)
    return configured_payments()


@pytest.fixture(scope="module")
def payment_buyer_cli(payments_config, buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    registry = _lane_setting("REGISTRY.API_URL").rstrip("/")
    return create_profiled_buyer_cli(
        binary=buyer_cli_binary,
        base=tmp_path_factory.mktemp("vm_payment_buyer"),
        domain_identity="vms.compute",
        marketplace_scheme=IdentityScheme.ED25519,
        marketplace_credential=str(payment_setting("BUYER_MARKETPLACE_CREDENTIAL")),
        registries=(registry,),
        registry_authorities={
            registry: {
                "authority": _lane_setting("REGISTRY.AUTHORITY_ID"),
                "identities": [{
                    "scheme": str(settings.REGISTRY.get("scheme", "eip191")),
                    "identifier": _lane_setting("REGISTRY.IDENTIFIER"),
                }],
            },
        },
        toml_sections=(
            "[Settlement]",
            "schema_version = 1",
            'priority = ["arkhai.payments.v1"]',
            "",
            *payment_config_toml(payments_config),
            "",
            "[vms]",
            f"payer_account = {_toml_quote(str(payment_setting('BUYER_ACCOUNT')))}",
            "",
        ),
    )


@pytest.fixture(scope="module")
def payment_deal_state() -> DomainDealState:
    return DomainDealState(domain_identity="vms.compute")


@pytest.fixture(scope="module")
def payment_run(
    payments_config, storefront_admin_client, provisioning_client,
    provisioning_test_client, site_capacity_admin_client, registry_client,
) -> Any:
    """Own backed supply and non-pausing rules; restore held loops on failure."""
    assert storefront_admin_client.get_health().status == "ok"
    assert provisioning_client.get_system_status().execution.mocked
    suffix = uuid.uuid4().hex[:8]
    pool = f"vm-payment-{suffix}"
    region = f"VM Payment {suffix}"
    create_rule, remove_rule = f"{pool}-create", f"{pool}-remove"
    context: dict[str, Any] = {
        "resource_id": f"{pool}-resource", "host_id": f"{pool}-host",
        "region": region, "remove_rule": remove_rule,
    }
    try:
        pause_storefront(storefront_admin_client)
        gross = int(str(payment_setting("COMPUTE_HOURLY_GROSS", "1000000")))
        clause: dict[str, Any] = {
            "mechanism": "arkhai.payments.v1", "asset": "USD/6",
            # Hour clauses are display units; the option builder scales USD/6.
            "rate": str(Decimal(gross) / Decimal(10**6)), "per": "hour",
            "mechanism_input": {
                "asset": "USD/6",
                "payee_account": str(payment_setting("SELLER_ACCOUNT")),
                "window": str(payment_setting("DISPUTE_WINDOW", "P7D")),
            },
        }
        assert clause["mechanism_input"]["payee_account"]
        provision_e2e_executor(
            provisioning_client, site_capacity_admin_client,
            host=context["host_id"], resource_id=context["resource_id"],
            pool_id=pool, sellable_units=1,
            attributes={"gpu_model": GPU_MODEL, "region": region},
            region=region, pricing={"gpu": {GPU_MODEL: {"settlements": [clause]}}},
            listing_shapes={"vm": [{"gpu": {"count": 1, "model": GPU_MODEL}}]},
        )
        refresh_storefront_projections(storefront_admin_client)
        advance_storefront(storefront_admin_client, "publication")
        listings = [
            listing for listing in registry_client.list_listings(status="open", limit=200).listings
            if listing.listing_resource.get("resource_id") == context["resource_id"]
        ]
        assert len(listings) == 1, "Owned VM supply did not publish one listing"
        context["listing_id"] = listings[0].id
        options = [dict(option) for option in listings[0].settlement_options]
        payment_options = [option for option in options if option["mechanism"] == "arkhai.payments.v1"]
        assert len(payment_options) == 1
        assert payment_options[0]["rates"][0]["value"] == str(gross)
        provisioning_test_client.add_mock_rule(
            rule_id=create_rule,
            match={"vm_action": "create", "host_id": context["host_id"]},
            pause_before_result=False,
            result_stdout=(
                'ok: [kvm1] => {\n    "vm_creation_data": '
                '{"action": "create", "vm_name": "e2e-payment-vm", "tenant_user": "vmuser", '
                '"external_ssh_port": "2222", "timestamp": "2030-01-01T00:00:01Z", '
                '"tenant_ssh_key_path": "/tmp/e2e.key", "frp": {"enabled": false}, '
                '"authentication": {"tenant": {"ssh_commands": '
                '{"external": "ssh vmuser@localhost", '
                '"internal": "ssh vmuser@10.0.0.1"}}}}\n}\n'
            ),
        )
        yield context
    finally:
        delete_mock_rules_if_present(provisioning_test_client, create_rule, remove_rule)
        storefront_admin_client.admin_resume_lifecycle_loops()


def _buyer_storefront() -> SyncStorefrontClient:
    signer = create_signer(
        IdentityScheme.ED25519, str(payment_setting("BUYER_MARKETPLACE_CREDENTIAL"))
    )
    seller = create_signer(
        str(payment_setting("SELLER_MARKETPLACE_SCHEME", "eip191")),
        str(payment_setting("SELLER_MARKETPLACE_CREDENTIAL")),
    )
    return SyncStorefrontClient(
        _lane_setting("SELLER.API_URL"), signer=signer, caller_role="buyer",
        expected_publishers=TrustedIdentitySet(identities=(seller.identity,)),
    )


def _delivery(negotiation_id: str) -> dict[str, Any]:
    with _buyer_storefront() as client:
        status = client.get_settle_status(negotiation_id)
    assert status.status == "ready"
    assert status.fulfillment_id
    assert status.tenant_credentials, "Ready VM has no tenant delivery"
    delivery = {
        **status.extra,
        "fulfillment_id": status.fulfillment_id,
        "tenant_credentials": status.tenant_credentials,
    }
    connection = delivery.get("connection_details")
    if isinstance(connection, str):
        connection = json.loads(connection)
    assert connection and connection.get("ssh_command"), "Ready VM has no usable mock SSH facts"
    assert connection.get("tenant_user") == "vmuser"
    assert str(connection.get("ssh_port")) == "2222"
    return delivery


def test_payment_deal_delivers_after_a_verified_receipt(
    payment_buyer_cli: BuyerCli, payment_deal_state: DomainDealState,
    payment_run: dict, provisioning_client, site_capacity,
) -> None:
    buy = payment_buyer_cli.run([
        "buy",
        "--resource", f'gpu_model="{GPU_MODEL}" region="{payment_run["region"]}"',
        "--settlement", "mechanism=arkhai.payments.v1 asset=USD/6",
        "--duration-hours", "1", "--ssh-public-key", SSH_PUBLIC_KEY,
        "--max-matches", "5", "--max-rounds", "10",
        "--poll-interval", "1.0", "--settlement-timeout", "300",
        "--expiration", "3600", "--yes",
    ], timeout=320.0)
    assert_market_run_succeeded(buy, command="market buy (arkhai.payments.v1)")
    lifecycle = ordered_events(
        buy.read_events(), "discover", "negotiation_started", "negotiation_completed",
        "payment_approved", "settlement_submitted", "settlement_poll", "run_ended",
    )
    assert lifecycle[-1]["status"] == "ready"
    assert lifecycle[1]["listing_id"] == payment_run["listing_id"]
    negotiation = str(lifecycle[-1]["negotiation_id"])
    transaction = str(lifecycle[3]["transaction_id"])
    delivery = _delivery(negotiation)
    assert delivery["settlement_ref"] == transaction
    lease = DealLease(provisioning_client, site_capacity, negotiation_id=negotiation)
    recorded = lease.refresh()
    assert recorded["host_id"] == payment_run["host_id"]
    assert recorded["status"] == "active"
    assert recorded["create_job_id"]
    assert provisioning_client.get_fulfillment_status(delivery["fulfillment_id"]).state == "active"
    payment_deal_state.complete(DealStage.DISCOVERY, listing_id=payment_run["listing_id"])
    payment_deal_state.complete(DealStage.NEGOTIATION, negotiation_id=negotiation)
    payment_deal_state.complete(DealStage.SETTLEMENT, settlement_id=transaction)
    payment_deal_state.complete(
        DealStage.DELIVERY, fulfillment_ref=delivery["fulfillment_id"],
        delivery={"kind": "mock_vm", "lease_id": lease.lease_id},
    )
    payment_run.update(run_id=buy.run_id, delivery=delivery, lease=lease)
    log.info("VM payment delivered: run=%s negotiation=%s transaction=%s fulfillment=%s",
             buy.run_id, negotiation, transaction, delivery["fulfillment_id"])


def test_settlement_re_driven_from_the_run_log_is_idempotent(
    payment_buyer_cli: BuyerCli, payment_deal_state: DomainDealState, payment_run: dict,
) -> None:
    require_state(payment_deal_state, "negotiation_id", "settlement_id", "fulfillment_ref")
    again = payment_buyer_cli.run([
        "settle", "--from", payment_run["run_id"],
        "--poll-interval", "1.0", "--settlement-timeout", "60",
    ], timeout=90.0)
    assert_market_run_succeeded(again, command="market settle --from <original run>")
    approved = again.wait_for_event("payment_approved", timeout=10.0)
    assert approved["transaction_id"] == payment_deal_state.settlement_id
    assert approved["negotiation_id"] == payment_deal_state.negotiation_id
    assert payment_deal_state.negotiation_id is not None
    delivery = _delivery(payment_deal_state.negotiation_id)
    for field in ("settlement_ref", "fulfillment_id", "tenant_credentials", "connection_details"):
        assert delivery.get(field) == payment_run["delivery"].get(field), field
    assert payment_deal_state.delivery is not None
    assert payment_run["lease"].refresh()["id"] == payment_deal_state.delivery["lease_id"]


def test_the_seller_refund_reverses_the_held_payment(
    payment_deal_state: DomainDealState, payment_run: dict,
    payments_config: ArkhaiPaymentsConfig, provisioning_client,
    provisioning_test_client, storefront_admin_client,
) -> None:
    require_state(payment_deal_state, "negotiation_id", "settlement_id", "fulfillment_ref")
    seller = create_signer(
        str(payment_setting("SELLER_MARKETPLACE_SCHEME", "eip191")),
        str(payment_setting("SELLER_MARKETPLACE_CREDENTIAL")),
    )
    with SyncStorefrontClient(
        _lane_setting("SELLER.API_URL"), signer=seller, caller_role="seller",
        expected_publishers=TrustedIdentitySet(identities=(seller.identity,)),
    ) as client:
        refunded = client.refund_settlement(payment_deal_state.negotiation_id)
    assert refunded.status == "refunded"
    assert refunded.settlement_ref == payment_deal_state.settlement_id
    with payments_client_for_owner(payments_config, str(payment_setting("BUYER_ACCOUNT"))) as client:
        assert payment_deal_state.settlement_id is not None
        snapshot = client.get_transaction(payment_deal_state.settlement_id).snapshot
    assert snapshot.parts and all(part.rate is None for part in snapshot.parts)
    assert all(part.reversed.root == part.gross.root for part in snapshot.parts)
    assert {part.status.value for part in snapshot.parts} == {"reversed"}

    # Financial refund does not end physical delivery. Expiry drives release.
    lease = payment_run["lease"]
    assert lease.refresh()["status"] == "active"
    try:
        assert provisioning_client.pause_lease_watchdog().get("paused") is True
        with contextmanager(convergence_paused)(provisioning_client):
            provisioning_test_client.add_mock_rule(
                rule_id=payment_run["remove_rule"],
                match={"vm_action": "vm_remove", "host_id": payment_run["host_id"]},
                pause_before_result=False,
            )
            lease.backdate((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
            provisioning_client.check_leases()
            releasing = lease.refresh()
            assert releasing["status"] == "releasing"
            assert releasing["fulfillment_id"] == payment_deal_state.fulfillment_ref
            provisioning_client.advance_fulfillment_convergence_cycle()
            provisioning_test_client.drain(timeout=30)
            assert payment_deal_state.fulfillment_ref is not None
            advance_fulfillment_to(provisioning_client, payment_deal_state.fulfillment_ref, "torn_down")
            provisioning_client.check_leases()
            assert lease.refresh()["status"] == "released"
            wait_for_stage_event(
                storefront_admin_client, "fulfillment", "capacity_released",
                negotiation_id=payment_deal_state.negotiation_id, timeout=10.0,
            )
            assert not lease.resource_consumed(storefront_admin_client, payment_run["resource_id"])
    finally:
        provisioning_client.resume_lease_watchdog()
    payment_deal_state.complete(
        DealStage.TEARDOWN,
        teardown={"kind": "mock_vm_released", "transaction": payment_deal_state.settlement_id},
    )
    payment_deal_state.assert_complete()
