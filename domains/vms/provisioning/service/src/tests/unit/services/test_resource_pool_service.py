"""
Unit tests for ResourcePoolService.

Scope (per ARCHITECTURE.md — Unit Tests jurisdiction):
  - CRUD: create/get/list/replace/patch/enable/disable
  - Tag-filtered lookup
  - Provider config validation (ansible required fields; unknown providers rejected)
  - YAML import: created/updated/disabled/unchanged diff, idempotency,
    validate_only (no writes)

External boundary: SQLAlchemy with an in-memory SQLite DB (not mocked) —
consistent with test_host_service.py's rationale.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from db.database import create_session_factory
from db.models import Base
from compute_provisioning import PoolCreate, PoolReplace, PoolUpdate
from services.resource_pool_service import (
    PoolAlreadyExistsError,
    PoolNotFoundError,
    PoolValidationError,
    ResourcePoolService,
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
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def session_factory(db_engine):
    return create_session_factory(db_engine)


@pytest.fixture
def svc(session_factory):
    return ResourcePoolService(session_factory=session_factory)


_ANSIBLE_CONFIG = {
    "playbook_path": "playbooks/vm-operations.yaml",
    "inventory_group": "kvm_hosts",
}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCreatePool:
    def test_create_returns_pool_with_provider_config(self, svc):
        pool = svc.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        assert pool.id == "hetzner-eu"
        assert pool.enabled is True
        assert pool.provider_config["playbook_path"] == _ANSIBLE_CONFIG["playbook_path"]
        assert pool.provider_config["extra_vars"] == {}

    def test_create_duplicate_id_raises(self, svc):
        svc.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        with pytest.raises(PoolAlreadyExistsError):
            svc.create_pool(
                PoolCreate(
                    id="hetzner-eu",
                    label="Hetzner EU (again)",
                    provider="ansible",
                    provider_config=_ANSIBLE_CONFIG,
                )
            )

    def test_create_unknown_provider_raises(self, svc):
        with pytest.raises(PoolValidationError):
            svc.create_pool(
                PoolCreate(
                    id="k8s-1",
                    label="K8s Cluster 1",
                    provider="kubernetes",
                    provider_config={"namespace": "default"},
                )
            )

    def test_create_ansible_missing_playbook_path_raises(self, svc):
        with pytest.raises(PoolValidationError):
            svc.create_pool(
                PoolCreate(
                    id="hetzner-eu",
                    label="Hetzner EU",
                    provider="ansible",
                    provider_config={"inventory_group": "kvm_hosts"},
                )
            )

    def test_create_ansible_missing_inventory_group_raises(self, svc):
        with pytest.raises(PoolValidationError):
            svc.create_pool(
                PoolCreate(
                    id="hetzner-eu",
                    label="Hetzner EU",
                    provider="ansible",
                    provider_config={"playbook_path": "playbooks/vm-operations.yaml"},
                )
            )


class TestGetAndListPools:
    def test_get_missing_returns_none(self, svc):
        assert svc.get_pool("does-not-exist") is None

    def test_get_returns_created_pool(self, svc):
        svc.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        pool = svc.get_pool("hetzner-eu")
        assert pool is not None
        assert pool.label == "Hetzner EU"

    def test_list_enabled_only_excludes_disabled(self, svc):
        svc.create_pool(
            PoolCreate(
                id="pool-a",
                label="A",
                provider="ansible",
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        svc.create_pool(
            PoolCreate(
                id="pool-b",
                label="B",
                provider="ansible",
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        svc.disable_pool("pool-b")

        enabled = svc.list_pools(enabled_only=True)
        assert {p.id for p in enabled} == {"pool-a"}

    def test_list_tag_filter(self, svc):
        svc.create_pool(
            PoolCreate(
                id="pool-eu",
                label="EU",
                provider="ansible",
                policy_tags={"region": "eu"},
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        svc.create_pool(
            PoolCreate(
                id="pool-us",
                label="US",
                provider="ansible",
                policy_tags={"region": "us"},
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        result = svc.list_pools(tag_filter={"region": "eu"})
        assert {p.id for p in result} == {"pool-eu"}


class TestUpdatePool:
    def test_patch_updates_label_only(self, svc):
        svc.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        updated = svc.update_pool("hetzner-eu", PoolUpdate(label="Hetzner EU Central"))
        assert updated.label == "Hetzner EU Central"
        assert updated.provider == "ansible"

    def test_replace_requires_full_desired_state(self, svc):
        svc.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        replaced = svc.replace_pool(
            "hetzner-eu",
            PoolReplace(
                label="Replacement",
                provider="ansible",
                enabled=False,
                policy_tags={},
                provider_config=_ANSIBLE_CONFIG,
            ),
        )
        assert replaced.enabled is False

    def test_update_missing_pool_raises(self, svc):
        with pytest.raises(PoolNotFoundError):
            svc.update_pool("does-not-exist", PoolUpdate(label="X"))

    def test_update_provider_config_revalidates(self, svc):
        svc.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        with pytest.raises(PoolValidationError):
            svc.update_pool(
                "hetzner-eu", PoolUpdate(provider_config={"extra_vars": {}})
            )

    def test_update_provider_config_persists(self, svc):
        svc.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        updated = svc.update_pool(
            "hetzner-eu",
            PoolUpdate(
                provider_config={
                    "playbook_path": "playbooks/new.yaml",
                    "inventory_group": "kvm_hosts",
                },
            ),
        )
        assert updated.provider_config["playbook_path"] == "playbooks/new.yaml"


class TestEnableDisablePool:
    def test_disable_then_enable(self, svc):
        svc.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        disabled = svc.disable_pool("hetzner-eu")
        assert disabled.enabled is False
        enabled = svc.enable_pool("hetzner-eu")
        assert enabled.enabled is True

    def test_disable_missing_pool_raises(self, svc):
        with pytest.raises(PoolNotFoundError):
            svc.disable_pool("does-not-exist")

    def test_default_pool_cannot_be_disabled(self, svc):
        svc.create_pool(
            PoolCreate(
                id="default",
                label="Default Pool",
                provider="ansible",
                provider_config=_ANSIBLE_CONFIG,
            )
        )

        with pytest.raises(PoolValidationError, match="cannot be disabled"):
            svc.disable_pool("default")


# ---------------------------------------------------------------------------
# YAML import / validate
# ---------------------------------------------------------------------------

_YAML = """
pools:
  - id: default
    label: Default Pool
    provider: ansible
    enabled: true
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
  - id: hetzner-eu-central
    label: Hetzner EU Central
    provider: ansible
    policy_tags:
      region: eu
    provider_config:
      playbook_path: playbooks/vm-operations-frp.yaml
      inventory_group: kvm_hosts_eu
      extra_vars:
        frp_server_addr: frp.eu.example.com
  - id: equinix-us-west
    label: Equinix US West
    provider: ansible
    policy_tags:
      region: us-west
    provider_config:
      playbook_path: playbooks/vm-operations-direct.yaml
      inventory_group: kvm_hosts_usw
