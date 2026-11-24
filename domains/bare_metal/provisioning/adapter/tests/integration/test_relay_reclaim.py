"""A grant's reclaim on its leased relay, prepared through the family's resolver.

The relays, their administration, and when a relay is resolved are the compute
family's and are tested there. What is bare metal's: the codec prepares a
reclaim with the relay its lease names, through that resolver, so a reclaim on
a disabled relay runs and ends the grant.

External boundary: SQLAlchemy against file-backed SQLite, over the resource-pool
and relay tables. The database is deterministic and does no network I/O, so the
real engine is used rather than a mock.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from arkhai_bare_metal import BARE_METAL_OFFERING_MODE, NODE_RECLAIM_ACCESS_ACTION
from compute_provisioning.hosts import ConnectionCodecs, ConnectionEnvelope, ExecutionHost
from compute_provisioning.jobs import JobRun
from compute_provisioning.relays import RelayExecutionResolver, RelayService
from compute_provisioning.relays.db import Base as RelaysBase
from cryptography.fernet import Fernet
from market_resource_pools.db import Base as PoolsBase
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bare_metal_provisioning_adapter.codec import BareMetalAnsibleCodec, BareMetalJobParams

# A development-only Fernet key. Generated for this fixture, never used on any
# network, and safe to read here precisely because it protects nothing.
_KEY = Fernet.generate_key().decode()

# A registered whole host reached over ssh. Documentation addresses only.
_HOST = ExecutionHost(
    host_id="bm-node-1",
    pool_id="default",
    connection=ConnectionEnvelope(
        kind="ssh",
        version=3,
        public={"ssh_host": "192.0.2.5", "ssh_port": 22, "ssh_user": "ops"},
    ),
)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'relays.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    PoolsBase.metadata.create_all(bind=engine)
    RelaysBase.metadata.create_all(bind=engine)
    try:
        yield sessionmaker(bind=engine)
    finally:
        engine.dispose()


def test_a_reclaim_on_a_disabled_relay_is_prepared(session_factory):
    """Disabling a relay drains it, so the reclaim ending a grant leased on it
    is prepared with the relay's address and token: refused, the tenant would
    keep the host past the lease end."""
    settings = SimpleNamespace(ssh_decryption_key=_KEY)
    relays = RelayService(session_factory, settings, connection_codecs=ConnectionCodecs([]))
    relays.create_relay(
        relay_id="buyer-relay",
        relay_addr="203.0.113.9",
        relay_port=7000,
        vm_port_range_start=6100,
        vm_port_range_count=10,
        token="admission-secret",
    )
    relays.set_enabled("buyer-relay", False)
    params = BareMetalJobParams(
        action=NODE_RECLAIM_ACCESS_ACTION,
        host_id=_HOST.host_id,
        physical_host_id="physical-1",
        escrow_uid="escrow-1",
        ssh_user="tenant-a",
        capacity_reservation_id="reservation-1",
        relay_id="buyer-relay",
        remote_port=6100,
    )
    run = JobRun(
        job_id="job-1",
        offering_mode=BARE_METAL_OFFERING_MODE,
        action=params.action,
        host=_HOST,
        parameters=params.model_dump(mode="json"),
        report_starting=lambda: None,
        report_handle=lambda handle: None,
        report_logs=lambda logs: None,
    )
    codec = BareMetalAnsibleCodec(
        relay_resolver=RelayExecutionResolver(session_factory=session_factory, settings=settings)
    )

    plan = codec.prepare(run)

    assert plan.variables["frp_server_addr"] == "203.0.113.9"
    assert plan.variables["frp_auth_token"] == "admission-secret"
    assert "relay_grant" not in plan.variables
