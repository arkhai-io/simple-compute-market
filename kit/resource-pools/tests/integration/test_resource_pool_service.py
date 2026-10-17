"""
Library integration tests for ResourcePoolService.

Scope (per TESTING.md — a library's public service API against a real
embedded database):
  - CRUD: create/get/list/replace/patch/enable/disable
  - Tag-filtered lookup
  - Provider config validation (required fields; unknown providers rejected)
  - YAML import: created/updated/disabled/unchanged diff, idempotency,
    validate_only (no writes)
  - Active-binding guardrail on disable

External boundary: SQLAlchemy with an in-memory SQLite DB (not mocked).

This package is provider-neutral kit code, so tests use a local
ansible-shaped stub handler rather than the real VM-domain
AnsiblePoolConfigHandler — the "ansible" provider string is just test data
here, not a dependency on the VM service.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from market_resource_pools import (
    PoolAlreadyExistsError,
    PoolNotFoundError,
    PoolValidationError,
    ResourcePoolService,
    PoolConfigValidationProblem,
)
from market_resource_pools_contracts import PoolCreate, PoolReplace, PoolResponse, PoolUpdate
from market_resource_pools.db import Base, ResourcePool
from sqlalchemy.orm import sessionmaker


def create_session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


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


class _AnsibleLikePoolConfigHandler:
    """Test stand-in shaped like the real (VM-domain) Ansible handler.

    Requires playbook_path/inventory_group, same as the real handler — the
    CRUD/validation tests below exercise that shape without importing
    VM-domain code into this kit package's own test suite.
    """

    provider = "ansible"
    _FIELDS = frozenset({"playbook_path", "inventory_group", "extra_vars"})

    def validate_config(self, config):
        normalized, problems = self.validate_config_problems(config)
        if problems:
            raise ValueError(problems[0].message)
        return normalized

    def validate_config_problems(self, config):
        problems: list[PoolConfigValidationProblem] = []
        for field in sorted(set(config) - self._FIELDS):
            problems.append(
                PoolConfigValidationProblem(
                    path=field, code="unknown_field",
                    message=f"unknown ansible provider_config field '{field}'",
                )
            )
        playbook_path = config.get("playbook_path")
        inventory_group = config.get("inventory_group")
        extra_vars = config.get("extra_vars", {})
        if not isinstance(playbook_path, str) or not playbook_path.strip():
            problems.append(
                PoolConfigValidationProblem(
                    path="playbook_path", code="required_field",
                    message="provider_config.playbook_path is required for provider='ansible'",
                )
            )
        if not isinstance(inventory_group, str) or not inventory_group.strip():
            problems.append(
                PoolConfigValidationProblem(
                    path="inventory_group", code="required_field",
                    message="provider_config.inventory_group is required for provider='ansible'",
                )
            )
        if not isinstance(extra_vars, dict):
            problems.append(
                PoolConfigValidationProblem(
                    path="extra_vars", code="invalid_type",
                    message="provider_config.extra_vars must be a mapping",
                )
            )
        if problems:
            return None, tuple(problems)
        return {
            "playbook_path": playbook_path,
            "inventory_group": inventory_group,
            "extra_vars": dict(extra_vars),
        }, ()

    def read_config(self, db, pool_id: str) -> dict[str, Any]:
        row = self._configs.get(pool_id) if hasattr(self, "_configs") else None
        return dict(row) if row else {}

    def read_config_for_execution(self, db, pool_id: str) -> dict[str, Any]:
        # No secrets in this fake, so both reads agree. Implemented anyway: the
        # split is part of the protocol, and a fake providing only half of it
        # would let a caller reach the wrong read without the suite noticing.
        return self.read_config(db, pool_id)

    def replace_config(self, db, pool_id: str, config) -> None:
        if not hasattr(self, "_configs"):
            self._configs: dict[str, dict] = {}
        self._configs[pool_id] = dict(config)

    def delete_config(self, db, pool_id: str) -> None:
        if hasattr(self, "_configs"):
            self._configs.pop(pool_id, None)


@pytest.fixture
def svc(session_factory):
    return ResourcePoolService(
        session_factory=session_factory,
        handlers={"ansible": _AnsibleLikePoolConfigHandler()},
    )


def _declared(tags: dict[str, Any] | None = None) -> dict[str, Any]:
    """Policy tags carrying the declarations every pool write requires.

    A backed pool advertising nothing is valid for any deliverable set, so it
    is the neutral choice for tests about something else.
    """
    return {
        "advertisable_modes": [],
        "capacity_backing": "backed",
        **(tags or {}),
    }


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
                policy_tags=_declared(),
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
                policy_tags=_declared(),
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        with pytest.raises(PoolAlreadyExistsError):
            svc.create_pool(
                PoolCreate(
                    id="hetzner-eu",
                    label="Hetzner EU (again)",
                    provider="ansible",
                    policy_tags=_declared(),
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
                    policy_tags=_declared(),
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
                    policy_tags=_declared(),
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
                    policy_tags=_declared(),
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
                policy_tags=_declared(),
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        pool = svc.get_pool("hetzner-eu")
        assert pool is not None
        assert pool.label == "Hetzner EU"

    def test_get_pool_in_session_uses_caller_session(self, svc, session_factory):
        svc.create_pool(
            PoolCreate(
                id="session-pool",
                label="Session Pool",
                provider="ansible",
                policy_tags=_declared(),
                provider_config=_ANSIBLE_CONFIG,
            )
        )

        with session_factory() as db:
            pool = svc.get_pool_in_session(db, "session-pool")

            assert pool is not None
            assert pool in db
            assert pool.provider_config["playbook_path"] == _ANSIBLE_CONFIG["playbook_path"]
            assert pool.provider_config["extra_vars"] == {}

    def test_list_enabled_only_excludes_disabled(self, svc):
        svc.create_pool(
            PoolCreate(
                id="pool-a",
                label="A",
                provider="ansible",
                policy_tags=_declared(),
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        svc.create_pool(
            PoolCreate(
                id="pool-b",
                label="B",
                provider="ansible",
                policy_tags=_declared(),
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
                policy_tags=_declared({"region": "eu"}),
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        svc.create_pool(
            PoolCreate(
                id="pool-us",
                label="US",
                provider="ansible",
                policy_tags=_declared({"region": "us"}),
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
                policy_tags=_declared(),
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
                policy_tags=_declared(),
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        replaced = svc.replace_pool(
            "hetzner-eu",
            PoolReplace(
                label="Replacement",
                provider="ansible",
                enabled=False,
                policy_tags=_declared(),
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
                policy_tags=_declared(),
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
                policy_tags=_declared(),
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
                policy_tags=_declared(),
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

    def test_default_pool_can_be_disabled(self, svc):
        """Disabling `default` only excludes it from scheduling — it never
        stops being the system-owned pool that exists. (Host
        fallback-to-default-on-omission is a VM-service concern, covered in
        the integration suite, not here.)"""
        svc.create_pool(
            PoolCreate(
                id="default",
                label="Default Pool",
                provider="ansible",
                policy_tags=_declared(),
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        disabled = svc.disable_pool("default")
        assert disabled.enabled is False
        still_there = svc.get_pool("default")
        assert still_there is not None
        assert still_there.enabled is False

    def test_disabling_pool_is_a_draining_operation(self, svc):
        svc.create_pool(
            PoolCreate(
                id="draining-pool",
                label="Draining",
                provider="ansible",
                policy_tags=_declared(),
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        assert svc.disable_pool("draining-pool").enabled is False


# ---------------------------------------------------------------------------
# YAML import / validate
# ---------------------------------------------------------------------------

_YAML = """
pools:
  - id: default
    label: Default Pool
    provider: ansible
    enabled: true
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
  - id: hetzner-eu-central
    label: Hetzner EU Central
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
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
      advertisable_modes: []
      capacity_backing: backed
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
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
  - id: hetzner-eu-central
    label: Hetzner EU Central
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
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

    def test_import_can_disable_pool_as_draining_operation(self, svc):
        svc.import_pools(_YAML)
        one_pool_yaml = """
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
"""
        diff = svc.import_pools(one_pool_yaml)
        assert "equinix-us-west" in diff.disabled

    def test_invalid_entry_rejects_entire_document(self, svc):
        mixed_yaml = """
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
  - id: good-pool
    label: Good Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
  - id: bad-pool
    label: Bad Pool
    provider: kubernetes
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
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
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
    provider_config:
      playbook_path: a.yaml
      inventory_group: all
  - id: default
    label: Duplicate
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
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

    def test_validate_accepts_disabled_default_pool(self, svc):
        """A disabled `default` in an authoritative document is valid —
        only omitting `default` entirely is rejected
        (test_missing_default_pool_rejected, below)."""
        response = svc.validate_pools(
            _YAML.replace("enabled: true", "enabled: false", 1)
        )
        assert response.valid is True
        assert response.diff is not None

    def test_missing_default_pool_rejected(self, svc):
        no_default_yaml = """
