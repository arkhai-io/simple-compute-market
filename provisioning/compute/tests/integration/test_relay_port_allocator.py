"""Ports are leased from the relay's window and reclaimed on every ending.

Uniqueness belongs to the relay because a remote port binds a listening socket
there. Two hosts dialing one relay are not independent namespaces: if one holds
a port the other cannot, and the relay's refusal of a second registration
arrives asynchronously in a tunnel client's log rather than as a failed
allocation.

Release is the allocator's primitive here; when it runs is the site ledger's
release decision, asserted where that decision is made.

External boundary: SQLAlchemy against file-backed SQLite. The uniqueness
constraint is the thing under test, so the real engine enforces it rather than
a fake agreeing with the code.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest
from market_fulfillment.settlement_repository import begin_sqlite_write_transaction
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from compute_provisioning.hosts import ConnectionCodecs
from compute_provisioning.relays import (
    Relay,
    RelayDisabledError,
    RelayPortAllocator,
    RelayPortLease,
    RelayService,
    RelayWindowExhaustedError,
)

# A lease end long past, so a lease's grants have expired and its port, once
# released, is out of quarantine at once; the quarantine's own tests use ends
# relative to now.
_ENDED = datetime(2020, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def allocator(session_factory):
    return RelayPortAllocator(session_factory)


def _stored(session_factory, owner_id: str) -> RelayPortLease:
    with Session(session_factory.kw["bind"]) as db:
        row = db.query(RelayPortLease).filter(RelayPortLease.owner_id == owner_id).one()
        db.expunge(row)
        return row


class TestGrantExpiryAndQuarantine:
    """A lease records when its grants expire, and a released port is held
    until that expiry plus the reuse margin, so a grant copied from the host
    that held it cannot register it for another host."""

    @pytest.mark.parametrize(
        ("grace", "margin", "setting"),
        [
            (timedelta(seconds=-1), timedelta(seconds=300), "relay_grant_expiry_grace_seconds"),
            (timedelta(hours=1), timedelta(0), "relay_port_reuse_margin_seconds"),
            (timedelta(hours=1), timedelta(seconds=-60), "relay_port_reuse_margin_seconds"),
        ],
    )
    def test_a_grace_or_margin_that_defeats_its_protection_is_refused(
        self, session_factory, grace, margin, setting
    ):
        """A negative grace expires a grant before its lease ends, and a margin
        that is not positive reissues a port while its old grant may still be
        admitted on a lagging relay clock."""
        with pytest.raises(ValueError, match=setting):
            RelayPortAllocator(session_factory, grant_expiry_grace=grace, reuse_margin=margin)

    def test_the_grant_expiry_is_the_lease_end_plus_the_grace_rounded_up(
        self, session_factory
    ):
        _relay(session_factory)
        allocator = RelayPortAllocator(session_factory, grant_expiry_grace=timedelta(seconds=90))
        end = datetime(2031, 3, 4, 5, 6, 7, 250_000, tzinfo=timezone.utc)

        allocator.allocate(
            relay_id="site-a", lease_ends_at=end, owner_kind="fulfillment", owner_id="cr-1"
        )

        assert _stored(session_factory, "cr-1").grant_expires_at == datetime(
            2031, 3, 4, 5, 7, 38
        )

    def test_a_lease_end_in_another_zone_is_stored_as_utc(self, session_factory):
        _relay(session_factory)
        allocator = RelayPortAllocator(session_factory, grant_expiry_grace=timedelta(0))
        end = datetime(2031, 3, 4, 7, 0, 0, tzinfo=timezone(timedelta(hours=2)))

        allocator.allocate(
            relay_id="site-a", lease_ends_at=end, owner_kind="fulfillment", owner_id="cr-1"
        )

        assert _stored(session_factory, "cr-1").grant_expires_at == datetime(2031, 3, 4, 5)

    def test_a_lease_cut_short_holds_its_port_and_another_is_issued(
        self, allocator, session_factory
    ):
        _relay(session_factory, start=6100, count=3)
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        first = allocator.allocate(
            relay_id="site-a", lease_ends_at=future, owner_kind="fulfillment", owner_id="cr-1"
        )
        allocator.release(owner_kind="fulfillment", owner_id="cr-1")

        second = allocator.allocate(
            relay_id="site-a", lease_ends_at=future, owner_kind="fulfillment", owner_id="cr-2"
        )

        assert second.remote_port != first.remote_port
        assert allocator.held_ports("site-a") == [second.remote_port]

    def test_the_margin_holds_a_port_past_its_grants_expiry(self, session_factory):
        _relay(session_factory, start=6100, count=3)
        allocator = RelayPortAllocator(
            session_factory,
            grant_expiry_grace=timedelta(0),
            reuse_margin=timedelta(seconds=300),
        )
        expired_a_minute_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
        first = allocator.allocate(
            relay_id="site-a",
            lease_ends_at=expired_a_minute_ago,
            owner_kind="fulfillment",
            owner_id="cr-1",
        )
        allocator.release(owner_kind="fulfillment", owner_id="cr-1")

        second = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-2"
        )

        assert second.remote_port != first.remote_port

    def test_a_raised_margin_reaches_a_lease_already_released(self, session_factory):
        """The margin is read when a port is selected, so raising it holds back
        a port released under the old one."""
        _relay(session_factory, start=6100, count=3)
        expired_ten_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
        before = RelayPortAllocator(
            session_factory, grant_expiry_grace=timedelta(0), reuse_margin=timedelta(minutes=5)
        )
        first = before.allocate(
            relay_id="site-a",
            lease_ends_at=expired_ten_minutes_ago,
            owner_kind="fulfillment",
            owner_id="cr-1",
        )
        before.release(owner_kind="fulfillment", owner_id="cr-1")

        raised = RelayPortAllocator(
            session_factory, grant_expiry_grace=timedelta(0), reuse_margin=timedelta(minutes=30)
        )
        second = raised.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-2"
        )
        assert second.remote_port != first.remote_port

        raised.release(owner_kind="fulfillment", owner_id="cr-2")
        third = before.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-3"
        )
        assert third.remote_port == first.remote_port

    def test_a_retenancy_replaces_the_last_tenancys_grant_fields(
        self, allocator, session_factory
    ):
        _relay(session_factory, start=6100, count=1)
        allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
        )
        with session_factory() as db, db.begin():
            db.query(RelayPortLease).one().grant_key_id = "the-last-tenancys-key"
        allocator.release(owner_kind="fulfillment", owner_id="cr-1")
        later = datetime(2031, 1, 1, tzinfo=timezone.utc)

        allocator.allocate(
            relay_id="site-a", lease_ends_at=later, owner_kind="fulfillment", owner_id="cr-2"
        )

        row = _stored(session_factory, "cr-2")
        assert row.grant_key_id is None
        assert row.grant_expires_at == datetime(2031, 1, 1) + timedelta(hours=1)


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
    def test_allocation_joins_the_callers_transaction(self, allocator, session_factory):
        _relay(session_factory)
        with session_factory() as writer:
            relay = writer.get(Relay, "site-a")
            relay.label = "accepted"
            writer.flush()
            lease = allocator.allocate_in_session(
                writer, relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
            )
            assert allocator.held_ports("site-a") == []
            writer.rollback()
        assert allocator.held_ports("site-a") == []

        with session_factory() as writer:
            relay = writer.get(Relay, "site-a")
            assert relay.label is None
            relay.label = "accepted"
            writer.flush()
            lease = allocator.allocate_in_session(
                writer, relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
            )
            writer.commit()
        assert allocator.held_ports("site-a") == [lease.remote_port]
        with session_factory() as reader:
            assert reader.get(Relay, "site-a").label == "accepted"

    def test_a_stale_port_read_retries_without_rolling_back_the_caller(
        self, allocator, session_factory
    ):
        _relay(session_factory)
        held = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
        )

        class StalePortAllocator(RelayPortAllocator):
            """One stale scan result, followed by fresh reads of durable state."""

            stale = True

            def _lowest_free(self, db, relay_id, window):
                if self.stale:
                    self.stale = False
                    return held.remote_port
                return super()._lowest_free(db, relay_id, window)

        with session_factory() as writer:
            relay = writer.get(Relay, "site-a")
            relay.label = "accepted"
            writer.flush()
            lease = StalePortAllocator(session_factory).allocate_in_session(
                writer, relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-2"
            )
            writer.commit()

        assert lease.remote_port != held.remote_port
        original = allocator.find_active_lease(owner_kind="fulfillment", owner_id="cr-1")
        assert original == held
        with session_factory() as reader:
            assert reader.get(Relay, "site-a").label == "accepted"

    def test_a_port_comes_from_the_relays_window(self, allocator, session_factory):
        _relay(session_factory, start=6100, count=10)
        lease = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
        )
        assert 6100 <= lease.remote_port <= 6109

    def test_a_second_allocation_does_not_reuse_a_held_port(
        self, allocator, session_factory
    ):
        _relay(session_factory)
        first = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
        )
        second = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-2"
        )
        assert first.remote_port != second.remote_port

    def test_two_hosts_on_one_relay_never_receive_the_same_port(
        self, allocator, session_factory
    ):
        """The property the whole lease model exists for."""
        _relay(session_factory)
        first = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1",
            host_id="kvm1",
        )
        second = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-2",
            host_id="kvm2",
        )
        assert first.remote_port != second.remote_port

    def test_two_relays_may_each_issue_the_same_port(self, allocator, session_factory):
        _relay(session_factory, relay_id="site-a", addr="10.0.0.9")
        _relay(session_factory, relay_id="site-b", addr="10.0.0.10")
        first = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
        )
        second = allocator.allocate(
            relay_id="site-b", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-2"
        )
        assert first.remote_port == second.remote_port

    def test_an_exhausted_window_names_the_relay_and_the_window(
        self, allocator, session_factory
    ):
        _relay(session_factory, start=6100, count=2)
        allocator.allocate(relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1")
        allocator.allocate(relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-2")
        with pytest.raises(RelayWindowExhaustedError) as excinfo:
            allocator.allocate(
                relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-3"
            )
        message = str(excinfo.value)
        assert "site-a" in message
        assert "6100" in message and "6101" in message

    def test_allocating_against_an_absent_relay_fails(self, allocator):
        with pytest.raises(RelayWindowExhaustedError):
            allocator.allocate(
                relay_id="never-created", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
            )

    def test_a_released_port_is_reused(self, allocator, session_factory):
        """A strategy that always moved forward would turn a finite window into
        an outage sooner than a leak warrants."""
        _relay(session_factory, start=6100, count=3)
        first = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
        )
        allocator.release(owner_kind="fulfillment", owner_id="cr-1")
        reused = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-2"
        )
        assert reused.remote_port == first.remote_port

    def test_the_database_refuses_a_duplicate_even_if_the_allocator_is_wrong(
        self, allocator, session_factory
    ):
        """Uniqueness is pinned where it is enforced, not in the allocator that
        could be rewritten around it."""
        _relay(session_factory)
        lease = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
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


def _relay_service(session_factory) -> RelayService:
    """The relay administration a disable goes through. Changing a relay's
    availability reads no host's connection, so no codec is composed."""
    return RelayService(session_factory, connection_codecs=ConnectionCodecs([]))


