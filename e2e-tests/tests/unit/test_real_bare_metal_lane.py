"""Real bare-metal source composition with controlled typed authority boundaries."""
from __future__ import annotations

import copy
import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import LeaseView
from market_resource_pools_client import SyncResourcePoolClient
from storefront_client.models import ListingSummary

from e2e_harness.real_provisioning_target import BareMetalHost, TargetInvalid, load_real_provisioning_target
from e2e_harness.ssh_host_key import canonical_host_public_key
from tests.e2e.roles.helpers.compute_deal import DealLease
from tests.e2e.roles.helpers.real_provisioning import JobWatch
from tests.e2e.roles.helpers.ssh_access import SshEndpoint, ssh_session
from tests.e2e.roles.scenarios.bare_metal.real_compute_deal_driver import (
    REAL_POOL_ID, REAL_REGION, REAL_RESOURCE_ID, RealBareMetalComputeDealDriver,
    RealBareMetalDealState, bare_metal_executor_is_real, target_connection,
)

lane = importlib.import_module("tests.e2e.roles.scenarios.bare_metal.test_real_provisioning_deal")
EXAMPLE = Path(__file__).resolve().parents[2] / "config/config-real-provisioning-target.yml.example"
TARGET = BareMetalHost.model_validate(yaml.safe_load(EXAMPLE.read_text())["REAL_PROVISIONING_TARGET"]["hosts"][1])


class Authority:
    """Recording family transport, composed with the production pool client."""

    def __init__(self):
        self.pool = None
        self.host = None
        self.operations = []
        self.host_writes = []
        self.relay = SimpleNamespace(id=TARGET.access.relay_id, enabled=True, token_configured=True,
                                     relay_addr="192.0.2.100", grant_keys=SimpleNamespace(active=object()))

    def authenticated_request(self, method, path, *args, **kwargs):
        body = args[0].model_dump(exclude_none=True) if args else None
        self.operations.append((method, path, body))
        if method == "GET":
            if self.pool is None:
                raise ComputeProvisioningError("missing", status_code=404)
        elif method == "POST":
            self.pool = {**body, "enabled": True, "created_at": datetime.now(timezone.utc),
                         "updated_at": datetime.now(timezone.utc)}
        elif method == "PATCH":
            self.pool.update(body)
        else:
            raise AssertionError(method)
        return self.pool

    def get_relay(self, relay_id):
        assert relay_id == self.relay.id
        return self.relay

    def get_host(self, host_id):
        assert host_id == TARGET.host_id
        if self.host is None:
            raise ComputeProvisioningError("missing", status_code=404)
        return self.host

    def register_host(self, body):
        self.host_writes.append(body)
        self.host = SimpleNamespace(host_id=body.host_id, pool_id=body.pool_id,
                                    enabled=body.enabled, connection=body.connection)
        return self.host

    def update_host(self, host_id, body):
        assert host_id == TARGET.host_id
        self.host_writes.append(body)
        self.host.connection = body.connection
        self.host.pool_id = body.pool_id
        return self.host

    def check_connectivity(self, host_id):
        return SimpleNamespace(host=host_id, reachable=True)


def driver(target=TARGET):
    authority = Authority()
    admin = MagicMock()
    admin.admin_run_lifecycle_cycle.return_value = {"sites": {"site": {"resource_pool": {"state": "loaded"}}}}
    site = MagicMock()
    site.snapshot.return_value = []
    return RealBareMetalComputeDealDriver(
        site_operator=SyncResourcePoolClient(authority),
        site_capacity_admin=SimpleNamespace(register_resource=AsyncMock(return_value={})),
        provisioning_client=authority, storefront_admin_client=admin, fulfillment=MagicMock(),
        site_capacity=site, buyer_config={"ssh_public_key": "public-test-reference"}, site_id="site",
        target=target, jobs=JobWatch(authority),
    )


def test_registration_composes_typed_pool_host_and_declaration_and_reconciles():
    instance = driver()
    instance.seed_supply()
    authority = instance.provisioning_client
    assert authority.pool["provider"] == "bare_metal.ansible"
    assert authority.pool["provider_config"] == {"relay_id": TARGET.access.relay_id}
    assert authority.pool["policy_tags"]["capacity_backing"] == "backed"
    assert authority.pool["policy_tags"]["deliverable_modes"] == ["bare_metal"]
    assert authority.host.connection == target_connection(TARGET)
    call = instance.site_capacity_admin.register_resource.await_args
    assert call.args == (REAL_RESOURCE_ID,)
    assert call.kwargs["capacity"] == {"units": 1, **TARGET.capacity.model_dump()}
    assert call.kwargs["attributes"]["physical_host_id"] == TARGET.physical_host_id
    assert call.kwargs["host_id"] == TARGET.host_id
    assert not hasattr(instance, "arm_create_gate")
    assert not hasattr(instance, "provisioning_test_client")
    instance.seed_supply()
    assert len(authority.host_writes) == 1
    assert [method for method, _path, _body in authority.operations] == ["GET", "POST", "GET"]