pools:
  - id: hetzner-eu-central
    label: Hetzner EU Central
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
    provider_config:
      playbook_path: playbooks/vm-operations-frp.yaml
      inventory_group: kvm_hosts_eu
"""
        response = svc.validate_pools(no_default_yaml)
        assert response.valid is False
        assert "missing_default_pool" in {p.code for p in response.problems}

    def test_validate_accumulates_all_detectable_problems(self, svc):
        response = svc.validate_pools("""
unknown_root: true
pools:
  - id: default
    label: ""
    provider: ansible
    enabld: true
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
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

    def test_invalid_hold_preference_rejected(self, svc):
        response = svc.validate_pools("""
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
      max_reservation_hold_seconds: -5
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
""")
        assert response.valid is False
        assert response.diff is None
        assert "invalid_hold_preference" in {p.code for p in response.problems}

    def test_valid_hold_preference_accepted(self, svc):
        response = svc.validate_pools("""
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
      max_reservation_hold_seconds: 120
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
""")
        assert response.valid is True
        assert response.diff is not None

    def test_deliverable_modes_projects_through_authoritative_document(self, svc):
        response = svc.validate_pools("""
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
      deliverable_modes: [vm, bare_metal]
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
""")

        assert response.valid is True
        assert response.diff is not None
        svc.import_pools("""
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
      deliverable_modes: [vm, bare_metal]
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
""")
        assert svc.get_pool("default").policy_tags["deliverable_modes"] == [
            "vm",
            "bare_metal",
        ]

    def test_malformed_deliverable_modes_rejected_by_document_validation(self, svc):
        response = svc.validate_pools("""
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
      deliverable_modes: vm
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
""")

        assert response.valid is False
        assert response.diff is None
        assert "invalid_deliverable_modes" in {p.code for p in response.problems}

    def test_invalid_sla_rejected(self, svc):
        response = svc.validate_pools("""
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
      sla: -1
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
""")
        assert response.valid is False
        assert response.diff is None
        assert "invalid_sla_preference" in {p.code for p in response.problems}

    def test_valid_sla_accepted(self, svc):
        response = svc.validate_pools("""
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
      sla: 99.9
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
""")
        assert response.valid is True
        assert response.diff is not None