def _owners(session_factory) -> list[str]:
    with session_factory() as db:
        return sorted(row.owner_id for row in db.query(RelayPortLease).all())


class TestADisabledRelayLeasesNoNewPort:
    """Disabling a relay drains it, and the allocator, the one place a lease is
    created, is where that holds: a new owner is refused whoever asks, and an
    owner already holding a lease receives it again, since its delivery is
    among the work the drain lets finish."""

    def test_a_new_owner_is_refused_standalone_and_no_lease_is_recorded(
        self, allocator, session_factory
    ):
        _relay(session_factory)
        _relay_service(session_factory).set_enabled("site-a", False)

        with pytest.raises(RelayDisabledError, match="site-a"):
            allocator.allocate(
                relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
            )

        assert _owners(session_factory) == []

    def test_a_new_owner_is_refused_in_the_callers_transaction(
        self, allocator, session_factory
    ):
        _relay(session_factory)
        _relay_service(session_factory).set_enabled("site-a", False)

        with session_factory() as db:
            begin_sqlite_write_transaction(db)
            with pytest.raises(RelayDisabledError, match="site-a"):
                allocator.allocate_in_session(
                    db, relay_id="site-a", lease_ends_at=_ENDED,
                    owner_kind="fulfillment", owner_id="cr-1",
                )
            db.commit()

        assert _owners(session_factory) == []

    def test_an_owner_holding_a_lease_receives_it_again(self, allocator, session_factory):
        _relay(session_factory)
        held = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
        )
        _relay_service(session_factory).set_enabled("site-a", False)

        again = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
        )
        with session_factory() as db:
            begin_sqlite_write_transaction(db)
            in_session = allocator.allocate_in_session(
                db, relay_id="site-a", lease_ends_at=_ENDED,
                owner_kind="fulfillment", owner_id="cr-1",
            )
            db.commit()

        assert again == held
        assert in_session == held
        assert allocator.held_ports("site-a") == [held.remote_port]

    def test_enabling_the_relay_again_lets_the_new_owner_allocate(
        self, allocator, session_factory
    ):
        _relay(session_factory)
        relays = _relay_service(session_factory)
        relays.set_enabled("site-a", False)
        with pytest.raises(RelayDisabledError):
            allocator.allocate(
                relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
            )

        relays.set_enabled("site-a", True)
        lease = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
        )

        assert allocator.held_ports("site-a") == [lease.remote_port]