"""


class TestImportPools:
    def test_fresh_import_creates_all(self, svc):
        diff = svc.import_pools(_YAML)
        assert set(diff.created) == {"default", "hetzner-eu-central", "equinix-us-west"}
        assert diff.updated == []
        assert svc.get_pool("hetzner-eu-central") is not None

    def test_reimporting_same_yaml_is_unchanged(self, svc):
        svc.import_pools(_YAML)
        diff = svc.import_pools(_YAML)
        assert diff.created == []
        assert diff.updated == []
        assert set(diff.unchanged) == {
            "default",
            "hetzner-eu-central",
            "equinix-us-west",
        }

    def test_changed_field_reports_updated(self, svc):
        svc.import_pools(_YAML)
        changed_yaml = _YAML.replace("Hetzner EU Central", "Hetzner EU Central (v2)")
        diff = svc.import_pools(changed_yaml)
        assert diff.updated == ["hetzner-eu-central"]
        assert svc.get_pool("hetzner-eu-central").label == "Hetzner EU Central (v2)"

    def test_pool_missing_from_reimport_is_disabled_not_deleted(self, svc):
        svc.import_pools(_YAML)
        one_pool_yaml = """
pools:
  - id: default
    label: Default Pool
    provider: ansible
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
  - id: hetzner-eu-central
    label: Hetzner EU Central
    provider: ansible
    provider_config:
      playbook_path: playbooks/vm-operations-frp.yaml
      inventory_group: kvm_hosts_eu
"""
        diff = svc.import_pools(one_pool_yaml)
        assert diff.disabled == ["equinix-us-west"]
        # Still resolvable, just disabled — not hard-deleted.
        pool = svc.get_pool("equinix-us-west")
        assert pool is not None
        assert pool.enabled is False

    def test_invalid_entry_rejects_entire_document(self, svc):
        mixed_yaml = """
