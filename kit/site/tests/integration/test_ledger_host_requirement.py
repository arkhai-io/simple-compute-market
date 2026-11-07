"""Admission and the offered read apply the usable-host rule.

The suite's pools name provider ``"test"``. Each case supplies the requirement
the composition would and, where it matters, a report of the hosts taking new
delivery, then declares capacity naming a host or none, to prove that a
declaration with no usable host is simply not a candidate in a backed pool
whose provider needs one, and is not offered by the projections' read.
"""

from __future__ import annotations

import sqlite3

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from market_resource_pools.db import Base as ResourcePoolBase
from market_resource_pools.db import DEFAULT_POOL_ID, ResourcePool
from market_site.db import Base
from market_site.ledger import (
    CapacityConflictError,
    CapacityLedgerService,
    UndeclaredOfferingModeError,
)
from market_site.projections import SiteProjectionService

BACKED_POOL_TAGS = {
    "deliverable_modes": ["vm"],
    "advertisable_modes": ["vm"],
    "capacity_backing": "backed",
}
UNBACKED_POOL_ID = "introductions"
UNBACKED_POOL_TAGS = {
    "deliverable_modes": [],
    "advertisable_modes": ["vm"],
    "capacity_backing": "unbacked",
}


class FakeDeliverableHosts:
    """A report over a fixed, mutable set, recording the session it was read in."""

    def __init__(self, host_ids=()) -> None:
        self.host_ids = set(host_ids)
        self.sessions: list[Session] = []

    def deliverable_host_ids(self, db: Session) -> frozenset[str]:
        self.sessions.append(db)
        return frozenset(self.host_ids)


class WriteProbingDeliverableHosts(FakeDeliverableHosts):
    """A report that, each time it is read, tries a write on another
    connection to the same database file, as a host disable would, and records
    whether the write was held off."""

    def __init__(self, path, host_ids=()) -> None:
        super().__init__(host_ids)
        self.path = path
        self.writes_held_off: list[bool] = []

    def deliverable_host_ids(self, db: Session) -> frozenset[str]:
        answer = super().deliverable_host_ids(db)
        # Autocommit and no busy wait, so the write either commits at once or
        # is refused at once.
        other = sqlite3.connect(self.path, timeout=0, isolation_level=None)
        try:
            other.execute("UPDATE resource_pools SET label = label")
            self.writes_held_off.append(False)
        except sqlite3.OperationalError as exc:
            assert "locked" in str(exc)
            self.writes_held_off.append(True)
        finally:
            other.close()
        return answer


def _make_ledger(
    *, host_requirement, deliverable_hosts=None, pool_tags=None, database_path=None
):
    if database_path is None:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        # As the compute service's engine is: file-backed, one connection per
        # session.
        engine = create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
    Base.metadata.create_all(bind=engine)
    ResourcePoolBase.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db, db.begin():
        db.add(
            ResourcePool(
                id=DEFAULT_POOL_ID,
                label="Default Pool",
                provider="test",
                enabled=True,
                policy_tags=dict(pool_tags or {"deliverable_modes": ["vm"]}),
            )
        )
        db.add(
            ResourcePool(
                id=UNBACKED_POOL_ID,
                label="Introductions",
                provider="test",
                enabled=True,
                policy_tags=dict(UNBACKED_POOL_TAGS),
            )
        )
    return CapacityLedgerService(
        session_factory,
        unit_claim_keys=("units", "gpu_count"),
        mirror_dimension="gpu_count",
        host_requirement=host_requirement,
        deliverable_hosts=deliverable_hosts,
    )

VM_CLAIM = {"offering_mode": "vm", "gpu_count": 1}


def _declare(
    ledger,
    resource_id: str,
    *,
    host_id: str | None = None,
    units: int = 4,
    pool_id: str = DEFAULT_POOL_ID,
    enabled: bool = True,
):
    ledger.register_resource(
        resource_id=resource_id,
        total_units=units,
        pool_id=pool_id,
        host_id=host_id,
        enabled=enabled,
    )


def _stored(ledger) -> dict[str, dict]:
    return {row["resource_id"]: row for row in ledger.list_resources()}


def _offered(ledger) -> dict[str, dict]:
    return {row["resource_id"]: row for row in ledger.list_offered_resources()}