class TestADisableRacingAnAcceptance:
    """A disable committed while an acceptance is in flight either waits for
    it, its lease then among the relay's, or is seen by it, and the acceptance
    is refused: a disabled relay holding no lease never then gains one.

    Independent sessions on a file-backed database, each step started only
    once the other has reached the point it waits on, with every wait bounded.
    SQLite has one writer, so here an acceptance holding the writer slot makes
    a disable wait whatever the allocator reads; on PostgreSQL that wait is the
    relay row's lock, which no lane here runs, so the last test holds that the
    allocator takes it.
    """

    def test_a_disable_waits_for_an_acceptance_that_has_allocated(
        self, allocator, session_factory, relay_engine
    ):
        _relay(session_factory)
        allocated, disabling, commit = threading.Event(), threading.Event(), threading.Event()
        outcomes: dict[str, object] = {}

        @event.listens_for(relay_engine, "before_cursor_execute")
        def report_the_disables_write(conn, cursor, statement, parameters, context, many):
            if threading.current_thread().name == "disabler" and statement.lstrip().upper().startswith(
                "UPDATE RELAYS"
            ):
                disabling.set()

        def accept() -> None:
            try:
                with session_factory() as db:
                    begin_sqlite_write_transaction(db)
                    lease = allocator.allocate_in_session(
                        db, relay_id="site-a", lease_ends_at=_ENDED,
                        owner_kind="fulfillment", owner_id="cr-1",
                    )
                    allocated.set()
                    if not commit.wait(timeout=10):
                        raise TimeoutError("the test never let the acceptance commit")
                    db.commit()
                    outcomes["accept"] = lease
            except Exception as exc:
                outcomes["accept"] = exc
            finally:
                allocated.set()

        def disable() -> None:
            try:
                outcomes["disable"] = _relay_service(session_factory).set_enabled(
                    "site-a", False
                )
            except Exception as exc:
                outcomes["disable"] = exc
            finally:
                disabling.set()

        acceptor = threading.Thread(target=accept, name="acceptor")
        disabler = threading.Thread(target=disable, name="disabler")
        acceptor.start()
        try:
            assert allocated.wait(timeout=10), "the acceptance never allocated"
            disabler.start()
            # The disable is about to issue its write while the acceptance,
            # allocated and uncommitted, holds the database's writer slot, so
            # it cannot have finished: it completes only after that commit.
            assert disabling.wait(timeout=10), "the disable never reached its write"
            assert "disable" not in outcomes, outcomes.get("disable")
        finally:
            commit.set()
            acceptor.join(timeout=10)
            if disabler.ident is not None:
                disabler.join(timeout=10)
        assert not acceptor.is_alive()
        assert not disabler.is_alive()

        lease = outcomes["accept"]
        assert not isinstance(lease, Exception), lease
        assert not isinstance(outcomes["disable"], Exception), outcomes["disable"]
        with session_factory() as db:
            assert db.get(Relay, "site-a").enabled is False
        assert allocator.held_ports("site-a") == [lease.remote_port]

    def test_an_acceptance_that_read_the_relay_enabled_is_refused_after_a_disable(
        self, allocator, session_factory
    ):
        """Preparation reads the relay in the acceptance's session, unlocked,
        before allocation; a disable committing in between is seen by the
        allocator's own read, not answered from that earlier one."""
        _relay(session_factory)
        with session_factory() as acceptance:
            assert acceptance.get(Relay, "site-a").enabled is True
            _relay_service(session_factory).set_enabled("site-a", False)

            begin_sqlite_write_transaction(acceptance)
            with pytest.raises(RelayDisabledError):
                allocator.allocate_in_session(
                    acceptance, relay_id="site-a", lease_ends_at=_ENDED,
                    owner_kind="fulfillment", owner_id="cr-1",
                )
            acceptance.rollback()

        assert _owners(session_factory) == []
        with session_factory() as db:
            assert db.get(Relay, "site-a").enabled is False

    def test_the_relay_is_read_for_update_before_a_port_is_claimed(
        self, allocator, session_factory, relay_engine
    ):
        """What makes the first order hold on PostgreSQL: the relay row is read
        with ``FOR UPDATE`` before the claim writes, so a disable's update of
        that row waits for the acceptance's commit. Each ORM read is rendered
        for PostgreSQL, since SQLite does not render the lock."""
        _relay(session_factory)
        trace: list[str] = []

        @event.listens_for(relay_engine, "before_cursor_execute")
        def claims(conn, cursor, statement, parameters, context, many):
            if statement.lstrip().upper().startswith(
                ("INSERT INTO RELAY_PORT_LEASES", "UPDATE RELAY_PORT_LEASES")
            ):
                trace.append("claim")

        with session_factory() as db:

            @event.listens_for(db, "do_orm_execute")
            def reads(state):
                if not state.is_select:
                    return
                rendered = str(state.statement.compile(dialect=postgresql.dialect()))
                if "FROM relays" in rendered:
                    trace.append("relay locked" if "FOR UPDATE" in rendered else "relay")

            begin_sqlite_write_transaction(db)
            allocator.allocate_in_session(
                db, relay_id="site-a", lease_ends_at=_ENDED,
                owner_kind="fulfillment", owner_id="cr-1",
            )
            db.commit()

        assert "claim" in trace
        assert "relay locked" in trace[: trace.index("claim")], trace
        assert "relay" not in trace, trace