class TestValidPolicyHintsOnIndividualPoolWrites:
    """Valid advisory hints round-trip through real pool persistence."""

    def test_create_pool_with_valid_hold_succeeds(self, svc):
        pool = svc.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                policy_tags=_declared({"max_reservation_hold_seconds": 60}),
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        assert pool.policy_tags == _declared({"max_reservation_hold_seconds": 60})

    def test_update_pool_omitting_policy_tags_skips_hold_validation(self, svc):
        """update_pool's policy_tags is optional -- omitting it entirely
        must not trigger hold validation against an absent value."""
        svc.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                policy_tags=_declared(),
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        pool = svc.update_pool("hetzner-eu", PoolUpdate(label="Renamed"))
        assert pool.label == "Renamed"

    def test_create_pool_with_valid_sla_succeeds(self, svc):
        pool = svc.create_pool(
            PoolCreate(
                id="hetzner-eu",
                label="Hetzner EU",
                provider="ansible",
                policy_tags=_declared({"sla": 99.9}),
                provider_config=_ANSIBLE_CONFIG,
            )
        )
        assert pool.policy_tags == _declared({"sla": 99.9})


class TestListingShapesPersistenceAndDocuments:
    """Shapes persist verbatim and raw documents retain structured refusals."""

    VALID = {"listing_shapes": {"vm": [{"gpu": {"count": 1, "model": "H100"}}]}}

    def _create(self, svc, tags):
        return svc.create_pool(
            PoolCreate(
                id="shaped",
                label="Shaped",
                provider="ansible",
                policy_tags=_declared(tags),
                provider_config=_ANSIBLE_CONFIG,
            )
        )

    def test_create_accepts_well_formed_shapes(self, svc):
        assert self._create(svc, self.VALID).policy_tags == _declared(self.VALID)

    def test_bulk_import_refuses_with_path_and_code(self, svc):
        response = svc.validate_pools("""
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
      listing_shapes:
        vm: []
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
""")
        assert response.valid is False
        assert response.diff is None
        refused = [p for p in response.problems if p.code == "invalid_listing_shapes"]
        assert refused and refused[0].path.endswith(".policy_tags.listing_shapes")


