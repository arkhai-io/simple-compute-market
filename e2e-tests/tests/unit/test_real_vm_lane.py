"""The real-provisioning VM lane's own logic, against fake clients.

The lane's registration of its host, the jobs it finds and waits for, the VM
list it reads the guest's absence from, its checks of the service's execution,
the delivered access, and the settlement preview; the resource's sole open listing,
created offering every ready mechanism or adopted with closed history retained,
and the re-reservation's claim; and the lease view's reading of a
GPU-less declaration. The scenario module is imported by name, never its
stage classes, so pytest does not collect them here.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import (
    ConnectionSubmission,
    JobListResponse,
    JobLogsResponse,
    JobStatusResponse,
    ResultEnvelope,
)
from market_alkahest.plans import ALKAHEST_MECHANISM
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from storefront_client import StorefrontClientError
from storefront_client.models import ListingListResponse, ListingSummary

from e2e_harness.real_provisioning_target import VmHost
from tests.e2e.roles.helpers.compute_deal import DealLease
from tests.e2e.roles.helpers.compute_deal_stages import (
    DEAL_TOKEN,
    LISTED_HOURLY_RATE,
    Stage09b_SettlementReadyAndCredentials,
)
from tests.e2e.roles.scenarios.vms.composed_listing import (
    ALKAHEST_SETTLEMENT, create_or_adopt_listing, listing_mechanisms, real_target_resource,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    provision_e2e_executor, register_e2e_host, register_e2e_pool,
)
from tests.e2e.roles.scenarios.vms.real_purchase_driver import RealVmPurchaseDriver
from tests.e2e.roles.scenarios.vms.real_compute_deal_driver import (
    REAL_POOL_ID,
    REAL_RESOURCE_ID,
    JobWatch,
    RealVmComputeDealDriver,
    RealVmDealState,
    assert_guest_absent,
    assert_registered_as_target,
    created_guest_name,
    delivered_endpoint,
    target_connection,
    vm_executor_is_real,
    configured_relay,
)

real_lane = importlib.import_module("tests.e2e.roles.scenarios.vms.test_real_provisioning_deal")

HOST = "example-kvm-1"
RESERVATION = "reservation-1"
#: RFC 5737 documentation addresses and a fictitious key path, as in the
#: committed example target; they name no real host.
TARGET = VmHost.model_validate({
    "domain": "vm",
    "host_id": HOST,
    "connection": {
        "ssh_host": "192.0.2.10",
        "ssh_user": "provisioner",
        "ssh_port": 22,
        "ssh_key_path": "/run/secrets/example-host-key",
    },
    "capacity": {"vcpu_count": 7, "ram_gb": 28, "disk_gb": 160},
    "listing_shape": {"vcpu_count": 2, "ram_gb": 4, "disk_gb": 30},
    "access": {"mode": "direct", "public_host": "198.51.100.7"},
})


# ---------------------------------------------------------------------------
# Registering the host
# ---------------------------------------------------------------------------

class FakeHosts:
    """The provisioning service's host registry, as `register_e2e_host` uses it."""

    def __init__(self, **hosts: SimpleNamespace) -> None:
        self.hosts = dict(hosts)
        self.registered: list = []
        self.updates: list = []
        self.enabled: list = []

    def get_host(self, host_id: str):
        if host_id not in self.hosts:
            raise ComputeProvisioningError("not found", status_code=404)
        return self.hosts[host_id]

    def register_host(self, body) -> None:
        self.registered.append(body)
        self.hosts[body.host_id] = _host(body.host_id, body.pool_id, body.connection)

    def update_host(self, host_id: str, body) -> None:
        self.updates.append(body)
        host = self.hosts[host_id]
        connection = _view(body.connection) if body.connection else host.connection
        self.hosts[host_id] = SimpleNamespace(
            host_id=host_id, pool_id=body.pool_id or host.pool_id, connection=connection,
            enabled=host.enabled,
        )

    def enable_host(self, host_id: str) -> None:
        self.enabled.append(host_id)
        self.hosts[host_id].enabled = True


def _view(submission: ConnectionSubmission) -> SimpleNamespace:
    # A stored connection carries the defaults its kind fills in.
    return SimpleNamespace(
        kind=submission.kind,
        version=submission.version,
        public={"public_host": None, "ssh_port": 22, "ssh_user": "root", **submission.public},
    )


def _host(host_id: str, pool_id: str, connection: ConnectionSubmission) -> SimpleNamespace:
    return SimpleNamespace(
        host_id=host_id, pool_id=pool_id, connection=_view(connection), enabled=True
    )


def test_a_new_host_is_registered_with_the_connection_given():
    hosts = FakeHosts()
    register_e2e_host(hosts, name=HOST, pool_id=REAL_POOL_ID, connection=target_connection(TARGET))
    (body,) = hosts.registered
    assert body.connection == target_connection(TARGET)
    assert hosts.updates == []
    assert_registered_as_target(hosts.get_host(HOST), TARGET)


def test_an_unchanged_host_is_left_as_it_is():
    hosts = FakeHosts(**{HOST: _host(HOST, REAL_POOL_ID, target_connection(TARGET))})
    register_e2e_host(hosts, name=HOST, pool_id=REAL_POOL_ID, connection=target_connection(TARGET))
    assert hosts.registered == [] and hosts.updates == [] and hosts.enabled == []


def test_a_host_an_earlier_run_left_disabled_is_enabled_again():
    """A declaration naming a disabled host is neither admitted nor published,
    so registration restores the host it reconciles."""
    disabled = _host(HOST, REAL_POOL_ID, target_connection(TARGET))
    disabled.enabled = False
    hosts = FakeHosts(**{HOST: disabled})

    host = register_e2e_host(
        hosts, name=HOST, pool_id=REAL_POOL_ID, connection=target_connection(TARGET)
    )

    assert hosts.enabled == [HOST]
    assert host.enabled is True


def test_a_host_an_earlier_run_left_has_its_connection_replaced():
    stale = ConnectionSubmission(
        kind="ssh",
        public={**target_connection(TARGET).public, "ssh_host": "192.0.2.99"},
    )
    hosts = FakeHosts(**{HOST: _host(HOST, REAL_POOL_ID, stale)})
    register_e2e_host(hosts, name=HOST, pool_id=REAL_POOL_ID, connection=target_connection(TARGET))
    (update,) = hosts.updates
    assert update.connection == target_connection(TARGET)
    assert update.pool_id == REAL_POOL_ID
    assert_registered_as_target(hosts.get_host(HOST), TARGET)


