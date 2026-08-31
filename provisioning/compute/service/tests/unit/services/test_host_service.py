"""
Unit tests for HostService.

Scope (per Architecture.md — Unit Tests jurisdiction):
  - seed_from_ini: parsing, upsert, idempotency
  - register_host: embedded key encryption
  - render_inventory_ini: correct INI output format
  - list_hosts: enabled_only filter

External boundary: SQLAlchemy with an in-memory SQLite DB (not mocked).
The DB is a deterministic dependency with no network I/O, so using the real
engine here is correct per the testing strategy.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import create_session_factory
from compute_provisioning_service.db.models import Base, DEFAULT_POOL_ID, Host, ResourcePool
from vm_provisioning_operator.models import HostCreate, HostUpdate
from vm_provisioning_adapter.services.host_service import HostService, _parse_ini


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # resource_pools must exist before Base's ansible_pool_configs FK resolves.
    from market_resource_pools.db import Base as PoolsBase
    PoolsBase.metadata.create_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # HostService requires pool_id to reference an existing pool. The real
    # migration always seeds "default" before hosts.pool_id can be NOT
    # NULL (see db/migrations.py); mirror that guarantee here since this
    # fixture builds schema directly rather than through the migration.
    with Session(engine) as session:
        session.add_all([
            ResourcePool(
                id=DEFAULT_POOL_ID, label="Default Pool", provider="ansible",
                enabled=True, policy_tags={},
            ),
            ResourcePool(
                id="whole-host-california", label="Whole Host California",
                provider="bare_metal.ansible", enabled=True,
                policy_tags={"deliverable_modes": ["bare_metal"]},
            ),
        ])
        session.commit()
    return engine


@pytest.fixture
def session_factory(db_engine):
    return create_session_factory(db_engine)


@pytest.fixture
def settings():
    m = MagicMock()
    m.ssh_decryption_key = ""
    m.database_url = "sqlite:///:memory:"
    return m


@pytest.fixture
def svc(session_factory, settings):
    return HostService(session_factory=session_factory, settings=settings)


# ---------------------------------------------------------------------------
# _parse_ini (module-level helper)
# ---------------------------------------------------------------------------


class TestParseIni:
    def test_parses_single_host(self):
        ini = (
            "[kvm_hosts]\n"
            "kvm1  ansible_host=10.0.0.1  ansible_user=ubuntu  "
            "ansible_ssh_private_key_file=/home/user/.ssh/id_ed25519\n"
        )
        result = _parse_ini(ini)
        assert len(result) == 1
        assert result[0]["name"] == "kvm1"
        assert result[0]["kvm_host"] == "10.0.0.1"
        assert result[0]["ssh_user"] == "ubuntu"
        assert result[0]["ansible_ssh_private_key_file"] == "/home/user/.ssh/id_ed25519"

    def test_parses_multiple_hosts(self):
        ini = (
            "[kvm_hosts]\n"
            "kvm1  ansible_host=10.0.0.1  ansible_user=ubuntu\n"
            "ww2  ansible_host=10.0.0.2  ansible_user=root\n"
        )
        result = _parse_ini(ini)
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert names == {"kvm1", "ww2"}

    def test_parses_gpu_model(self):
        ini = (
            "[kvm_hosts]\n"
            "kvm1  ansible_host=10.0.0.1  ansible_user=ubuntu  gpus=8  gpu_model=H100\n"
        )
        result = _parse_ini(ini)
        assert result[0]["gpu_count"] == 8
        assert result[0]["gpu_model"] == "H100"

    def test_gpu_model_absent_when_not_specified(self):
        ini = "[kvm_hosts]\nkvm1  ansible_host=10.0.0.1  ansible_user=ubuntu\n"
        result = _parse_ini(ini)
        assert result[0]["gpu_model"] is None

    def test_skips_group_headers_and_comments(self):
        ini = (
            "# this is a comment\n"
            "[kvm_hosts]\n"
            "kvm1  ansible_host=10.0.0.1  ansible_user=ubuntu\n"
            "[other_group]\n"
            "other  ansible_host=9.9.9.9  ansible_user=nobody\n"
        )
        result = _parse_ini(ini)
        names = {r["name"] for r in result}
        assert "kvm1" in names
        assert "other" not in names

    def test_parses_bare_metal_nodes_group(self):
        ini = (
            "[bare_metal_nodes]\n"
            "bm-node-1  ansible_host=10.0.1.1  ansible_user=root\n"
        )
        result = _parse_ini(ini)
        assert len(result) == 1
        assert result[0]["name"] == "bm-node-1"
        assert result[0]["kvm_host"] == "10.0.1.1"
        assert result[0]["ssh_user"] == "root"

    def test_parses_explicit_pool_id(self):
        ini = (
            "[bare_metal_nodes]\n"
            "bm-node-1 ansible_host=10.0.1.1 ansible_user=root "
            "pool_id=whole-host-california\n"
        )
        result = _parse_ini(ini)
        assert result[0]["pool_id"] == "whole-host-california"

    def test_skips_entry_missing_ansible_host(self):
        ini = "bad_entry  ansible_user=ubuntu\n"
        result = _parse_ini(ini)
        assert result == []

    def test_skips_entry_missing_ansible_user(self):
        ini = "bad_entry  ansible_host=10.0.0.1\n"
        result = _parse_ini(ini)
        assert result == []

    def test_empty_string_returns_empty(self):
        assert _parse_ini("") == []


# ---------------------------------------------------------------------------
# seed_from_ini
# ---------------------------------------------------------------------------


class TestSeedFromIni:
    _INI = (
        "[kvm_hosts]\n"
        "kvm1  ansible_host=10.0.0.1  ansible_user=ubuntu  "
        "ansible_ssh_private_key_file=/home/user/.ssh/id_ed25519\n"
        "ww2  ansible_host=10.0.0.2  ansible_user=root  "
        "ansible_ssh_private_key_file=/home/user/.ssh/id_ed25519\n"
    )

    def test_inserts_correct_rows(self, svc):
        hosts = svc.seed_from_ini(self._INI, ssh_key_type="path")
        assert len(hosts) == 2
        names = {h.name for h in hosts}
        assert names == {"kvm1", "ww2"}

    def test_stores_key_path_verbatim(self, svc):
        hosts = svc.seed_from_ini(self._INI, ssh_key_type="path")
        kvm1 = next(h for h in hosts if h.name == "kvm1")
        assert kvm1.ssh_key_value == "/home/user/.ssh/id_ed25519"
        assert kvm1.ssh_key_type == "path"

    def test_gpu_model_persists_through_seed(self, svc):
        ini = (
            "[kvm_hosts]\n"
            "kvm1  ansible_host=10.0.0.1  ansible_user=ubuntu  gpus=8  gpu_model=H100\n"
        )
        hosts = svc.seed_from_ini(ini, ssh_key_type="path")
        assert hosts[0].gpu_count == 8
        assert hosts[0].gpu_model == "H100"

    def test_explicit_pool_persists_through_seed(self, svc):
        ini = (
            "[bare_metal_nodes]\n"
            "bm-node-1 ansible_host=10.0.1.1 ansible_user=root "
            "pool_id=whole-host-california\n"
        )
        hosts = svc.seed_from_ini(ini, ssh_key_type="path")
        assert hosts[0].pool_id == "whole-host-california"

    def test_unknown_explicit_pool_is_rejected(self, svc):
        ini = (
            "[bare_metal_nodes]\n"
            "bm-node-1 ansible_host=10.0.1.1 ansible_user=root pool_id=missing\n"
        )
        with pytest.raises(ValueError, match="Pool 'missing' does not exist"):
            svc.seed_from_ini(ini, ssh_key_type="path")

    def test_idempotent_on_repeat_call(self, svc):
        svc.seed_from_ini(self._INI, ssh_key_type="path")
        svc.seed_from_ini(self._INI, ssh_key_type="path")
        all_hosts = svc.list_hosts(enabled_only=False)
        names = [h.name for h in all_hosts]
        # No duplicates
        assert len(names) == len(set(names))
        assert len(names) == 2

    def test_upsert_updates_existing_row(self, svc):
        svc.seed_from_ini(self._INI, ssh_key_type="path")
        updated_ini = (
            "[kvm_hosts]\n"
            "kvm1  ansible_host=10.9.9.9  ansible_user=newuser  "
            "ansible_ssh_private_key_file=/home/user/.ssh/id_ed25519\n"
        )
        svc.seed_from_ini(updated_ini, ssh_key_type="path")
        kvm1 = svc.get_host("kvm1")
        assert kvm1.kvm_host == "10.9.9.9"
        assert kvm1.ssh_user == "newuser"

    def test_absent_hosts_not_touched(self, svc):
        """Append-only: hosts not in the new INI are left as-is."""
        svc.seed_from_ini(self._INI, ssh_key_type="path")
        ini_ww2_only = (
            "[kvm_hosts]\n"
            "ww2  ansible_host=10.0.0.2  ansible_user=root  "
            "ansible_ssh_private_key_file=/home/user/.ssh/id_ed25519\n"
        )
        svc.seed_from_ini(ini_ww2_only, ssh_key_type="path")
        kvm1 = svc.get_host("kvm1")
        assert kvm1 is not None
        assert kvm1.enabled is True


# ---------------------------------------------------------------------------
# register_host with embedded key
# ---------------------------------------------------------------------------


class TestRegisterHostEmbeddedKey:
    def test_embedded_key_is_encrypted_in_db(self, svc, settings, tmp_path):
        from cryptography.fernet import Fernet
        from vm_provisioning_adapter.crypto import decrypt_key

        key = Fernet.generate_key().decode()
        settings.ssh_decryption_key = key

        raw_pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nfakedata\n-----END OPENSSH PRIVATE KEY-----\n"
        body = HostCreate(
            name="enc-host",
            kvm_host="1.2.3.4",
            ssh_user="ubuntu",
            ssh_key_type="embedded",
            ssh_key_value=raw_pem,
            gpu_count=0,
        )
        host = svc.register_host(body)

        # The stored value must not be the plaintext
        assert host.ssh_key_value != raw_pem
        # But it must be decryptable back to the plaintext
        assert decrypt_key(host.ssh_key_value, key) == raw_pem

    def test_embedded_key_decryptable_via_get_decrypted_key_value(self, svc, settings):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        settings.ssh_decryption_key = key
        raw_pem = "FAKE PEM CONTENT"

        body = HostCreate(
            name="enc2",
            kvm_host="5.6.7.8",
            ssh_user="root",
            ssh_key_type="embedded",
            ssh_key_value=raw_pem,
        )
        host = svc.register_host(body)
        assert svc.get_decrypted_key_value(host) == raw_pem


# ---------------------------------------------------------------------------
# render_inventory_ini
# ---------------------------------------------------------------------------


class TestRenderInventoryIni:
    def test_emits_kvm_hosts_group_header(self, svc):
        hosts = [
            Host(name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
                 ssh_key_type="path", ssh_key_value="/key", gpu_count=0, enabled=True),
        ]
        ini = svc.render_inventory_ini(hosts)
        assert ini.startswith("[kvm_hosts]")

    def test_path_host_writes_key_path_directly(self, svc):
        hosts = [
            Host(name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
                 ssh_key_type="path", ssh_key_value="/home/appuser/.ssh/id_ed25519",
                 gpu_count=0, enabled=True),
        ]
        ini = svc.render_inventory_ini(hosts)
        assert "ansible_ssh_private_key_file=/home/appuser/.ssh/id_ed25519" in ini

    def test_embedded_host_uses_sentinel(self, svc):
        hosts = [
            Host(name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
                 ssh_key_type="embedded", ssh_key_value="ENCRYPTED",
                 gpu_count=0, enabled=True),
        ]
        ini = svc.render_inventory_ini(hosts)
        assert "__embedded_key_kvm1__" in ini

    def test_correct_variable_names(self, svc):
        hosts = [
            Host(name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
                 ssh_key_type="path", ssh_key_value="/key", gpu_count=0, enabled=True),
        ]
        ini = svc.render_inventory_ini(hosts)
        assert "ansible_host=10.0.0.1" in ini
        assert "ansible_user=ubuntu" in ini

    def test_multiple_hosts_all_present(self, svc):
        hosts = [
            Host(name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
                 ssh_key_type="path", ssh_key_value="/key", gpu_count=0, enabled=True),
            Host(name="ww2", kvm_host="10.0.0.2", ssh_user="root",
                 ssh_key_type="path", ssh_key_value="/key", gpu_count=1, enabled=True),
        ]
        ini = svc.render_inventory_ini(hosts)
        assert "kvm1" in ini
        assert "ww2" in ini


# ---------------------------------------------------------------------------
# list_hosts enabled_only filter
# ---------------------------------------------------------------------------


class TestListHosts:
    def test_enabled_only_excludes_disabled(self, svc):
        body = HostCreate(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key",
        )
        svc.register_host(body)
        svc.disable_host("kvm1")

        enabled = svc.list_hosts(enabled_only=True)
        assert all(h.enabled for h in enabled)
        assert not any(h.name == "kvm1" for h in enabled)

    def test_enabled_only_false_includes_disabled(self, svc):
        body = HostCreate(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key",
        )
        svc.register_host(body)
        svc.disable_host("kvm1")

        all_hosts = svc.list_hosts(enabled_only=False)
        assert any(h.name == "kvm1" for h in all_hosts)

    def test_search_filter(self, svc):
        for name, ip in [("alpha", "10.0.0.1"), ("beta", "10.0.0.2"), ("gamma", "10.0.0.3")]:
            svc.register_host(HostCreate(
                name=name, kvm_host=ip, ssh_user="ubuntu",
                ssh_key_type="path", ssh_key_value="/key",
            ))
        result = svc.list_hosts(search="alph")
        assert len(result) == 1
        assert result[0].name == "alpha"


# ---------------------------------------------------------------------------
# pool_id assignment
# ---------------------------------------------------------------------------


class TestHostPoolAssignment:
    def test_register_host_defaults_to_default_pool(self, svc):
        host = svc.register_host(HostCreate(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key",
        ))
        assert host.pool_id == DEFAULT_POOL_ID

    def test_register_host_with_explicit_pool_id(self, svc, session_factory):
        with session_factory() as db:
            db.add(ResourcePool(
                id="hetzner-eu", label="Hetzner EU", provider="ansible",
                enabled=True, policy_tags={},
            ))
            db.commit()

        host = svc.register_host(HostCreate(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key", pool_id="hetzner-eu",
        ))
        assert host.pool_id == "hetzner-eu"

    def test_register_host_with_nonexistent_pool_id_raises(self, svc):
        with pytest.raises(ValueError):
            svc.register_host(HostCreate(
                name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
                ssh_key_type="path", ssh_key_value="/key", pool_id="does-not-exist",
            ))

    def test_update_host_reassigns_pool(self, svc, session_factory):
        svc.register_host(HostCreate(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key",
        ))
        with session_factory() as db:
            db.add(ResourcePool(
                id="hetzner-eu", label="Hetzner EU", provider="ansible",
                enabled=True, policy_tags={},
            ))
            db.commit()

        updated = svc.update_host("kvm1", HostUpdate(pool_id="hetzner-eu"))
        assert updated.pool_id == "hetzner-eu"

    def test_update_host_with_nonexistent_pool_id_raises(self, svc):
        svc.register_host(HostCreate(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key",
        ))
        with pytest.raises(ValueError):
            svc.update_host("kvm1", HostUpdate(pool_id="does-not-exist"))


class TestGpuModel:
    def test_register_host_stores_gpu_model(self, svc):
        host = svc.register_host(HostCreate(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key",
            gpu_count=8, gpu_model="H100",
        ))
        assert host.gpu_model == "H100"

    def test_register_host_gpu_model_defaults_to_none(self, svc):
        host = svc.register_host(HostCreate(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key",
        ))
        assert host.gpu_model is None

    def test_update_host_sets_gpu_model(self, svc):
        svc.register_host(HostCreate(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key",
        ))
        updated = svc.update_host("kvm1", HostUpdate(gpu_model="A100"))
        assert updated.gpu_model == "A100"

    def test_update_host_omitting_gpu_model_leaves_it_unchanged(self, svc):
        svc.register_host(HostCreate(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key", gpu_model="H100",
        ))
        updated = svc.update_host("kvm1", HostUpdate(kvm_host="10.0.0.2"))
        assert updated.gpu_model == "H100"
