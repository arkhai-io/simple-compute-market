"""The SSH port survives from operator input to an Ansible connection.

A host that has no inbound route answers SSH on a tunnel port rather than on
22 at ``kvm_host``. Four layers have to carry the port for that host to be
reachable: the INI parser, the wire models, the registry row, and both
inventory renderers. A test at any single layer passes while the port is
dropped at another, so the round trip at the end of this file is the property
that actually matters — the rest localise a failure once it exists.

External boundary: SQLAlchemy against in-memory SQLite, as in
``test_host_service.py``. The database is deterministic and does no network
I/O, so the real engine is used rather than a mock.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import create_session_factory, run_migrations
from compute_provisioning_service.db.models import Base, DEFAULT_POOL_ID, Host, ResourcePool
from vm_provisioning_operator.models import HostCreate, HostResponse, HostUpdate
from vm_provisioning_adapter.services.ansible_service import AnsibleService
from vm_provisioning_adapter.services.host_service import HostService, _parse_ini


_PLAYBOOK_PATH = "/configured/playbook.yaml"
_INVENTORY_GROUP = "kvm_hosts"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sqlite_memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def db_engine():
    engine = _sqlite_memory_engine()
    from market_resource_pools.db import Base as PoolsBase
    PoolsBase.metadata.create_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        session.add(ResourcePool(
            id=DEFAULT_POOL_ID, label="Default Pool", provider="ansible",
            enabled=True, policy_tags={},
        ))
        session.commit()
    return engine


@pytest.fixture
def settings():
    m = MagicMock()
    m.ssh_decryption_key = ""
    m.database_url = "sqlite:///:memory:"
    return m


@pytest.fixture
def svc(db_engine, settings):
    return HostService(session_factory=create_session_factory(db_engine), settings=settings)


def _host_create(**overrides) -> HostCreate:
    payload = {
        "name": "kvm1",
        "kvm_host": "10.0.0.5",
        "ssh_user": "root",
        "ssh_key_value": "/home/appuser/.ssh/id_ed25519",
    }
    payload.update(overrides)
    return HostCreate(**payload)


# ---------------------------------------------------------------------------
# INI parsing
# ---------------------------------------------------------------------------


class TestParseAnsiblePort:
    def test_port_is_read_when_present(self):
        parsed = _parse_ini(
            "[kvm_hosts]\n"
            "kvm1 ansible_host=10.0.0.5 ansible_user=root ansible_port=6000\n"
        )
        assert parsed[0]["ssh_port"] == 6000

    def test_absent_port_defaults_to_22(self):
        parsed = _parse_ini(
            "[kvm_hosts]\nkvm1 ansible_host=10.0.0.5 ansible_user=root\n"
        )
        assert parsed[0]["ssh_port"] == 22

    def test_bare_metal_group_is_parsed_too(self):
        parsed = _parse_ini(
            "[bare_metal_nodes]\n"
            "node1 ansible_host=10.0.0.9 ansible_user=root ansible_port=6001\n"
        )
        assert parsed[0]["ssh_port"] == 6001

    @pytest.mark.parametrize("value", ["notanumber", "", "0", "65536", "-1", "22.5"])
    def test_a_malformed_port_skips_the_entry(self, value):
        """A wrong port makes a host unreachable, so it must not be guessed.

        This differs on purpose from ``gpus=``, which degrades to 0: a wrong
        capacity hint produces a visibly wrong listing, while a silently
        substituted port produces a connection failure that looks like a
        network problem.
        """
        parsed = _parse_ini(
            "[kvm_hosts]\n"
            f"kvm1 ansible_host=10.0.0.5 ansible_user=root ansible_port={value}\n"
        )
        assert parsed == []

    def test_a_malformed_port_does_not_discard_other_hosts(self):
        parsed = _parse_ini(
            "[kvm_hosts]\n"
            "kvm1 ansible_host=10.0.0.5 ansible_user=root ansible_port=oops\n"
            "kvm2 ansible_host=10.0.0.6 ansible_user=root ansible_port=6002\n"
        )
        assert [(e["name"], e["ssh_port"]) for e in parsed] == [("kvm2", 6002)]

    def test_a_malformed_gpus_still_degrades_rather_than_skipping(self):
        """The two fields differ deliberately; assert the contrast holds."""
        parsed = _parse_ini(
            "[kvm_hosts]\nkvm1 ansible_host=10.0.0.5 ansible_user=root gpus=lots\n"
        )
        assert parsed[0]["gpu_count"] == 0
        assert parsed[0]["ssh_port"] == 22


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistryCarriesThePort:
    def test_register_defaults_to_22(self, svc):
        host = svc.register_host(_host_create())
        assert host.ssh_port == 22

    def test_register_stores_an_explicit_port(self, svc):
        host = svc.register_host(_host_create(ssh_port=6000))
        assert host.ssh_port == 6000

    def test_update_changes_the_port(self, svc):
        svc.register_host(_host_create(ssh_port=6000))
        assert svc.update_host("kvm1", HostUpdate(ssh_port=6005)).ssh_port == 6005

    def test_update_without_a_port_leaves_it_alone(self, svc):
        svc.register_host(_host_create(ssh_port=6000))
        assert svc.update_host("kvm1", HostUpdate(ssh_user="ops")).ssh_port == 6000

    @pytest.mark.parametrize("value", [0, 65536, -1])
    def test_out_of_range_is_rejected_at_the_wire_model(self, value):
        with pytest.raises(ValueError):
            _host_create(ssh_port=value)

    def test_response_model_exposes_the_port(self, svc):
        host = svc.register_host(_host_create(ssh_port=6000))
        assert HostResponse.model_validate(host).ssh_port == 6000

    def test_seed_from_ini_stores_the_port(self, svc):
        svc.seed_from_ini(
            "[kvm_hosts]\n"
            "kvm1 ansible_host=10.0.0.5 ansible_user=root ansible_port=6000\n"
        )
        assert svc.get_host("kvm1").ssh_port == 6000

    def test_seed_from_ini_updates_the_port_on_reimport(self, svc):
        svc.seed_from_ini(
            "[kvm_hosts]\n"
            "kvm1 ansible_host=10.0.0.5 ansible_user=root ansible_port=6000\n"
        )
        svc.seed_from_ini(
            "[kvm_hosts]\n"
            "kvm1 ansible_host=10.0.0.5 ansible_user=root ansible_port=6007\n"
        )
        assert svc.get_host("kvm1").ssh_port == 6007


# ---------------------------------------------------------------------------
# Inventory rendering
# ---------------------------------------------------------------------------


def _host_row(**overrides) -> Host:
    fields = {
        "name": "kvm1",
        "kvm_host": "10.0.0.5",
        "public_host": None,
        "ssh_user": "root",
        "ssh_port": 6000,
        "ssh_key_type": "path",
        "ssh_key_value": "/keys/id_ed25519",
        "gpu_count": 0,
        "enabled": True,
        "pool_id": DEFAULT_POOL_ID,
    }
    fields.update(overrides)
    return Host(**fields)


def _port_segment(line: str) -> str:
    return next(part for part in line.split() if part.startswith("ansible_port="))


class TestBothRenderersEmitThePort:
    def test_host_service_renderer_emits_it(self, svc):
        rendered = svc.render_inventory_ini([_host_row()])
        assert "ansible_port=6000" in rendered

    def test_ansible_service_renderer_emits_it(self, settings, tmp_path):
        service = AnsibleService.__new__(AnsibleService)
        service._settings = settings
        path = service.write_inventory([_host_row()])
        try:
            assert "ansible_port=6000" in path.read_text(encoding="utf-8")
        finally:
            path.unlink(missing_ok=True)

    def test_the_default_port_renders_explicitly(self, svc):
        """An absent line would be ambiguous between 22 and 'not recorded'.

        The column is NOT NULL, so the registry never holds the second state
        and the INI can say so.
        """
        assert "ansible_port=22" in svc.render_inventory_ini([_host_row(ssh_port=22)])

    def test_the_two_renderers_agree(self, svc, settings):
        """These are two renderings of one registry row and must not drift.

        They already differ on ``public_host``; a host that connects
        differently depending on which path built its inventory is a defect
        that would only appear on one code path.
        """
        host = _host_row(ssh_port=6009)
        from_service = svc.render_inventory_ini([host]).splitlines()[1]

        renderer = AnsibleService.__new__(AnsibleService)
        renderer._settings = settings
        path = renderer.write_inventory([host])
        try:
            from_ansible = path.read_text(encoding="utf-8").splitlines()[1]
        finally:
            path.unlink(missing_ok=True)

        assert _port_segment(from_service) == _port_segment(from_ansible)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


class TestMigration:
    def _engine_without_the_column(self):
        """A database as it stood before the column existed."""
        engine = _sqlite_memory_engine()
        run_migrations(
            engine,
            default_playbook_path=_PLAYBOOK_PATH,
            default_inventory_group=_INVENTORY_GROUP,
        )
        with engine.begin() as connection:
            # The migration is one event covering three independent parts;
            # reverting the part under test is enough to re-apply it.
            connection.execute(text("ALTER TABLE hosts DROP COLUMN ssh_port"))
            connection.execute(text(
                "DELETE FROM schema_migrations WHERE id = '20260901_001_relay_reachable_hosts'"
            ))
        return engine

    def _insert_host(self, engine, name: str) -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO hosts (name, kvm_host, ssh_user, ssh_key_type, "
                    "ssh_key_value, gpu_count, enabled, pool_id) VALUES "
                    "(:n, '10.0.0.5', 'root', 'path', '/keys/id', 0, 1, :p)"
                ),
                {"n": name, "p": DEFAULT_POOL_ID},
            )

    def test_pre_existing_rows_backfill_to_22(self):
        engine = self._engine_without_the_column()
        self._insert_host(engine, "legacy1")
        self._insert_host(engine, "legacy2")

        run_migrations(
            engine,
            default_playbook_path=_PLAYBOOK_PATH,
            default_inventory_group=_INVENTORY_GROUP,
        )

        with engine.begin() as connection:
            ports = connection.execute(
                text("SELECT ssh_port FROM hosts ORDER BY name")
            ).scalars().all()
        assert ports == [22, 22]

    def test_the_column_is_added(self):
        engine = self._engine_without_the_column()
        assert "ssh_port" not in {
            c["name"] for c in inspect(engine).get_columns("hosts")
        }
        run_migrations(
            engine,
            default_playbook_path=_PLAYBOOK_PATH,
            default_inventory_group=_INVENTORY_GROUP,
        )
        assert "ssh_port" in {
            c["name"] for c in inspect(engine).get_columns("hosts")
        }

    def test_running_twice_is_idempotent(self):
        engine = self._engine_without_the_column()
        self._insert_host(engine, "legacy1")
        for _ in range(2):
            run_migrations(
                engine,
                default_playbook_path=_PLAYBOOK_PATH,
                default_inventory_group=_INVENTORY_GROUP,
            )
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT ssh_port FROM hosts")
            ).scalar_one() == 22


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_an_imported_port_reaches_the_rendered_inventory(self, svc):
        """The property the change exists for.

        Every single-layer test above can pass while the port is dropped one
        layer along; only the round trip proves an operator's inventory line
        becomes the port Ansible connects on.
        """
        svc.seed_from_ini(
            "[kvm_hosts]\n"
            "kvm1 ansible_host=10.0.0.5 ansible_user=root ansible_port=6000\n"
        )
        rendered = svc.render_inventory_ini(svc.list_hosts())
        assert "ansible_port=6000" in rendered

    def test_a_registered_port_reaches_the_rendered_inventory(self, svc):
        svc.register_host(_host_create(ssh_port=6004))
        assert "ansible_port=6004" in svc.render_inventory_ini(svc.list_hosts())
