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

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.database import create_session_factory
from db.models import Base, Host
from models.host_model import HostCreate, HostUpdate
from services.host_service import HostService, _parse_ini


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
    Base.metadata.create_all(bind=engine)
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
            "ww1  ansible_host=10.0.0.1  ansible_user=ubuntu  "
            "ansible_ssh_private_key_file=/home/user/.ssh/id_ed25519\n"
        )
        result = _parse_ini(ini)
        assert len(result) == 1
        assert result[0]["name"] == "ww1"
        assert result[0]["kvm_host"] == "10.0.0.1"
        assert result[0]["ssh_user"] == "ubuntu"
        assert result[0]["ansible_ssh_private_key_file"] == "/home/user/.ssh/id_ed25519"

    def test_parses_multiple_hosts(self):
        ini = (
            "[kvm_hosts]\n"
            "ww1  ansible_host=10.0.0.1  ansible_user=ubuntu\n"
            "ww2  ansible_host=10.0.0.2  ansible_user=root\n"
        )
        result = _parse_ini(ini)
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert names == {"ww1", "ww2"}

    def test_skips_group_headers_and_comments(self):
        ini = (
            "# this is a comment\n"
            "[kvm_hosts]\n"
            "ww1  ansible_host=10.0.0.1  ansible_user=ubuntu\n"
            "[other_group]\n"
            "other  ansible_host=9.9.9.9  ansible_user=nobody\n"
        )
        result = _parse_ini(ini)
        # Both ww1 and other should be parsed (group membership is not filtered)
        names = {r["name"] for r in result}
        assert "ww1" in names

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
        "ww1  ansible_host=10.0.0.1  ansible_user=ubuntu  "
        "ansible_ssh_private_key_file=/home/user/.ssh/id_ed25519\n"
        "ww2  ansible_host=10.0.0.2  ansible_user=root  "
        "ansible_ssh_private_key_file=/home/user/.ssh/id_ed25519\n"
    )

    def test_inserts_correct_rows(self, svc):
        hosts = svc.seed_from_ini(self._INI, ssh_key_type="path")
        assert len(hosts) == 2
        names = {h.name for h in hosts}
        assert names == {"ww1", "ww2"}

    def test_stores_key_path_verbatim(self, svc):
        hosts = svc.seed_from_ini(self._INI, ssh_key_type="path")
        ww1 = next(h for h in hosts if h.name == "ww1")
        assert ww1.ssh_key_value == "/home/user/.ssh/id_ed25519"
        assert ww1.ssh_key_type == "path"

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
            "ww1  ansible_host=10.9.9.9  ansible_user=newuser  "
            "ansible_ssh_private_key_file=/home/user/.ssh/id_ed25519\n"
        )
        svc.seed_from_ini(updated_ini, ssh_key_type="path")
        ww1 = svc.get_host("ww1")
        assert ww1.kvm_host == "10.9.9.9"
        assert ww1.ssh_user == "newuser"

    def test_absent_hosts_not_touched(self, svc):
        """Append-only: hosts not in the new INI are left as-is."""
        svc.seed_from_ini(self._INI, ssh_key_type="path")
        ini_ww2_only = (
            "[kvm_hosts]\n"
            "ww2  ansible_host=10.0.0.2  ansible_user=root  "
            "ansible_ssh_private_key_file=/home/user/.ssh/id_ed25519\n"
        )
        svc.seed_from_ini(ini_ww2_only, ssh_key_type="path")
        ww1 = svc.get_host("ww1")
        assert ww1 is not None
        assert ww1.enabled is True


# ---------------------------------------------------------------------------
# register_host with embedded key
# ---------------------------------------------------------------------------


class TestRegisterHostEmbeddedKey:
    def test_embedded_key_is_encrypted_in_db(self, svc, settings, tmp_path):
        from cryptography.fernet import Fernet
        from crypto import decrypt_key

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
            Host(name="ww1", kvm_host="10.0.0.1", ssh_user="ubuntu",
                 ssh_key_type="path", ssh_key_value="/key", gpu_count=0, enabled=True),
        ]
        ini = svc.render_inventory_ini(hosts)
        assert ini.startswith("[kvm_hosts]")

    def test_path_host_writes_key_path_directly(self, svc):
        hosts = [
            Host(name="ww1", kvm_host="10.0.0.1", ssh_user="ubuntu",
                 ssh_key_type="path", ssh_key_value="/home/appuser/.ssh/id_ed25519",
                 gpu_count=0, enabled=True),
        ]
        ini = svc.render_inventory_ini(hosts)
        assert "ansible_ssh_private_key_file=/home/appuser/.ssh/id_ed25519" in ini

    def test_embedded_host_uses_sentinel(self, svc):
        hosts = [
            Host(name="ww1", kvm_host="10.0.0.1", ssh_user="ubuntu",
                 ssh_key_type="embedded", ssh_key_value="ENCRYPTED",
                 gpu_count=0, enabled=True),
        ]
        ini = svc.render_inventory_ini(hosts)
        assert "__embedded_key_ww1__" in ini

    def test_correct_variable_names(self, svc):
        hosts = [
            Host(name="ww1", kvm_host="10.0.0.1", ssh_user="ubuntu",
                 ssh_key_type="path", ssh_key_value="/key", gpu_count=0, enabled=True),
        ]
        ini = svc.render_inventory_ini(hosts)
        assert "ansible_host=10.0.0.1" in ini
        assert "ansible_user=ubuntu" in ini

    def test_multiple_hosts_all_present(self, svc):
        hosts = [
            Host(name="ww1", kvm_host="10.0.0.1", ssh_user="ubuntu",
                 ssh_key_type="path", ssh_key_value="/key", gpu_count=0, enabled=True),
            Host(name="ww2", kvm_host="10.0.0.2", ssh_user="root",
                 ssh_key_type="path", ssh_key_value="/key", gpu_count=1, enabled=True),
        ]
        ini = svc.render_inventory_ini(hosts)
        assert "ww1" in ini
        assert "ww2" in ini


# ---------------------------------------------------------------------------
# list_hosts enabled_only filter
# ---------------------------------------------------------------------------


class TestListHosts:
    def test_enabled_only_excludes_disabled(self, svc):
        body = HostCreate(
            name="ww1", kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key",
        )
        svc.register_host(body)
        svc.disable_host("ww1")

        enabled = svc.list_hosts(enabled_only=True)
        assert all(h.enabled for h in enabled)
        assert not any(h.name == "ww1" for h in enabled)

    def test_enabled_only_false_includes_disabled(self, svc):
        body = HostCreate(
            name="ww1", kvm_host="10.0.0.1", ssh_user="ubuntu",
            ssh_key_type="path", ssh_key_value="/key",
        )
        svc.register_host(body)
        svc.disable_host("ww1")

        all_hosts = svc.list_hosts(enabled_only=False)
        assert any(h.name == "ww1" for h in all_hosts)

    def test_search_filter(self, svc):
        for name, ip in [("alpha", "10.0.0.1"), ("beta", "10.0.0.2"), ("gamma", "10.0.0.3")]:
            svc.register_host(HostCreate(
                name=name, kvm_host=ip, ssh_user="ubuntu",
                ssh_key_type="path", ssh_key_value="/key",
            ))
        result = svc.list_hosts(search="alph")
        assert len(result) == 1
        assert result[0].name == "alpha"