def test_without_a_connection_a_new_host_gets_the_placeholder_and_an_old_one_keeps_its_own():
    hosts = FakeHosts(**{"kvm-old": _host("kvm-old", "old-pool", target_connection(TARGET))})
    register_e2e_host(hosts, name="kvm-new", pool_id="pool")
    register_e2e_host(hosts, name="kvm-old", pool_id="pool")
    (body,) = hosts.registered
    assert body.connection.public == {
        "ssh_host": "127.0.0.1", "ssh_user": "e2e", "key_path": "/dev/null"
    }
    assert body.connection.version == 2
    (update,) = hosts.updates
    assert update.connection is None and update.pool_id == "pool"


def test_the_target_connection_is_at_the_version_the_service_accepts():
    assert target_connection(TARGET).version == 2
    hosts = FakeHosts(**{HOST: _host(
        HOST, REAL_POOL_ID,
        ConnectionSubmission(kind="ssh", version=1, public=target_connection(TARGET).public),
    )})
    with pytest.raises(AssertionError, match="not the target's"):
        assert_registered_as_target(hosts.get_host(HOST), TARGET)
    register_e2e_host(hosts, name=HOST, pool_id=REAL_POOL_ID, connection=target_connection(TARGET))
    (update,) = hosts.updates
    assert update.connection.version == 2
    assert_registered_as_target(hosts.get_host(HOST), TARGET)


def test_a_host_registered_otherwise_is_not_the_target():
    hosts = FakeHosts(**{HOST: _host(
        HOST, REAL_POOL_ID,
        ConnectionSubmission(kind="ssh", public={**target_connection(TARGET).public, "ssh_port": 2200}),
    )})
    with pytest.raises(AssertionError, match="not the target's"):
        assert_registered_as_target(hosts.get_host(HOST), TARGET)


# ---------------------------------------------------------------------------
# The service's execution, the delivered access, and the create's guest
# ---------------------------------------------------------------------------

def _execution(*entries: tuple[str, bool]) -> SimpleNamespace:
    return SimpleNamespace(executors=[
        SimpleNamespace(offering_mode=mode, mocked=mocked) for mode, mocked in entries
    ])


def test_a_real_vm_executor_passes_beside_any_other():
    assert vm_executor_is_real(_execution(("bare_metal", True), ("vm", False))).mocked is False


@pytest.mark.parametrize(
    "execution",
    [_execution(("vm", True)), _execution(("bare_metal", False)), _execution()],
    ids=["vm mocked", "no vm executor", "no executor"],
)
def test_a_mocked_or_absent_vm_executor_fails_naming_the_executors(execution):
    with pytest.raises(AssertionError, match="executors="):
        vm_executor_is_real(execution)


def test_the_delivered_endpoint_is_read_from_the_connection_details():
    status = SimpleNamespace(extra={
        "connection_details": '{"host": "198.51.100.7", "port": 30022, "user": "vmuser"}'
    })
    endpoint = delivered_endpoint(status)
    assert (endpoint.host, endpoint.port, endpoint.user) == ("198.51.100.7", 30022, "vmuser")


@pytest.mark.parametrize(
    "details", [None, {"host": "198.51.100.7", "port": 30022}, '{"host": "", "port": 1, "user": "u"}']
)
def test_an_incomplete_delivery_fails(details):
    with pytest.raises(AssertionError, match="no complete SSH endpoint"):
        delivered_endpoint(SimpleNamespace(extra={"connection_details": details}))


def _job(job_id: str, status: str = "succeeded", *, host: str = HOST, result=None) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job_id, status=status, params={}, host_id=host,
        capacity_reservation_id=RESERVATION, result=result, error=None if status != "failed" else "boom",
    )


def test_the_create_jobs_guest_is_read_from_its_detail():
    job = _job("create-1", result=ResultEnvelope(
        offering_mode="vm", result_kind="vm_create",
        value={"evidence": None, "detail": {"vm_name": "guest-1"}},
    ))
    assert created_guest_name(job) == "guest-1"
    with pytest.raises(AssertionError, match="no guest name"):
        created_guest_name(_job("create-2"))


# ---------------------------------------------------------------------------
# Finding a reservation's job and waiting for it
# ---------------------------------------------------------------------------

class FakeJobClient:
    """The job reads `JobWatch` makes: a listing, and each job's statuses in turn."""

    def __init__(self, jobs: list[JobStatusResponse], statuses: dict[str, list[JobStatusResponse]] | None = None):
        self.jobs = jobs
        self.statuses = {job_id: list(seen) for job_id, seen in (statuses or {}).items()}
        self.listed_with: list[dict] = []

    def list_jobs(self, **query) -> JobListResponse:
        self.listed_with.append(query)
        return JobListResponse(jobs=self.jobs, total=len(self.jobs), offset=0, limit=query["limit"])

    def get_job(self, job_id: str) -> JobStatusResponse:
        seen = self.statuses[job_id]
        return seen.pop(0) if len(seen) > 1 else seen[0]

    def get_job_logs(self, job_id: str) -> JobLogsResponse:
        return JobLogsResponse(job_id=job_id, status="failed", logs=f"playbook output of {job_id}")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _watch(client: FakeJobClient, *, bound: float = 60.0) -> tuple[JobWatch, FakeClock]:
    clock = FakeClock()
    return JobWatch(client, bound=bound, poll_interval=10.0, clock=clock, sleep=clock.sleep), clock


def test_exactly_one_job_on_the_target_is_found():
    client = FakeJobClient([_job("create-1")])
    watch, _clock = _watch(client)
    assert watch.only_job(RESERVATION, host_id=HOST, context="dispatching").job_id == "create-1"
    assert client.listed_with == [
        {"capacity_reservation_id": RESERVATION, "limit": 100, "sort": "created_at_asc"}
    ]


def test_the_one_job_besides_the_create_is_the_teardown():
    watch, _clock = _watch(FakeJobClient([_job("create-1"), _job("teardown-1", "running")]))
    assert watch.only_job(
        RESERVATION, host_id=HOST, besides=("create-1",), context="tearing down"
    ).job_id == "teardown-1"


def test_no_job_fails_naming_the_reservation_and_the_fulfillment():
    watch, _clock = _watch(FakeJobClient([]))
    with pytest.raises(AssertionError, match=f"{RESERVATION} ran no job.*fulfillment f-1 is 'dispatching'"):
        watch.only_job(RESERVATION, host_id=HOST, context="fulfillment f-1 is 'dispatching'")