@pytest.mark.parametrize("attribute,value", [("enabled", False), ("token_configured", False), ("grant_keys", SimpleNamespace(active=None))])
def test_unready_relay_prevents_every_supply_write(attribute, value):
    instance = driver()
    setattr(instance.provisioning_client.relay, attribute, value)
    with pytest.raises(AssertionError):
        instance.seed_supply()
    assert instance.provisioning_client.operations == []
    assert instance.provisioning_client.host_writes == []
    instance.site_capacity_admin.register_resource.assert_not_awaited()


def test_another_declaration_for_the_host_requires_operator_reconciliation():
    instance = driver()
    instance.site_capacity.snapshot.return_value = [{"resource_id": "older-owned-declaration", "host_id": TARGET.host_id}]
    with pytest.raises(AssertionError, match="another capacity declaration"):
        instance.seed_supply()
    assert instance.provisioning_client.operations == []
    instance.site_capacity_admin.register_resource.assert_not_awaited()


def test_registration_adopts_configured_resource_and_pool_without_a_second_declaration():
    target = BareMetalHost.model_validate({
        **TARGET.model_dump(), "pool_id": "example-owned-pool",
        "resource_id": "example-owned-resource",
    })
    instance = driver(target)
    instance.site_capacity.snapshot.return_value = [{
        "resource_id": target.resource_id, "host_id": target.host_id,
        "attributes": {"physical_host_id": target.physical_host_id},
    }]
    instance.seed_supply()
    assert instance.provisioning_client.pool["id"] == target.pool_id
    assert instance.provisioning_client.host.pool_id == target.pool_id
    registration = instance.site_capacity_admin.register_resource.await_args
    assert registration.args == (target.resource_id,)
    assert registration.kwargs["pool_id"] == target.pool_id
    assert registration.kwargs["host_id"] == target.host_id
    instance.site_capacity.snapshot.return_value.append({
        "resource_id": "example-other-resource", "host_id": target.host_id,
    })
    with pytest.raises(AssertionError, match="another capacity declaration"):
        instance.seed_supply()


def test_pool_authentication_failure_is_not_treated_as_missing():
    instance = driver()
    instance.site_operator = MagicMock()
    instance.site_operator.get_pool.side_effect = ComputeProvisioningError("forbidden", status_code=403)
    with pytest.raises(ComputeProvisioningError):
        instance.seed_supply()
    instance.site_operator.create_pool.assert_not_called()
    assert instance.provisioning_client.host_writes == []


def listing(**changes):
    resource = {"host_id": TARGET.host_id, "physical_host_id": TARGET.physical_host_id,
                "region": REAL_REGION, "capacity_backing": "backed", **TARGET.capacity.model_dump()}
    resource.update(changes)
    return ListingSummary(listing_id="listing", status="open", listing_resource=resource)


def test_rerun_adopts_existing_public_machine_shape_without_a_public_resource_id():
    instance = driver()
    found = listing()
    instance.storefront_admin_client.list_listings.return_value = SimpleNamespace(listings=[found])
    assert instance.open_listing_for_run() is found
    instance.storefront_admin_client.pause_listing.assert_not_called()
    instance.storefront_admin_client.create_listing.assert_not_called()


@pytest.mark.parametrize("rows", [[], [listing(), listing()]])
def test_rerun_refuses_missing_or_ambiguous_open_listing(rows):
    instance = driver()
    instance.storefront_admin_client.list_listings.return_value = SimpleNamespace(listings=rows)
    with pytest.raises(AssertionError, match="one open"):
        instance.open_listing_for_run()


def test_rerun_refuses_old_machine_shape():
    instance = driver()
    instance.storefront_admin_client.list_listings.return_value = SimpleNamespace(listings=[listing(ram_gb=999)])
    with pytest.raises(AssertionError, match="shape differs"):
        instance.open_listing_for_run()


@pytest.mark.parametrize("entries", [[], [SimpleNamespace(offering_mode="vm", mocked=False)],
                                     [SimpleNamespace(offering_mode="bare_metal", mocked=True)]])