def _snapshot_ids(ledger) -> set[str]:
    return {row["resource_id"] for row in ledger.snapshot()}


def _no_hold_exists(ledger) -> bool:
    return all(
        row["available_units"] == row["value"] for row in ledger.list_resources()
    )


def _capacity_version(ledger) -> int:
    return ledger.events_after(0)[1]


def test_a_declaration_naming_no_host_is_not_admitted_where_the_provider_needs_one():
    ledger = _make_ledger(host_requirement={"test": True})
    _declare(ledger, "no-host")

    assert ledger.probe(claim=VM_CLAIM) is None
    assert ledger.reserve(claim=VM_CLAIM, deal_ref={}) is None
    assert _no_hold_exists(ledger)


def test_the_claim_falls_through_to_a_declaration_naming_a_host():
    ledger = _make_ledger(host_requirement={"test": True})
    # Registered first, so it would be the first candidate if it were one.
    _declare(ledger, "no-host")
    _declare(ledger, "hosted", host_id="kvm1")

    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    assert reserved is not None
    assert reserved["resource_id"] == "hosted"


def test_a_provider_the_requirement_does_not_name_needs_a_host():
    ledger = _make_ledger(host_requirement={"some-other-provider": False})
    _declare(ledger, "no-host")

    assert ledger.probe(claim=VM_CLAIM) is None


@pytest.mark.parametrize("host_requirement", [None, {"test": False}])
def test_a_declaration_naming_no_host_is_admitted_where_no_host_is_needed(
    host_requirement,
):
    ledger = _make_ledger(host_requirement=host_requirement)
    _declare(ledger, "no-host")

    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    assert reserved is not None
    assert reserved["resource_id"] == "no-host"


def test_with_no_requirement_a_report_refuses_nothing():
    ledger = _make_ledger(
        host_requirement=None, deliverable_hosts=FakeDeliverableHosts()
    )
    _declare(ledger, "named", host_id="disabled-host")

    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    assert reserved["resource_id"] == "named"


def test_without_a_report_any_named_host_is_admitted():
    """A composition supplying no report has nothing to judge a host by."""
    ledger = _make_ledger(host_requirement={"test": True})
    _declare(ledger, "named", host_id="not-registered-anywhere")

    assert ledger.reserve(claim=VM_CLAIM, deal_ref={}) is not None


@pytest.mark.parametrize(
    "host_id", ["disabled-host", "never-registered"], ids=["disabled", "unregistered"]
)
def test_probe_and_reserve_refuse_a_host_not_taking_delivery_and_fall_through(host_id):
    hosts = FakeDeliverableHosts({"kvm1"})
    ledger = _make_ledger(host_requirement={"test": True}, deliverable_hosts=hosts)
    # Registered first, so it would be the first candidate if it were one.
    _declare(ledger, "undeliverable", host_id=host_id)
    _declare(ledger, "hosted", host_id="kvm1")

    assert ledger.probe(claim=VM_CLAIM)["resource_id"] == "hosted"
    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    assert reserved["resource_id"] == "hosted"


def test_each_admission_reads_the_report_once_in_its_own_session():
    hosts = FakeDeliverableHosts({"kvm1"})
    ledger = _make_ledger(host_requirement={"test": True}, deliverable_hosts=hosts)
    _declare(ledger, "first", host_id="kvm1")
    _declare(ledger, "second", host_id="kvm1-other")

    ledger.probe(claim=VM_CLAIM)
    ledger.reserve(claim=VM_CLAIM, deal_ref={})

    # One read per call, however many candidates it walks, each in a session
    # of the call's own.
    assert len(hosts.sessions) == 2
    assert all(isinstance(db, Session) for db in hosts.sessions)
    assert hosts.sessions[0] is not hosts.sessions[1]


@pytest.mark.parametrize(
    "host_id", ["disabled-host", "never-registered"], ids=["disabled", "unregistered"]
)
def test_a_claim_only_a_host_not_taking_delivery_could_serve_gets_no_capacity(host_id):
    ledger = _make_ledger(
        host_requirement={"test": True},
        deliverable_hosts=FakeDeliverableHosts({"kvm1"}),
    )
    _declare(ledger, "undeliverable", host_id=host_id)

    assert ledger.probe(claim=VM_CLAIM) is None
    assert ledger.reserve(claim=VM_CLAIM, deal_ref={}) is None
    assert _no_hold_exists(ledger)