def test_several_jobs_fail_listing_them():
    watch, _clock = _watch(FakeJobClient([_job("create-1"), _job("create-2")]))
    with pytest.raises(AssertionError, match="ran 2 jobs.*create-1.*create-2"):
        watch.only_job(RESERVATION, host_id=HOST, context="dispatching")


def test_a_job_on_another_host_fails():
    watch, _clock = _watch(FakeJobClient([_job("create-1", host="kvm-other")]))
    with pytest.raises(AssertionError, match="not the target host"):
        watch.only_job(RESERVATION, host_id=HOST, context="dispatching")


def test_a_job_is_read_until_it_succeeds():
    client = FakeJobClient([], {"create-1": [
        _job("create-1", "queued"), _job("create-1", "running"), _job("create-1"),
    ]})
    watch, clock = _watch(client)
    assert watch.until_succeeded("create-1", describe="create job").status == "succeeded"
    assert clock.slept == [10.0, 10.0]


def test_a_failed_job_fails_with_its_error_and_logs():
    watch, _clock = _watch(FakeJobClient([], {"create-1": [_job("create-1", "failed")]}))
    with pytest.raises(AssertionError, match="(?s)create job create-1 failed: boom.*playbook output of create-1"):
        watch.until_succeeded("create-1", describe="create job")


def test_a_job_still_running_at_the_bound_fails_with_its_status_and_logs():
    watch, clock = _watch(FakeJobClient([], {"create-1": [_job("create-1", "running")]}), bound=25.0)
    with pytest.raises(AssertionError, match="(?s)within 25.0s.*'running'.*playbook output of create-1"):
        watch.until_succeeded("create-1", describe="create job")
    # The last sleep stops at the bound rather than running past it.
    assert clock.slept == [10.0, 10.0, 5.0]


# ---------------------------------------------------------------------------
# The guest's absence from the host's VM list
# ---------------------------------------------------------------------------

def _listed(*names: str, **listing) -> JobStatusResponse:
    value = {
        "ansible_result": {
            "action": "list", "status": "success",
            "vms": [{"id": "-", "name": name, "state": "running"} for name in names],
            **listing,
        }
    }
    return _job("list-1", result=ResultEnvelope(offering_mode="vm", result_kind="vm_list", value=value))


def _list_check(listed: JobStatusResponse, vm_name: str = "guest-1"):
    operator = MagicMock()
    operator.list_vms.return_value = SimpleNamespace(job_id="list-1")
    watch, _clock = _watch(FakeJobClient([], {"list-1": [listed]}))
    try:
        return assert_guest_absent(watch, operator, host_id=HOST, vm_name=vm_name)
    finally:
        operator.list_vms.assert_called_once_with(HOST)


def test_a_list_without_the_guest_passes():
    assert _list_check(_listed("other-guest")) == ["other-guest"]
    assert _list_check(_listed()) == []


def test_a_list_naming_the_guest_fails():
    with pytest.raises(AssertionError, match="still lists guest 'guest-1'"):
        _list_check(_listed("guest-1", "other-guest"))


@pytest.mark.parametrize(
    "listed",
    [
        _job("list-1"),
        _listed(status="failed"),
        _listed(vms="guest-1"),
        _listed(vms=[{"state": "running"}]),
        _job("list-1", result=ResultEnvelope(offering_mode="vm", result_kind="vm_list", value={})),
    ],
    ids=["no result", "unsuccessful list", "list not a list", "entry without a name", "no list fact"],
)
def test_a_missing_or_malformed_list_fails(listed):
    with pytest.raises(AssertionError, match="VM list job list-1 reported"):
        _list_check(listed)


def test_a_failed_list_job_fails():
    with pytest.raises(AssertionError, match="VM list job list-1 failed"):
        _list_check(_job("list-1", "failed"))


# ---------------------------------------------------------------------------
# The settlement preflight
# ---------------------------------------------------------------------------

def _preflight(chosen: str) -> RealVmDealState:
    state = RealVmDealState(_evaluate_settle_passed=True, expected_host_id=chosen)
    real_lane.TestStage08a2_SettlementPreviewChoseTheTarget().test_08a2_the_settlement_preview_chose_the_target_host(
        TARGET, MagicMock(spec=RealVmComputeDealDriver), state
    )
    return state


def test_the_preflight_passes_when_the_preview_chose_the_target():
    assert _preflight(HOST)._settle_preflight_passed is True


def test_the_preflight_fails_and_settlement_stays_blocked_when_another_host_was_chosen():
    state = RealVmDealState(_evaluate_settle_passed=True, expected_host_id="kvm-other")
    with pytest.raises(AssertionError, match="chose host 'kvm-other', not the target"):
        real_lane.TestStage08a2_SettlementPreviewChoseTheTarget().test_08a2_the_settlement_preview_chose_the_target_host(
            TARGET, MagicMock(spec=RealVmComputeDealDriver), state
        )
    assert state._settle_preflight_passed is False


# ---------------------------------------------------------------------------
# A rerun's listing, and the re-reservation's claim
# ---------------------------------------------------------------------------

CAPACITY = TARGET.capacity.model_dump()
LISTING_SHAPE = TARGET.listing_shape.model_dump()


#: The two mechanisms a deal on a real target's resource may settle by.
BOTH = (ALKAHEST_MECHANISM, ARKHAI_PAYMENTS_MECHANISM)
CONTACT_EXCHANGE = "contact-exchange.v1"
OFFER_RESOURCE = {"offering_mode": "vm", "resource_id": REAL_RESOURCE_ID, **LISTING_SHAPE}
#: Each mechanism's settlement, as a module states it; the fake storefront
#: reads only the mechanism.
SETTLEMENTS = {mechanism: {"mechanism": mechanism} for mechanism in BOTH}


def _option(mechanism: str) -> dict:
    rates = [RateValue(field="amount", per="hour", value=1)]
    settlement = {"schema": mechanism}
    return SettlementOption(
        option_id=derive_settlement_option_id(
            price={"asset": "USD/6", "rates": rates}, settlement=settlement,
        ),
        price={"asset": "USD/6", "rates": rates},
        settlement=settlement,
    ).model_dump(mode="json")


def _listing(
    listing_id: str, *, status: str = "open", paused: bool = False,
    resource_id: str = REAL_RESOURCE_ID, mechanisms: tuple[str, ...] = BOTH, **shape,
) -> ListingSummary:
    return ListingSummary.from_dict({
        "listing_id": listing_id, "status": status, "paused": paused,
        "listing_resource": {
            "offering_mode": "vm", "resource_id": resource_id, **LISTING_SHAPE, **shape,
        },
        "settlement_options": [_option(mechanism) for mechanism in mechanisms],
    })


