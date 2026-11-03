"""VM's share of relay access: its pool configuration's relay reference, and
the relay inputs its codec renders.

The relays themselves, their administration, and their rebinding rules are the
compute family's and are tested there. What is VM's: a pool's configuration
names a relay by reference, its redacted read never carries the relay's token
while its execution read resolves it, repointing a pool runs the family's
rebinding refusal, and a relay's resolved token reaches the variables a VM job
runs with.

External boundary: SQLAlchemy against file-backed SQLite, over a schema built
from the resource-pool, relay, and VM models. The database is deterministic and
does no network I/O, so the real engine is used rather than a mock.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from compute_provisioning.hosts import ConnectionCodecs
from compute_provisioning.relays import (
    PoolRelay,
    RelayExecutionResolver,
    RelayPortLease,
    RelayRebindingRefused,
    RelayService,
)
from compute_provisioning_ansible import render_extra_vars
from cryptography.fernet import Fernet
from market_resource_pools import ResourcePool

from vm_provisioning_adapter.codec import VmAnsibleCodec
from vm_provisioning_adapter.models.jobs_model import VmJobParams
from vm_provisioning_adapter.services.ansible_pool_config_handler import (
    AnsiblePoolConfigHandler,
)

_PLAYBOOK_PATH = "/configured/playbook.yaml"
# A development-only Fernet key. Generated for this fixture, never used on any
# network, and safe to read here precisely because it protects nothing.
_KEY = Fernet.generate_key().decode()


@pytest.fixture
def settings():
    return SimpleNamespace(ssh_decryption_key=_KEY)


@pytest.fixture
def relays(session_factory, settings):
    return RelayService(
        session_factory=session_factory,
        settings=settings,
        connection_codecs=ConnectionCodecs([]),
    )


@pytest.fixture
def handler(settings):
    return AnsiblePoolConfigHandler(settings=settings)


def _make_relay(relays, **overrides):
    fields = {
        "relay_id": "site-a",
        "relay_addr": "10.0.0.9",
        "relay_port": 7000,
        "vm_port_range_start": 6100,
        "vm_port_range_count": 100,
    }
    fields.update(overrides)
    return relays.create_relay(**fields)


def _pool_on_relay(session_factory, handler, *, pool_id="gpu-pool", relay_id="site-a"):
    """A pool already pointing at a relay. Written before any lease exists,
    which is the real order: a lease is what a VM on that pool produced."""
    with session_factory() as db, db.begin():
        db.add(ResourcePool(id=pool_id, label=pool_id, provider="vm.ansible", enabled=True))
        handler.replace_config(
            db, pool_id, {"playbook_path": _PLAYBOOK_PATH, "relay_id": relay_id}
        )


def _make_lease(session_factory, *, relay_id="site-a", pool_id="gpu-pool", host="kvm1"):
    with session_factory() as db, db.begin():
        db.add(
            RelayPortLease(
                id=f"lease-{relay_id}",
                relay_id=relay_id,
                remote_port=6100,
                host_id=host,
                pool_id=pool_id,
                owner_kind="fulfillment",
                owner_id=f"cr-{relay_id}",
            )
        )


class TestTheReaderSplit:
    """The redacted read has the unqualified name; only execution resolves."""

    def test_the_plain_read_returns_the_reference_and_no_token(
        self, session_factory, relays, handler
    ):
        _make_relay(relays, token="admission-secret")
        _pool_on_relay(session_factory, handler)
        with session_factory() as db:
            config = handler.read_config(db, "gpu-pool")
        assert config["relay_id"] == "site-a"
        assert "relay_token" not in config
        assert "relay_addr" not in config

    def test_the_execution_read_resolves_the_relay_and_decrypts(
        self, session_factory, relays, handler
    ):
        _make_relay(relays, token="admission-secret")
        _pool_on_relay(session_factory, handler)
        with session_factory() as db:
            config = handler.read_config_for_execution(db, "gpu-pool")
        assert config["relay_addr"] == "10.0.0.9"
        assert config["vm_port_range_start"] == 6100
        assert config["relay_token"] == "admission-secret"

    def test_a_pool_with_no_relay_resolves_to_no_relay_fields(self, session_factory, handler):
        with session_factory() as db, db.begin():
            db.add(ResourcePool(id="nat-pool", label="NAT", provider="vm.ansible", enabled=True))
            handler.replace_config(db, "nat-pool", {"playbook_path": _PLAYBOOK_PATH})
        with session_factory() as db:
            config = handler.read_config_for_execution(db, "nat-pool")
        assert config["relay_id"] is None
        assert "relay_token" not in config

    def test_a_disabled_relay_resolves_to_no_relay_fields(
        self, session_factory, relays, handler
    ):
        """So the single rejection point for an unusable relay stays in
        pre-dispatch validation rather than being split across two layers."""
        _make_relay(relays, token="admission-secret")
        _pool_on_relay(session_factory, handler)
        relays.set_enabled("site-a", False)
        with session_factory() as db:
            config = handler.read_config_for_execution(db, "gpu-pool")
        assert "relay_token" not in config

    def test_the_relay_endpoint_is_not_writable_as_pool_configuration(self, handler):
        """The window belongs to the relay. Accepting it here is what would
        let two pools disagree about one listening namespace."""
        normalized, problems = handler.validate_config_problems(
            {"playbook_path": _PLAYBOOK_PATH, "vm_port_range_start": 6100}
        )
        assert normalized is None
        assert any(p.code == "unknown_field" for p in problems)


class TestPoolRebinding:
    """Repointing a pool runs the family's rule: refused while its hosts hold
    leases, unless the relay is the same on both sides."""

    def test_a_pool_cannot_be_repointed_while_its_hosts_hold_leases(
        self, session_factory, relays, handler
    ):
        _make_relay(relays, relay_id="site-a", relay_addr="10.0.0.9")
        _make_relay(relays, relay_id="site-b", relay_addr="10.0.0.10")
        _pool_on_relay(session_factory, handler, relay_id="site-a")
        _make_lease(session_factory, relay_id="site-a")

        with session_factory() as db, db.begin():
            with pytest.raises(RelayRebindingRefused):
                handler.replace_config(
                    db, "gpu-pool", {"playbook_path": _PLAYBOOK_PATH, "relay_id": "site-b"}
                )

    def test_a_pool_write_that_keeps_its_relay_is_unaffected(
        self, session_factory, relays, handler
    ):
        _make_relay(relays, relay_id="site-a", relay_addr="10.0.0.9")
        _pool_on_relay(session_factory, handler, relay_id="site-a")
        _make_lease(session_factory, relay_id="site-a")
        with session_factory() as db, db.begin():
            handler.replace_config(
                db, "gpu-pool", {"playbook_path": "/other/playbook.yaml", "relay_id": "site-a"}
            )
        with session_factory() as db:
            assert handler.read_config(db, "gpu-pool")["playbook_path"] == "/other/playbook.yaml"

    def test_the_reference_is_stored_where_every_providers_is(
        self, session_factory, relays, handler
    ):
        """A VM pool's relay is the family's pool relay reference."""
        _make_relay(relays, relay_id="shared")
        _pool_on_relay(session_factory, handler, pool_id="gpu-pool", relay_id="shared")
        _pool_on_relay(session_factory, handler, pool_id="cpu-pool", relay_id="shared")
        with session_factory() as db:
            held = db.query(PoolRelay).filter(PoolRelay.relay_id == "shared").all()
        assert {row.pool_id for row in held} == {"gpu-pool", "cpu-pool"}


class TestRelayInputsReachTheJob:
    def test_a_rotated_token_reaches_the_rendered_job_variables(
        self, relays, session_factory, settings
    ):
        """How far the service-side path carries a rotation, and no further.

        Asserted through what a job runs with rather than through a successful
        write to the relay row: a rotation that stores correctly and never
        reaches a playbook has changed nothing an operator cares about.

        This does **not** show that the host's tunnel client adopts the token.
        That needs the client's own configuration rewritten and the client
        restarted, which `vm-create.yml` does and `test_vm_management_contracts`
        pins; whether the restart behaves as intended against a real relay is
        the live gate's business. A rotation takes effect without a restart in
        the variables, and only after one on the host.
        """
        _make_relay(relays, token="original")
        params = VmJobParams(
            host_id="kvm1",
            vm_action="create",
            offering_mode="vm",
            relay_id="site-a",
            vm_remote_port=6100,
        )
        relays.rotate_token("site-a", "rotated")

        resolver = RelayExecutionResolver(session_factory=session_factory, settings=settings)
        rendered = render_extra_vars(VmAnsibleCodec().variables(resolver.resolve_into(params)))

        assert 'frp_auth_token: "rotated"' in rendered.splitlines()
        assert "original" not in rendered
