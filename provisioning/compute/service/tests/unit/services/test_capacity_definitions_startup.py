"""A mounted capacity-definitions document, across process lifetimes.

Startup reconciles the document only when it differs from the one it last
reconciled, so capacity administered through the API survives a restart. The
database file and the document persist while the process is rebuilt, which is
the shape of the real system, and each start runs the same entry point the
service's startup step runs.
"""

from __future__ import annotations

import textwrap
from types import SimpleNamespace

import pytest
from market_resource_pools import ResourcePool
from market_site import CapacityLedgerService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compute_provisioning_service import app_runtime
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.models import DefinitionDocumentImport
from compute_provisioning_service.services.definition_documents import (
    CapacityDefinitionsRejected,
)

_DOCUMENT = textwrap.dedent(
    """
    resources:
      - resource_id: compute-kvm1
        pool_id: default
        resource_type: compute.gpu
        host_id: kvm1
        capacity: {gpu_count: 8}
        attributes: {gpu_model: H200}
    """
)


class _Deployment:
    def __init__(self, tmp_path):
        self.document = tmp_path / "capacity-definitions.yaml"
        engine = create_engine(f"sqlite:///{tmp_path / 'provisioning.db'}")
        run_migrations(
            engine,
            default_playbook_path="/configured/playbook.yaml",
            default_inventory_group="kvm_hosts",
        )
        self.session_factory = sessionmaker(bind=engine)
        self.settings = SimpleNamespace(
            resolved_capacity_definitions_path=self.document,
        )

    def write_document(self, text: str) -> None:
        self.document.write_text(text, encoding="utf-8")

    def recorded_digest(self) -> str | None:
        with self.session_factory() as db:
            row = db.get(DefinitionDocumentImport, "capacity")
            return None if row is None else row.digest

    def restart(self, monkeypatch) -> CapacityLedgerService:
        """Bring the service up again against the same database and document."""
        ledger = CapacityLedgerService(
            self.session_factory,
            unit_claim_keys=("units", "gpu_count"),
            mirror_dimension="gpu_count",
        )
        monkeypatch.setattr(
            _container_module, "resolved_session_factory", self.session_factory,
            raising=False,
        )
        monkeypatch.setattr(
            _container_module, "resolved_capacity_ledger_service", ledger,
            raising=False,
        )
        monkeypatch.setattr(app_runtime, "settings", self.settings, raising=False)
        app_runtime.import_capacity_definitions_if_configured()
        return ledger


@pytest.fixture
def deployment(tmp_path):
    return _Deployment(tmp_path)


def _resource(ledger: CapacityLedgerService, resource_id: str) -> dict:
    return {row["resource_id"]: row for row in ledger.list_resources()}[resource_id]


def test_a_first_start_declares_the_documented_capacity(deployment, monkeypatch):
    deployment.write_document(_DOCUMENT)

    ledger = deployment.restart(monkeypatch)

    resource = _resource(ledger, "compute-kvm1")
    assert resource["capacity"] == {"gpu_count": 8}
    assert resource["host_id"] == "kvm1"
    assert deployment.recorded_digest() is not None


def test_an_edited_document_is_applied_at_the_next_start(deployment, monkeypatch):
    deployment.write_document(_DOCUMENT)
    deployment.restart(monkeypatch)

    deployment.write_document(_DOCUMENT.replace("gpu_count: 8", "gpu_count: 4"))
    ledger = deployment.restart(monkeypatch)

    assert _resource(ledger, "compute-kvm1")["capacity"] == {"gpu_count": 4}


def test_an_unchanged_document_does_not_revert_api_administration(
    deployment, monkeypatch
):
    """The property the digest gate exists for: an operator disables the
    declaration through the API, the mounted document still says enabled,
    and a restart must not put it back."""
    deployment.write_document(_DOCUMENT)
    ledger = deployment.restart(monkeypatch)
    ledger.register_resource(
        resource_id="compute-kvm1", pool_id="default", resource_type="compute.gpu",
        host_id="kvm1", capacity={"gpu_count": 8},
        attributes={"gpu_model": "H200"}, enabled=False,
    )

    for _ in range(3):
        ledger = deployment.restart(monkeypatch)

    assert _resource(ledger, "compute-kvm1")["enabled"] is False


def test_a_declaration_may_name_a_pool_created_before_it(deployment, monkeypatch):
    with deployment.session_factory() as db, db.begin():
        db.add(ResourcePool(
            id="gpu-pool", label="GPU pool", provider="ansible", enabled=True,
            policy_tags={"deliverable_modes": ["vm"]},
        ))
    deployment.write_document(_DOCUMENT.replace("pool_id: default", "pool_id: gpu-pool"))

    ledger = deployment.restart(monkeypatch)

    assert _resource(ledger, "compute-kvm1")["pool_id"] == "gpu-pool"


def test_a_refused_document_applies_nothing_and_records_no_digest(
    deployment, monkeypatch
):
    """Refusal rolls back the apply and the digest together, so the next
    start retries rather than treating a refused document as reconciled."""
    deployment.write_document(
        _DOCUMENT
        + "  - resource_id: compute-kvm2\n"
        + "    pool_id: no-such-pool\n"
        + "    resource_type: compute.gpu\n"
        + "    capacity: {gpu_count: 1}\n"
    )

    with pytest.raises(CapacityDefinitionsRejected, match="no-such-pool"):
        deployment.restart(monkeypatch)

    assert deployment.recorded_digest() is None
    ledger = CapacityLedgerService(deployment.session_factory)
    assert ledger.list_resources() == []


def test_a_configured_document_that_is_missing_fails_startup(
    deployment, monkeypatch
):
    with pytest.raises(FileNotFoundError):
        deployment.restart(monkeypatch)


def test_an_unconfigured_document_is_skipped(deployment, monkeypatch):
    deployment.settings.resolved_capacity_definitions_path = None

    ledger = deployment.restart(monkeypatch)

    assert ledger.list_resources() == []
    assert deployment.recorded_digest() is None
