"""A relay is an administered resource, and its token is not readable.

Three properties are pinned here, each of which failed differently in the design
that preceded this one:

* A relay's rendezvous, window, and token are stated once, on a row that pools
  reference. Held per pool, two pools sharing a relay could allocate from one
  listening namespace under disagreeing windows.
* No read path that serves a response, an export, or a reconciliation
  comparison yields an admission token. Only an explicitly named execution read
  does.
* Reconciliation of a definition document follows a change to that document. A
  process restart is not a change, and re-applying a document nobody submitted
  reverts whatever else changed the database.

External boundary: SQLAlchemy against in-memory SQLite, as elsewhere in this
suite. The database is deterministic and does no network I/O, so the real engine
is used rather than a mock.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.models import (
    DefinitionDocumentImport,
    Relay,
    ResourcePool,
)
from compute_provisioning_service.services.relay_definitions import (
    RelayDefinitionError,
    import_relay_definitions,
    parse_relay_definitions,
)
from compute_provisioning_service.services.relay_rebinding import (
    RelayRebindingRefused,
)
from compute_provisioning_service.services.relay_service import (
    RelayEndpointConflictError,
    RelayNotFoundError,
    RelayService,
    RelayValidationError,
)
from vm_provisioning_adapter.services.ansible_pool_config_handler import (
    AnsiblePoolConfigHandler,
)

_PLAYBOOK_PATH = "/configured/playbook.yaml"
_INVENTORY_GROUP = "kvm_hosts"
# A development-only Fernet key. Generated for this fixture, never used on any
# network, and safe to read here precisely because it protects nothing.
_KEY = Fernet.generate_key().decode()


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(
        engine,
        default_playbook_path=_PLAYBOOK_PATH,
        default_inventory_group=_INVENTORY_GROUP,
    )
    return sessionmaker(bind=engine)


@pytest.fixture
def settings():
    return SimpleNamespace(ssh_decryption_key=_KEY, relay_token="bootstrap-token")


@pytest.fixture
def relays(session_factory, settings):
    return RelayService(session_factory=session_factory, settings=settings)


def _make_relay(relays, **overrides):
    fields = {
        "relay_id": "site-a",
        "relay_addr": "10.0.0.9",
        "relay_port": 7000,
        "vm_port_range_start": 6100,
        "vm_port_range_count": 100,
    }
    fields.update(overrides)
    return relays.create_relay(**fields)


class TestRelayAdministration:
    def test_a_relay_is_created_and_read_back(self, relays):
        created = _make_relay(relays, label="Site A")
        fetched = relays.get_relay(created.id)
        assert (fetched.relay_addr, fetched.relay_port) == ("10.0.0.9", 7000)
        assert fetched.vm_port_range_count == 100
        assert fetched.enabled is True

    def test_an_address_is_normalized_on_write(self, relays):
        created = _make_relay(relays, relay_addr="  Relay.Local  ")
        assert created.relay_addr == "relay.local"

    def test_a_duplicate_rendezvous_is_refused_with_both_named(self, relays):
        _make_relay(relays, relay_id="first")
        with pytest.raises(RelayEndpointConflictError) as excinfo:
            _make_relay(relays, relay_id="second")
        assert "first" in str(excinfo.value)
        assert "10.0.0.9:7000" in str(excinfo.value)

    def test_a_differently_spelled_duplicate_is_still_a_duplicate(self, relays):
        _make_relay(relays, relay_id="first", relay_addr="relay.local")
        with pytest.raises(RelayEndpointConflictError):
            _make_relay(relays, relay_id="second", relay_addr="RELAY.LOCAL")

    def test_an_update_onto_another_relays_rendezvous_is_refused(self, relays):
        _make_relay(relays, relay_id="first")
        _make_relay(relays, relay_id="second", relay_addr="10.0.0.10")
        with pytest.raises(RelayEndpointConflictError):
            relays.update_relay("second", relay_addr="10.0.0.9", relay_port=7000)

    def test_an_update_keeping_its_own_rendezvous_is_allowed(self, relays):
        """The conflict check must exclude the row being updated, or every
        edit that leaves the address alone would collide with itself."""
        _make_relay(relays, relay_id="only")
        updated = relays.update_relay("only", label="renamed")
        assert updated.label == "renamed"
        assert updated.relay_addr == "10.0.0.9"

    def test_an_omitted_field_is_unchanged(self, relays):
        _make_relay(relays, label="original")
        updated = relays.update_relay("site-a", vm_port_range_count=50)
        assert updated.label == "original"
        assert updated.vm_port_range_count == 50

    def test_a_relay_can_be_disabled_and_enabled(self, relays):
        _make_relay(relays)
        assert relays.set_enabled("site-a", False).enabled is False
        assert relays.set_enabled("site-a", True).enabled is True

    def test_an_unknown_relay_is_reported_as_missing(self, relays):
        with pytest.raises(RelayNotFoundError):
            relays.get_relay("absent")

    @pytest.mark.parametrize(
        "window", [{"vm_port_range_start": 0}, {"vm_port_range_count": -1}]
    )
    def test_an_unusable_window_is_refused(self, relays, window):
        with pytest.raises(RelayValidationError):
            _make_relay(relays, **window)

    def test_a_window_running_past_the_port_space_is_refused(self, relays):
        with pytest.raises(RelayValidationError):
            _make_relay(relays, vm_port_range_start=65500, vm_port_range_count=100)


class TestTokenConfidentiality:
    def test_a_stored_token_is_ciphertext(self, relays, session_factory):
        _make_relay(relays, token="admission-secret")
        with Session(session_factory.kw["bind"]) as db:
            stored = db.get(Relay, "site-a").relay_token_encrypted
        assert stored is not None
        assert "admission-secret" not in stored

    def test_the_stored_token_needs_the_profile_key_to_recover(self, relays, session_factory):
        _make_relay(relays, token="admission-secret")
        with Session(session_factory.kw["bind"]) as db:
            stored = db.get(Relay, "site-a").relay_token_encrypted
        assert Fernet(_KEY.encode()).decrypt(stored.encode()).decode() == "admission-secret"
        with pytest.raises(Exception):
            Fernet(Fernet.generate_key()).decrypt(stored.encode())

    def test_no_relay_view_carries_the_token(self, relays):
        view = _make_relay(relays, token="admission-secret")
        assert "admission-secret" not in repr(view)
        assert not hasattr(view, "relay_token_encrypted")

    def test_a_view_reports_whether_a_token_is_configured(self, relays):
        assert _make_relay(relays, relay_id="bare").token_configured is False
        assert (
            _make_relay(
                relays, relay_id="ready", relay_addr="10.0.0.10", token="t"
            ).token_configured
            is True
        )

    def test_rotation_replaces_the_token(self, relays, session_factory):
        _make_relay(relays, token="first")
        relays.rotate_token("site-a", "second")
        with Session(session_factory.kw["bind"]) as db:
            stored = db.get(Relay, "site-a").relay_token_encrypted
        assert Fernet(_KEY.encode()).decrypt(stored.encode()).decode() == "second"

    def test_a_token_cannot_be_cleared_by_rotation(self, relays):
        """Clearing one disables every VM path on that relay, so it is not
        something an empty value should be able to express."""
        _make_relay(relays, token="first")
        with pytest.raises(RelayValidationError):
            relays.rotate_token("site-a", "")


class TestTheReaderSplit:
    """The redacted read has the unqualified name; only execution resolves."""

    def _pool_with_relay(self, session_factory, relays, handler):
        _make_relay(relays, token="admission-secret")
        with session_factory() as db, db.begin():
            db.add(ResourcePool(id="gpu-pool", label="GPU", provider="ansible", enabled=True))
            handler.replace_config(
                db,
                "gpu-pool",
                {"playbook_path": _PLAYBOOK_PATH, "relay_id": "site-a"},
            )

    def test_the_plain_read_returns_the_reference_and_no_token(
        self, session_factory, relays, settings
    ):
        handler = AnsiblePoolConfigHandler(settings=settings)
        self._pool_with_relay(session_factory, relays, handler)
        with session_factory() as db:
            config = handler.read_config(db, "gpu-pool")
        assert config["relay_id"] == "site-a"
        assert "relay_token" not in config
        assert "relay_addr" not in config

    def test_the_execution_read_resolves_the_relay_and_decrypts(
        self, session_factory, relays, settings
    ):
        handler = AnsiblePoolConfigHandler(settings=settings)
        self._pool_with_relay(session_factory, relays, handler)
        with session_factory() as db:
            config = handler.read_config_for_execution(db, "gpu-pool")
        assert config["relay_addr"] == "10.0.0.9"
        assert config["vm_port_range_start"] == 6100
        assert config["relay_token"] == "admission-secret"

    def test_a_pool_with_no_relay_resolves_to_no_relay_fields(
        self, session_factory, settings
    ):
        handler = AnsiblePoolConfigHandler(settings=settings)
        with session_factory() as db, db.begin():
            db.add(ResourcePool(id="nat-pool", label="NAT", provider="ansible", enabled=True))
            handler.replace_config(db, "nat-pool", {"playbook_path": _PLAYBOOK_PATH})
        with session_factory() as db:
            config = handler.read_config_for_execution(db, "nat-pool")
        assert config["relay_id"] is None
        assert "relay_token" not in config

    def test_a_disabled_relay_resolves_to_no_relay_fields(
        self, session_factory, relays, settings
    ):
        """So the single rejection point for an unusable relay stays in
        pre-dispatch validation rather than being split across two layers."""
        handler = AnsiblePoolConfigHandler(settings=settings)
        self._pool_with_relay(session_factory, relays, handler)
        relays.set_enabled("site-a", False)
        with session_factory() as db:
            config = handler.read_config_for_execution(db, "gpu-pool")
        assert "relay_token" not in config

    def test_the_relay_endpoint_is_not_writable_as_pool_configuration(
        self, session_factory, settings
    ):
        """The window belongs to the relay. Accepting it here is what would
        let two pools disagree about one listening namespace."""
        handler = AnsiblePoolConfigHandler(settings=settings)
        normalized, problems = handler.validate_config_problems(
            {"playbook_path": _PLAYBOOK_PATH, "vm_port_range_start": 6100}
        )
        assert normalized is None
        assert any(p.code == "unknown_field" for p in problems)


class TestRelayDefinitionDocuments:
    def _document(self, **overrides):
        entry = {
            "id": "site-a",
            "relay_addr": "10.0.0.9",
            "relay_port": 7000,
            "vm_port_range_start": 6100,
            "vm_port_range_count": 100,
            "token_secret_key": "relay_token",
        }
        entry.update(overrides)
        return {"relays": [entry]}

    def _yaml(self, **overrides):
        import yaml

        return yaml.safe_dump(self._document(**overrides))

    def test_a_named_profile_key_supplies_the_token(self, relays, settings, session_factory):
        import_relay_definitions(
            self._yaml(), relay_service=relays, settings=settings
        )
        with Session(session_factory.kw["bind"]) as db:
            stored = db.get(Relay, "site-a").relay_token_encrypted
        assert Fernet(_KEY.encode()).decrypt(stored.encode()).decode() == "bootstrap-token"

    def test_a_missing_profile_key_fails_naming_it(self, relays, settings):
        with pytest.raises(RelayDefinitionError) as excinfo:
            import_relay_definitions(
                self._yaml(token_secret_key="absent_key"),
                relay_service=relays,
                settings=settings,
            )
        assert "absent_key" in str(excinfo.value)

    def test_a_relay_is_not_created_when_its_key_is_missing(self, relays, settings):
        with pytest.raises(RelayDefinitionError):
            import_relay_definitions(
                self._yaml(token_secret_key="absent_key"),
                relay_service=relays,
                settings=settings,
            )
        assert relays.list_relays() == []

    def test_a_rotated_token_survives_a_reconciliation(
        self, relays, settings, session_factory
    ):
        """The one field a reconciliation must never revert.

        The document still names the profile key holding the bootstrap value.
        Re-reading it would silently undo an operator's rotation on any edit to
        an unrelated field.
        """
        import_relay_definitions(self._yaml(), relay_service=relays, settings=settings)
        relays.rotate_token("site-a", "rotated-by-operator")

        import_relay_definitions(
            self._yaml(vm_port_range_count=50),
            relay_service=relays,
            settings=settings,
        )

        with Session(session_factory.kw["bind"]) as db:
            row = db.get(Relay, "site-a")
        assert row.vm_port_range_count == 50
        assert (
            Fernet(_KEY.encode()).decrypt(row.relay_token_encrypted.encode()).decode()
            == "rotated-by-operator"
        )

    def test_an_unchanged_document_reports_everything_unchanged(self, relays, settings):
        import_relay_definitions(self._yaml(), relay_service=relays, settings=settings)
        diff = import_relay_definitions(
            self._yaml(), relay_service=relays, settings=settings
        )
        assert diff.unchanged == ("site-a",)
        assert diff.created == ()
        assert diff.updated == ()

    def test_an_edited_document_updates_the_relay(self, relays, settings):
        import_relay_definitions(self._yaml(), relay_service=relays, settings=settings)
        diff = import_relay_definitions(
            self._yaml(vm_port_range_start=7100),
            relay_service=relays,
            settings=settings,
        )
        assert diff.updated == ("site-a",)
        assert relays.get_relay("site-a").vm_port_range_start == 7100

    def test_an_unknown_field_is_refused(self):
        import yaml

        document = self._document()
        document["relays"][0]["token_secret_kye"] = "relay_token"
        with pytest.raises(RelayDefinitionError) as excinfo:
            parse_relay_definitions(yaml.safe_dump(document))
        assert "token_secret_kye" in str(excinfo.value)

    def test_two_entries_on_one_rendezvous_are_refused(self):
        import yaml

        document = self._document()
        second = dict(document["relays"][0])
        second["id"] = "site-b"
        document["relays"].append(second)
        with pytest.raises(RelayDefinitionError):
            parse_relay_definitions(yaml.safe_dump(document))

    def test_a_missing_required_field_names_it(self):
        import yaml

        document = self._document()
        del document["relays"][0]["vm_port_range_count"]
        with pytest.raises(RelayDefinitionError) as excinfo:
            parse_relay_definitions(yaml.safe_dump(document))
        assert "vm_port_range_count" in str(excinfo.value)


class TestTheDigestGate:
    """Reconciliation follows a change to a document, not a process start.

    Import is idempotent with respect to the document, not the database.
    Applying it on every startup reverts whatever else changed the database,
    silently, on eviction, drain, and crash recovery.
    """

    def _importer(self, session_factory, settings):
        from compute_provisioning_service.services.definition_documents import (
            DefinitionDocumentImporter,
        )

        return DefinitionDocumentImporter(
            session_factory=session_factory,
            settings=settings,
            pool_service=None,
            relay_service=None,
        )

    def test_nothing_is_recorded_before_a_first_import(self, session_factory):
        with session_factory() as db:
            assert db.get(DefinitionDocumentImport, "relays") is None

    def test_a_changed_document_produces_a_different_digest(
        self, session_factory, settings
    ):
        importer = self._importer(session_factory, settings)
        assert importer.digest_of("relays: []\n") != importer.digest_of("relays: [1]\n")

    def test_a_digest_is_written_and_read_back(self, session_factory, settings):
        importer = self._importer(session_factory, settings)
        digest = importer.digest_of("relays: []\n")
        with session_factory() as db, db.begin():
            importer._record_digest(db, "relays", digest)
        with session_factory() as db:
            assert importer._recorded_digest(db, "relays") == digest

    def test_recording_twice_updates_rather_than_duplicating(
        self, session_factory, settings
    ):
        importer = self._importer(session_factory, settings)
        with session_factory() as db, db.begin():
            importer._record_digest(db, "pools", importer.digest_of("a"))
        with session_factory() as db, db.begin():
            importer._record_digest(db, "pools", importer.digest_of("b"))
        with session_factory() as db:
            assert importer._recorded_digest(db, "pools") == importer.digest_of("b")
            assert db.query(DefinitionDocumentImport).count() == 1

    def test_pools_and_relays_are_tracked_separately(self, session_factory, settings):
        importer = self._importer(session_factory, settings)
        with session_factory() as db, db.begin():
            importer._record_digest(db, "pools", importer.digest_of("pool-doc"))
        with session_factory() as db:
            assert importer._recorded_digest(db, "relays") is None
            assert importer._recorded_digest(db, "pools") is not None


class TestRebinding:
    """A relay binding is fixed for a VM's life.

    The buyer holds a rendezvous address and a port. Both are delivered, and a
    remote port is not portable between relays — 6142 on one says nothing about
    6142 on another, which may already be leased. So a rebinding that moved
    existing VMs would strand every buyer on the affected hosts, and these
    rules refuse it rather than accept it and reissue connection strings the
    system has no way to deliver.
    """

    def _make_lease(self, session_factory, *, relay_id="site-a",
                    pool_id="gpu-pool", host="kvm1"):
        from compute_provisioning_service.db.models import RelayPortLease

        with session_factory() as db, db.begin():
            db.add(
                RelayPortLease(
                    id=f"lease-{relay_id}",
                    relay_id=relay_id,
                    remote_port=6100,
                    host_name=host,
                    pool_id=pool_id,
                    owner_kind="fulfillment",
                    owner_id=f"cr-{relay_id}",
                )
            )

    def _relay_with_lease(self, session_factory, relays, *, relay_id="site-a",
                          addr="10.0.0.9", pool_id="gpu-pool", host="kvm1"):
        _make_relay(relays, relay_id=relay_id, relay_addr=addr)
        self._make_lease(
            session_factory, relay_id=relay_id, pool_id=pool_id, host=host
        )

    def _pool_on_relay(self, session_factory, handler, *, pool_id, relay_id):
        """A pool already pointing at a relay. Written before any lease exists,
        which is the real order: a lease is what a VM on that pool produced."""
        with session_factory() as db, db.begin():
            db.add(ResourcePool(id=pool_id, label=pool_id, provider="ansible", enabled=True))
            handler.replace_config(
                db, pool_id,
                {"playbook_path": _PLAYBOOK_PATH, "relay_id": relay_id},
            )

    def test_a_relay_cannot_move_while_it_carries_tunnels(
        self, session_factory, relays
    ):
        self._relay_with_lease(session_factory, relays)
        with pytest.raises(RelayRebindingRefused) as excinfo:
            relays.update_relay("site-a", relay_addr="10.0.0.20")
        message = str(excinfo.value)
        assert "kvm1:6100" in message
        assert "Disable the pool" in message

    def test_a_relay_can_move_once_drained(self, session_factory, relays):
        from compute_provisioning_service.db.models import RelayPortLease
        from datetime import datetime, timezone

        self._relay_with_lease(session_factory, relays)
        with session_factory() as db, db.begin():
            db.query(RelayPortLease).one().released_at = datetime.now(timezone.utc)

        assert relays.update_relay("site-a", relay_addr="10.0.0.20").relay_addr == "10.0.0.20"

    def test_a_relay_edit_that_does_not_move_it_is_unaffected(
        self, session_factory, relays
    ):
        """Only the endpoint is protected. A window or label change touches
        nothing a buyer holds."""
        self._relay_with_lease(session_factory, relays)
        assert relays.update_relay("site-a", label="renamed").label == "renamed"
        assert relays.update_relay("site-a", vm_port_range_count=50).vm_port_range_count == 50

    def test_a_pool_cannot_be_repointed_while_its_hosts_hold_leases(
        self, session_factory, relays, settings
    ):
        handler = AnsiblePoolConfigHandler(settings=settings)
        _make_relay(relays, relay_id="site-a", relay_addr="10.0.0.9")
        _make_relay(relays, relay_id="site-b", relay_addr="10.0.0.10")
        self._pool_on_relay(session_factory, handler, pool_id="gpu-pool", relay_id="site-a")
        self._make_lease(session_factory, relay_id="site-a", pool_id="gpu-pool")

        with session_factory() as db, db.begin():
            with pytest.raises(RelayRebindingRefused):
                handler.replace_config(
                    db, "gpu-pool",
                    {"playbook_path": _PLAYBOOK_PATH, "relay_id": "site-b"},
                )

    def test_a_carrying_relay_cannot_have_its_token_rotated(
        self, session_factory, relays
    ):
        """Rotation joins the drain rule, for a different reason than the
        endpoint does.

        It does not change the address or port a buyer holds — but a host
        adopts a new token only by restarting its tunnel client, since `auth`
        is not reloadable, and that restart drops every proxy the client
        registered. `frps` also admits on one token, so a rotation invalidates
        every client still holding the old one.
        """
        self._relay_with_lease(session_factory, relays)

        with pytest.raises(RelayRebindingRefused) as excinfo:
            relays.rotate_token("site-a", "rotated")

        assert "kvm1:6100" in str(excinfo.value)

    def test_a_token_can_be_set_before_any_host_dials(self, relays):
        """The ordinary case is unaffected: a relay with no leases has nothing
        to disturb."""
        _make_relay(relays)

        assert relays.rotate_token("site-a", "first-token").token_configured is True

    def test_a_token_can_be_rotated_once_drained(self, session_factory, relays):
        from datetime import datetime, timezone

        from compute_provisioning_service.db.models import RelayPortLease

        self._relay_with_lease(session_factory, relays)
        with session_factory() as db, db.begin():
            db.query(RelayPortLease).one().released_at = datetime.now(timezone.utc)

        assert relays.rotate_token("site-a", "rotated").token_configured is True

    def test_a_pool_write_that_keeps_its_relay_is_unaffected(
        self, session_factory, relays, settings
    ):
        handler = AnsiblePoolConfigHandler(settings=settings)
        _make_relay(relays, relay_id="site-a", relay_addr="10.0.0.9")
        self._pool_on_relay(session_factory, handler, pool_id="gpu-pool", relay_id="site-a")
        self._make_lease(session_factory, relay_id="site-a", pool_id="gpu-pool")
        with session_factory() as db, db.begin():
            handler.replace_config(
                db, "gpu-pool",
                {"playbook_path": "/other/playbook.yaml", "relay_id": "site-a"},
            )
        with session_factory() as db:
            assert handler.read_config(db, "gpu-pool")["playbook_path"] == "/other/playbook.yaml"


class TestExecutionTimeTokenResolution:
    """The token is resolved here and nowhere earlier.

    Earlier, it travelled in the accepted operation — which is persisted in a
    JSON column and returned by the job endpoints, so the credential was
    neither encrypted at rest nor withheld from a read. Resolving at execution
    also means a rotation reaches a retry of a job accepted before it.
    """

    def _resolver(self, session_factory, settings):
        from compute_provisioning_service.services.relay_execution import (
            RelayExecutionResolver,
        )

        return RelayExecutionResolver(session_factory=session_factory, settings=settings)

    def _params(self, **overrides):
        from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams

        fields = {"vm_host": "kvm1", "vm_action": "create", "executor_kind": "vm"}
        fields.update(overrides)
        return AnsibleJobParams(**fields)

    def test_a_job_with_no_relay_passes_through(self, session_factory, settings):
        params = self._params()
        assert self._resolver(session_factory, settings).resolve_into(params) is params

    def test_the_address_and_token_are_filled_in(self, relays, session_factory, settings):
        _make_relay(relays, token="admission-token")
        resolved = self._resolver(session_factory, settings).resolve_into(
            self._params(relay_id="site-a", vm_remote_port=6100)
        )
        assert resolved.relay_addr == "10.0.0.9"
        assert resolved.relay_port == 7000
        assert resolved.relay_token == "admission-token"

    def test_a_rotated_token_reaches_the_rendered_job_variables(
        self, relays, session_factory, settings
    ):
        """How far the service-side path carries a rotation, and no further.

        Asserted through what a job runs with rather than through a successful
        write to the relay row: a rotation that stores correctly and never
        reaches a playbook has changed nothing an operator cares about.

        This does **not** show that the host's tunnel client adopts the token.
        That needs the client's own configuration rewritten and the client
        restarted, which `vm-create.yml` does and `test_vm_management_contracts`
        pins; whether the restart behaves as intended against a real relay is
        the live gate's business. An earlier name for this test claimed
        rotation took effect "without a restart", which was true of the
        variables and false of the host.
        """
        from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams
        from vm_provisioning_adapter.services.ansible_service import AnsibleService

        _make_relay(relays, token="original")
        params = AnsibleJobParams(
            vm_host="kvm1",
            vm_action="create",
            executor_kind="vm",
            relay_id="site-a",
            vm_remote_port=6100,
        )
        relays.rotate_token("site-a", "rotated")

        resolved = self._resolver(session_factory, settings).resolve_into(params)
        lines = AnsibleService(settings)._build_builtin_var_lines(resolved)

        assert 'frp_auth_token: "rotated"' in lines
        assert "original" not in "\n".join(lines)

    def test_a_rotation_reaches_a_job_accepted_before_it(
        self, relays, session_factory, settings
    ):
        """The second reason for late binding. A snapshot would pin the value
        that was correct at acceptance, which after a rotation is exactly the
        value that no longer works."""
        _make_relay(relays, token="original")
        params = self._params(relay_id="site-a", vm_remote_port=6100)
        relays.rotate_token("site-a", "rotated")

        resolved = self._resolver(session_factory, settings).resolve_into(params)

        assert resolved.relay_token == "rotated"

    @pytest.mark.parametrize(
        "break_it, expected",
        [
            (lambda r: r.set_enabled("site-a", False), "disabled"),
            (lambda r: None, "no admission token"),
        ],
    )
    def test_an_unusable_relay_fails_the_job(
        self, relays, session_factory, settings, break_it, expected
    ):
        from compute_provisioning_service.services.relay_execution import (
            RelayUnusableAtExecutionError,
        )

        _make_relay(relays, token="admission-token" if expected == "disabled" else None)
        break_it(relays)
        with pytest.raises(RelayUnusableAtExecutionError) as excinfo:
            self._resolver(session_factory, settings).resolve_into(
                self._params(relay_id="site-a", vm_remote_port=6100)
            )
        assert expected in str(excinfo.value)

    def test_a_vanished_relay_fails_the_job(self, session_factory, settings):
        from compute_provisioning_service.services.relay_execution import (
            RelayUnusableAtExecutionError,
        )

        with pytest.raises(RelayUnusableAtExecutionError):
            self._resolver(session_factory, settings).resolve_into(
                self._params(relay_id="never-created", vm_remote_port=6100)
            )