class FakeStorefront:
    """The storefront's listing reads, creation and pause, as 02b makes them.

    Creation publishes an option for each settlement stated whose mechanism
    is ready, as the storefront's composition suppresses an unready one, and
    refuses a second listing on a resource, whose source backs one listing.
    """

    def __init__(self, *listings: ListingSummary, ready: tuple[str, ...] = BOTH) -> None:
        self.listings = {listing.listing_id: listing for listing in listings}
        self.ready = ready
        self.read: list[tuple[int, int]] = []
        self.paused: list[str] = []
        self.created: list[dict] = []

    def get_system_status(self) -> SimpleNamespace:
        # Contact exchange is a composed seller mechanism too, ready wherever
        # contact profiles are configured, and settles no paid deal.
        return SimpleNamespace(settlement=[
            *({"mechanism": mechanism, "ready": mechanism in self.ready} for mechanism in BOTH),
            {"mechanism": CONTACT_EXCHANGE, "ready": True},
        ])

    def list_listings(self, *, limit: int, offset: int) -> ListingListResponse:
        self.read.append((limit, offset))
        page = list(self.listings.values())[offset:offset + limit]
        return ListingListResponse(listings=page, count=len(page), limit=limit, offset=offset)

    def create_listing(self, **request) -> SimpleNamespace:
        resource_id = request["listing_resource"]["resource_id"]
        assert not any(
            listing.listing_resource["resource_id"] == resource_id
            for listing in self.listings.values()
        ), f"this publication source is already bound to a listing: {resource_id}"
        self.created.append(request)
        listing_id = f"listing-{len(self.listings) + 1}"
        self.listings[listing_id] = _listing(
            listing_id, paused=request["paused"],
            resource_id=resource_id,
            mechanisms=tuple(
                each["mechanism"] for each in request["settlements"]
                if each["mechanism"] in self.ready
            ),
        )
        return SimpleNamespace(listing_id=listing_id)

    def pause_listing(self, listing_id: str) -> None:
        self.paused.append(listing_id)
        self.listings[listing_id].paused = True

    def get_listing(self, listing_id: str) -> ListingSummary:
        return self.listings[listing_id]


def _listing_for(
    storefront: FakeStorefront, mechanism: str = ALKAHEST_MECHANISM,
    settlements: dict = SETTLEMENTS,
) -> tuple[ListingSummary, bool]:
    """The listing a module of ``mechanism`` creates or adopts on the fake."""
    return create_or_adopt_listing(
        storefront_admin_client=storefront, storefront_seller_client=storefront,
        resource=OFFER_RESOURCE, shape=LISTING_SHAPE, mechanism=mechanism,
        settlements=settlements, max_duration_seconds=3600,
    )


def _driver(*, storefront_admin_client=None, target=TARGET) -> RealVmComputeDealDriver:
    return RealVmComputeDealDriver(
        provisioning_client=None, storefront_client=None,
        storefront_admin_client=storefront_admin_client, storefront_service_client=None,
        site_capacity_admin_client=None, site_capacity=None, site_id="site",
        vm_operator_client=None, target=target, buyer_public_key="k",
        listing_shape={}, jobs=JobWatch(None),
    )


def test_the_re_reservation_claims_the_resource_and_the_sold_capacity_as_dimensions():
    admin = MagicMock()
    _driver().reserve_released_capacity(admin, listing_id="listing-1", escrow_uid="0xescrow")
    admin.admin_reserve_capacity.assert_called_once_with(
        required_attributes={"resource_id": REAL_RESOURCE_ID, "dimensions": CAPACITY},
        listing_id="listing-1",
        escrow_uid="0xescrow",
    )


def test_selected_vm_resource_is_shared_by_listing_and_capacity_checks():
    target = VmHost.model_validate({**TARGET.model_dump(), "resource_id": "example-cpu-resource"})
    admin = MagicMock()
    driver = _driver(storefront_admin_client=admin, target=target)
    assert real_target_resource(target)["resource_id"] == "example-cpu-resource"
    driver.reserve_released_capacity(admin, listing_id="listing-1", escrow_uid="escrow-1")
    assert driver.reserved_resource_id == "example-cpu-resource"
    assert admin.admin_reserve_capacity.call_args.kwargs["required_attributes"]["resource_id"] == "example-cpu-resource"


@pytest.mark.parametrize(
    ("ready", "offered"),
    [(BOTH, BOTH), ((ALKAHEST_MECHANISM,), (ALKAHEST_MECHANISM,))],
    ids=["two mechanisms", "one mechanism"],
)
def test_creation_states_one_settlement_per_ready_deal_mechanism(ready, offered):
    """Contact exchange, ready beside them, settles no paid deal and is not stated."""
    storefront = FakeStorefront(ready=ready)
    listing, adopted = _listing_for(storefront)
    assert adopted is False
    (request,) = storefront.created
    assert [each["mechanism"] for each in request["settlements"]] == list(ready)
    assert request["paused"] is True and request["listing_resource"] == OFFER_RESOURCE
    assert listing_mechanisms(listing) == offered
    assert (listing.status, listing.paused) == ("open", True)


@pytest.mark.parametrize(
    "order",
    [BOTH, tuple(reversed(BOTH))],
    ids=["alkahest first", "payments first"],
)
def test_an_alkahest_module_and_a_payments_module_share_one_listing(order):
    storefront = FakeStorefront()
    first, created = _listing_for(storefront, order[0])
    second, adopted = _listing_for(storefront, order[1])
    assert (created, adopted) == (False, True)
    assert second.listing_id == first.listing_id
    assert len(storefront.created) == 1 and len(storefront.listings) == 1


def test_a_listing_lacking_the_modules_mechanism_fails_naming_it_and_its_options():
    storefront = FakeStorefront(_listing("listing-1", mechanisms=(ALKAHEST_MECHANISM,)))
    with pytest.raises(AssertionError) as failure:
        _listing_for(storefront, ARKHAI_PAYMENTS_MECHANISM)
    message = str(failure.value)
    assert f"listing listing-1 on this resource offers no {ARKHAI_PAYMENTS_MECHANISM}" in message
    assert storefront.listings["listing-1"].extra["settlement_options"][0]["option_id"] in message
    assert storefront.paused == [] and storefront.created == []


