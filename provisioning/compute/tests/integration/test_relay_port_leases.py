"""A relay port lease is scoped to the relay, not to a host or a pool.

A `tcp` proxy's remote port binds a listening socket on the relay itself, so
every client dialing that relay draws from one port namespace. Keying the lease
on the host — or on the pool, which is the tempting simplification — lets two
holders be issued the same port. The relay binds the first and refuses the
second, and that refusal arrives asynchronously in a tunnel client's log rather
than as a failed allocation.

These tests pin the constraints at the database, where they are enforced, rather
than in an allocator that could be rewritten around them, over a schema built
from the family's own models.

External boundary: SQLAlchemy against file-backed SQLite. The database is
deterministic and does no network I/O, so the real engine is used rather than a
mock.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from compute_provisioning.relays import Relay, RelayPortLease


def _relay(relay_id: str, addr: str, port: int, **overrides) -> Relay:
    fields = {
        "id": relay_id,
        "relay_addr": Relay.normalize_addr(addr),
        "relay_port": port,
        "vm_port_range_start": 6100,
        "vm_port_range_count": 100,
    }
    fields.update(overrides)
    return Relay(**fields)


def _lease(relay_id: str, port: int, **overrides) -> RelayPortLease:
    fields = {
        "id": str(uuid.uuid4()),
        "relay_id": relay_id,
        "remote_port": port,
        "host_id": "kvm1",
        "pool_id": "gpu-pool",
        "owner_kind": "job",
        "owner_id": str(uuid.uuid4()),
    }
    fields.update(overrides)
    return RelayPortLease(**fields)


class TestLeaseScoping:
    def test_one_relay_cannot_issue_a_port_twice(self, relay_engine):
        with Session(relay_engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100))
            session.commit()
            session.add(_lease("10.0.0.9:7000", 6100))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_two_hosts_on_one_relay_cannot_share_a_port(self, relay_engine):
        """The defect a host-scoped key would have allowed.

        Both rows differ in host and owner; only the relay and port match. A
        `(host, port)` constraint would accept the second, and the relay would
        refuse it later and elsewhere.
        """
        with Session(relay_engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100, host_id="kvm1"))
            session.commit()
            session.add(_lease("10.0.0.9:7000", 6100, host_id="kvm2"))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_two_pools_on_one_relay_cannot_share_a_port(self, relay_engine):
        """The same defect one level up, which pool-scoping would have allowed.

        A site running a GPU pool and a bare-metal pool through one rendezvous
        is the ordinary case, not a corner.
        """
        with Session(relay_engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100, pool_id="gpu-pool"))
            session.commit()
            session.add(_lease("10.0.0.9:7000", 6100, pool_id="bare-metal-pool"))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_two_relays_may_each_issue_the_same_port(self, relay_engine):
        """Uniqueness must not be broader than the resource either."""
        with Session(relay_engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100))
            session.add(_lease("10.0.0.10:7000", 6100))
            session.commit()
            assert session.query(RelayPortLease).count() == 2

    def test_the_same_relay_on_a_different_port_is_allowed(self, relay_engine):
        with Session(relay_engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100))
            session.add(_lease("10.0.0.9:7000", 6101))
            session.commit()
            assert session.query(RelayPortLease).count() == 2


class TestOneActiveLeasePerOwner:
    """Two retries of one fulfillment hold one relay port between them.

    Two retries that each found no active lease for their owner before either
    committed each write one, on different ports; the partial unique index on
    the owner refuses the second. The rows are written directly, so this pins
    the database's refusal, whatever the allocator does.
    """

    def test_two_retries_for_one_owner_hold_one_port(self, relay_engine):
        first, second = Session(relay_engine), Session(relay_engine)
        try:
            first.add(_lease("site-a", 6100, owner_kind="fulfillment", owner_id="cr-1"))
            second.add(_lease("site-a", 6101, owner_kind="fulfillment", owner_id="cr-1"))
            first.commit()
            with pytest.raises(IntegrityError):
                second.commit()
        finally:
            first.close()
            second.close()

        with Session(relay_engine) as session:
            held = session.query(RelayPortLease).filter_by(owner_id="cr-1").all()
        assert [lease.remote_port for lease in held] == [6100]

    def test_a_released_lease_does_not_hold_its_owner(self, relay_engine):
        """Release is soft, so the index counts only unreleased rows."""
        with Session(relay_engine) as session:
            session.add(
                _lease(
                    "site-a", 6100, owner_kind="fulfillment", owner_id="cr-1",
                    released_at=datetime.now(timezone.utc),
                )
            )
            session.add(_lease("site-a", 6101, owner_kind="fulfillment", owner_id="cr-1"))
            session.commit()
            assert session.query(RelayPortLease).filter_by(owner_id="cr-1").count() == 2


class TestRelayIdentity:
    """Identity is a row, so it survives the endpoint changing.

    The invariants below are enforced by a unique constraint on the relay table,
    and identity does not move when a relay does.
    """

    def test_one_rendezvous_cannot_be_recorded_twice(self, relay_engine):
        """What stops one relay issuing a listening port to two callers."""
        with Session(relay_engine) as session:
            session.add(_relay("a", "10.0.0.9", 7000))
            session.commit()
            session.add(_relay("b", "10.0.0.9", 7000))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_addresses_are_normalized_before_they_are_compared(self):
        """Two spellings of one endpoint collide instead of creating two rows."""
        assert Relay.normalize_addr("  Relay.Local  ") == "relay.local"

    def test_two_relays_are_distinct_identities(self, relay_engine):
        with Session(relay_engine) as session:
            session.add(_relay("a", "10.0.0.9", 7000))
            session.add(_relay("b", "10.0.0.10", 7000))
            session.commit()
            assert session.query(Relay).count() == 2

    def test_a_relay_address_change_keeps_its_leases(self, relay_engine):
        """The property a foreign key buys that a derived string could not:
        leases follow the relay row, not an address."""
        with Session(relay_engine) as session:
            session.add(_relay("moving", "10.0.0.9", 7000))
            session.add(_lease("moving", 6100))
            session.commit()

            session.get(Relay, "moving").relay_addr = "10.0.0.20"
            session.commit()

            held = session.query(RelayPortLease).filter(
                RelayPortLease.relay_id == "moving"
            ).all()
            assert [lease.remote_port for lease in held] == [6100]
