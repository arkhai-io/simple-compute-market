"""A relay port lease is scoped to the relay, not to a host or a pool.

A `tcp` proxy's remote port binds a listening socket on the relay itself, so
every client dialing that relay draws from one port namespace. Keying the lease
on the host — or on the pool, which is the tempting simplification — lets two
holders be issued the same port. The relay binds the first and refuses the
second, and that refusal arrives asynchronously in a tunnel client's log rather
than as a failed allocation.

These tests pin the constraints at the database, where they are enforced, rather
than in an allocator that could be rewritten around them, over a schema built
from VM's own models.

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

from vm_provisioning_adapter.db import AnsiblePoolConfig, Relay, RelayPortLease


_PLAYBOOK_PATH = "/configured/playbook.yaml"


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


def _pool_config(pool_id: str, **overrides) -> AnsiblePoolConfig:
    fields = {
        "pool_id": pool_id,
        "playbook_path": _PLAYBOOK_PATH,
        "extra_vars": {},
    }
    fields.update(overrides)
    return AnsiblePoolConfig(**fields)


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
    def test_one_relay_cannot_issue_a_port_twice(self, vm_engine):
        with Session(vm_engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100))
            session.commit()
            session.add(_lease("10.0.0.9:7000", 6100))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_two_hosts_on_one_relay_cannot_share_a_port(self, vm_engine):
        """The defect a host-scoped key would have allowed.

        Both rows differ in host and owner; only the relay and port match. A
        `(host, port)` constraint would accept the second, and the relay would
        refuse it later and elsewhere.
        """
        with Session(vm_engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100, host_id="kvm1"))
            session.commit()
            session.add(_lease("10.0.0.9:7000", 6100, host_id="kvm2"))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_two_pools_on_one_relay_cannot_share_a_port(self, vm_engine):
        """The same defect one level up, which pool-scoping would have allowed.

        A site running a GPU pool and a bare-metal pool through one rendezvous
        is the ordinary case, not a corner.
        """
        with Session(vm_engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100, pool_id="gpu-pool"))
            session.commit()
            session.add(_lease("10.0.0.9:7000", 6100, pool_id="bare-metal-pool"))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_two_relays_may_each_issue_the_same_port(self, vm_engine):
        """Uniqueness must not be broader than the resource either."""
        with Session(vm_engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100))
            session.add(_lease("10.0.0.10:7000", 6100))
            session.commit()
            assert session.query(RelayPortLease).count() == 2

    def test_the_same_relay_on_a_different_port_is_allowed(self, vm_engine):
        with Session(vm_engine) as session:
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

    def test_two_retries_for_one_owner_hold_one_port(self, vm_engine):
        first, second = Session(vm_engine), Session(vm_engine)
        try:
            first.add(_lease("site-a", 6100, owner_kind="fulfillment", owner_id="cr-1"))
            second.add(_lease("site-a", 6101, owner_kind="fulfillment", owner_id="cr-1"))
            first.commit()
            with pytest.raises(IntegrityError):
                second.commit()
        finally:
            first.close()
            second.close()

        with Session(vm_engine) as session:
            held = session.query(RelayPortLease).filter_by(owner_id="cr-1").all()
        assert [lease.remote_port for lease in held] == [6100]

    def test_a_released_lease_does_not_hold_its_owner(self, vm_engine):
        """Release is soft, so the index counts only unreleased rows."""
        with Session(vm_engine) as session:
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

    def test_one_rendezvous_cannot_be_recorded_twice(self, vm_engine):
        """What stops one relay issuing a listening port to two callers."""
        with Session(vm_engine) as session:
            session.add(_relay("a", "10.0.0.9", 7000))
            session.commit()
            session.add(_relay("b", "10.0.0.9", 7000))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_addresses_are_normalized_before_they_are_compared(self):
        """Two spellings of one endpoint collide instead of creating two rows."""
        assert Relay.normalize_addr("  Relay.Local  ") == "relay.local"

    def test_two_pools_may_reference_one_relay(self, vm_engine):
        """The ordinary case: a GPU pool and a bare-metal pool, one rendezvous."""
        with Session(vm_engine) as session:
            session.add(_relay("shared", "10.0.0.9", 7000))
            session.add(_pool_config("gpu-pool", relay_id="shared"))
            session.add(_pool_config("bare-metal-pool", relay_id="shared"))
            session.commit()
            configs = session.query(AnsiblePoolConfig).filter(
                AnsiblePoolConfig.relay_id == "shared"
            ).all()
            assert {c.pool_id for c in configs} == {"gpu-pool", "bare-metal-pool"}

    def test_two_relays_are_distinct_identities(self, vm_engine):
        with Session(vm_engine) as session:
            session.add(_relay("a", "10.0.0.9", 7000))
            session.add(_relay("b", "10.0.0.10", 7000))
            session.commit()
            assert session.query(Relay).count() == 2

    def test_a_pool_with_no_relay_holds_no_identity(self, vm_engine):
        """A pool with no relay serves VMs by direct NAT; it holds no leases."""
        with Session(vm_engine) as session:
            session.add(_pool_config("nat-pool"))
            session.commit()
            assert session.get(AnsiblePoolConfig, "nat-pool").relay_id is None

    def test_a_relay_address_change_keeps_its_leases(self, vm_engine):
        """The property a foreign key buys that a derived string could not:
        leases follow the relay row, not an address."""
        with Session(vm_engine) as session:
            session.add(_relay("moving", "10.0.0.9", 7000))
            session.add(_lease("moving", 6100))
            session.commit()

            session.get(Relay, "moving").relay_addr = "10.0.0.20"
            session.commit()

            held = session.query(RelayPortLease).filter(
                RelayPortLease.relay_id == "moving"
            ).all()
            assert [lease.remote_port for lease in held] == [6100]
