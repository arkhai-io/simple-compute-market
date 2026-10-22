"""A receipt-gated, fixed-term whole-host purchase on the mock bare-metal lane.

The profiled Ed25519 buyer has no wallet. Financial reversal and physical
release are separate operations; mock access is never evidence of real SSH.
"""

from __future__ import annotations

import base64
import os
import time
from typing import Any

import pytest
from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION, NODE_RECLAIM_ACCESS_ACTION
from arkhai_bare_metal_buyer.fulfillment import BareMetalFulfillmentTransport
from core_buyer.profile_service import BuyerProfileService
from core_buyer.run_log import read_run, read_run_identity
from market_arkhai_payments import (
    ArkhaiPaymentsConfig,
    PaymentSettlementData,
    agreement_from_bytes,
    payments_client_for_owner,
)
from market_core.schemas import SettlementOption, compute_rate_total
from market_identity import (
    Ed25519Signer,
    Identity,
    IdentityScheme,
    ProfileRepository,
    TrustedIdentitySet,
    create_signer,
)
from market_pool_overrides import SyncPoolOverrideClient
from registry_client import SyncRegistryClient
from storefront_client import SyncStorefrontClient

from tests.e2e.roles.buyer_cli import BuyerCli, _toml_quote, create_profiled_buyer_cli
from tests.e2e.roles.helpers.cleanup import run_cleanup
from tests.e2e.roles.helpers.compute_deal import (
    advance_fulfillment_to,
    advance_storefront,
    dry_run_storefront,
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
from tests.e2e.roles.helpers.payment_compensation import (
    PurchaseCompensation,
    fulfillment_or_none,
    refund_may_clear,
)
from tests.e2e.roles.helpers.payments import (
    configured_payments,
    payment_config_toml,
    payment_setting,
)
from tests.e2e.roles.scenarios.bare_metal.compute_deal_driver import (
    MACHINE_ADDRESS,
    WHOLE_HOST_CAPACITY,
    BareMetalComputeDealDriver,
)
from tests.e2e.roles.scenarios.bare_metal.conftest import lane_setting

pytestmark = pytest.mark.e2e_bare_metal_payment_deal


def _pins(role: str) -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=(Identity(
        scheme=IdentityScheme(lane_setting(f"{role}_scheme")),
        identifier=lane_setting(f"{role}_identifier"),
    ),))


def _purchase_signer(cli: BuyerCli, run_id: str | None = None) -> Any:
    service = BuyerProfileService(
        repository=ProfileRepository(cli.data_dir / "arkhai/buyer/profiles.json"),
        environ=cli.credential_env,
        run_logs_directory=cli.run_dir,
    )
    if run_id is None:
        return service.resolve_fresh_signer()[1]
    recorded = read_run_identity(run_id, directory=cli.run_dir)
    return service.resolve_recovery_signer(
        profile_id=recorded.profile_id, principal=recorded.principal,
    )[1]


@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    lane_setting("registry_url")
    lane_setting("storefront_url")
    config = configured_payments()
    assert config.livemode is False
    for key in ("SELLER_ACCOUNT", "COMPUTE_HOURLY_GROSS", "DISPUTE_WINDOW"):
        assert payment_setting(key), f"PAYMENTS.{key} is required for the whole-host fixture"
    assert str(payment_setting("COMPUTE_HOURLY_GROSS")) == "1000000"
    assert str(payment_setting("DISPUTE_WINDOW")) == "P7D"
    return config