def test_a_ready_mechanism_the_run_states_no_settlement_for_fails_before_creation():
    storefront = FakeStorefront()
    with pytest.raises(AssertionError, match=ARKHAI_PAYMENTS_MECHANISM):
        _listing_for(storefront, settlements={ALKAHEST_MECHANISM: SETTLEMENTS[ALKAHEST_MECHANISM]})
    assert storefront.created == []


def test_a_module_whose_mechanism_is_not_ready_creates_nothing():
    storefront = FakeStorefront(ready=(ALKAHEST_MECHANISM,))
    with pytest.raises(AssertionError, match=f"{ARKHAI_PAYMENTS_MECHANISM} not ready"):
        _listing_for(storefront, ARKHAI_PAYMENTS_MECHANISM)
    assert storefront.created == []


def test_the_real_modules_alkahest_rate_is_the_canonical_asking_rate_in_whole_tokens():
    assert ALKAHEST_SETTLEMENT["rate"] == "10"
    assert ALKAHEST_SETTLEMENT["asset"] == DEAL_TOKEN["contract_address"]
    assert int(ALKAHEST_SETTLEMENT["rate"]) * 10 ** DEAL_TOKEN["decimals"] == LISTED_HOURLY_RATE


def test_an_open_listing_of_the_targets_shape_is_paused_and_adopted():
    storefront = FakeStorefront(_listing("listing-1"))
    adopted, was_adopted = _listing_for(storefront)
    assert was_adopted is True
    assert (adopted.listing_id, adopted.status, adopted.paused) == ("listing-1", "open", True)
    assert storefront.paused == ["listing-1"] and storefront.created == []


def test_a_listing_already_paused_is_adopted_without_another_pause():
    storefront = FakeStorefront(_listing("listing-1", paused=True))
    assert _listing_for(storefront)[0].listing_id == "listing-1"
    assert storefront.paused == []


@pytest.mark.parametrize("mechanism", BOTH)
@pytest.mark.parametrize("closed_first", [True, False])
def test_the_only_open_listing_is_adopted_without_changing_closed_history(
    mechanism, closed_first,
):
    closed = _listing("historical", status="closed", disk_gb=100)
    current = _listing("current")
    rows = (closed, current) if closed_first else (current, closed)
    storefront = FakeStorefront(*rows)

    adopted, was_adopted = _listing_for(storefront, mechanism)

    assert was_adopted and adopted is current
    assert storefront.paused == ["current"] and storefront.created == []
    assert storefront.listings["historical"] is closed
    assert (closed.status, closed.paused) == ("closed", False)


@pytest.mark.parametrize(
    "listings",
    [
        (_listing("listing-1", status="closed"),),
        (_listing("listing-1"), _listing("listing-2", paused=True)),
        (_listing("listing-1", disk_gb=100),),
        (_listing("listing-1", status="unknown"), _listing("listing-2")),
    ],
    ids=["closed", "two", "another shape", "unknown status"],
)
def test_a_listing_this_run_cannot_adopt_fails_naming_the_listings_and_the_capacity(listings):
    storefront = FakeStorefront(*listings)
    with pytest.raises(AssertionError) as failure:
        _listing_for(storefront)
    message = str(failure.value)
    assert f"the listing shape {LISTING_SHAPE}" in message, message
    for listing in listings:
        shape = {name: listing.listing_resource[name] for name in CAPACITY}
        assert (
            f"{listing.listing_id} {listing.status!r} paused={listing.paused} {shape} "
            f"offering {list(BOTH)}"
        ) in message, message
    assert storefront.paused == [] and storefront.created == []


def test_listings_on_other_resources_are_ignored():
    storefront = FakeStorefront(
        _listing("other-closed", status="closed", resource_id="compute-e2e-001"),
        _listing("other-shape", resource_id="compute-e2e-002", disk_gb=10),
    )
    listing, adopted = _listing_for(storefront)
    assert adopted is False and listing.listing_id not in {"other-closed", "other-shape"}
    assert storefront.paused == []


def test_02b_records_an_adopted_listing_and_creates_none():
    storefront = FakeStorefront(_listing("listing-1"))
    seller = MagicMock()
    state = RealVmDealState(_registry_reachable=True, _target_host_confirmed=True)
    real_lane.TestStage02b_ListingCreated().test_02b_create_the_listing_paused(
        _driver(storefront_admin_client=storefront), seller, storefront, OFFER_RESOURCE, state
    )
    assert state.seller_listing_id == "listing-1"
    seller.create_listing.assert_not_called()


def test_a_listing_on_a_later_page_is_found():
    others = [_listing(f"other-{n}", resource_id="compute-e2e-001") for n in range(200)]
    storefront = FakeStorefront(*others, _listing("listing-1"))
    assert _listing_for(storefront)[0].listing_id == "listing-1"
    assert storefront.read == [(200, 0), (200, 200)]


# ---------------------------------------------------------------------------
# Recovering a failed run's guest
# ---------------------------------------------------------------------------

class _Status(SimpleNamespace):
    def model_dump(self, mode: str = "python") -> dict:
        return dict(vars(self))


class FakeService(FakeJobClient):
    """The provisioning service's lease and convergence steps, as recovery drives
    them: a create the convergence step settles once its job succeeded, a lease
    the watchdog step expires, and a teardown each convergence step moves on."""

    def __init__(self, *, state: str, lease_status: str = "active", lease_ends_in: float = 3600):
        create = [_job("create-1", "running"), _job("create-1", result=ResultEnvelope(
            offering_mode="vm", result_kind="vm_create",
            value={"evidence": None, "detail": {"vm_name": "guest-1"}},
        ))]
        super().__init__([_job("create-1")], {"create-1": create})
        self.state = state
        self.lease = SimpleNamespace(
            status=lease_status,
            lease_end_utc=datetime.now(timezone.utc) + timedelta(seconds=lease_ends_in),
            release_job_id=None,
        )
        self.listed: list[str] = []

    def get_fulfillment_status(self, fulfillment_id: str) -> _Status:
        return _Status(capacity_reservation_id=RESERVATION, state=self.state)

    def advance_fulfillment_convergence_cycle(self) -> None:
        if self.state == "dispatching" and self.statuses["create-1"][-1].status == "succeeded":
            self.state = "active"
        elif self.state == "teardown_dispatch_pending":
            self.state = "tearing_down"
            self.jobs = [*self.jobs, _job("teardown-1")]
            self.statuses["teardown-1"] = [_job("teardown-1")]
        elif self.state == "tearing_down":
            self.state = "torn_down"

    def get_lease(self, reservation: str) -> SimpleNamespace:
        return self.lease

    def check_leases(self) -> None:
        expired = self.lease.lease_end_utc < datetime.now(timezone.utc)
        if self.lease.status == "active" and expired and self.state == "active":
            self.lease.status, self.lease.release_job_id = "releasing", "f-1"
            self.state = "teardown_dispatch_pending"
        elif self.lease.status == "releasing" and self.state == "torn_down":
            self.lease.status = "released"


