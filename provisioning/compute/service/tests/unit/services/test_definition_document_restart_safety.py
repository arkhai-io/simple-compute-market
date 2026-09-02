"""A pod restart must not revert work done through the API.

This is the failure the digest gate exists to prevent, and it is the reason a
test that merely calls the import function twice is not sufficient. Import is
idempotent with respect to the *document* and not the *database*: calling it
against state something else changed reverts that change, because a diff against
the document is exactly what detects it.

So these tests drive the real startup entry points against a real database and a
real mounted file, rebuilding the module-level container between runs the way a
new process would. What is being proven is that an operator who repoints a relay
at 10am still has it repointed after the pod is evicted at 2pm.

External boundary: SQLAlchemy against file-backed SQLite in a temp directory,
plus a real YAML file on disk. Both are deterministic and do no network I/O, so
the real implementations are used rather than mocks — a mocked file or session
would not exercise the thing under test.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compute_provisioning_service import app_runtime
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.services.relay_service import RelayService

_PLAYBOOK_PATH = "/configured/playbook.yaml"
_INVENTORY_GROUP = "kvm_hosts"
# Development-only Fernet key, generated per run and never used on a network.
_KEY = Fernet.generate_key().decode()


def _relay_document(**overrides) -> str:
    entry = {
        "id": "site-a",
        "relay_addr": "10.0.0.9",
        "relay_port": 7000,
        "vm_port_range_start": 6100,
        "vm_port_range_count": 100,
        "token_secret_key": "relay_token",
    }
    entry.update(overrides)
    return yaml.safe_dump({"relays": [entry]})


class _Deployment:
    """One database and one mounted document, across many process lifetimes.

    ``restart`` rebuilds the module-level container the way a new pod would,
    while the database file and the mounted document persist — which is the
    shape of the real system, where a PVC outlives the process.
    """

    def __init__(self, tmp_path):
        self.db_path = tmp_path / "provisioning.db"
        self.document = tmp_path / "relays.yaml"
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        run_migrations(
            self.engine,
            default_playbook_path=_PLAYBOOK_PATH,
            default_inventory_group=_INVENTORY_GROUP,
        )
        self.session_factory = sessionmaker(bind=self.engine)
        self.settings = SimpleNamespace(
            ssh_decryption_key=_KEY,
            relay_token="bootstrap-token",
            resolved_relay_definitions_path=self.document,
            resolved_pool_definitions_path=None,
        )

    def write_document(self, text: str) -> None:
        self.document.write_text(text, encoding="utf-8")

    def restart(self, monkeypatch) -> RelayService:
        """Bring the service up again against the same database and document."""
        relay_service = RelayService(
            session_factory=self.session_factory, settings=self.settings
        )
        monkeypatch.setattr(
            _container_module, "resolved_session_factory", self.session_factory,
            raising=False,
        )
        monkeypatch.setattr(
            _container_module, "resolved_relay_service", relay_service, raising=False
        )
        monkeypatch.setattr(app_runtime, "settings", self.settings, raising=False)
        app_runtime.import_relay_definitions_if_configured()
        return relay_service


@pytest.fixture
def deployment(tmp_path):
    return _Deployment(tmp_path)


class TestARestartDoesNotRevertAdministration:
    def test_a_first_start_establishes_the_relay(self, deployment, monkeypatch):
        deployment.write_document(_relay_document())
        relays = deployment.restart(monkeypatch)
        assert relays.get_relay("site-a").relay_addr == "10.0.0.9"
        assert relays.get_relay("site-a").token_configured is True

    def test_a_repointed_relay_survives_a_restart(self, deployment, monkeypatch):
        """The property the whole gate exists for.

        An operator repoints a relay through the controller. The mounted
        document still declares the old address. Under unconditional startup
        import the next eviction would silently put it back.
        """
        deployment.write_document(_relay_document())
        relays = deployment.restart(monkeypatch)
        relays.update_relay("site-a", relay_addr="10.0.0.99", vm_port_range_count=25)

        relays = deployment.restart(monkeypatch)

        view = relays.get_relay("site-a")
        assert view.relay_addr == "10.0.0.99"
        assert view.vm_port_range_count == 25

    def test_a_rotated_token_survives_a_restart(self, deployment, monkeypatch):
        deployment.write_document(_relay_document())
        relays = deployment.restart(monkeypatch)
        relays.rotate_token("site-a", "rotated-by-operator")

        relays = deployment.restart(monkeypatch)

        with deployment.session_factory() as db:
            from compute_provisioning_service.db.models import Relay

            stored = db.get(Relay, "site-a").relay_token_encrypted
        assert (
            Fernet(_KEY.encode()).decrypt(stored.encode()).decode()
            == "rotated-by-operator"
        )

    def test_a_disabled_relay_stays_disabled_across_a_restart(
        self, deployment, monkeypatch
    ):
        deployment.write_document(_relay_document())
        relays = deployment.restart(monkeypatch)
        relays.set_enabled("site-a", False)

        relays = deployment.restart(monkeypatch)

        assert relays.get_relay("site-a").enabled is False

    def test_many_restarts_change_nothing(self, deployment, monkeypatch):
        deployment.write_document(_relay_document())
        relays = deployment.restart(monkeypatch)
        relays.update_relay("site-a", label="operator-set")

        for _ in range(4):
            relays = deployment.restart(monkeypatch)

        assert relays.get_relay("site-a").label == "operator-set"


class TestAnEditedDocumentStillReconciles:
    def test_editing_the_document_applies_on_the_next_start(
        self, deployment, monkeypatch
    ):
        """Gating changes *when* reconciliation happens, not what it does."""
        deployment.write_document(_relay_document())
        deployment.restart(monkeypatch)

        deployment.write_document(_relay_document(vm_port_range_start=7100))
        relays = deployment.restart(monkeypatch)

        assert relays.get_relay("site-a").vm_port_range_start == 7100

    def test_an_edited_document_overrides_an_administrative_change(
        self, deployment, monkeypatch
    ):
        """Deliberate, and the reason the digest is over the whole document.

        An operator who has just edited the document is asserting what it says.
        The token is the exception, and is protected structurally rather than
        by the digest.
        """
        deployment.write_document(_relay_document())
        relays = deployment.restart(monkeypatch)
        relays.update_relay("site-a", vm_port_range_count=25)

        deployment.write_document(_relay_document(vm_port_range_count=64))
        relays = deployment.restart(monkeypatch)

        assert relays.get_relay("site-a").vm_port_range_count == 64

    def test_a_token_rotation_still_survives_an_edited_document(
        self, deployment, monkeypatch
    ):
        deployment.write_document(_relay_document())
        relays = deployment.restart(monkeypatch)
        relays.rotate_token("site-a", "rotated-by-operator")

        deployment.write_document(_relay_document(vm_port_range_count=64))
        deployment.restart(monkeypatch)

        with deployment.session_factory() as db:
            from compute_provisioning_service.db.models import Relay

            stored = db.get(Relay, "site-a").relay_token_encrypted
        assert (
            Fernet(_KEY.encode()).decrypt(stored.encode()).decode()
            == "rotated-by-operator"
        )


class TestAFailedApplyIsRetried:
    def test_a_failed_import_records_no_digest(self, deployment, monkeypatch):
        """Otherwise a half-applied document is recorded as done and skipped
        forever, leaving the database in a state no document describes."""
        deployment.write_document(_relay_document(token_secret_key="absent_key"))

        with pytest.raises(Exception):
            deployment.restart(monkeypatch)

        assert app_runtime._recorded_digest(deployment.session_factory, "relays") is None

    def test_the_next_start_retries_after_the_document_is_fixed(
        self, deployment, monkeypatch
    ):
        deployment.write_document(_relay_document(token_secret_key="absent_key"))
        with pytest.raises(Exception):
            deployment.restart(monkeypatch)

        deployment.write_document(_relay_document())
        relays = deployment.restart(monkeypatch)

        assert relays.get_relay("site-a").token_configured is True


class TestAnUnmountedDocument:
    def test_a_relay_outlives_the_document_that_established_it(
        self, deployment, monkeypatch
    ):
        """Establishing a relay from a document and administering it through
        the API are the same relay, not two."""
        deployment.write_document(_relay_document())
        deployment.restart(monkeypatch)

        deployment.settings.resolved_relay_definitions_path = None
        relays = deployment.restart(monkeypatch)

        assert relays.get_relay("site-a").relay_addr == "10.0.0.9"