def test_real_executor_check_refuses_missing_or_mocked_mode(entries):
    with pytest.raises(AssertionError, match="does not execute bare-metal"):
        bare_metal_executor_is_real(SimpleNamespace(executors=entries))


def test_real_executor_check_is_mode_specific():
    real = SimpleNamespace(offering_mode="bare_metal", mocked=False)
    assert bare_metal_executor_is_real(SimpleNamespace(executors=[real, SimpleNamespace(offering_mode="vm", mocked=True)])) is real


def holding(**changes):
    values = dict(owner_kind="fulfillment", owner_id="reservation", host_id=TARGET.host_id,
                  remote_port=6300, released_at=None, grant_expires_at=datetime.now(timezone.utc))
    values.update(changes)
    return SimpleNamespace(**values)


def delivered_driver(lease):
    instance = driver()
    authority = instance.provisioning_client
    authority.get_fulfillment_status = lambda identity: SimpleNamespace(capacity_reservation_id="reservation", state="active")
    authority.list_relay_leases = lambda identity: SimpleNamespace(leases=[lease])
    instance.fulfillment.access.return_value = {"host": authority.relay.relay_addr, "port": 6300, "username": "tenant"}
    return instance


def test_delivery_requires_exact_reservation_host_and_leased_port():
    instance = delivered_driver(holding())
    endpoint = instance.delivered_access(RealBareMetalDealState(negotiation_id="negotiation", fulfillment_id="fulfillment"))
    assert endpoint == SshEndpoint("192.0.2.100", 6300, "tenant")


@pytest.mark.parametrize("changes", [{"owner_id": "other"}, {"host_id": "other"}, {"remote_port": 6301}, {"released_at": datetime.now(timezone.utc)}])
def test_delivery_rejects_foreign_or_released_holdings(changes):
    instance = delivered_driver(holding(**changes))
    with pytest.raises(AssertionError):
        instance.delivered_access(RealBareMetalDealState(negotiation_id="negotiation", fulfillment_id="fulfillment"))


def test_released_holding_retains_quarantine_expiry():
    instance = delivered_driver(holding(released_at=datetime.now(timezone.utc)))
    instance.assert_relay_released("fulfillment", SshEndpoint("192.0.2.100", 6300, "tenant"))
    instance.provisioning_client.list_relay_leases = lambda identity: SimpleNamespace(leases=[holding(released_at=datetime.now(timezone.utc), grant_expires_at=None)])
    with pytest.raises(AssertionError, match="grant expiry"):
        instance.assert_relay_released("fulfillment", SshEndpoint("192.0.2.100", 6300, "tenant"))


def test_wrong_preview_host_blocks_settlement_preflight():
    instance = driver()
    state = RealBareMetalDealState(_evaluate_settle_passed=True, expected_host_id="other")
    with pytest.raises(AssertionError, match="another host"):
        lane.TestStage08a2_SettlementPreviewChoseTheTarget().test_08a2_preview_selected_target(instance, state)
    assert not state._settle_preflight_passed


def test_malformed_host_key_fails_in_target_loader_before_any_lane_fixture():
    data = copy.deepcopy(yaml.safe_load(EXAMPLE.read_text()))
    data["REAL_PROVISIONING_TARGET"]["hosts"][1]["ssh_host_public_key"] = "ssh-ed25519 not-a-key"
    with pytest.raises(TargetInvalid, match="ssh_host_public_key"):
        load_real_provisioning_target(data)


def test_failure_finalizer_names_own_identities_and_never_releases_capacity_blindly():
    instance = driver()
    instance.fulfillment.status.side_effect = RuntimeError("unreachable")
    state = RealBareMetalDealState(negotiation_id="our-negotiation", real_escrow_uid="our-escrow")
    with pytest.raises(AssertionError, match="operator recovery required.*our-negotiation"):
        instance.tear_down_after_failure(state)
    instance.site_capacity.release.assert_not_called()
    instance.site_capacity.truncate_lease.assert_not_called()