class FakeSettlement:
    """The storefront's settle status, and the wait for the deal's
    ``job_submitted``: the status names the fulfillment once that event has
    come, which ``arrives`` says whether it ever does. A ``status`` of None is
    a settlement the storefront holds no record of (404) until that event, as
    for a submission that failed on the client's side while the storefront
    was still recording it."""

    def __init__(self, *, status: str | None = "provisioning", arrives: bool = True) -> None:
        self.status = status
        self.arrives = arrives
        self.recorded = False
        self.waits: list[dict] = []

    def get_settle_status(self, escrow_uid: str) -> SimpleNamespace:
        if self.status is None and not self.recorded:
            raise StorefrontClientError(f"No settlement job for escrow {escrow_uid}", status_code=404)
        return SimpleNamespace(
            status=self.status or "provisioning", fulfillment_id="f-1" if self.recorded else None
        )

    def wait_for_stage_event(self, stage: str, event: str, **query) -> SimpleNamespace:
        self.waits.append({"stage": stage, "event": event, **query})
        if not self.arrives:
            raise TimeoutError(f"{stage}/{event} not seen within {query.get('timeout')}s")
        self.recorded = True
        return SimpleNamespace(stage=stage, event=event)


def _recover(
    service: FakeService, *, guests: tuple[str, ...] = (), settlement=None, **state
) -> MagicMock:
    site = MagicMock()

    def truncate(reservation, end):
        service.lease.lease_end_utc = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return {}

    site.truncate_lease.side_effect = truncate
    service.statuses["list-1"] = [_listed(*guests)]
    operator = MagicMock()
    operator.list_vms.return_value = SimpleNamespace(job_id="list-1")
    if settlement is None:
        settlement = MagicMock()
        settlement.get_settle_status.return_value = SimpleNamespace(fulfillment_id="f-1")
    clock = FakeClock()
    driver = RealVmComputeDealDriver(
        provisioning_client=service, storefront_client=settlement,
        storefront_admin_client=settlement, storefront_service_client=None,
        site_capacity_admin_client=None, site_capacity=site, site_id="site",
        vm_operator_client=operator, target=TARGET, buyer_public_key="ssh-ed25519 AAAA e2e-buyer",
        listing_shape={}, jobs=JobWatch(service, clock=clock, sleep=clock.sleep),
    )
    driver.tear_down_after_failure(RealVmDealState(
        real_escrow_uid="0xescrow", negotiation_id="negotiation-1",
        _settle_preflight_passed=True, **state
    ))
    return site


def test_a_create_still_in_flight_is_settled_then_torn_down():
    """Settle dispatched, 08b failed before recording the fulfillment: the
    create is waited for and converged, then the lease expired and torn down."""
    service = FakeService(state="dispatching")
    site = _recover(service)
    site.truncate_lease.assert_called_once()
    assert (service.state, service.lease.status) == ("torn_down", "released")


def test_a_lease_already_back_dated_is_not_truncated_again():
    service = FakeService(state="active", lease_ends_in=-60)
    site = _recover(service, fulfillment_id="f-1", create_job_id="create-1", vm_name="guest-1")
    site.truncate_lease.assert_not_called()
    assert (service.state, service.lease.status) == ("torn_down", "released")


def test_a_guest_still_listed_fails_naming_what_an_operator_needs():
    service = FakeService(state="active")
    with pytest.raises(AssertionError) as failure:
        _recover(
            service, guests=("guest-1",),
            fulfillment_id="f-1", create_job_id="create-1", vm_name="guest-1",
        )
    message = str(failure.value)
    for named in ("'f-1'", f"'{RESERVATION}'", "'create-1'", "'teardown-1'", "'guest-1'", f"'{HOST}'"):
        assert named in message, message


def test_an_accepted_settlement_whose_dispatch_is_recorded_late_is_torn_down():
    """08b failed before the settle status named the fulfillment: recovery
    waits for the deal's ``job_submitted``, reads the status again, and tears
    the guest down as for a create still in flight."""
    service = FakeService(state="dispatching")
    settlement = FakeSettlement()
    site = _recover(service, settlement=settlement)
    assert [(wait["event"], wait["negotiation_id"]) for wait in settlement.waits] == [
        ("job_submitted", "negotiation-1")
    ]
    site.truncate_lease.assert_called_once()
    assert (service.state, service.lease.status) == ("torn_down", "released")


@pytest.mark.parametrize("status", ["provisioning", "a-status-added-later"])
def test_an_accepted_settlement_that_never_names_its_fulfillment_fails_naming_it(status):
    """A status recovery does not know is taken as accepted, so a guest is
    never passed over for a status the storefront adds later."""
    service = FakeService(state="dispatching")
    with pytest.raises(AssertionError) as failure:
        _recover(service, settlement=FakeSettlement(status=status, arrives=False))
    message = str(failure.value)
    for named in ("'0xescrow'", "'negotiation-1'", f"'{status}'", f"'{HOST}'"):
        assert named in message, message
    assert service.listed_with == []


def test_a_settlement_recorded_only_after_its_submission_failed_is_torn_down():
    """No settlement is recorded when recovery first reads, but the deal's
    dispatch is logged within the bound: the guest is torn down."""
    service = FakeService(state="dispatching")
    settlement = FakeSettlement(status=None)
    site = _recover(service, settlement=settlement)
    assert len(settlement.waits) == 1
    site.truncate_lease.assert_called_once()
    assert (service.state, service.lease.status) == ("torn_down", "released")


@pytest.mark.parametrize(
    ("status", "waits"), [("refunding", 0), (None, 1)], ids=["refund before delivery", "no record"],
)
def test_a_settlement_the_storefront_did_not_accept_leaves_nothing_to_tear_down(status, waits):
    """A status showing nothing dispatched returns at once; a settlement never
    recorded returns once its dispatch has not come within the bound."""
    service = FakeService(state="dispatching")
    site = MagicMock()
    settlement = FakeSettlement(status=status, arrives=False)
    driver = RealVmComputeDealDriver(
        provisioning_client=service, storefront_client=settlement,
        storefront_admin_client=settlement, storefront_service_client=None,
        site_capacity_admin_client=None, site_capacity=site, site_id="site",
        vm_operator_client=MagicMock(), target=TARGET, buyer_public_key="k",
        listing_shape={}, jobs=JobWatch(service),
    )
    driver.tear_down_after_failure(RealVmDealState(real_escrow_uid="0xescrow"))
    assert len(settlement.waits) == waits
    site.truncate_lease.assert_not_called()
    assert service.listed_with == []


