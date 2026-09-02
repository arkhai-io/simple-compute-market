"""Ports are leased from the relay's window and reclaimed on every ending.

Uniqueness belongs to the relay because a remote port binds a listening socket
there. Two hosts dialing one relay are not independent namespaces: if one holds
a port the other cannot, and the relay's refusal of a second registration
arrives asynchronously in a tunnel client's log rather than as a failed
allocation.

Release is asserted per terminal path rather than through one representative,
because the point of attaching it to every ending is that no ending is missed —
a test that exercises only teardown proves the opposite of what is wanted.

External boundary: SQLAlchemy against in-memory SQLite. The uniqueness
constraint is the thing under test, so the real engine enforces it rather than
a fake agreeing with the code.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.models import Relay, RelayPortLease
from compute_provisioning_service.services.relay_port_allocator import (
    RelayPortAllocator,
    RelayWindowExhaustedError,
)

_PLAYBOOK_PATH = "/configured/playbook.yaml"
_INVENTORY_GROUP = "kvm_hosts"


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(
        engine,
        default_playbook_path=_PLAYBOOK_PATH,
        default_inventory_group=_INVENTORY_GROUP,
    )
    return sessionmaker(bind=engine)


@pytest.fixture
def allocator(session_factory):
    return RelayPortAllocator(session_factory)


def _relay(session_factory, relay_id="site-a", addr="10.0.0.9", start=6100, count=100):
    with session_factory() as db, db.begin():
        db.add(
            Relay(
                id=relay_id,
                relay_addr=addr,
                relay_port=7000,
                vm_port_range_start=start,
                vm_port_range_count=count,
            )
        )
    return relay_id


class TestAllocation:
    def test_a_port_comes_from_the_relays_window(self, allocator, session_factory):
        _relay(session_factory, start=6100, count=10)
        lease = allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id="cr-1"
        )
        assert 6100 <= lease.remote_port <= 6109

    def test_a_second_allocation_does_not_reuse_a_held_port(
        self, allocator, session_factory
    ):
        _relay(session_factory)
        first = allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id="cr-1"
        )
        second = allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id="cr-2"
        )
        assert first.remote_port != second.remote_port

    def test_two_hosts_on_one_relay_never_receive_the_same_port(
        self, allocator, session_factory
    ):
        """The property the whole lease model exists for."""
        _relay(session_factory)
        first = allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id="cr-1",
            host_name="kvm1",
        )
        second = allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id="cr-2",
            host_name="kvm2",
        )
        assert first.remote_port != second.remote_port

    def test_two_relays_may_each_issue_the_same_port(self, allocator, session_factory):
        _relay(session_factory, relay_id="site-a", addr="10.0.0.9")
        _relay(session_factory, relay_id="site-b", addr="10.0.0.10")
        first = allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id="cr-1"
        )
        second = allocator.allocate(
            relay_id="site-b", owner_kind="fulfillment", owner_id="cr-2"
        )
        assert first.remote_port == second.remote_port

    def test_an_exhausted_window_names_the_relay_and_the_window(
        self, allocator, session_factory
    ):
        _relay(session_factory, start=6100, count=2)
        allocator.allocate(relay_id="site-a", owner_kind="fulfillment", owner_id="cr-1")
        allocator.allocate(relay_id="site-a", owner_kind="fulfillment", owner_id="cr-2")
        with pytest.raises(RelayWindowExhaustedError) as excinfo:
            allocator.allocate(
                relay_id="site-a", owner_kind="fulfillment", owner_id="cr-3"
            )
        message = str(excinfo.value)
        assert "site-a" in message
        assert "6100" in message and "6101" in message

    def test_allocating_against_an_absent_relay_fails(self, allocator):
        with pytest.raises(RelayWindowExhaustedError):
            allocator.allocate(
                relay_id="never-created", owner_kind="fulfillment", owner_id="cr-1"
            )

    def test_a_released_port_is_reused(self, allocator, session_factory):
        """A strategy that always moved forward would turn a finite window into
        an outage sooner than a leak warrants."""
        _relay(session_factory, start=6100, count=3)
        first = allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id="cr-1"
        )
        allocator.release(owner_kind="fulfillment", owner_id="cr-1")
        reused = allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id="cr-2"
        )
        assert reused.remote_port == first.remote_port

    def test_the_database_refuses_a_duplicate_even_if_the_allocator_is_wrong(
        self, allocator, session_factory
    ):
        """Uniqueness is pinned where it is enforced, not in the allocator that
        could be rewritten around it."""
        from sqlalchemy.exc import IntegrityError

        _relay(session_factory)
        lease = allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id="cr-1"
        )
        with Session(session_factory.kw["bind"]) as db:
            db.add(
                RelayPortLease(
                    id="hand-written",
                    relay_id="site-a",
                    remote_port=lease.remote_port,
                    owner_kind="fulfillment",
                    owner_id="cr-9",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()


class TestRelease:
    @pytest.mark.parametrize(
        "ending",
        ["teardown", "dispatch-never-started", "creation-failed", "cancelled", "expired"],
    )
    def test_every_terminal_ending_releases_the_lease(
        self, allocator, session_factory, ending
    ):
        """Asserted per path rather than through one representative: the point
        of attaching release to every ending is that none is missed."""
        _relay(session_factory)
        allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id=ending
        )
        assert allocator.release(owner_kind="fulfillment", owner_id=ending) == 1
        assert allocator.held_ports("site-a") == []

    def test_releasing_twice_is_harmless(self, allocator, session_factory):
        """Terminal paths overlap; the ones that do must not fail each other."""
        _relay(session_factory)
        allocator.allocate(relay_id="site-a", owner_kind="fulfillment", owner_id="cr-1")
        assert allocator.release(owner_kind="fulfillment", owner_id="cr-1") == 1
        assert allocator.release(owner_kind="fulfillment", owner_id="cr-1") == 0

    def test_releasing_one_owner_leaves_another_alone(self, allocator, session_factory):
        _relay(session_factory)
        allocator.allocate(relay_id="site-a", owner_kind="fulfillment", owner_id="cr-1")
        kept = allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id="cr-2"
        )
        allocator.release(owner_kind="fulfillment", owner_id="cr-1")
        assert allocator.held_ports("site-a") == [kept.remote_port]


class TestReconciliation:
    def _age(self, session_factory, owner_id, delta):
        with session_factory() as db, db.begin():
            lease = (
                db.query(RelayPortLease)
                .filter(RelayPortLease.owner_id == owner_id)
                .one()
            )
            lease.created_at = (datetime.now(timezone.utc) - delta).replace(tzinfo=None)

    def test_a_lease_whose_owner_is_terminal_beyond_the_grace_is_released(
        self, allocator, session_factory
    ):
        _relay(session_factory)
        allocator.allocate(relay_id="site-a", owner_kind="fulfillment", owner_id="cr-1")
        self._age(session_factory, "cr-1", timedelta(hours=3))

        released = allocator.reconcile(
            is_owner_terminal=lambda kind, owner: True, grace=timedelta(hours=1)
        )

        assert released == 1
        assert allocator.held_ports("site-a") == []

    def test_a_lease_whose_owner_is_still_live_is_left_alone(
        self, allocator, session_factory
    ):
        _relay(session_factory)
        lease = allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id="cr-1"
        )
        self._age(session_factory, "cr-1", timedelta(hours=3))

        released = allocator.reconcile(
            is_owner_terminal=lambda kind, owner: False, grace=timedelta(hours=1)
        )

        assert released == 0
        assert allocator.held_ports("site-a") == [lease.remote_port]

    def test_a_recent_lease_is_left_alone_even_when_terminal(
        self, allocator, session_factory
    ):
        """The grace period is what keeps reconciliation from racing the
        ordinary release paths it exists to back up."""
        _relay(session_factory)
        allocator.allocate(relay_id="site-a", owner_kind="fulfillment", owner_id="cr-1")

        released = allocator.reconcile(
            is_owner_terminal=lambda kind, owner: True, grace=timedelta(hours=1)
        )

        assert released == 0