def test_failed_run_recovers_only_its_lease_through_real_convergence_helper():
    instance = driver()
    authority = instance.provisioning_client
    lease = SimpleNamespace(status="active", lease_end_utc=datetime.now(timezone.utc) + timedelta(hours=1), release_job_id=None)
    current = {"state": "active"}
    requests = []

    def status(identity):
        assert identity == "our-fulfillment"
        return SimpleNamespace(state=current["state"], capacity_reservation_id="our-reservation",
                               model_dump=lambda **kwargs: {"state": current["state"]})

    def get_lease(identity):
        requests.append(("lease", identity))
        assert identity == "our-reservation"
        return lease

    def check_leases():
        if current["state"] == "active":
            lease.status = "releasing"
            lease.release_job_id = "our-fulfillment"
            current["state"] = "teardown_dispatch_pending"
        elif current["state"] == "torn_down":
            lease.status = "released"

    def advance():
        current["state"] = {"teardown_dispatch_pending": "tearing_down", "tearing_down": "torn_down"}[current["state"]]

    authority.get_fulfillment_status = status
    authority.get_lease = get_lease
    authority.check_leases = check_leases
    authority.advance_fulfillment_convergence_cycle = advance
    authority.list_jobs = lambda **kwargs: SimpleNamespace(jobs=[
        SimpleNamespace(job_id="our-grant", host_id=TARGET.host_id, status="succeeded"),
        SimpleNamespace(job_id="our-reclaim", host_id=TARGET.host_id, status="succeeded"),
    ])
    authority.get_job = lambda identity: SimpleNamespace(job_id=identity, status="succeeded")
    state = RealBareMetalDealState(negotiation_id="our-negotiation", real_escrow_uid="our-escrow",
                                  fulfillment_id="our-fulfillment", create_job_id="our-grant")
    instance.tear_down_after_failure(state)
    assert lease.status == "released"
    assert set(identity for _kind, identity in requests) == {"our-reservation"}
    assert instance.site_capacity.truncate_lease.call_args.args[0] == "our-reservation"
    instance.site_capacity.release.assert_not_called()


def test_host_key_comments_carry_no_trust_authority():
    assert canonical_host_public_key(TARGET.ssh_host_public_key + " operator-☃") == TARGET.ssh_host_public_key


@pytest.mark.parametrize("observed_job,accepted", [("observed-grant", True), ("another-grant", False)])
def test_grant_job_stage_uses_actual_normalized_deal_lease(observed_job, accepted):
    end = datetime.now(timezone.utc) + timedelta(hours=1)
    response = LeaseView(
        capacity_reservation_id="development-reservation", deal_ref={"escrow_uid": "development-escrow"},
        offering_mode="bare_metal", executor_target=TARGET.physical_host_id,
        lease_end_utc=end, create_job_id=observed_job, status="active",
    )
    provider = SimpleNamespace(get_lease=MagicMock(return_value=response))
    site = SimpleNamespace(
        list_reservations=MagicMock(return_value=[{
            "capacity_reservation_id": "development-reservation", "lease_end_utc": end.isoformat(),
        }]),
        get_reservation=MagicMock(return_value={"escrow_uid": "development-escrow", "resource_id": REAL_RESOURCE_ID}),
    )
    view = DealLease(provider, site, escrow_uid="development-escrow")
    state = RealBareMetalDealState(deal_lease=view, create_job_id="observed-grant")
    stage = lane.TestStage09c3_LeaseNamesTheGrantJob()
    if accepted:
        stage.test_09c3_lease_names_the_observed_grant(state)
    else:
        with pytest.raises(AssertionError):
            stage.test_09c3_lease_names_the_observed_grant(state)
    provider.get_lease.assert_called_once_with("development-reservation")
    site.list_reservations.assert_called_once_with(escrow_uid="development-escrow")


def test_two_cleanup_cycles_use_distinct_unrelated_keys_in_one_real_ssh_session(tmp_path):
    # Controlled SSH process: the documentation address is a development fixture
    # and must never be used on a public network. No network is contacted here.
    executable = tmp_path / "refuse-public-key"
    executable.write_text("#!/bin/sh\nprintf 'Permission denied (publickey).\\n' >&2\nexit 255\n")
    executable.chmod(0o700)
    state = RealBareMetalDealState(delivered_access=SshEndpoint("192.0.2.100", 6300, "tenant"))
    stage = lane.TestStage09e_UnrelatedKeyRefused()
    with ssh_session(ssh=str(executable), host_key=TARGET.ssh_host_public_key) as session:
        stage.test_09e_unrelated_key_is_refused(state, session, "normal")
        stage.test_09e_unrelated_key_is_refused(state, session, "refusal")
        normal = session.directory / "unrelated-normal"
        successor = session.directory / "unrelated-refusal"
        assert normal.is_file() and successor.is_file()
        assert normal.read_bytes() != successor.read_bytes()
        with pytest.raises(FileExistsError):
            session.new_key("unrelated-normal")