class TestListingShapeConstraintsPersistenceAndDocuments:
    """Constrained shapes persist verbatim; malformed documents carry paths."""

    VALID = {"listing_shapes": {"vm": [
        {"gpu": {"model": "H100", "count": {"offer": 1, "max": 4}}, "memory": {"gib": {"max": 512}}},
    ]}}

    def _create(self, svc, tags):
        return svc.create_pool(
            PoolCreate(
                id="shaped",
                label="Shaped",
                provider="ansible",
                policy_tags=_declared(tags),
                provider_config=_ANSIBLE_CONFIG,
            )
        )

    def test_create_keeps_a_constrained_list_verbatim(self, svc):
        assert self._create(svc, self.VALID).policy_tags == _declared(self.VALID)

    def test_bulk_import_refuses_a_conflicting_duplicate_naming_both_entries(self, svc):
        response = svc.validate_pools("""
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
      listing_shapes:
        vm:
          - gpu: {model: H100, count: {offer: 1, max: 4}}
          - gpu: {model: H100, count: {offer: 1, max: 8}}
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
""")
        assert response.valid is False
        assert response.diff is None
        refused = [p for p in response.problems if p.code == "invalid_listing_shapes"]
        assert len(refused) == 1
        assert refused[0].path.endswith(".policy_tags.listing_shapes")
        assert "vm[0, 1]" in refused[0].message

    def test_bulk_import_refuses_a_malformed_constraint(self, svc):
        response = svc.validate_pools("""
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
      listing_shapes:
        vm:
          - gpu: {model: H100, count: {offer: 1, step: 2}}
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
""")
        assert response.valid is False
        assert response.diff is None
        assert [p.code for p in response.problems] == ["invalid_listing_shapes"]


class TestAskingRatesPersistenceAndDocuments:
    """Asking rates persist verbatim and documents report structural problems."""

    VALID = {"asking_rates": {"vm": [{"shape": {"gpu": {"count": 1, "model": "H100"}},
                                      "amount": "2.10", "asset": "usd", "period": "hour"}]}}

    def _create(self, svc, tags):
        return svc.create_pool(
            PoolCreate(
                id="priced",
                label="Priced",
                provider="ansible",
                policy_tags=_declared(tags),
                provider_config=_ANSIBLE_CONFIG,
            )
        )

    def test_create_keeps_a_valid_declaration_verbatim(self, svc):
        assert self._create(svc, self.VALID).policy_tags == _declared(self.VALID)

    def test_bulk_import_refuses_with_path_and_code(self, svc):
        response = svc.validate_pools("""
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
      asking_rates:
        vm:
          - {shape: {gpu: {count: 1, model: H100}}, amount: "-1", asset: usd, period: hour}
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
""")
        assert response.valid is False
        assert response.diff is None
        refused = [p for p in response.problems if p.code == "invalid_asking_rates"]
        assert refused and refused[0].path.endswith(".policy_tags.asking_rates")


class TestPricingRatesPersistenceAndDocuments:
    """Pricing persists verbatim and raw documents retain structured refusals."""

    VALID = {"pricing": {
        "gpu": {"H100": {"rates": [{"asset": "usd", "rate": "2", "per": "hour"}]}},
        "memory": {"rates": [{"asset": "usd", "rate": "0.05", "per": "hour"}]},
    }}

    def _create(self, svc, tags):
        return svc.create_pool(
            PoolCreate(
                id="priced",
                label="Priced",
                provider="ansible",
                policy_tags=_declared(tags),
                provider_config=_ANSIBLE_CONFIG,
            )
        )

    def test_create_keeps_a_valid_declaration_verbatim(self, svc):
        assert self._create(svc, self.VALID).policy_tags == _declared(self.VALID)

    def test_bulk_import_refuses_with_path_and_code(self, svc):
        response = svc.validate_pools("""
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      advertisable_modes: []
      capacity_backing: backed
      pricing:
        cpu:
          rates:
            - {asset: usd, rate: "0.5", per: hour}
            - {asset: usd, rate: "0.6", per: hour}
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
""")
        assert response.valid is False
        refused = [p for p in response.problems if p.code == "invalid_pricing_rates"]
        assert refused and refused[0].path.endswith(".policy_tags.pricing")
        assert "appears more than once" in refused[0].message


