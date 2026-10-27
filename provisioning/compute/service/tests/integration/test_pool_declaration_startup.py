"""A site's pools at startup: the pool document, the fresh-site seed, and the
declaration check.

A configured pool document is the site's authority over its pools. A fresh site
with none is seeded from ``pool_seed_path``, once, and a site that holds any
pool is never seeded. Then every stored pool must carry valid advertisement and
backing declarations: a pool lacking either must never reach the resource-pool
projection, where a consumer could not tell it from a site that predates the
declarations, so the service refuses to start, naming the pool.

External boundary: SQLAlchemy against file-backed SQLite and real pool and
seed documents in a temp directory, driven through the real startup entry
points and the real importer. Both are deterministic and do no network I/O.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from bare_metal_provisioning_adapter.services.bare_metal_pool_config_handler import BareMetalPoolConfigHandler
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from compute_provisioning_service import app_runtime
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.config import settings as service_settings
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
from market_resource_pools_contracts import resolve_pool_declarations
from vm_provisioning_adapter.db import AnsiblePoolConfig
from vm_provisioning_adapter.services.ansible_pool_config_handler import (
    AnsiblePoolConfigHandler,
)

_POOL_KIND = "pools"

# The seed document the service is packaged with, resolved as the service
# resolves its default `pool_seed_path`.
_PACKAGED_SEED = service_settings.resolved_pool_seed_path

_BARE_METAL_DOCUMENT = (
    Path(__file__).resolve().parents[5] / "dev-env/bare-metal/resource-pools.yaml"
).read_text(encoding="utf-8")

_DECLARED_DOCUMENT = """
pools:
  - id: default
    label: Default Pool
    provider: vm.ansible
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
    provider: vm.ansible
    policy_tags:
      deliverable_modes: [vm]
    provider_config:
      playbook_path: /configured/playbook.yaml