def test_a_host_returned_to_the_report_is_matched_again():
    hosts = FakeDeliverableHosts()
    ledger = _make_ledger(host_requirement={"test": True}, deliverable_hosts=hosts)
    _declare(ledger, "named", host_id="kvm1")
    assert ledger.probe(claim=VM_CLAIM) is None

    hosts.host_ids.add("kvm1")

    assert ledger.reserve(claim=VM_CLAIM, deal_ref={})["resource_id"] == "named"


def test_a_disabled_declaration_stays_unmatched_and_unoffered_when_its_host_returns():
    hosts = FakeDeliverableHosts()
    ledger = _make_ledger(
        host_requirement={"test": True},
        deliverable_hosts=hosts,
        pool_tags=BACKED_POOL_TAGS,
    )
    _declare(ledger, "named", host_id="kvm1", enabled=False)

    hosts.host_ids.add("kvm1")

    assert ledger.probe(claim=VM_CLAIM) is None
    assert _offered(ledger)["named"]["enabled"] is False
    assert "named" not in _snapshot_ids(ledger)


def test_resize_applies_the_same_rule():
    ledger = _make_ledger(host_requirement={"test": True})
    _declare(ledger, "hosted", host_id="kvm1", units=2)
    _declare(ledger, "no-host", units=8)
    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    resized = ledger.resize_reservation(
        old_capacity_reservation_id=reserved["capacity_reservation_id"],
        new_claim={"offering_mode": "vm", "gpu_count": 4},
    )

    # Only the declaration naming no host could hold four, so nothing changes.
    assert resized is None
    stored = _stored(ledger)
    assert stored["hosted"]["available_units"] == 1
    assert stored["no-host"]["available_units"] == 8


def test_resize_refuses_a_declaration_whose_host_is_disabled():
    hosts = FakeDeliverableHosts({"kvm1"})
    ledger = _make_ledger(host_requirement={"test": True}, deliverable_hosts=hosts)
    _declare(ledger, "hosted", host_id="kvm1", units=2)
    _declare(ledger, "big", host_id="kvm2", units=8)
    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    resized = ledger.resize_reservation(
        old_capacity_reservation_id=reserved["capacity_reservation_id"],
        new_claim={"offering_mode": "vm", "gpu_count": 4},
    )

    # Only the declaration on the host not taking delivery could hold four.
    assert resized is None
    stored = _stored(ledger)
    assert stored["hosted"]["available_units"] == 1
    assert stored["big"]["available_units"] == 8


@pytest.mark.parametrize(
    "host_id", ["disabled-host", "never-registered"], ids=["disabled", "unregistered"]
)
def test_resize_falls_through_to_a_declaration_with_a_usable_host(host_id):
    hosts = FakeDeliverableHosts({"kvm1", "kvm3"})
    ledger = _make_ledger(host_requirement={"test": True}, deliverable_hosts=hosts)
    _declare(ledger, "hosted", host_id="kvm1", units=2)
    # Registered before the usable one, so it would be the first candidate.
    _declare(ledger, "undeliverable", host_id=host_id, units=8)
    _declare(ledger, "usable", host_id="kvm3", units=8)
    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    resized = ledger.resize_reservation(
        old_capacity_reservation_id=reserved["capacity_reservation_id"],
        new_claim={"offering_mode": "vm", "gpu_count": 4},
    )

    assert resized["resource_id"] == "usable"
    stored = _stored(ledger)
    assert stored["undeliverable"]["available_units"] == 8
    assert stored["usable"]["available_units"] == 4


def test_assignment_refuses_a_destination_naming_no_host():
    ledger = _make_ledger(host_requirement={"test": True})
    _declare(ledger, "hosted", host_id="kvm1")
    _declare(ledger, "no-host")
    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    with pytest.raises(CapacityConflictError, match="names no host"):
        ledger.assign_settlement_resource(
            capacity_reservation_id=reserved["capacity_reservation_id"],
            settlement_resource_id="no-host",
        )