def test_malformed_document_hints_accumulate_and_import_changes_nothing(svc):
    for pool_id in ("default", "survivor"):
        svc.create_pool(PoolCreate(
            id=pool_id, label=pool_id, provider="ansible",
            policy_tags=_declared(), provider_config=_ANSIBLE_CONFIG,
        ))
    before = svc.export_pools_yaml()
    document = yaml.safe_dump({"pools": [{
        "id": "default", "label": "Changed", "provider": "ansible",
        "policy_tags": _declared({
            "max_reservation_hold_seconds": -1, "sla": -1,
            "listing_shapes": {"vm": []}, "asking_rates": None,
            "pricing": {"memory": {"rates": "invalid"}},
        }),
        "provider_config": {**_ANSIBLE_CONFIG, "playbook_path": "other.yaml"},
    }]})
    result = svc.validate_pools(document)
    assert result.valid is False
    assert result.diff is None
    assert {(p.path, p.code) for p in result.problems} == {
        ("pools[0].policy_tags.max_reservation_hold_seconds", "invalid_hold_preference"),
        ("pools[0].policy_tags.sla", "invalid_sla_preference"),
        ("pools[0].policy_tags.listing_shapes", "invalid_listing_shapes"),
        ("pools[0].policy_tags.asking_rates", "invalid_asking_rates"),
        ("pools[0].policy_tags.pricing", "invalid_pricing_rates"),
    }
    assert svc.export_pools_yaml() == before
    with pytest.raises(PoolValidationError, match=r"pools\[0\]\.policy_tags"):
        svc.import_pools(document)
    assert svc.export_pools_yaml() == before


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

    def read_config_for_execution(self, db, pool_id):
        # No secrets in this fake, so both reads agree. Implemented anyway: the
        # split is part of the protocol, and a fake that provides only half of
        # it would let a caller reach the wrong read without the suite noticing.
        return self.read_config(db, pool_id)

    def replace_config(self, db, pool_id: str, config):
        self.replaced.append(pool_id)
        self.configs[pool_id] = dict(config)

    def delete_config(self, db, pool_id: str):
        self.deleted.append(pool_id)
        self.configs.pop(pool_id, None)


@pytest.fixture
def recorded_pools(session_factory):
    handlers = {provider: _StubPoolConfigHandler(provider) for provider in ("old", "new")}
    service = ResourcePoolService(session_factory=session_factory, handlers=handlers)
    for pool_id in ("default", "existing", "omitted"):
        service.create_pool(PoolCreate(
            id=pool_id, label=pool_id, provider="old", policy_tags=_declared({"region": "eu"}),
            provider_config={"setting": pool_id},
        ))
    return service, handlers


def _pool_snapshot(service):
    return [PoolResponse.model_validate(pool) for pool in service.list_pools()]


@pytest.mark.parametrize("operation", ["replace", "patch"])
def test_provider_change_refuses_before_any_metadata_or_config_write(recorded_pools, operation):
    service, handlers = recorded_pools
    before = _pool_snapshot(service)
    writes = {provider: list(handler.replaced) for provider, handler in handlers.items()}
    data = dict(
        label="Changed", provider="new", enabled=False,
        policy_tags=_declared({"region": "us"}), provider_config={"new_setting": True},
    )

    with pytest.raises(PoolValidationError) as refused:
        if operation == "replace":
            service.replace_pool("existing", PoolReplace(**data))
        else:
            service.update_pool("existing", PoolUpdate(**data))

    assert str(refused.value) == (
        "provider of pool 'existing' is fixed at creation as 'old' and cannot become 'new'; "
        "declare a second pool with the intended provider and migrate its members instead"
    )
    assert _pool_snapshot(service) == before
    for provider, handler in handlers.items():
        assert handler.replaced == writes[provider]
        assert handler.deleted == []
    assert handlers["old"].configs["existing"] == {"setting": "existing"}
    assert handlers["new"].configs == {}


def test_equal_provider_patch_and_omitted_tags_do_not_write_config(recorded_pools):
    service, handlers = recorded_pools
    before = PoolResponse.model_validate(service.get_pool("existing"))
    writes = list(handlers["old"].replaced)

    unchanged = service.update_pool("existing", PoolUpdate(provider="old"))
    assert PoolResponse.model_validate(unchanged) == before
    renamed = service.update_pool("existing", PoolUpdate(label="Renamed"))
    assert renamed.label == "Renamed"
    assert renamed.provider == before.provider
    assert renamed.policy_tags == before.policy_tags
    assert renamed.provider_config == before.provider_config
    assert handlers["old"].replaced == writes


def test_same_provider_config_replace_and_patch_remain_editable(recorded_pools):
    service, handlers = recorded_pools
    replaced = service.replace_pool("existing", PoolReplace(
        label="Replaced", provider="old", enabled=False, policy_tags=_declared(),
        provider_config={"setting": "replacement"},
    ))
    assert replaced.provider_config == {"setting": "replacement"}
    patched = service.update_pool("existing", PoolUpdate(
        provider="old", provider_config={"setting": "patch"},
    ))
    assert patched.provider == "old"
    assert patched.enabled is False
    assert patched.provider_config == {"setting": "patch"}
    assert handlers["new"].replaced == []