# ---------------------------------------------------------------------------
# The lease view over a GPU-less declaration
# ---------------------------------------------------------------------------

def _lease_over(row: dict) -> DealLease:
    site = MagicMock()
    site.reservations_for_negotiation.return_value = [
        {"capacity_reservation_id": RESERVATION, "lease_end_utc": "2030-01-01T00:00:00Z"}
    ]
    site.snapshot.return_value = [{"resource_id": "res-1", **row}]
    return DealLease(MagicMock(), site, negotiation_id="negotiation-1")


def test_a_gpu_less_declaration_is_held_while_any_dimension_is_short():
    declared = {"vcpu_count": 7, "ram_gb": 28, "disk_gb": 160}
    held = _lease_over({"value": None, "capacity": declared, "available": {**declared, "vcpu_count": 0}})
    free = _lease_over({"value": None, "capacity": declared, "available": declared})
    assert held.resource_consumed(None, "res-1") is True
    assert free.resource_consumed(None, "res-1") is False


def test_a_gpu_declaration_is_still_read_from_its_mirror():
    held = _lease_over({"value": 1, "available_units": 0, "capacity": {}, "available": {}})
    free = _lease_over({"value": 1, "available_units": 1})
    assert held.resource_consumed(None, "res-1") is True
    assert free.resource_consumed(None, "res-1") is False



def test_executor_fixture_refuses_unready_relay_before_lifecycle_holds():
    section = TARGET.model_dump()
    section["access"] = {"mode": "relay", "relay_id": "example-vm-relay"}
    target = VmHost.model_validate(section)
    client = MagicMock()
    client.get_system_status.return_value.execution = SimpleNamespace(
        executors=[SimpleNamespace(offering_mode="vm", mocked=False)],
    )
    client.get_relay.return_value = SimpleNamespace(id="example-vm-relay", enabled=False)
    with pytest.raises(AssertionError, match="disabled"):
        real_lane.real_vm_execution.__wrapped__(target, client)
    assert [call[0] for call in client.method_calls] == ["get_system_status", "get_relay"]


def _relay_target():
    section = TARGET.model_dump()
    section["access"] = {"mode": "relay", "relay_id": "example-vm-relay"}
    return VmHost.model_validate(section)


def _relay(**changes):
    fields = dict(id="example-vm-relay", relay_addr="192.0.2.22", enabled=True,
                  token_configured=True, grant_keys=SimpleNamespace(active=SimpleNamespace(kid="example-kid")))
    return SimpleNamespace(**{**fields, **changes})


@pytest.mark.parametrize(("changes", "reason"), [
    ({"enabled": False}, "disabled"),
    ({"token_configured": False}, "token"),
    ({"grant_keys": SimpleNamespace(active=None)}, "active grant key"),
    ({"id": "another-relay"}, "another identity"),
])
def test_relay_preflight_refuses_unusable_operator_configuration(changes, reason):
    client = MagicMock()
    client.get_relay.return_value = _relay(**changes)
    with pytest.raises(AssertionError, match=reason):
        configured_relay(client, _relay_target())
    assert [call[0] for call in client.method_calls] == ["get_relay"]


def test_direct_target_does_not_read_or_create_a_relay():
    client = MagicMock()
    assert configured_relay(client, TARGET) is None
    assert client.method_calls == []


def test_relay_endpoint_is_the_reservations_leased_port():
    driver = _driver()
    driver.target = _relay_target()
    client = MagicMock()
    client.get_relay.return_value = _relay()
    client.get_fulfillment_status.return_value = SimpleNamespace(capacity_reservation_id=RESERVATION, state="active")
    holding = SimpleNamespace(owner_kind="fulfillment", owner_id=RESERVATION,
                              remote_port=30022, host_id=HOST, released_at=None)
    client.list_relay_leases.return_value = SimpleNamespace(leases=[holding])
    driver.provisioning_client = client
    driver.storefront_client = MagicMock()
    driver.storefront_client.get_settle_status.return_value.extra = {
        "connection_details": {"host": "192.0.2.22", "port": 30022, "user": "vmuser"},
    }
    state = RealVmDealState(real_escrow_uid="escrow", fulfillment_id="fulfillment")
    assert driver.delivered_access(state).port == holding.remote_port
    holding.remote_port += 1
    with pytest.raises(AssertionError, match="differs"):
        driver.delivered_access(state)


def test_released_relay_port_requires_release_expiry_and_no_active_owner():
    driver = _driver()
    driver.target = _relay_target()
    client = MagicMock()
    client.get_fulfillment_status.return_value = SimpleNamespace(capacity_reservation_id=RESERVATION, state="torn_down")
    holding = SimpleNamespace(owner_kind="fulfillment", owner_id=RESERVATION,
                              remote_port=30022, released_at=datetime.now(timezone.utc),
                              grant_expires_at=datetime.now(timezone.utc))
    client.list_relay_leases.return_value = SimpleNamespace(leases=[holding])
    driver.provisioning_client = client
    endpoint = delivered_endpoint(SimpleNamespace(extra={"connection_details": {
        "host": "192.0.2.22", "port": 30022, "user": "vmuser",
    }}))
    driver.assert_relay_released("f-1", endpoint)
    holding.released_at = None
    with pytest.raises(AssertionError, match="record release"):
        driver.assert_relay_released("f-1", endpoint)
    holding.released_at = datetime.now(timezone.utc)
    holding.grant_expires_at = None
    with pytest.raises(AssertionError, match="grant expiry"):
        driver.assert_relay_released("f-1", endpoint)


def test_both_deals_are_recovered_even_when_second_recovery_fails():
    class RecordingRecovery(RealVmComputeDealDriver):
        def tear_down_after_failure(self, state):
            self.attempted.append(state.negotiation_id)
            if state.negotiation_id == "second":
                raise AssertionError("second-guest-remains")

    driver = RecordingRecovery(**vars(_driver()))
    driver.attempted = []
    state = RealVmDealState(
        negotiation_id="first", _settle_preflight_passed=True,
        second_negotiation_id="second", second_escrow_uid="escrow-2",
        _second_settlement_submitted=True,
    )
    with pytest.raises(AssertionError, match="second deal: second-guest-remains"):
        driver.recover_both(state)
    assert driver.attempted == ["second", "first"]


