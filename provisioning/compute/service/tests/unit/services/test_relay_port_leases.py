"""A relay port lease is scoped to the relay, not to a host or a pool.

A `tcp` proxy's remote port binds a listening socket on the relay itself, so
every client dialing that relay draws from one port namespace. Keying the lease
on the host — or on the pool, which is the tempting simplification — lets two
holders be issued the same port. The relay binds the first and refuses the
second, and that refusal arrives asynchronously in a tunnel client's log rather
than as a failed allocation, which is the coordination failure this change set
out to remove.

These tests pin the constraint at the database, where it is enforced, rather
than in an allocator that could be rewritten around it.

External boundary: SQLAlchemy against in-memory SQLite, as elsewhere in this
suite. The database is deterministic and does no network I/O, so the real engine
is used rather than a mock.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.models import AnsiblePoolConfig, Relay, RelayPortLease


_PLAYBOOK_PATH = "/configured/playbook.yaml"
_INVENTORY_GROUP = "kvm_hosts"


def _engine():
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
    return engine


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
        "inventory_group": _INVENTORY_GROUP,
        "extra_vars": {},
    }
    fields.update(overrides)
    return AnsiblePoolConfig(**fields)


def _lease(relay_id: str, port: int, **overrides) -> RelayPortLease:
    fields = {
        "id": str(uuid.uuid4()),
        "relay_id": relay_id,
        "remote_port": port,
        "host_name": "kvm1",
        "pool_id": "gpu-pool",
        "owner_kind": "job",
        "owner_id": str(uuid.uuid4()),
    }
    fields.update(overrides)
    return RelayPortLease(**fields)


class TestLeaseScoping:
    def test_one_relay_cannot_issue_a_port_twice(self):
        engine = _engine()
        with Session(engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100))
            session.commit()
            session.add(_lease("10.0.0.9:7000", 6100))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_two_hosts_on_one_relay_cannot_share_a_port(self):
        """The defect a host-scoped key would have allowed.

        Both rows differ in host and owner; only the relay and port match. A
        `(host, port)` constraint would accept the second, and the relay would
        refuse it later and elsewhere.
        """
        engine = _engine()
        with Session(engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100, host_name="kvm1"))
            session.commit()
            session.add(_lease("10.0.0.9:7000", 6100, host_name="kvm2"))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_two_pools_on_one_relay_cannot_share_a_port(self):
        """The same defect one level up, which pool-scoping would have allowed.

        A site running a GPU pool and a bare-metal pool through one rendezvous
        is the ordinary case, not a corner.
        """
        engine = _engine()
        with Session(engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100, pool_id="gpu-pool"))
            session.commit()
            session.add(_lease("10.0.0.9:7000", 6100, pool_id="bare-metal-pool"))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_two_relays_may_each_issue_the_same_port(self):
        """Uniqueness must not be broader than the resource either."""
        engine = _engine()
        with Session(engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100))
            session.add(_lease("10.0.0.10:7000", 6100))
            session.commit()
            assert session.query(RelayPortLease).count() == 2

    def test_the_same_relay_on_a_different_port_is_allowed(self):
        engine = _engine()
        with Session(engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100))
            session.add(_lease("10.0.0.9:7000", 6101))
            session.commit()
            assert session.query(RelayPortLease).count() == 2


class TestRelayIdentity:
    """Identity is a row, so it survives the endpoint changing.

    An earlier shape derived identity from ``relay_addr:relay_port`` held on
    the pool. The invariants below are the same ones that shape had to satisfy;
    what changed is that they are now enforced by a unique constraint on the
    relay table rather than by a normalizing property, and that identity no
    longer moves when a relay does.
    """

    def test_one_rendezvous_cannot_be_recorded_twice(self):
        """What stops one relay issuing a listening port to two callers."""
        engine = _engine()
        with Session(engine) as session:
            session.add(_relay("a", "10.0.0.9", 7000))
            session.commit()
            session.add(_relay("b", "10.0.0.9", 7000))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_addresses_are_normalized_before_they_are_compared(self):
        """Two spellings of one endpoint collide instead of creating two rows."""
        assert Relay.normalize_addr("  Relay.Local  ") == "relay.local"

    def test_two_pools_may_reference_one_relay(self):
        """The ordinary case: a GPU pool and a bare-metal pool, one rendezvous."""
        engine = _engine()
        with Session(engine) as session:
            session.add(_relay("shared", "10.0.0.9", 7000))
            session.add(_pool_config("gpu-pool", relay_id="shared"))
            session.add(_pool_config("bare-metal-pool", relay_id="shared"))
            session.commit()
            configs = session.query(AnsiblePoolConfig).filter(
                AnsiblePoolConfig.relay_id == "shared"
            ).all()
            assert {c.pool_id for c in configs} == {"gpu-pool", "bare-metal-pool"}

    def test_two_relays_are_distinct_identities(self):
        engine = _engine()
        with Session(engine) as session:
            session.add(_relay("a", "10.0.0.9", 7000))
            session.add(_relay("b", "10.0.0.10", 7000))
            session.commit()
            assert session.query(Relay).count() == 2

    def test_a_pool_with_no_relay_holds_no_identity(self):
        """A pool with no relay serves VMs by direct NAT; it holds no leases."""
        engine = _engine()
        with Session(engine) as session:
            session.add(_pool_config("nat-pool"))
            session.commit()
            assert session.get(AnsiblePoolConfig, "nat-pool").relay_id is None

    def test_a_relay_address_change_keeps_its_leases(self):
        """The property a foreign key buys that a derived string could not.

        Under a derived identity the old address's leases became records under
        an identity nothing pointed at any more, while the new identity was
        free to reissue ports still bound on the relay.
        """
        engine = _engine()
        with Session(engine) as session:
            session.add(_relay("moving", "10.0.0.9", 7000))
            session.add(_lease("moving", 6100))
            session.commit()

            session.get(Relay, "moving").relay_addr = "10.0.0.20"
            session.commit()

            held = session.query(RelayPortLease).filter(
                RelayPortLease.relay_id == "moving"
            ).all()
            assert [lease.remote_port for lease in held] == [6100]


class TestMigrations:
    def test_the_lease_table_carries_the_endpoint_constraint(self):
        engine = _engine()
        constraints = inspect(engine).get_unique_constraints("relay_port_leases")
        columns = [sorted(c["column_names"]) for c in constraints]
        assert ["relay_id", "remote_port"] in columns

    def test_the_relay_table_carries_the_endpoint_constraint(self):
        engine = _engine()
        constraints = inspect(engine).get_unique_constraints("relays")
        columns = [sorted(c["column_names"]) for c in constraints]
        assert ["relay_addr", "relay_port"] in columns

    def test_pool_config_gains_the_relay_reference(self):
        engine = _engine()
        names = {c["name"] for c in inspect(engine).get_columns("ansible_pool_configs")}
        assert "relay_id" in names

    def test_the_document_import_digest_table_exists(self):
        engine = _engine()
        names = {
            c["name"]
            for c in inspect(engine).get_columns("definition_document_imports")
        }
        assert {"document_kind", "digest", "imported_at"} <= names

    def test_existing_pool_rows_keep_working_without_a_relay(self):
        """Nullable reference: a pool configured before this change is unchanged."""
        engine = _engine()
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO ansible_pool_configs "
                "(pool_id, playbook_path, requirement_delegate, inventory_group, extra_vars) "
                "VALUES ('legacy', :p, 'vm_management_v1', :g, '{}')"
            ), {"p": _PLAYBOOK_PATH, "g": _INVENTORY_GROUP})
        with Session(engine) as session:
            assert session.get(AnsiblePoolConfig, "legacy").relay_id is None

    def test_running_migrations_twice_is_idempotent(self):
        engine = _engine()
        run_migrations(
            engine,
            default_playbook_path=_PLAYBOOK_PATH,
            default_inventory_group=_INVENTORY_GROUP,
        )
        with Session(engine) as session:
            session.add(_lease("10.0.0.9:7000", 6100))
            session.commit()
            assert session.query(RelayPortLease).count() == 1