def test_assignment_refuses_a_destination_whose_host_is_disabled_and_keeps_the_debit():
    hosts = FakeDeliverableHosts({"kvm1", "kvm2"})
    ledger = _make_ledger(host_requirement={"test": True}, deliverable_hosts=hosts)
    _declare(ledger, "hosted", host_id="kvm1")
    _declare(ledger, "other", host_id="kvm2")
    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})
    assert reserved["resource_id"] == "hosted"
    version = _capacity_version(ledger)

    hosts.host_ids.discard("kvm2")
    with pytest.raises(CapacityConflictError, match="not taking new delivery"):
        ledger.assign_settlement_resource(
            capacity_reservation_id=reserved["capacity_reservation_id"],
            settlement_resource_id="other",
        )

    capacity_reservation_id = reserved["capacity_reservation_id"]
    assert ledger.get_reservation_backing_resource_id(capacity_reservation_id) == "hosted"
    stored = _stored(ledger)
    assert stored["hosted"]["available_units"] == 3
    assert stored["other"]["available_units"] == 4
    assert _capacity_version(ledger) == version


@pytest.mark.parametrize(
    "host_id", ["disabled-host", "never-registered", None],
    ids=["disabled", "unregistered", "no-host"],
)
def test_the_offered_read_reports_a_declaration_with_no_usable_host_not_enabled(host_id):
    ledger = _make_ledger(
        host_requirement={"test": True},
        deliverable_hosts=FakeDeliverableHosts({"kvm1"}),
        pool_tags=BACKED_POOL_TAGS,
    )
    _declare(ledger, "undeliverable", host_id=host_id)
    _declare(ledger, "hosted", host_id="kvm1")

    offered = _offered(ledger)
    assert offered["undeliverable"]["enabled"] is False
    assert offered["hosted"]["enabled"] is True
    assert _snapshot_ids(ledger) == {"hosted"}
    # The operator's listing keeps what was declared.
    assert _stored(ledger)["undeliverable"]["enabled"] is True


def test_the_offered_read_differs_from_the_stored_one_only_in_enabled():
    ledger = _make_ledger(
        host_requirement={"test": True},
        deliverable_hosts=FakeDeliverableHosts(),
        pool_tags=BACKED_POOL_TAGS,
    )
    _declare(ledger, "named", host_id="kvm1")

    offered = _offered(ledger)["named"]
    stored = _stored(ledger)["named"]

    assert {**offered, "enabled": True} == stored


def test_a_host_leaving_the_report_records_no_event_and_projections_advance():
    """The report is read, never written, so the ledger records nothing for a
    change in it; that a host write records none is the compute service's
    evidence."""
    hosts = FakeDeliverableHosts({"kvm1"})
    ledger = _make_ledger(
        host_requirement={"test": True},
        deliverable_hosts=hosts,
        pool_tags=BACKED_POOL_TAGS,
    )
    _declare(ledger, "named", host_id="kvm1")
    projections = SiteProjectionService(ledger)
    buckets_before, rows_before = projections.capacity_buckets()
    pools_before, _ = projections.resource_pools()
    version = _capacity_version(ledger)

    hosts.host_ids.clear()

    buckets_after, rows_after = projections.capacity_buckets()
    pools_after, pool_rows = projections.resource_pools()
    assert [row["resource_count"] for row in rows_before] == [1]
    assert rows_after == []
    assert buckets_after.revision == buckets_before.revision + 1
    assert buckets_after.digest != buckets_before.digest
    assert pools_after.revision == pools_before.revision + 1
    [pool] = [row for row in pool_rows if row["pool_id"] == DEFAULT_POOL_ID]
    assert [entry["enabled"] for entry in pool["resources"]] == [False]
    assert _capacity_version(ledger) == version


@pytest.mark.parametrize("host_id", ["disabled-host", None], ids=["disabled", "no-host"])
def test_an_unbacked_pools_declaration_keeps_its_own_enabled(host_id):
    ledger = _make_ledger(
        host_requirement={"test": True},
        deliverable_hosts=FakeDeliverableHosts(),
        pool_tags=BACKED_POOL_TAGS,
    )
    _declare(ledger, "introduction", host_id=host_id, pool_id=UNBACKED_POOL_ID)

    assert _offered(ledger)["introduction"]["enabled"] is True


def test_a_pool_delivering_a_mode_is_judged_by_its_modes_not_its_backing_label():
    """The site reads no backing: delivering a mode is what puts a pool under
    the rule, as it is what lets admission reach it."""
    ledger = _make_ledger(
        host_requirement={"test": True},
        deliverable_hosts=FakeDeliverableHosts(),
        pool_tags={"deliverable_modes": ["vm"]},
    )
    _declare(ledger, "named", host_id="kvm1")

    assert _offered(ledger)["named"]["enabled"] is False


