"""Unit tests for AnsiblePoolConfigHandler.

External boundary: SQLAlchemy with an in-memory SQLite DB (not mocked),
matching test_host_service.py's rationale -- a deterministic dependency
with no network I/O.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import create_session_factory
from compute_provisioning_service.db.models import Base
from market_resource_pools import ResourcePool
from vm_provisioning_adapter.services.ansible_pool_config_handler import (
    AnsiblePoolConfigHandler,
)


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
    with Session(engine) as session:
        session.add(ResourcePool(
            id="pool-a", label="Pool A", provider="ansible",
            enabled=True, policy_tags={},
        ))
        session.commit()
    return engine


@pytest.fixture
def session_factory(db_engine):
    return create_session_factory(db_engine)


@pytest.fixture
def handler() -> AnsiblePoolConfigHandler:
    return AnsiblePoolConfigHandler()


_BASE_CONFIG = {
    "playbook_path": "/opt/playbooks/vm-operations.yaml",
    "requirement_delegate": "vm_management_v1",
    "extra_vars": {},
}


# ---------------------------------------------------------------------------
# validate_config_problems -- VM size default fields
# ---------------------------------------------------------------------------

class TestValidateVmSizeDefaults:
    def test_all_three_fields_optional_and_absent_by_default(self, handler):
        normalized, problems = handler.validate_config_problems(_BASE_CONFIG)
        assert problems == ()
        assert normalized["default_vm_ram"] is None
        assert normalized["default_vm_vcpus"] is None
        assert normalized["default_vm_disk_size"] is None

    def test_explicit_none_is_accepted_as_absent(self, handler):
        config = {
            **_BASE_CONFIG,
            "default_vm_ram": None,
            "default_vm_vcpus": None,
            "default_vm_disk_size": None,
        }
        normalized, problems = handler.validate_config_problems(config)
        assert problems == ()
        assert normalized["default_vm_ram"] is None

    def test_accepts_a_full_valid_set(self, handler):
        config = {
            **_BASE_CONFIG,
            "default_vm_ram": 65536,
            "default_vm_vcpus": 16,
            "default_vm_disk_size": "500G",
        }
        normalized, problems = handler.validate_config_problems(config)
        assert problems == ()
        assert normalized["default_vm_ram"] == 65536
        assert normalized["default_vm_vcpus"] == 16
        assert normalized["default_vm_disk_size"] == "500G"

    @pytest.mark.parametrize("field", ["default_vm_ram", "default_vm_vcpus"])
    @pytest.mark.parametrize("bad_value", [0, -1, "16", 16.0, True])
    def test_rejects_non_positive_or_non_int_ram_and_vcpus(self, handler, field, bad_value):
        config = {**_BASE_CONFIG, field: bad_value}
        normalized, problems = handler.validate_config_problems(config)
        assert normalized is None
        assert any(p.path == field and p.code == "invalid_type" for p in problems)

    @pytest.mark.parametrize("bad_value", ["", "   ", 500, ["500G"]])
    def test_rejects_empty_or_non_string_disk_size(self, handler, bad_value):
        config = {**_BASE_CONFIG, "default_vm_disk_size": bad_value}
        normalized, problems = handler.validate_config_problems(config)
        assert normalized is None
        assert any(
            p.path == "default_vm_disk_size" and p.code == "invalid_type" for p in problems
        )

    def test_still_rejects_unknown_fields_alongside_valid_size_defaults(self, handler):
        """Confirms the allowlist extension didn't accidentally loosen the
        existing unknown-field rejection."""
        config = {**_BASE_CONFIG, "default_vm_ram": 65536, "ssh_key": "nope"}
        normalized, problems = handler.validate_config_problems(config)
        assert normalized is None
        assert any(p.path == "ssh_key" and p.code == "unknown_field" for p in problems)


# ---------------------------------------------------------------------------
# read_config / replace_config -- persistence round-trip
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_read_config_on_pool_with_no_row_returns_empty_dict(self, handler, session_factory):
        with session_factory() as db:
            assert handler.read_config(db, "pool-a") == {}

    def test_replace_then_read_round_trips_size_defaults(self, handler, session_factory):
        config = {
            **_BASE_CONFIG,
            "default_vm_ram": 65536,
            "default_vm_vcpus": 16,
            "default_vm_disk_size": "500G",
        }
        with session_factory() as db:
            handler.replace_config(db, "pool-a", config)
            db.commit()

        with session_factory() as db:
            read_back = handler.read_config(db, "pool-a")
        assert read_back["default_vm_ram"] == 65536
        assert read_back["default_vm_vcpus"] == 16
        assert read_back["default_vm_disk_size"] == "500G"

    def test_replace_with_no_size_defaults_persists_as_null(self, handler, session_factory):
        with session_factory() as db:
            handler.replace_config(db, "pool-a", _BASE_CONFIG)
            db.commit()

        with session_factory() as db:
            read_back = handler.read_config(db, "pool-a")
        assert read_back["default_vm_ram"] is None
        assert read_back["default_vm_vcpus"] is None
        assert read_back["default_vm_disk_size"] is None

    def test_replace_updates_an_existing_row_including_clearing_a_default(
        self, handler, session_factory,
    ):
        """A pool previously configured with a size default, then
        re-replaced without one, must actually clear it -- not retain the
        old value because replace_config only touched changed fields."""
        with session_factory() as db:
            handler.replace_config(
                db, "pool-a", {**_BASE_CONFIG, "default_vm_ram": 65536},
            )
            db.commit()

        with session_factory() as db:
            handler.replace_config(db, "pool-a", _BASE_CONFIG)
            db.commit()

        with session_factory() as db:
            read_back = handler.read_config(db, "pool-a")
        assert read_back["default_vm_ram"] is None

    def test_delete_config_removes_size_defaults_with_the_row(self, handler, session_factory):
        with session_factory() as db:
            handler.replace_config(
                db, "pool-a", {**_BASE_CONFIG, "default_vm_ram": 65536},
            )
            db.commit()
            handler.delete_config(db, "pool-a")
            db.commit()

        with session_factory() as db:
            assert handler.read_config(db, "pool-a") == {}
