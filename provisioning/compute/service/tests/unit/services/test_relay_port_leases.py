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
from compute_provisioning_service.db.models import AnsiblePoolConfig, RelayPortLease


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
    """Identity is derived from the endpoint, so it cannot disagree with it."""

    def _config(self, **overrides) -> AnsiblePoolConfig:
        fields = {
            "pool_id": "gpu-pool",
            "playbook_path": _PLAYBOOK_PATH,
            "inventory_group": _INVENTORY_GROUP,
            "extra_vars": {},
            "relay_addr": "10.0.0.9",
            "relay_port": 7000,
        }
        fields.update(overrides)
        return AnsiblePoolConfig(**fields)

    def test_identity_comes_from_the_configured_endpoint(self):
        assert self._config().relay_id == "10.0.0.9:7000"

    def test_two_pools_on_one_endpoint_resolve_to_one_identity(self):
        """Which is what makes a genuine collision detectable."""
        first = self._config(pool_id="gpu-pool")
        second = self._config(pool_id="bare-metal-pool")
        assert first.relay_id == second.relay_id

    def test_two_pools_on_different_endpoints_do_not_collide(self):
        assert self._config().relay_id != self._config(relay_addr="10.0.0.10").relay_id

    def test_identity_is_normalized(self):
        assert self._config(relay_addr="  Relay.Local  ").relay_id == "relay.local:7000"

    @pytest.mark.parametrize(
        "overrides", [{"relay_addr": None}, {"relay_port": None}, {"relay_addr": ""}]
    )
    def test_an_unconfigured_relay_has_no_identity(self, overrides):
        """A pool with no relay serves VMs by direct NAT; it holds no leases."""
        assert self._config(**overrides).relay_id is None


class TestMigrations:
    def test_the_lease_table_carries_the_endpoint_constraint(self):
        engine = _engine()
        constraints = inspect(engine).get_unique_constraints("relay_port_leases")
        columns = [sorted(c["column_names"]) for c in constraints]
        assert ["relay_id", "remote_port"] in columns

    def test_pool_config_gains_the_relay_columns(self):
        engine = _engine()
        names = {c["name"] for c in inspect(engine).get_columns("ansible_pool_configs")}
        assert {
            "relay_addr", "relay_port", "vm_port_range_start", "vm_port_range_count",
        } <= names

    def test_existing_pool_rows_keep_working_without_a_relay(self):
        """Nullable columns: a pool configured before this change is unchanged."""
        engine = _engine()
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO ansible_pool_configs "
                "(pool_id, playbook_path, requirement_delegate, inventory_group, extra_vars) "
                "VALUES ('legacy', :p, 'vm_management_v1', :g, '{}')"
            ), {"p": _PLAYBOOK_PATH, "g": _INVENTORY_GROUP})
        with Session(engine) as session:
            config = session.get(AnsiblePoolConfig, "legacy")
            assert config.relay_addr is None
            assert config.relay_id is None

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
