"""A disabled relay's pools' hosts take no new delivery.

The site authority judges every claim against the hosts taking new delivery
the compute composition reports. Disabling a relay drains it, so every host
placed in, or declared in, a pool referencing it leaves that report, and
returns to it when the relay is enabled again; a disabled host stays out
whatever its relay.

External boundary: SQLAlchemy against file-backed SQLite, over the resource-pool,
host, relay, and site capacity tables. The real host authority is the report
composed over, and the database is deterministic and does no network I/O, so
the real engine is used rather than a mock.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from market_resource_pools import ResourcePool
from market_site.db import Base as SiteBase
from market_site.db import CapacityBucket
from sqlalchemy.orm import sessionmaker

from compute_provisioning.hosts import ConnectionCodecs, ConnectionEnvelope
from compute_provisioning.hosts.db import Host
from compute_provisioning.hosts.service import HostAuthority
from compute_provisioning.relays import PoolRelay, Relay, RelayDeliverableHosts, RelayService

# A development-only Fernet key, generated per run and never used on a network.
_KEY = Fernet.generate_key().decode()


@pytest.fixture
def session_factory(relay_engine):
    """The family's relay schema, and the site's capacity declarations."""
    SiteBase.metadata.create_all(bind=relay_engine)
    return sessionmaker(bind=relay_engine)


@pytest.fixture
def relays(session_factory):
    service = RelayService(
        session_factory=session_factory,
        settings=SimpleNamespace(ssh_decryption_key=_KEY),
        connection_codecs=ConnectionCodecs([]),
    )
    for relay_id, addr in (("site-a", "203.0.113.9"), ("site-b", "203.0.113.10")):
        service.create_relay(
            relay_id=relay_id,
            relay_addr=addr,
            relay_port=7000,
            vm_port_range_start=6100,
            vm_port_range_count=100,
        )
    return service


@pytest.fixture
def report(session_factory):
    return RelayDeliverableHosts(HostAuthority(session_factory, codecs=ConnectionCodecs([])))


@pytest.fixture
def hosts(session_factory, relays):
    """Pools on each relay and one with none, a host placed and declared in
    each, a disabled host on relay ``site-a``'s pool, an unplaced host whose
    declaration is in that pool, and an unplaced host declared nowhere."""
    with session_factory() as db, db.begin():
        for pool_id, relay_id in (("on-a", "site-a"), ("on-b", "site-b"), ("direct", None)):
            db.add(ResourcePool(id=pool_id, label=pool_id, provider="test", enabled=True))
            db.flush()
            if relay_id is not None:
                db.add(PoolRelay(pool_id=pool_id, relay_id=relay_id))
        for host_id, placed_in, declared_in, enabled in (
            ("host-a", "on-a", "on-a", True),
            ("host-a-off", "on-a", "on-a", False),
            ("host-a-declared", None, "on-a", True),
            ("host-b", "on-b", "on-b", True),
            ("host-direct", "direct", "direct", True),
            ("host-unplaced", None, None, True),
        ):
            host = Host(host_id=host_id, enabled=enabled, pool_id=placed_in)
            host.set_connection(ConnectionEnvelope(kind="ssh", version=3, public={}))
            db.add(host)
            if declared_in is not None:
                db.add(CapacityBucket(
                    backing_resource_id=f"{host_id}-resource", pool_id=declared_in,
                    host_id=host_id, capacity={},
                ))


def _reported(session_factory, report) -> frozenset[str]:
    with session_factory() as db:
        return report.deliverable_host_ids(db)


def test_every_enabled_host_is_reported_while_every_relay_is_enabled(
    session_factory, report, hosts
):
    assert _reported(session_factory, report) == {
        "host-a", "host-a-declared", "host-b", "host-direct", "host-unplaced",
    }


def test_a_host_placed_or_declared_in_a_pool_on_a_disabled_relay_is_left_out(
    session_factory, relays, report, hosts
):
    """The unplaced host whose declaration is in the relay's pool would take
    its deliveries through the relay all the same."""
    relays.set_enabled("site-a", False)

    assert _reported(session_factory, report) == {"host-b", "host-direct", "host-unplaced"}


def test_enabling_the_relay_again_returns_its_hosts(session_factory, relays, report, hosts):
    relays.set_enabled("site-a", False)
    relays.set_enabled("site-a", True)

    assert {"host-a", "host-a-declared"} <= _reported(session_factory, report)


def test_a_disabled_host_stays_out_whatever_its_relay(session_factory, relays, report, hosts):
    reported = _reported(session_factory, report)
    relays.set_enabled("site-a", False)
    relays.set_enabled("site-a", True)

    assert "host-a-off" not in reported
    assert "host-a-off" not in _reported(session_factory, report)


def test_the_report_is_read_in_the_callers_session(session_factory, report, hosts):
    """A decision is judged against the relay state its own transaction sees,
    an uncommitted disable included."""
    with session_factory() as db:
        db.get(Relay, "site-b").enabled = False
        db.flush()

        assert "host-b" not in report.deliverable_host_ids(db)
        db.rollback()

    assert "host-b" in _reported(session_factory, report)