@pytest.fixture(scope="module")
def payment_buyer_cli(payments_config, buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    url = lane_setting("registry_url")
    scheme = lane_setting("registry_scheme")
    identifier = lane_setting("registry_identifier")
    authority = lane_setting("registry_authority_id")
    sections = (
        "[bare_metal]",
        f"registry_url = {_toml_quote(url)}",
        f"registry_authority = {_toml_quote(authority)}",
        "registry_principals = [{ scheme = " + _toml_quote(scheme)
        + ", identifier = " + _toml_quote(identifier) + " }]",
        f"payer_account = {_toml_quote(str(payment_setting('BUYER_ACCOUNT')))}",
        "",
        *payment_config_toml(payments_config, table="bare_metal.arkhai_payments"),
    )
    return create_profiled_buyer_cli(
        binary=buyer_cli_binary,
        base=tmp_path_factory.mktemp("bare_metal_payment_buyer"),
        domain_identity="bare_metal.v1",
        marketplace_scheme=IdentityScheme.ED25519,
        marketplace_credential=str(payment_setting("BUYER_MARKETPLACE_CREDENTIAL")),
        registries=(url,),
        registry_authorities={url: {"authority": authority,
                                   "identities": [{"scheme": scheme, "identifier": identifier}]}},
        toml_sections=sections,
    )


@pytest.fixture(scope="module")
def payment_deal_state() -> DomainDealState:
    return DomainDealState(domain_identity="bare_metal.v1")


@pytest.fixture(scope="module")
def payment_run() -> dict[str, Any]:
    return {}


@pytest.fixture(scope="module")
def payment_fulfillment(payment_buyer_cli) -> BareMetalFulfillmentTransport:
    signer = _purchase_signer(payment_buyer_cli)
    return BareMetalFulfillmentTransport(
        seller_url=lane_setting("storefront_url"),
        principal=signer.identity,
        signer=signer,
        resolve_seller_principals=lambda: _pins("storefront"),
    )


def _release(transport, negotiation_id, fulfillment_id, provisioning_client, admin) -> dict:
    teardown = transport.teardown(negotiation_id)
    assert teardown["fulfillment_id"] == fulfillment_id
    advance_fulfillment_to(provisioning_client, fulfillment_id, "torn_down", max_advances=8)
    provisioning_client.check_leases()
    wait_for_stage_event(
        admin, "fulfillment", "capacity_released",
        negotiation_id=negotiation_id, timeout=15.0,
    )
    released = transport.status(negotiation_id)
    assert released["state"] == "released"
    return released


def _seller_refund(negotiation_id: str):
    """Refund the purchase as the lane's pinned seller; a repeat returns the same result."""
    seller = create_signer(
        lane_setting("storefront_scheme"), str(payment_setting("SELLER_MARKETPLACE_CREDENTIAL")),
    )
    assert seller.identity in _pins("storefront").identities
    with SyncStorefrontClient(
        lane_setting("storefront_url"), signer=seller, caller_role="seller",
        expected_publishers=_pins("storefront"),
    ) as storefront:
        return storefront.refund_settlement(negotiation_id)


@pytest.fixture(scope="module")
def payment_supply(
    payments_config, payment_buyer_cli, payment_fulfillment, payment_deal_state, payment_run,
    bare_metal_site_operator, bare_metal_site_capacity, provisioning_client,
    provisioning_test_client, storefront_admin_client, site_capacity,
):
    # Only the public SSH key leaves this fixture's memory.
    public = Ed25519Signer(os.urandom(32)).identity.identifier
    public_bytes = base64.urlsafe_b64decode(public + "=" * (-len(public) % 4))
    ssh_blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + public_bytes
    ssh_key = "ssh-ed25519 " + base64.b64encode(ssh_blob).decode("ascii")
    driver = BareMetalComputeDealDriver(
        site_operator=bare_metal_site_operator,
        site_capacity_admin=bare_metal_site_capacity,
        provisioning_client=provisioning_client,
        provisioning_test_client=provisioning_test_client,
        storefront_admin_client=storefront_admin_client,
        fulfillment=payment_fulfillment,
        site_capacity=site_capacity,
        buyer_config={"ssh_public_key": ssh_key},
        site_id=lane_setting("site_id"),
    )
    overrides = SyncPoolOverrideClient(storefront_admin_client)
    try:
        pause_storefront(storefront_admin_client)
        assert provisioning_client.pause_fulfillment_convergence().get("paused") is True
        assert provisioning_client.pause_lease_watchdog().get("paused") is True
        driver.seed_supply()
        overrides.put_pool_override({
            "site_id": driver.site_id, "pool_id": driver.pool_id,
            "offering_mode": "bare_metal",
            "settlements": [{
                "mechanism": "arkhai.payments.v1", "asset": "USD/6",
                "rate": "1.00", "per": "hour",
                "mechanism_input": {
                    "payee_account": str(payment_setting("SELLER_ACCOUNT")),
                    "asset": "USD/6", "window": str(payment_setting("DISPUTE_WINDOW")),
                },
            }],
        })
        for rule_id, action in (
            (driver.create_rule_id, NODE_GRANT_ACCESS_ACTION),
            (driver.teardown_rule_id, NODE_RECLAIM_ACCESS_ACTION),
        ):
            provisioning_test_client.add_bare_metal_mock_rule(
                rule_id=rule_id, match={"action": action, "host_id": driver.host_id},
                pause_before_result=False,
            )
        preview = dry_run_storefront(storefront_admin_client, "publication")
        assert any(
            item.get("action") == "publish"
            and item.get("source", {}).get("physical_resource_id") == driver.reserved_resource_id
            for item in preview["actions"]
        ), preview
        report = advance_storefront(storefront_admin_client, "publication")
        listings = [
            str(item["listing_id"]) for item in report["actions"]
            if item["action"] == "publish"
            and item["source"]["physical_resource_id"] == driver.reserved_resource_id
        ]
        assert len(listings) == 1, report
        resource = next(row for row in site_capacity.snapshot()
                        if row["resource_id"] == driver.reserved_resource_id)
        assert resource["available"]["units"] == WHOLE_HOST_CAPACITY["units"]
        payment_run["listing_id"] = listings[0]
        payment_run["ssh_public_key"] = ssh_key
        yield driver
    finally:
        # A deal the refund stage did not finish is still outstanding at the
        # payments service and the site.
        compensation = PurchaseCompensation(
            run_dir=payment_buyer_cli.run_dir,
            status=lambda negotiation_id: fulfillment_or_none(
                payment_fulfillment.status, negotiation_id,
            ),
            refund=_seller_refund,
            release=lambda negotiation_id, status: _release(
                payment_fulfillment, negotiation_id, str(status["fulfillment_id"]),
                provisioning_client, storefront_admin_client,
            ),
            retryable=refund_may_clear,
        )
        # Resuming held loops runs last and always, so a failing step above it
        # cannot leave them stopped for the lane's next module.
        run_cleanup(
            [
                *compensation.steps(settled=payment_deal_state.teardown is not None),
                # Deleting a rule that is already gone reports it not deleted;
                # only a real failure raises, and it is reported like any step's.
                ("remove the access-grant mock rule", lambda: provisioning_test_client
                 .delete_bare_metal_mock_rule(driver.create_rule_id)),
                ("remove the access-reclaim mock rule", lambda: provisioning_test_client
                 .delete_bare_metal_mock_rule(driver.teardown_rule_id)),
                ("drain provisioning", lambda: provisioning_test_client.drain(timeout=30)),
                ("remove the pool override", lambda: overrides.delete_pool_override(
                    driver.site_id, driver.pool_id, "bare_metal",
                )),
            ],
            always=[
                ("resume the lease watchdog", provisioning_client.resume_lease_watchdog),
                ("resume fulfillment convergence",
                 provisioning_client.resume_fulfillment_convergence),
                ("resume the storefront's loops",
                 storefront_admin_client.admin_resume_lifecycle_loops),
            ],
        )


def test_payment_deal_delivers_after_a_verified_receipt(
    payment_buyer_cli: BuyerCli, payment_deal_state: DomainDealState, payment_run: dict,
    payment_supply, payment_fulfillment, provisioning_client, site_capacity,
) -> None:
    with _purchase_registry(payment_buyer_cli) as registry:
        listing = registry.get_listing(payment_run["listing_id"])
    assert listing.status == "open"
    assert listing.listing_resource["capacity_backing"] == "backed"
    assert listing.publisher_principals == _pins("storefront")
    options = [SettlementOption.model_validate(item) for item in listing.settlement_options]
    assert len(options) == 1
    option = options[0]
    assert option.mechanism == "arkhai.payments.v1"
    assert option.params["payee_account"] == str(payment_setting("SELLER_ACCOUNT"))
    assert option.params["window"] == str(payment_setting("DISPUTE_WINDOW"))
    assert option.asset == "USD/6"
    assert option.rates[0].per == "hour"
    assert compute_rate_total(option.rates[0], 3600) == 1000000
    payment_deal_state.complete(DealStage.DISCOVERY, listing_id=str(listing.id))
    buy = payment_buyer_cli.run([
        "bare-metal", "buy", str(listing.id),
        "--option-id", option.option_id,
        "--ssh-public-key", payment_run["ssh_public_key"],
        "--duration-seconds", "3600", "--payment-timeout-seconds", "300",
        "--config", str(payment_buyer_cli.config_path),
    ], timeout=330.0)
    payment_run["buy"] = buy
    assert_market_run_succeeded(buy, command="market bare-metal buy (arkhai.payments.v1)")
    started, accepted, approved, ended = ordered_events(
        buy.read_events(), "run_started", "agreement_accepted", "payment_approved", "run_ended",
    )
    assert ended["status"] == "agreed"
    assert started["listing_id"] == payment_deal_state.listing_id
    assert started["option_id"] == option.option_id
    assert all(event["run_id"] == buy.run_id for event in (started, accepted, approved, ended))
    assert accepted["agreement_ref"] == accepted["negotiation_id"] == ended["negotiation_id"]
    agreement = agreement_from_bytes(base64.b64decode(accepted["agreement_bytes"], validate=True))
    data = PaymentSettlementData.parse(accepted["settlement_data"])
    data.require_bound_to(agreement)
    assert agreement["settlement"]["option_id"] == option.option_id
    assert approved["transaction_id"] == data.transaction_id == ended["transaction_id"]
    assert ended["fulfillment"]["settlement_ref"] == data.transaction_id
    assert ended["fulfillment"]["negotiation_id"] == accepted["negotiation_id"]
    payment_run["run_id"] = buy.run_id
    payment_deal_state.complete(DealStage.NEGOTIATION, negotiation_id=accepted["negotiation_id"])
    payment_deal_state.complete(DealStage.SETTLEMENT, settlement_id=data.transaction_id)
    status = payment_fulfillment.status(payment_deal_state.negotiation_id)
    payment_deal_state.fulfillment_ref = str(status["fulfillment_id"])
    advance_fulfillment_to(
        provisioning_client, payment_deal_state.fulfillment_ref, "active", max_advances=8,
    )
    deadline = time.monotonic() + 30
    while payment_fulfillment.status(payment_deal_state.negotiation_id)["state"] != "active":
        assert time.monotonic() < deadline, "purchase fulfillment did not become ready"
        time.sleep(0.2)
    payment_supply.assert_delivery(payment_deal_state)
    delivered = payment_fulfillment.result(payment_deal_state.negotiation_id)
    assert delivered["receipt"]["access_ref"]["fulfillment_id"] == payment_deal_state.fulfillment_ref
    assert delivered["receipt"]["host_id"] == payment_supply.host_id
    assert payment_fulfillment.access(payment_deal_state.negotiation_id)["host"] == MACHINE_ADDRESS
    resource = next(row for row in site_capacity.snapshot()
                    if row["resource_id"] == payment_supply.reserved_resource_id)
    assert resource["available"]["units"] == 0
    payment_deal_state.complete(
        DealStage.DELIVERY, fulfillment_ref=payment_deal_state.fulfillment_ref, delivery=delivered,
    )


def _purchase_registry(cli):
    """The discovery client signs as the purchase profile, not the lane buyer."""
    return SyncRegistryClient(
        lane_setting("registry_url"), signer=_purchase_signer(cli), caller_role="buyer",
        expected_registries=_pins("registry"), registry_authority=lane_setting("registry_authority_id"),
    )


def test_settlement_re_driven_from_the_run_log_is_idempotent(
    payment_buyer_cli: BuyerCli, payment_deal_state: DomainDealState, payment_run: dict,
    payment_fulfillment,
) -> None:
    require_state(payment_deal_state, "settlement_id", "fulfillment_ref", "delivery")
    signer = _purchase_signer(payment_buyer_cli, payment_run["run_id"])
    events = read_run(payment_run["run_id"], signer=signer, directory=payment_buyer_cli.run_dir)
    _, accepted, approved, ended = ordered_events(
        events, "run_started", "agreement_accepted", "payment_approved", "run_ended",
    )
    assert accepted["negotiation_id"] == payment_deal_state.negotiation_id
    assert approved["transaction_id"] == ended["transaction_id"] == payment_deal_state.settlement_id
    assert accepted["agreement_bytes"] == payment_run["buy"].wait_for_event("agreement_accepted")["agreement_bytes"]
    assert signer.identity == payment_fulfillment.principal
    with SyncStorefrontClient(
        lane_setting("storefront_url"), signer=signer, caller_role="buyer",
        expected_publishers=_pins("storefront"),
    ) as buyer:
        again = buyer.settle_agreement(accepted["negotiation_id"])
    assert not again.pending
    assert again.settlement_ref == payment_deal_state.settlement_id
    status = payment_fulfillment.status(accepted["negotiation_id"])
    assert status["fulfillment_id"] == payment_deal_state.fulfillment_ref
    assert payment_fulfillment.result(accepted["negotiation_id"]) == payment_deal_state.delivery


def test_the_seller_refund_reverses_the_held_payment(
    payment_deal_state: DomainDealState, payments_config: ArkhaiPaymentsConfig,
    payment_supply, payment_fulfillment, provisioning_client, storefront_admin_client, site_capacity,
) -> None:
    require_state(payment_deal_state, "negotiation_id", "settlement_id", "fulfillment_ref")
    refunded = _seller_refund(payment_deal_state.negotiation_id)
    assert refunded.status == "refunded"
    assert refunded.settlement_ref == payment_deal_state.settlement_id
    with payments_client_for_owner(payments_config, str(payment_setting("BUYER_ACCOUNT"))) as client:
        snapshot = client.get_transaction(str(payment_deal_state.settlement_id)).snapshot
    assert snapshot.parts and {part.status.value for part in snapshot.parts} == {"reversed"}
    assert all(part.rate is None and part.reversed.root == part.gross.root
               and part.released.root == "0" and part.held.root == "0"
               for part in snapshot.parts)
    released = _release(
        payment_fulfillment, payment_deal_state.negotiation_id, payment_deal_state.fulfillment_ref,
        provisioning_client, storefront_admin_client,
    )
    resource = next(row for row in site_capacity.snapshot()
                    if row["resource_id"] == payment_supply.reserved_resource_id)
    assert resource["available"]["units"] == WHOLE_HOST_CAPACITY["units"]
    payment_deal_state.complete(DealStage.TEARDOWN, teardown={
        "transaction": refunded.settlement_ref, "physical": released,
    })
    payment_deal_state.assert_complete()