class TestTheReleasePrimitive:
    """What `release` does when something calls it — nothing more.

    Whether a release path calls it is asserted where that path is composed,
    against the orchestration; a test here named for a lifecycle path would
    claim wiring it does not exercise.
    """

    def test_releasing_a_held_lease_frees_its_port(self, allocator, session_factory):
        _relay(session_factory)
        allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
        )
        assert allocator.release(owner_kind="fulfillment", owner_id="cr-1") == 1
        assert allocator.held_ports("site-a") == []

    def test_releasing_in_a_caller_session_does_not_commit(
        self, allocator, session_factory
    ):
        """The release effect needs release to join the ledger's transaction, so
        that the port and the reservation's capacity are returned together."""
        _relay(session_factory)
        allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
        )
        with session_factory() as db:
            assert RelayPortAllocator.release_in_session(
                db, owner_kind="fulfillment", owner_id="cr-1"
            ) == 1
            db.rollback()
        assert allocator.held_ports("site-a") != []

    def test_releasing_twice_is_harmless(self, allocator, session_factory):
        """Terminal paths overlap; the ones that do must not fail each other."""
        _relay(session_factory)
        allocator.allocate(relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1")
        assert allocator.release(owner_kind="fulfillment", owner_id="cr-1") == 1
        assert allocator.release(owner_kind="fulfillment", owner_id="cr-1") == 0

    def test_releasing_one_owner_leaves_another_alone(self, allocator, session_factory):
        _relay(session_factory)
        allocator.allocate(relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1")
        kept = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-2"
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

    def test_a_lease_whose_owner_is_released_beyond_the_grace_is_released(
        self, allocator, session_factory
    ):
        _relay(session_factory)
        allocator.allocate(relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1")
        self._age(session_factory, "cr-1", timedelta(hours=3))

        released = allocator.reconcile(
            is_owner_released=lambda kind, owner: True, grace=timedelta(hours=1)
        )

        assert released == 1
        assert allocator.held_ports("site-a") == []

    def test_a_lease_whose_owner_is_still_live_is_left_alone(
        self, allocator, session_factory
    ):
        _relay(session_factory)
        lease = allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1"
        )
        self._age(session_factory, "cr-1", timedelta(hours=3))

        released = allocator.reconcile(
            is_owner_released=lambda kind, owner: False, grace=timedelta(hours=1)
        )

        assert released == 0
        assert allocator.held_ports("site-a") == [lease.remote_port]

    def test_a_recent_lease_is_left_alone_even_when_released(
        self, allocator, session_factory
    ):
        """The grace period is what keeps reconciliation from racing the
        ordinary release paths it exists to back up."""
        _relay(session_factory)
        allocator.allocate(relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-1")

        released = allocator.reconcile(
            is_owner_released=lambda kind, owner: True, grace=timedelta(hours=1)
        )

        assert released == 0

    def test_an_abandoned_owner_is_recovered_by_the_sweep(
        self, allocator, session_factory
    ):
        """A release the effect did not see, recovered by the sweep.

        Allocation runs in its own transaction, so a lease taken during an
        acceptance that then rolls back can outlive anything that would release
        it with the reservation; the backstop recovers it once the reservation
        is released.
        """
        _relay(session_factory)
        allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-abandoned"
        )
        self._age(session_factory, "cr-abandoned", timedelta(hours=3))

        def released(kind: str, owner: str) -> bool:
            # What the deployed predicate reports for an abandoned record.
            return kind == "fulfillment" and owner == "cr-abandoned"

        assert allocator.reconcile(
            is_owner_released=released, grace=timedelta(hours=1)
        ) == 1
        assert allocator.held_ports("site-a") == []

    def test_a_lease_whose_owner_vanished_is_recovered(
        self, allocator, session_factory
    ):
        """A record that no longer exists is orphaned by definition; the
        deployed predicate reports it released for that reason."""
        _relay(session_factory)
        allocator.allocate(
            relay_id="site-a", lease_ends_at=_ENDED, owner_kind="fulfillment", owner_id="cr-gone"
        )
        self._age(session_factory, "cr-gone", timedelta(hours=3))

        assert allocator.reconcile(
            is_owner_released=lambda kind, owner: True, grace=timedelta(hours=1)
        ) == 1