def test_real_listing_sells_two_guest_shapes_without_changing_declared_capacity():
    driver = _driver()
    assert driver.capacity == CAPACITY
    assert driver.listing_status_after_first_fulfillment == "open"
    assert real_lane.offer_resource.__wrapped__(TARGET)["vcpu_count"] == LISTING_SHAPE["vcpu_count"]
    for dimension, amount in LISTING_SHAPE.items():
        assert 2 * amount <= CAPACITY[dimension]


@pytest.mark.parametrize(("expected", "observed"), [("open", "open"), ("closed", "closed"), ("open", "closed"), ("closed", "open")])
def test_shared_ready_stage_checks_each_lanes_actual_capacity_expectation(expected, observed):
    admin = MagicMock()
    admin.wait_for_settlement.return_value = SimpleNamespace(ready=True, status="ready")
    admin.get_listing.return_value = SimpleNamespace(status=observed)
    driver = SimpleNamespace(listing_status_after_first_fulfillment=expected, assert_delivery=MagicMock())
    state = RealVmDealState(settlement_ref="escrow", provisioning_result_injected=True,
                            seller_listing_id="listing", negotiation_id="negotiation", _listing_reconciled=True)
    call = lambda: Stage09b_SettlementReadyAndCredentials().test_09b_settlement_ready_credentials_and_listing_closed(admin, driver, state)
    if expected == observed:
        call()
        assert state.settlement_status == "ready"
    else:
        with pytest.raises(AssertionError, match="Expected listing status"):
            call()
        assert state.settlement_status is None


def test_pool_registration_sends_and_reconciles_relay_config_through_typed_client():
    class PoolTransport:
        def __init__(self):
            self.row = None
            self.operations = []

        def authenticated_request(self, method, path, *args, **kwargs):
            body = args[0].model_dump(exclude_none=True) if args else None
            self.operations.append((method, body))
            if method == "GET":
                if self.row is None:
                    raise ComputeProvisioningError("missing", status_code=404)
            elif method == "POST":
                self.row = {**body, "created_at": datetime.now(timezone.utc),
                            "updated_at": datetime.now(timezone.utc)}
            elif method == "PATCH":
                self.row.update(body)
            else:
                raise AssertionError(method)
            return self.row

    transport = PoolTransport()
    relay = {"relay_id": "example-vm-relay"}
    shape = real_lane.capacity_source_for(real_lane.offer_resource.__wrapped__(TARGET))["listing_shape"]
    kwargs = dict(pool_id="example-pool", listing_mode="specific_resource",
                  listing_shapes={"vm": [shape]})
    created = register_e2e_pool(transport, provider_config=relay, **kwargs)
    assert created.provider_config == relay
    assert [body["provider_config"] for method, body in transport.operations if method == "POST"] == [relay]
    transport.operations.clear()
    register_e2e_pool(transport, provider_config=relay, **kwargs)
    assert [method for method, _ in transport.operations] == ["GET"]
    register_e2e_pool(transport, **kwargs)
    assert transport.row["provider_config"] == relay
    register_e2e_pool(transport, provider_config={}, **kwargs)
    assert transport.row["provider_config"] == {}
    assert [body["provider_config"] for method, body in transport.operations if method == "PATCH"] == [{}]


    class ExecutorTransport(PoolTransport, FakeHosts):
        def __init__(self):
            PoolTransport.__init__(self)
            FakeHosts.__init__(self)

    transport = ExecutorTransport()
    site = SimpleNamespace(register_resource=AsyncMock(return_value={"registered": True}))
    host = provision_e2e_executor(
        transport, site, host=HOST, resource_id=REAL_RESOURCE_ID,
        attributes={"region": "example-region"}, pool_id="example-pool",
        sellable_units=None, capacity=CAPACITY, connection=target_connection(TARGET),
        listing_shapes={"vm": [shape]}, provider_config=relay,
    )
    assert host.host_id == HOST and transport.row["provider_config"] == relay
    assert site.register_resource.await_args.kwargs["capacity"] == CAPACITY


@pytest.mark.parametrize("resource_id", [None, "example-cpu-resource"])
@pytest.mark.parametrize("listing_ids", [[], ["selected"], ["other"], ["selected", "other"]])
def test_real_purchase_refuses_ambiguous_discovery_before_payment(resource_id, listing_ids):
    target = TARGET.model_copy(update={"resource_id": resource_id})
    registry = MagicMock()
    registry.list_listings.return_value.listings = [SimpleNamespace(id=value) for value in listing_ids]
    listing = SimpleNamespace(id="selected", listing_resource=real_target_resource(target))
    registry.get_listing.return_value = listing
    admin = MagicMock()
    admin.admin_refresh_site_projections.return_value = {"sites": {"site": {"resource_pool": {"state": "loaded"}}}}
    driver = RealVmPurchaseDriver(
        provisioning_client=None, storefront_client=None,
        storefront_admin_client=admin, storefront_service_client=None,
        site_capacity_admin_client=None, site_capacity=None, site_id="site",
        vm_operator_client=None, target=target, buyer_public_key="k",
        listing_shape={}, jobs=JobWatch(None), purchase_registry=registry,
        seller_account="seller", dispute_window="P7D",
    )
    if listing_ids == ["selected"]:
        assert driver.discover("selected") is listing
        assert driver.second_purchase("other-key").reserved_resource_id == (resource_id or REAL_RESOURCE_ID)
    else:
        with pytest.raises(AssertionError, match="ambiguous"):
            driver.discover("selected")
        registry.get_listing.assert_not_called()
    registry.list_listings.assert_called_once_with(region="e2e-real-host", limit=2)


def test_real_purchase_refuses_unconfirmed_projection_before_registry_discovery():
    admin, registry = MagicMock(), MagicMock()
    admin.admin_refresh_site_projections.return_value = {
        "sites": {"site": {"resource_pool": {"state": "unavailable"}}},
    }
    driver = RealVmPurchaseDriver(
        provisioning_client=None, storefront_client=None,
        storefront_admin_client=admin, storefront_service_client=None,
        site_capacity_admin_client=None, site_capacity=None, site_id="site",
        vm_operator_client=None, target=TARGET, buyer_public_key="k",
        listing_shape={}, jobs=JobWatch(None), purchase_registry=registry,
        seller_account="seller", dispute_window="P7D",
    )
    with pytest.raises(AssertionError, match="site projections did not confirm"):
        driver.discover("selected")
    registry.list_listings.assert_not_called()
    registry.get_listing.assert_not_called()