def _provider_change_document(service):
    document = yaml.safe_load(service.export_pools_yaml())
    # A valid new entry precedes the immutable-field change and an existing
    # entry is omitted, so refusal must prevent creation and disablement too.
    document["pools"] = [
        document["pools"][0],
        {"id": "fresh", "label": "Fresh", "provider": "new",
         "policy_tags": _declared(), "provider_config": {"setting": "new"}},
        {**document["pools"][1], "label": "Changed", "provider": "new",
         "policy_tags": _declared({"capacity_backing": "unbacked"}),
         "provider_config": {"setting": "changed"}},
    ]
    document["pools"][0]["label"] = "Changed default"
    return yaml.safe_dump(document)


def test_documents_report_both_immutable_fields_and_apply_nothing(recorded_pools, session_factory):
    service, handlers = recorded_pools
    before = _pool_snapshot(service)
    exported = service.export_pools_yaml()
    writes = {provider: list(handler.replaced) for provider, handler in handlers.items()}
    document = _provider_change_document(service)

    result = service.validate_pools(document)
    assert result.valid is False
    assert result.diff is None
    assert [(p.path, p.code) for p in result.problems] == [
        ("pools[2].provider", "provider_immutable"),
        ("pools[2].policy_tags.capacity_backing", "capacity_backing_immutable"),
    ]
    for validate_only in (False, True):
        with pytest.raises(PoolValidationError, match=r"pools\[2\]\.provider:"):
            service.import_pools(document, validate_only=validate_only)
    with pytest.raises(PoolValidationError, match=r"pools\[2\]\.policy_tags.capacity_backing:"):
        with session_factory() as db, db.begin():
            service.import_pools_in_session(db, document)
    assert _pool_snapshot(service) == before
    assert service.export_pools_yaml() == exported
    for provider, handler in handlers.items():
        assert handler.replaced == writes[provider]
        assert handler.deleted == []
    assert handlers["new"].configs == {}


def test_new_document_entry_may_declare_a_different_provider(recorded_pools):
    service, _ = recorded_pools
    document = yaml.safe_load(service.export_pools_yaml())
    document["pools"].append({
        "id": "second", "label": "Second", "provider": "new",
        "policy_tags": _declared(), "provider_config": {"setting": "new"},
    })
    result = service.validate_pools(yaml.safe_dump(document))
    assert result.valid is True
    assert result.diff.created == ["second"]
    diff = service.import_pools(yaml.safe_dump(document))
    assert diff.created == ["second"]
    assert service.get_pool("second").provider == "new"


def test_document_request_problems_precede_all_stored_comparisons(recorded_pools):
    service, _ = recorded_pools
    before = _pool_snapshot(service)
    document = yaml.safe_load(_provider_change_document(service))
    document["pools"][1]["label"] = ""
    response = service.validate_pools(yaml.safe_dump(document))
    assert response.diff is None
    assert [(p.path, p.code) for p in response.problems] == [("pools[1].label", "required_field")]
    with pytest.raises(PoolValidationError, match=r"pools\[1\]\.label:"):
        service.import_pools(yaml.safe_dump(document))
    assert _pool_snapshot(service) == before


@pytest.mark.parametrize("operation", ["replace", "patch", "document"])
def test_provider_configuration_validation_precedes_provider_comparison(session_factory, operation):
    service = ResourcePoolService(session_factory, {
        "ansible": _AnsibleLikePoolConfigHandler(), "old": _StubPoolConfigHandler("old"),
    })
    service.create_pool(PoolCreate(
        id="default", label="Default", provider="old", policy_tags=_declared(), provider_config={},
    ))
    before = _pool_snapshot(service)
    data = dict(label="Changed", provider="ansible", enabled=False,
                policy_tags=_declared(), provider_config={})
    if operation == "document":
        document = yaml.safe_dump({"pools": [{"id": "default", **data}]})
        response = service.validate_pools(document)
        assert response.valid is False
        assert response.diff is None
        assert {p.code for p in response.problems} == {"required_field"}
        with pytest.raises(PoolValidationError, match="playbook_path"):
            service.import_pools(document)
    else:
        with pytest.raises(PoolValidationError, match="playbook_path"):
            if operation == "replace":
                service.replace_pool("default", PoolReplace(**data))
            else:
                service.update_pool("default", PoolUpdate(**data))
    assert _pool_snapshot(service) == before


@pytest.mark.parametrize("operation", ["replace", "patch", "document"])
def test_unknown_provider_keeps_its_existing_refusal(recorded_pools, operation):
    service, _ = recorded_pools
    before = _pool_snapshot(service)
    data = dict(label="Changed", provider="unknown", enabled=False,
                policy_tags=_declared(), provider_config={})
    with pytest.raises(PoolValidationError, match="no pool config handler registered"):
        if operation == "replace":
            service.replace_pool("existing", PoolReplace(**data))
        elif operation == "patch":
            service.update_pool("existing", PoolUpdate(**data))
        else:
            service.import_pools(yaml.safe_dump({"pools": [{"id": "default", **data}]}))
    assert _pool_snapshot(service) == before