pools:
  - id: default
    label: Default Pool
    provider: ansible
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
  - id: good-pool
    label: Good Pool
    provider: ansible
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
  - id: bad-pool
    label: Bad Pool
    provider: kubernetes
    provider_config: {}
"""
        with pytest.raises(PoolValidationError):
            svc.import_pools(mixed_yaml)
        assert svc.list_pools() == []

    def test_duplicate_ids_reject_entire_document(self, svc):
        duplicate_yaml = """
pools:
  - id: default
    label: Default Pool
    provider: ansible
    provider_config:
      playbook_path: a.yaml
      inventory_group: all
  - id: default
    label: Duplicate
    provider: ansible
    provider_config:
      playbook_path: b.yaml
      inventory_group: all
"""
        with pytest.raises(PoolValidationError, match="duplicate pool id"):
            svc.import_pools(duplicate_yaml)
        assert svc.list_pools() == []

    def test_validate_only_computes_diff_without_writing(self, svc):
        response = svc.validate_pools(_YAML)
        assert response.valid is True
        assert response.problems == []
        assert response.diff is not None
        assert set(response.diff.created) == {
            "default",
            "hetzner-eu-central",
            "equinix-us-west",
        }
        assert svc.list_pools() == []

    def test_validate_rejects_disabled_default_pool(self, svc):
        response = svc.validate_pools(
            _YAML.replace("enabled: true", "enabled: false", 1)
        )

        assert response.valid is False
        assert response.diff is None
        assert "default_pool_disabled" in {
            problem.code for problem in response.problems
        }

    def test_validate_accumulates_all_detectable_problems(self, svc):
        response = svc.validate_pools("""
unknown_root: true
pools:
  - id: default
    label: ""
    provider: ansible
    enabld: true
    provider_config:
      unexpected: value
  - id: default
    label: Duplicate
    provider: missing-provider
    enabled: nope
    policy_tags: []
    provider_config: {}
""")
        assert response.valid is False
        assert response.diff is None
        codes = [problem.code for problem in response.problems]
        assert codes.count("unknown_field") >= 2
        assert "duplicate_id" in codes
        assert "required_field" in codes
        assert "unknown_provider" in codes
        assert codes.count("invalid_type") >= 2
        assert len(response.problems) >= 8

    def test_validate_reports_invalid_yaml_as_response(self, svc):
        response = svc.validate_pools("not: valid: yaml: [")
        assert response.valid is False
        assert response.diff is None
        assert response.problems[0].code == "invalid_yaml"

    def test_invalid_yaml_raises(self, svc):
        with pytest.raises(PoolValidationError):
            svc.import_pools("not: valid: yaml: [")

    def test_missing_pools_key_raises(self, svc):
        with pytest.raises(PoolValidationError):
            svc.import_pools("other_key: []")


class _StubPoolConfigHandler:
    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.configs: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.replaced: list[str] = []

    def validate_config(self, config):
        return dict(config)

    def validate_config_problems(self, config):
        return dict(config), ()

    def read_config(self, db, pool_id: str):
        return dict(self.configs.get(pool_id, {}))

    def replace_config(self, db, pool_id: str, config):
        self.replaced.append(pool_id)
        self.configs[pool_id] = dict(config)

    def delete_config(self, db, pool_id: str):
        self.deleted.append(pool_id)
        self.configs.pop(pool_id, None)


def test_replace_provider_cleans_up_old_provider_config(session_factory):
    old_handler = _StubPoolConfigHandler("old")
    new_handler = _StubPoolConfigHandler("new")
    service = ResourcePoolService(
        session_factory=session_factory,
        handlers={"old": old_handler, "new": new_handler},
    )
    service.create_pool(
        PoolCreate(
            id="switchable",
            label="Switchable",
            provider="old",
            provider_config={"old_setting": True},
        )
    )

    replaced = service.replace_pool(
        "switchable",
        PoolReplace(
            label="Switched",
            provider="new",
            enabled=True,
            policy_tags={},
            provider_config={"new_setting": True},
        ),
    )

    assert replaced.provider == "new"
    assert old_handler.deleted == ["switchable"]
    assert "switchable" not in old_handler.configs
    assert new_handler.replaced == ["switchable"]
    assert new_handler.configs["switchable"] == {"new_setting": True}