def test_a_pool_whose_deliverable_modes_do_not_parse_is_judged_to_deliver():
    """Startup and every write refuse such a pool; the offered read fails closed."""
    ledger = _make_ledger(
        host_requirement={"test": True},
        deliverable_hosts=FakeDeliverableHosts(),
        pool_tags={**BACKED_POOL_TAGS, "deliverable_modes": "vm"},
    )
    _declare(ledger, "named", host_id="kvm1")

    assert _offered(ledger)["named"]["enabled"] is False


def test_a_pool_delivering_no_mode_keeps_its_declarations_own_enabled():
    """Such a backed pool may advertise only what it delivers, so nothing of
    it can be listed or admitted; its declarations are judged as an unbacked
    pool's are."""
    ledger = _make_ledger(
        host_requirement={"test": True},
        deliverable_hosts=FakeDeliverableHosts(),
        pool_tags={
            "deliverable_modes": [],
            "advertisable_modes": [],
            "capacity_backing": "backed",
        },
    )
    _declare(ledger, "named", host_id="kvm1")

    assert _offered(ledger)["named"]["enabled"] is True
    with pytest.raises(UndeclaredOfferingModeError):
        ledger.probe(claim=VM_CLAIM)


def test_with_no_requirement_the_offered_read_is_the_stored_one():
    ledger = _make_ledger(
        host_requirement=None,
        deliverable_hosts=FakeDeliverableHosts(),
        pool_tags=BACKED_POOL_TAGS,
    )
    _declare(ledger, "no-host")
    _declare(ledger, "named", host_id="kvm1")
    _declare(ledger, "off", host_id="kvm2", enabled=False)

    assert ledger.list_offered_resources() == ledger.list_resources()


def _file_backed_ledger(tmp_path):
    path = tmp_path / "site.db"
    hosts = WriteProbingDeliverableHosts(path, {"kvm1", "kvm2"})
    ledger = _make_ledger(
        host_requirement={"test": True},
        deliverable_hosts=hosts,
        pool_tags=BACKED_POOL_TAGS,
        database_path=path,
    )
    _declare(ledger, "hosted", host_id="kvm1", units=2)
    _declare(ledger, "other", host_id="kvm2", units=8)
    return ledger, hosts


def test_no_write_commits_between_a_decisions_host_read_and_its_end(tmp_path):
    """A host disabled while a decision runs commits only after it, so no
    decision acts on a host state that has changed under it."""
    ledger, hosts = _file_backed_ledger(tmp_path)

    ledger.probe(claim=VM_CLAIM)
    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})
    ledger.resize_reservation(
        old_capacity_reservation_id=reserved["capacity_reservation_id"],
        new_claim={"offering_mode": "vm", "gpu_count": 4},
    )
    second = ledger.reserve(claim=VM_CLAIM, deal_ref={})
    ledger.assign_settlement_resource(
        capacity_reservation_id=second["capacity_reservation_id"],
        settlement_resource_id="other",
    )
    ledger.list_offered_resources()

    assert hosts.writes_held_off == [True] * 6


def test_a_decision_holds_writes_off_after_lapsing_an_expired_hold(tmp_path):
    """Lapsing commits, so the decision's transaction begins after it."""
    ledger, hosts = _file_backed_ledger(tmp_path)
    lapsing = ledger.reserve(claim=VM_CLAIM, deal_ref={}, ttl_seconds=-1)
    hosts.writes_held_off.clear()

    reserved = ledger.reserve(claim=VM_CLAIM, deal_ref={})

    assert ledger.get_reservation(lapsing["capacity_reservation_id"])["state"] == (
        "released"
    )
    assert reserved is not None
    assert hosts.writes_held_off == [True]


def test_a_write_is_not_held_off_once_the_decision_ends(tmp_path):
    """A decision holds other writers off only while it runs: once it ends,
    another session's write proceeds."""
    ledger, hosts = _file_backed_ledger(tmp_path)
    ledger.probe(claim=VM_CLAIM)

    other = sqlite3.connect(hosts.path, timeout=0, isolation_level=None)
    try:
        other.execute("UPDATE resource_pools SET label = label")
    finally:
        other.close()
