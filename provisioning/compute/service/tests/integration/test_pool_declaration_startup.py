"""Startup refuses pools without valid advertisement and backing declarations.

A pool lacking either declaration must never reach the resource-pool
projection, where a consumer could not tell it from a site that predates the
declarations. The service therefore refuses to start, naming the pool, rather
than serving it.

External boundary: SQLAlchemy against file-backed SQLite and a real mounted
pool document in a temp directory, driven through the real startup entry
points. Both are deterministic and do no network I/O.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from compute_provisioning_service import app_runtime
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.models import DefinitionDocumentImport
from compute_provisioning_service.services.definition_documents import (
    DefinitionDocumentImporter,
)
from market_resource_pools import (
    DEFAULT_POOL_ID,
    PoolValidationError,
    ResourcePool,
    ResourcePoolService,
)
from vm_provisioning_adapter.services.ansible_pool_config_handler import (
    AnsiblePoolConfigHandler,
)

_POOL_KIND = "pools"

_DECLARED_DOCUMENT = """
pools:
  - id: default
    label: Default Pool
    provider: ansible
    policy_tags:
      deliverable_modes: [vm]
      advertisable_modes: [vm]
      capacity_backing: backed
    provider_config:
      playbook_path: /configured/playbook.yaml
"""

_PREDATING_DOCUMENT = """
pools:
  - id: default
    label: Default Pool (edited)
    provider: ansible
    policy_tags:
      deliverable_modes: [vm]
    provider_config:
      playbook_path: /configured/playbook.yaml
"""


class _Deployment:
    def __init__(self, tmp_path, monkeypatch):
        self.engine = create_engine(f"sqlite:///{tmp_path / 'provisioning.db'}")
        run_migrations(
            self.engine,
            default_playbook_path="/configured/playbook.yaml",
            default_inventory_group="kvm_hosts",
        )
        self.session_factory = sessionmaker(bind=self.engine)
        self.document = tmp_path / "pools.yaml"
        self.pool_service = ResourcePoolService(
            session_factory=self.session_factory,
            handlers={"ansible": AnsiblePoolConfigHandler()},
        )
        monkeypatch.setattr(
            _container_module,
            "resolved_resource_pool_service",
            self.pool_service,
            raising=False,
        )

    def importer(self) -> DefinitionDocumentImporter:
        return DefinitionDocumentImporter(
            session_factory=self.session_factory,
            settings=SimpleNamespace(resolved_pool_definitions_path=self.document),
            pool_service=self.pool_service,
            relay_service=None,
        )

    def recorded_digest(self) -> str | None:
        with self.session_factory() as db:
            row = db.get(DefinitionDocumentImport, _POOL_KIND)
            return None if row is None else row.digest

    def default_tags(self) -> dict:
        with Session(self.engine) as db:
            return dict(db.get(ResourcePool, DEFAULT_POOL_ID).policy_tags)


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    return _Deployment(tmp_path, monkeypatch)


def test_migrated_state_passes_the_startup_check(deployment):
    app_runtime.verify_pool_declarations()


def test_a_stored_pool_without_declarations_stops_startup_and_is_named(deployment):
    with Session(deployment.engine) as db, db.begin():
        db.add(ResourcePool(
            id="rewritten-by-older-version",
            label="Rewritten",
            provider="ansible",
            enabled=True,
            policy_tags={"deliverable_modes": ["vm"]},
        ))

    with pytest.raises(PoolValidationError) as exc_info:
        app_runtime.verify_pool_declarations()

    message = str(exc_info.value)
    assert "pool 'rewritten-by-older-version' advertisable_modes" in message
    assert "pool 'rewritten-by-older-version' capacity_backing" in message
    assert "pool 'default'" not in message


def test_a_changed_document_predating_declarations_is_refused_naming_the_pool(
    deployment,
):
    deployment.document.write_text(_PREDATING_DOCUMENT, encoding="utf-8")
    before = deployment.default_tags()

    with pytest.raises(PoolValidationError) as exc_info:
        deployment.importer().import_pool_definitions()

    assert "pools[0].policy_tags.capacity_backing" in str(exc_info.value)
    assert deployment.recorded_digest() is None
    assert deployment.default_tags() == before


def test_an_unchanged_document_over_valid_state_still_starts(deployment):
    deployment.document.write_text(_DECLARED_DOCUMENT, encoding="utf-8")
    first = deployment.importer().import_pool_definitions()
    assert first.reconciled is True

    second = deployment.importer().import_pool_definitions()

    assert second.reconciled is False
    app_runtime.verify_pool_declarations()


def test_the_check_runs_after_the_pool_document_import():
    names = [step.name for step in app_runtime.startup_steps()]

    assert names.index("import-pool-definitions") < names.index("verify-pool-declarations")
    assert names.index("verify-pool-declarations") < names.index("seed-inventory")
