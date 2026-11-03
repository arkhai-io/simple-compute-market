"""A pool's relay reference: one table, one write, one rule, whatever the provider.

External boundary: SQLAlchemy against file-backed SQLite, over the resource-pool
and relay tables. The database is deterministic and does no network I/O, so the
real engine is used rather than a mock.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from market_resource_pools import ResourcePool

from compute_provisioning.hosts import ConnectionCodecs, ConnectionEnvelope
from compute_provisioning.hosts.db import Host
from compute_provisioning.relays import (
    ManagementRouteRefused,
    PoolRelay,
    RelayPortLease,
    RelayRebindingRefused,
    RelayService,
    check_host_pool_change,
    pool_relay_id,
    relay_execution_fields,
    set_pool_relay,
)
from market_resource_pools import PoolValidationError

# A development-only Fernet key, generated per run and never used on a network.
_KEY = Fernet.generate_key().decode()


@pytest.fixture
def relays(session_factory):
    service = RelayService(
        session_factory=session_factory,
        settings=SimpleNamespace(ssh_decryption_key=_KEY),
        connection_codecs=ConnectionCodecs([]),
    )
    for relay_id, addr in (("site-a", "10.0.0.9"), ("site-b", "10.0.0.10")):
        service.create_relay(
            relay_id=relay_id,
            relay_addr=addr,
            relay_port=7000,
            vm_port_range_start=6100,
            vm_port_range_count=100,
            token=f"{relay_id}-token",
        )
    return service


@pytest.fixture
def pools(session_factory):
    """A VM pool and a bare-metal pool: the reference is the same for both."""
    with session_factory() as db, db.begin():
        db.add(ResourcePool(id="vm-pool", label="vm", provider="vm.ansible", enabled=True))
        db.add(ResourcePool(id="bm-pool", label="bm", provider="bare_metal.ansible", enabled=True))
        db.add(ResourcePool(id="bm-other", label="bm2", provider="bare_metal.ansible", enabled=True))


class _AddressCodec:
    """A connection kind whose only field is the address the host is reached at."""

    kind, version = "addr", 1

    def build(self, public, secrets, *, previous=None):
        return ConnectionEnvelope(kind="addr", version=1, public=dict(public), protected={})

    def validate(self, envelope):
        return envelope

    def address(self, envelope):
        return envelope.public["address"]


_CODECS = ConnectionCodecs([_AddressCodec()])


def _set(session_factory, pool_id, relay_id, codecs=_CODECS):
    with session_factory() as db, db.begin():
        set_pool_relay(db, pool_id, relay_id, codecs=codecs)


def _place(session_factory, host_id, pool_id, address):
    with session_factory() as db, db.begin():
        host = Host(host_id=host_id, enabled=True, pool_id=pool_id)
        host.set_connection(
            ConnectionEnvelope(kind="addr", version=1, public={"address": address}, protected={})
        )
        db.add(host)


def _read(session_factory, pool_id):
    with session_factory() as db:
        return pool_relay_id(db, pool_id)


def _lease(session_factory, *, relay_id="site-a", pool_id="bm-pool", host="bm-host-1"):
    with session_factory() as db, db.begin():
        db.add(
            RelayPortLease(
                id=f"lease-{pool_id}",
                relay_id=relay_id,
                remote_port=6100,
                host_id=host,
                pool_id=pool_id,
                owner_kind="fulfillment",
                owner_id=f"cr-{pool_id}",
            )
        )


class TestTheReference:
    def test_a_reference_round_trips(self, session_factory, relays, pools):
        _set(session_factory, "bm-pool", "site-a")
        assert _read(session_factory, "bm-pool") == "site-a"

    def test_a_pool_with_no_reference_reads_none(self, session_factory, pools):
        assert _read(session_factory, "vm-pool") is None
        assert _read(session_factory, None) is None

    def test_clearing_a_reference_removes_its_row(self, session_factory, relays, pools):
        _set(session_factory, "bm-pool", "site-a")
        _set(session_factory, "bm-pool", None)
        with session_factory() as db:
            assert db.get(PoolRelay, "bm-pool") is None

    def test_a_relay_that_does_not_exist_is_refused(self, session_factory, relays, pools):
        with pytest.raises(PoolValidationError) as excinfo:
            _set(session_factory, "bm-pool", "never-created")

        assert "never-created" in str(excinfo.value)
        assert _read(session_factory, "bm-pool") is None

    def test_two_providers_pools_may_reference_one_relay(self, session_factory, relays, pools):
        """The ordinary case: a VM pool and a bare-metal pool, one rendezvous."""
        _set(session_factory, "vm-pool", "site-a")
        _set(session_factory, "bm-pool", "site-a")
        with session_factory() as db:
            held = db.query(PoolRelay).filter(PoolRelay.relay_id == "site-a").all()
        assert {row.pool_id for row in held} == {"vm-pool", "bm-pool"}


class TestTheWriteRunsTheRebindingRule:
    def test_a_change_is_refused_while_the_pool_holds_a_lease(
        self, session_factory, relays, pools
    ):
        _set(session_factory, "bm-pool", "site-a")
        _lease(session_factory)

        with pytest.raises(RelayRebindingRefused) as excinfo:
            _set(session_factory, "bm-pool", "site-b")

        assert "bm-host-1:6100" in str(excinfo.value)
        assert _read(session_factory, "bm-pool") == "site-a"

    def test_clearing_is_a_change_and_is_refused_too(self, session_factory, relays, pools):
        _set(session_factory, "bm-pool", "site-a")
        _lease(session_factory)

        with pytest.raises(RelayRebindingRefused):
            _set(session_factory, "bm-pool", None)

    def test_restating_the_same_relay_is_free(self, session_factory, relays, pools):
        _set(session_factory, "bm-pool", "site-a")
        _lease(session_factory)

        _set(session_factory, "bm-pool", "site-a")

        assert _read(session_factory, "bm-pool") == "site-a"

    def test_a_change_is_accepted_once_drained(self, session_factory, relays, pools):
        _set(session_factory, "bm-pool", "site-a")
        _lease(session_factory)
        with session_factory() as db, db.begin():
            db.query(RelayPortLease).one().released_at = datetime.now(timezone.utc)

        _set(session_factory, "bm-pool", "site-b")

        assert _read(session_factory, "bm-pool") == "site-b"


class TestTheWriteChecksTheHostsManagementRoutes:
    def test_a_pool_is_not_pointed_at_the_relay_a_host_is_reached_through(
        self, session_factory, relays, pools
    ):
        _place(session_factory, "bm-host-1", "bm-pool", "10.0.0.9")

        with pytest.raises(ManagementRouteRefused) as excinfo:
            _set(session_factory, "bm-pool", "site-a")

        assert "bm-host-1" in str(excinfo.value) and "site-a" in str(excinfo.value)
        assert _read(session_factory, "bm-pool") is None

    def test_a_relay_its_hosts_are_not_reached_through_is_accepted(
        self, session_factory, relays, pools
    ):
        _place(session_factory, "bm-host-1", "bm-pool", "10.0.0.9")

        _set(session_factory, "bm-pool", "site-b")

        assert _read(session_factory, "bm-pool") == "site-b"

    def test_without_codecs_a_pool_holding_hosts_is_not_pointed_at_a_relay(
        self, session_factory, relays, pools
    ):
        """No host can be checked, so the write is refused rather than let
        through unchecked; a pool holding no host has nothing to check."""
        _place(session_factory, "bm-host-1", "bm-pool", "192.0.2.1")

        with pytest.raises(RuntimeError, match="connection codecs"):
            _set(session_factory, "bm-pool", "site-a", codecs=None)
        _set(session_factory, "vm-pool", "site-a", codecs=None)

        assert _read(session_factory, "bm-pool") is None
        assert _read(session_factory, "vm-pool") == "site-a"


class TestAHostMoveReadsTheFamilysReference:
    def test_a_move_between_providers_on_one_relay_is_free(
        self, session_factory, relays, pools
    ):
        _set(session_factory, "vm-pool", "site-a")
        _set(session_factory, "bm-pool", "site-a")
        _lease(session_factory, pool_id="vm-pool", host="host-1")

        with session_factory() as db:
            check_host_pool_change(
                db, host_id="host-1", current_pool_id="vm-pool", new_pool_id="bm-pool"
            )

    def test_a_move_to_a_pool_on_another_relay_is_refused(
        self, session_factory, relays, pools
    ):
        _set(session_factory, "bm-pool", "site-a")
        _set(session_factory, "bm-other", "site-b")
        _lease(session_factory, pool_id="bm-pool", host="host-1")

        with session_factory() as db, pytest.raises(RelayRebindingRefused):
            check_host_pool_change(
                db, host_id="host-1", current_pool_id="bm-pool", new_pool_id="bm-other"
            )


class TestTheExecutionFields:
    def test_a_usable_relay_resolves_with_its_token(self, session_factory, relays):
        with session_factory() as db:
            fields = relay_execution_fields(db, "site-a", _KEY)
        assert (fields["relay_addr"], fields["relay_port"]) == ("10.0.0.9", 7000)
        assert fields["vm_port_range_start"] == 6100
        assert fields["relay_token"] == "site-a-token"

    def test_a_disabled_or_missing_relay_resolves_to_nothing(self, session_factory, relays):
        relays.set_enabled("site-a", False)
        with session_factory() as db:
            assert relay_execution_fields(db, "site-a", _KEY) == {}
            assert relay_execution_fields(db, "never-created", _KEY) == {}
            assert relay_execution_fields(db, None, _KEY) == {}