# ---------------------------------------------------------------------------
# Advertisement and backing declarations
# ---------------------------------------------------------------------------

_BACKED_VM = {
    "deliverable_modes": ["vm"],
    "advertisable_modes": ["vm"],
    "capacity_backing": "backed",
}


def _document(tags_block: str, *, pool_id: str = "default") -> str:
    """A one-pool authoritative document with the given policy_tags block."""
    return f"""
pools:
  - id: {pool_id}
    label: Pool
    provider: ansible
{tags_block}
    provider_config:
      playbook_path: playbooks/vm-operations.yaml
      inventory_group: kvm_hosts
"""


_DOC_BACKED_VM = _document(
    "    policy_tags:\n"
    "      deliverable_modes: [vm]\n"
    "      advertisable_modes: [vm]\n"
    "      capacity_backing: backed"
)


def _create_backed_vm(svc, pool_id: str = "default") -> None:
    svc.create_pool(
        PoolCreate(
            id=pool_id,
            label="Pool",
            provider="ansible",
            policy_tags=dict(_BACKED_VM),
            provider_config=_ANSIBLE_CONFIG,
        )
    )


def _replace_with(tags):
    return PoolReplace(
        label="Pool",
        provider="ansible",
        enabled=True,
        policy_tags=tags,
        provider_config=_ANSIBLE_CONFIG,
    )


class TestDeclarationsOnDocumentsAndPersistence:
    """Raw documents report declaration problems without changing persisted pools."""

    @pytest.mark.parametrize(
        ("tags", "named"),
        [
            pytest.param({"deliverable_modes": ["vm"]}, "advertisable_modes", id="absent"),
            pytest.param({**_BACKED_VM, "capacity_backing": "maybe"}, "capacity_backing", id="malformed"),
            pytest.param(
                {**_BACKED_VM, "advertisable_modes": ["vm", "bare_metal"]},
                "bare_metal",
                id="backed-widened",
            ),
            pytest.param(
                {**_BACKED_VM, "deliverable_modes": []},
                "advertisable_modes",
                id="backed-narrowed",
            ),
            pytest.param(
                {**_BACKED_VM, "capacity_backing": "unbacked"},
                "unbacked",
                id="unbacked-delivers",
            ),
        ],
    )
    def test_document_refuses_invalid_declarations_without_mutation(self, svc, tags, named):
        _create_backed_vm(svc, "existing")
        before = svc.export_pools_yaml()
        document = yaml.safe_load(_DOC_BACKED_VM)
        document["pools"][0]["policy_tags"] = tags
        yaml_text = yaml.safe_dump(document)
        response = svc.validate_pools(yaml_text)
        assert response.valid is False
        assert response.diff is None
        assert any(named in problem.message for problem in response.problems)
        with pytest.raises(PoolValidationError, match=named):
            svc.import_pools(yaml_text)
        assert svc.export_pools_yaml() == before

    def test_unbacked_pool_advertises_with_nothing_delivered(self, svc):
        tags = {
            "deliverable_modes": [],
            "advertisable_modes": ["vm"],
            "capacity_backing": "unbacked",
        }
        pool = svc.create_pool(
            PoolCreate(
                id="out-of-band",
                label="Out of band",
                provider="ansible",
                policy_tags=tags,
                provider_config=_ANSIBLE_CONFIG,
            )
        )

        assert pool.policy_tags == tags

    def test_document_reports_each_missing_declaration_per_entry(self, svc):
        response = svc.validate_pools(
            _document("    policy_tags:\n      deliverable_modes: [vm]")
        )

        assert response.valid is False
        missing = {
            p.path for p in response.problems if p.code == "missing_declaration"
        }
        assert missing == {
            "pools[0].policy_tags.advertisable_modes",
            "pools[0].policy_tags.capacity_backing",
        }

    def test_document_predating_declarations_imports_nothing(self, svc):
        with pytest.raises(PoolValidationError):
            svc.import_pools(_document(""))

        assert svc.list_pools() == []

    def test_import_error_names_entry_and_tag(self, svc):
        with pytest.raises(PoolValidationError) as exc_info:
            svc.import_pools(_document(""))

        assert "pools[0].policy_tags.capacity_backing" in str(exc_info.value)

    def test_export_carries_both_declarations_and_reimports_unchanged(self, svc):
        svc.import_pools(_DOC_BACKED_VM)

        exported = svc.export_pools_yaml()
        diff = svc.import_pools(exported)

        for entry in yaml.safe_load(exported)["pools"]:
            assert entry["policy_tags"]["advertisable_modes"] == ["vm"]
            assert entry["policy_tags"]["capacity_backing"] == "backed"
        assert diff.unchanged == ["default"]
        assert diff.updated == []