"""


class _Deployment:
    """One database, a pool document path, and a seed document path.

    ``start`` runs the startup steps that decide a site's pools, in the
    service's order, against this deployment's configuration.
    """

    def __init__(
        self, tmp_path, monkeypatch, *,
        pool_document=None, seed=_PACKAGED_SEED, existing_default=False,
    ):
        self.engine = create_engine(f"sqlite:///{tmp_path / 'provisioning.db'}")
        self.document = tmp_path / "pools.yaml"
        if pool_document is not None:
            self.document.write_text(pool_document, encoding="utf-8")
        run_migrations(self.engine)
        if existing_default:
            # Migration creates no pool: a site already serving holds its VM
            # `default`, with both declarations and its playbook.
            with Session(self.engine) as db, db.begin():
                db.add(ResourcePool(
                    id=DEFAULT_POOL_ID, label="Default Pool", provider="vm.ansible",
                    enabled=True, policy_tags={
                        "deliverable_modes": ["vm"],
                        "advertisable_modes": ["vm"],
                        "capacity_backing": "backed",
                    },
                ))
                db.flush()
                db.add(AnsiblePoolConfig(
                    pool_id=DEFAULT_POOL_ID, playbook_path="/configured/playbook.yaml",
                    extra_vars={},
                ))
        self.session_factory = sessionmaker(bind=self.engine)
        self.pool_service = ResourcePoolService(
            session_factory=self.session_factory,
            handlers={
                "vm.ansible": AnsiblePoolConfigHandler(),
                "bare_metal.ansible": BareMetalPoolConfigHandler(),
            },
        )
        self.settings = SimpleNamespace(
            resolved_pool_definitions_path=self.document if pool_document is not None else None,
            resolved_pool_seed_path=seed,
        )
        monkeypatch.setattr(app_runtime, "settings", self.settings)
        for name, value in (
            ("resolved_resource_pool_service", self.pool_service),
            ("resolved_session_factory", self.session_factory),
            ("resolved_capacity_ledger_service", None),
        ):
            monkeypatch.setattr(_container_module, name, value, raising=False)

    def start(self) -> None:
        app_runtime.import_pool_definitions_if_configured()
        app_runtime.seed_initial_pools_if_fresh()
        app_runtime.verify_pool_declarations()

    def importer(self) -> DefinitionDocumentImporter:
        """The importer over the mounted document, whether or not configured."""
        return DefinitionDocumentImporter(
            session_factory=self.session_factory,
            settings=SimpleNamespace(resolved_pool_definitions_path=self.document),
            pool_service=self.pool_service,
        )

    def recorded_digest(self) -> str | None:
        with self.session_factory() as db:
            row = db.get(DefinitionDocumentImport, _POOL_KIND)
            return None if row is None else row.digest

    def recorded_kinds(self) -> list[str]:
        with self.session_factory() as db:
            return [row.document_kind for row in db.query(DefinitionDocumentImport)]

    def pool_ids(self) -> list[str]:
        return sorted(pool.id for pool in self.pool_service.list_pools())

    def default_tags(self) -> dict:
        with Session(self.engine) as db:
            return dict(db.get(ResourcePool, DEFAULT_POOL_ID).policy_tags)


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    return _Deployment(tmp_path, monkeypatch, existing_default=True)


def test_a_site_holding_default_passes_the_startup_check(deployment):
    app_runtime.verify_pool_declarations()


def test_a_stored_pool_without_declarations_stops_startup_and_is_named(deployment):
    with Session(deployment.engine) as db, db.begin():
        db.add(ResourcePool(
            id="rewritten-by-older-version",
            label="Rewritten",
            provider="vm.ansible",
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


def test_the_seed_runs_between_the_pool_document_and_the_declaration_check():
    names = [step.name for step in app_runtime.startup_steps()]

    assert (
        names.index("import-pool-definitions")
        < names.index("seed-initial-pools")
        < names.index("verify-pool-declarations")
        < names.index("seed-inventory")
    )


def test_a_fresh_site_with_no_pool_document_is_seeded_once(tmp_path, monkeypatch, caplog):
    deployment = _Deployment(tmp_path, monkeypatch)

    with caplog.at_level(logging.INFO):
        deployment.start()

    assert deployment.pool_ids() == ["bare-metal-default", "vm-default"]
    for pool_id, provider, mode in (
        ("vm-default", "vm.ansible", "vm"),
        ("bare-metal-default", "bare_metal.ansible", "bare_metal"),
    ):
        pool = deployment.pool_service.get_pool(pool_id)
        assert (pool.provider, pool.enabled) == (provider, True)
        # Neither pool states a playbook: each job takes its domain's
        # configured one when it is prepared.
        assert pool.provider_config.get("playbook_path") is None
        declarations = resolve_pool_declarations(pool.policy_tags)
        assert declarations.advertisable_modes == frozenset({mode})
        assert declarations.backing.label == "backed"
        assert pool.policy_tags["deliverable_modes"] == [mode]
        assert f"Pool seed: created pool {pool_id} from {_PACKAGED_SEED}" in caplog.text
    # The seed is no submitted document: nothing records it.
    assert deployment.recorded_kinds() == []

    # A second start finds pools stored and changes nothing.
    before = deployment.pool_service.export_pools_yaml()
    deployment.start()
    assert deployment.pool_service.export_pools_yaml() == before
    assert deployment.recorded_kinds() == []


@pytest.mark.parametrize("document", [_DECLARED_DOCUMENT, _BARE_METAL_DOCUMENT])
def test_a_fresh_site_with_a_pool_document_takes_its_pools_and_no_seed(
    tmp_path, monkeypatch, document,
):
    deployment = _Deployment(tmp_path, monkeypatch, pool_document=document)

    deployment.start()

    assert deployment.pool_ids() == [DEFAULT_POOL_ID]
    assert deployment.recorded_digest() == DefinitionDocumentImporter.digest_of(document)


def test_a_site_holding_pools_is_not_seeded(deployment):
    before = deployment.pool_service.export_pools_yaml()

    deployment.start()

    assert deployment.pool_ids() == [DEFAULT_POOL_ID]
    assert deployment.pool_service.export_pools_yaml() == before
    assert deployment.recorded_kinds() == []


def test_a_site_holding_only_a_disabled_pool_is_not_seeded(tmp_path, monkeypatch):
    deployment = _Deployment(tmp_path, monkeypatch, existing_default=True)
    deployment.pool_service.disable_pool(DEFAULT_POOL_ID)

    deployment.start()

    assert deployment.pool_ids() == [DEFAULT_POOL_ID]


def test_an_empty_seed_path_seeds_nothing_and_starts(tmp_path, monkeypatch):
    deployment = _Deployment(tmp_path, monkeypatch, seed=None)

    deployment.start()

    assert deployment.pool_ids() == []


def test_a_missing_seed_document_fails_startup_and_creates_no_pool(tmp_path, monkeypatch):
    deployment = _Deployment(tmp_path, monkeypatch, seed=tmp_path / "absent.yaml")

    with pytest.raises(FileNotFoundError, match="pool seed"):
        deployment.start()

    assert deployment.pool_ids() == []


@pytest.mark.parametrize("site", ["pools stored", "pool document configured"])
@pytest.mark.parametrize("seed_problem", ["missing", "invalid"])
def test_a_seed_document_that_does_not_apply_is_not_read(
    tmp_path, monkeypatch, caplog, site, seed_problem,
):
    """Only a seed that applies fails startup: a site holding pools, or
    governed by its pool document, never reads one."""
    seed = tmp_path / "seed.yaml"
    if seed_problem == "invalid":
        seed.write_text("pools: [{id: no-provider, label: No provider}]", encoding="utf-8")
    deployment = _Deployment(
        tmp_path, monkeypatch, seed=seed,
        existing_default=site == "pools stored",
        pool_document=_DECLARED_DOCUMENT if site == "pool document configured" else None,
    )
    before = deployment.pool_service.export_pools_yaml()

    with caplog.at_level(logging.INFO):
        deployment.start()

    # The step skips before it opens the seed document.
    assert {
        "pools stored": "Pool seed: skipped — pools are already stored",
        "pool document configured": "Pool seed: skipped — a pool document is configured",
    }[site] in caplog.text
    assert deployment.pool_ids() == [DEFAULT_POOL_ID]
    if site == "pools stored":
        assert deployment.pool_service.export_pools_yaml() == before


def test_an_operator_seed_document_replaces_the_packaged_one(tmp_path, monkeypatch):
    seed = tmp_path / "seed.yaml"
    seed.write_text(_DECLARED_DOCUMENT.replace("id: default", "id: gpu-h200"), encoding="utf-8")
    deployment = _Deployment(tmp_path, monkeypatch, seed=seed)

    deployment.start()

    assert deployment.pool_ids() == ["gpu-h200"]
    assert deployment.recorded_kinds() == []


def test_an_invalid_seed_document_fails_startup_and_creates_no_pool(tmp_path, monkeypatch):
    """A valid entry ahead of the invalid one is not created either: the seed
    lands whole or not at all."""
    seed = yaml.safe_load(_PACKAGED_SEED.read_text(encoding="utf-8"))
    seed["pools"].append({"id": "no-provider", "label": "No provider"})
    path = tmp_path / "seed.yaml"
    path.write_text(yaml.safe_dump(seed), encoding="utf-8")
    deployment = _Deployment(tmp_path, monkeypatch, seed=path)

    with pytest.raises(PoolValidationError, match=r"pools\[2\]"):
        deployment.start()

    assert deployment.pool_ids() == []
    assert deployment.recorded_kinds() == []


def test_a_mounted_document_does_not_replace_an_existing_default_provider(deployment):
    deployment.document.write_text(_BARE_METAL_DOCUMENT, encoding="utf-8")

    with pytest.raises(PoolValidationError, match="fixed at creation"):
        deployment.importer().import_pool_definitions()
    assert deployment.pool_service.get_pool("default").provider == "vm.ansible"
    assert deployment.recorded_digest() is None


@pytest.mark.parametrize("missing", [False, True])
def test_a_bad_pool_document_on_a_fresh_site_is_not_replaced_by_the_seed(
    tmp_path, monkeypatch, missing,
):
    deployment = _Deployment(
        tmp_path, monkeypatch, pool_document="pools: [{id: default, label: Default}]",
    )
    if missing:
        deployment.document.unlink()

    with pytest.raises(FileNotFoundError if missing else PoolValidationError):
        deployment.start()
    # The seed step itself leaves a site with a configured document alone.
    app_runtime.seed_initial_pools_if_fresh()

    assert deployment.pool_ids() == []
    assert deployment.recorded_digest() is None


def test_changed_provider_document_retries_without_state_or_digest_changes_and_can_be_corrected(
    deployment,
):
    deployment.document.write_text(_DECLARED_DOCUMENT, encoding="utf-8")
    assert deployment.importer().import_pool_definitions().reconciled is True
    before = deployment.pool_service.export_pools_yaml()
    digest = deployment.recorded_digest()
    assert digest == DefinitionDocumentImporter.digest_of(_DECLARED_DOCUMENT)
    document = yaml.safe_load(_DECLARED_DOCUMENT)
    document["pools"][0].update(
        label="Changed", provider="bare_metal.ansible", provider_config={},
    )
    # A valid entry before the refusal must not be created by a failed startup.
    document["pools"].insert(0, {
        "id": "second", "label": "Second", "provider": "bare_metal.ansible",
        "policy_tags": {"advertisable_modes": [], "capacity_backing": "backed"},
        "provider_config": {},
    })
    deployment.document.write_text(yaml.safe_dump(document), encoding="utf-8")

    for _ in range(2):
        with pytest.raises(PoolValidationError) as refused:
            deployment.importer().import_pool_definitions()
        assert "pools[1].provider:" in str(refused.value)
        assert "pool 'default'" in str(refused.value)
        assert "migrate its members" in str(refused.value)
        assert deployment.pool_service.export_pools_yaml() == before
        assert deployment.recorded_digest() == digest
        assert deployment.pool_service.get_pool("second") is None

    document["pools"][1].update(
        provider="vm.ansible", provider_config={"playbook_path": "/configured/corrected.yaml"},
    )
    corrected = yaml.safe_dump(document)
    deployment.document.write_text(corrected, encoding="utf-8")
    assert deployment.importer().import_pool_definitions().reconciled is True
    assert deployment.recorded_digest() == DefinitionDocumentImporter.digest_of(corrected)
    assert deployment.recorded_digest() != digest
    default = deployment.pool_service.get_pool("default")
    assert default.provider == "vm.ansible"
    assert default.label == "Changed"
    assert default.provider_config["playbook_path"] == "/configured/corrected.yaml"
    assert deployment.pool_service.get_pool("second").provider == "bare_metal.ansible"
    assert deployment.importer().import_pool_definitions().reconciled is False
    app_runtime.verify_pool_declarations()