class TestBackingIsFixedAtCreation:
    def test_replace_changing_backing_is_refused_and_pool_survives(self, svc):
        _create_backed_vm(svc)

        with pytest.raises(PoolValidationError, match="fixed at creation"):
            svc.replace_pool(
                "default",
                _replace_with({
                    "deliverable_modes": [],
                    "advertisable_modes": [],
                    "capacity_backing": "unbacked",
                }),
            )

        assert svc.get_pool("default").policy_tags == _BACKED_VM

    def test_patch_changing_backing_is_refused_and_pool_survives(self, svc):
        _create_backed_vm(svc)

        with pytest.raises(PoolValidationError, match="fixed at creation"):
            svc.update_pool(
                "default",
                PoolUpdate(policy_tags={
                    "deliverable_modes": [],
                    "advertisable_modes": [],
                    "capacity_backing": "unbacked",
                }),
            )

        assert svc.get_pool("default").policy_tags == _BACKED_VM

    def test_restating_the_same_backing_is_accepted(self, svc):
        _create_backed_vm(svc)

        replaced = svc.replace_pool(
            "default", _replace_with({**_BACKED_VM, "advertisable_modes": []}),
        )

        assert replaced.policy_tags["advertisable_modes"] == []

    def test_import_changing_backing_is_refused_and_validate_only_reports_it(self, svc):
        svc.import_pools(_DOC_BACKED_VM)
        unbacked = _document(
            "    policy_tags:\n"
            "      deliverable_modes: []\n"
            "      advertisable_modes: [vm]\n"
            "      capacity_backing: unbacked"
        )

        response = svc.validate_pools(unbacked)
        assert response.valid is False
        assert response.diff is None
        assert [(p.path, p.code) for p in response.problems] == [
            ("pools[0].policy_tags.capacity_backing", "capacity_backing_immutable"),
        ]
        with pytest.raises(PoolValidationError, match="pools\\[0\\]"):
            svc.import_pools(unbacked)
        with pytest.raises(PoolValidationError, match="fixed at creation"):
            svc.import_pools(unbacked, validate_only=True)

        assert svc.get_pool("default").policy_tags == _BACKED_VM


class TestStoredDeclarations:
    def test_valid_stored_pools_pass(self, svc):
        _create_backed_vm(svc)

        svc.require_valid_stored_declarations()

    def test_rows_written_without_declarations_are_named(self, svc, session_factory):
        _create_backed_vm(svc, "declared")
        with session_factory() as db, db.begin():
            db.add(ResourcePool(
                id="legacy",
                label="Legacy",
                provider="ansible",
                policy_tags={"deliverable_modes": ["vm"]},
            ))

        with session_factory() as db:
            problems = svc.stored_declaration_problems(db)
        assert {(pool_id, p.code) for pool_id, p in problems} == {
            ("legacy", "missing_declaration"),
        }
        with pytest.raises(PoolValidationError, match="pool 'legacy'"):
            svc.require_valid_stored_declarations()

    def test_malformed_stored_delivery_is_named(self, svc, session_factory):
        with session_factory() as db, db.begin():
            db.add(ResourcePool(
                id="drifted",
                label="Drifted",
                provider="ansible",
                policy_tags={**_BACKED_VM, "deliverable_modes": "vm"},
            ))

        with pytest.raises(PoolValidationError, match="pool 'drifted' deliverable_modes"):
            svc.require_valid_stored_declarations()

    def test_a_pool_without_backing_may_be_given_one(self, svc, session_factory):
        # The repair path for a row an older version rewrote: supplying the
        # value is not a change to it.
        with session_factory() as db, db.begin():
            db.add(ResourcePool(
                id="legacy", label="Legacy", provider="ansible",
                policy_tags={"deliverable_modes": ["vm"]},
            ))

        repaired = svc.replace_pool("legacy", _replace_with(dict(_BACKED_VM)))

        assert repaired.policy_tags == _BACKED_VM

    def test_a_document_may_give_a_pool_without_backing_its_declarations(
        self, svc, session_factory,
    ):
        # The rollback repair: the service refuses to start, so the API is
        # unavailable, and a changed definition document is imported first.
        with session_factory() as db, db.begin():
            db.add(ResourcePool(
                id="default", label="Pool", provider="ansible",
                policy_tags={"deliverable_modes": ["vm"]},
            ))

        svc.import_pools(_DOC_BACKED_VM)

        assert svc.get_pool("default").policy_tags == _BACKED_VM
        svc.require_valid_stored_declarations()
