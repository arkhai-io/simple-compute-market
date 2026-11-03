"""Host definitions documents against a real SQLite database.

Reconciliation runs in a caller's session through the host authority, so what
it writes, what it leaves alone, which hooks it runs, and what a rollback
discards are proved here against real persistence. A fake codec stands in for a
connection kind, with the rules of ``ssh`` that equality and keys turn on: it
fills ``port`` and ``user`` with defaults in its canonical form, names a key by
``key_path`` or protects a submitted ``token``, keeps a stored token when a
connection names no key path, and refuses a connection naming no key at all.
It stores ``key_path`` as null when none is named, as ``ssh`` stores it, but
none of ``ssh``'s other optional fields.
"""

from __future__ import annotations

import pytest
import yaml
from compute_provisioning_contracts import (
    ConnectionSubmission,
    HostCreate,
    HostDefinitionsImportRequest,
    HostDefinitionsImportResponse,
)
from market_resource_pools.db import Base as PoolsBase
from market_resource_pools.db import ResourcePool
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning.hosts import ConnectionCodecs, ConnectionEnvelope, ProtectedValue
from compute_provisioning.hosts.db import Base as HostsBase
from compute_provisioning.hosts.db import Host
from compute_provisioning.hosts.definitions import (
    reconcile_host_definitions_in_session,
    render_host_definitions,
)
from compute_provisioning.hosts.route_service import HostRouteService
from compute_provisioning.hosts.service import (
    ConnectionChangeRefusedError,
    HostAuthority,
    PoolChangeRefusedError,
)
from compute_provisioning.route_errors import ProvisioningRouteError

_PUBLIC_FIELDS = frozenset({"address", "port", "user", "key_path"})


class _KeyedCodec:
    kind, version = "fake", 2

    def build(self, public, secrets, *, previous=None):
        unknown = sorted(set(public) - _PUBLIC_FIELDS)
        if unknown:
            raise ValueError(f"fake connection: unknown fields {unknown}")
        protected = {}
        if "token" in secrets:
            protected["token"] = ProtectedValue("reverse-v1", secrets["token"][::-1])
        elif public.get("key_path") is None and previous is not None and "token" in previous.protected:
            protected["token"] = previous.protected["token"]
        return self.validate(ConnectionEnvelope(kind="fake", version=2, public=public, protected=protected))

    def validate(self, envelope):
        """The canonical form: defaults filled, exactly one key named."""
        public = envelope.public
        if "address" not in public:
            raise ValueError("fake connection needs an address")
        fields = {
            "address": public["address"],
            "port": public.get("port", 22),
            "user": public.get("user", "root"),
            "key_path": public.get("key_path"),
        }
        if (fields["key_path"] is None) == ("token" not in envelope.protected):
            raise ValueError("fake connection: exactly one of key_path and token names the key")
        return ConnectionEnvelope(kind="fake", version=2, public=fields, protected=dict(envelope.protected))


@pytest.fixture
def engine():
    return _with_pools(
        create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    )


def _with_pools(engine):
    """``engine`` with the pool and host tables and three pools."""
    PoolsBase.metadata.create_all(engine)
    HostsBase.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        for pool_id in ("default", "gpu", "other"):
            db.add(ResourcePool(id=pool_id, label=pool_id, provider="test", policy_tags={}))
        db.commit()
    return engine


@pytest.fixture
def host_writes(engine):
    """Every INSERT or UPDATE of the hosts table, as issued."""
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT INTO HOSTS", "UPDATE HOSTS")):
            statements.append(statement)

    return statements


@pytest.fixture
def moves():
    return []


@pytest.fixture
def refused_hosts():
    """Hosts every pool-change hook move of which is refused."""
    return set()


@pytest.fixture
def authority(engine, moves, refused_hosts):
    def hook(db, host_id, current, new):
        if host_id in refused_hosts:
            raise PoolChangeRefusedError(f"{host_id} holds what this pool protects")
        moves.append((host_id, current, new))

    return HostAuthority(
        sessionmaker(bind=engine), codecs=ConnectionCodecs([_KeyedCodec()]), pool_change_hooks=(hook,)
    )


def _register(authority, host_id, *, pool_id=None, enabled=True, token=None, **public):
    public = {"address": "192.0.2.10", **public}
    if token is None:
        public.setdefault("key_path", "/keys/id")
    authority.register_host(
        HostCreate(
            host_id=host_id,
            pool_id=pool_id,
            enabled=enabled,
            connection=ConnectionSubmission(
                kind="fake", version=2, public=public, secrets={"token": token} if token else {}
            ),
        )
    )


def _entry(host_id, *, pool_id=None, enabled=None, **public) -> dict:
    entry = {"host_id": host_id}
    if pool_id is not None:
        entry["pool_id"] = pool_id
    if enabled is not None:
        entry["enabled"] = enabled
    entry["connection"] = {"kind": "fake", "version": 2, "public": {"address": "192.0.2.10", **public}}
    return entry


def _document(*entries) -> str:
    return yaml.safe_dump({"hosts": list(entries)})


def _apply(authority, yaml_text, *, commit=True):
    """Reconcile in one session; commit a valid outcome when asked, else roll back."""
    with authority.session() as db:
        outcome = reconcile_host_definitions_in_session(db, authority, yaml_text)
        if outcome.valid and commit:
            db.commit()
        else:
            db.rollback()
    return outcome


def _codes(outcome) -> list[tuple[str, str]]:
    return [(problem.path, problem.code) for problem in outcome.problems]


# --- "A host definitions entry declares the whole host" ------------------------


def test_an_entry_omitting_the_pool_unplaces_a_placed_host_through_the_hooks(authority, moves) -> None:
    _register(authority, "kvm1", pool_id="gpu")
    moves.clear()

    outcome = _apply(authority, _document(_entry("kvm1", key_path="/keys/id")))

    assert outcome.valid and outcome.diff.updated == ["kvm1"]
    assert authority.get_host("kvm1").pool_id is None
    assert moves == [("kvm1", "gpu", None)]


def test_an_entry_omitting_enabled_enables_a_disabled_host(authority) -> None:
    _register(authority, "kvm1", enabled=False)

    outcome = _apply(authority, _document(_entry("kvm1", key_path="/keys/id")))

    assert outcome.diff.updated == ["kvm1"]
    assert authority.get_host("kvm1").enabled is True


def test_an_entry_equal_to_the_stored_host_writes_nothing_and_runs_no_hook(
    authority, moves, host_writes
) -> None:
    _register(authority, "kvm1", pool_id="gpu")
    assert host_writes, "the recorder sees the registration's insert"
    host_writes.clear()
    moves.clear()
    document = _document(_entry("kvm1", pool_id="gpu", enabled=False, key_path="/keys/id"))
    assert _apply(authority, document).diff.updated == ["kvm1"]
    assert host_writes, "the recorder sees the update an unequal entry issues"
    before = authority.get_host("kvm1")
    host_writes.clear()

    outcome = _apply(authority, document)

    assert outcome.valid and outcome.diff.unchanged == ["kvm1"]
    assert (outcome.diff.created, outcome.diff.updated) == ([], [])
    assert host_writes == [] and moves == []
    assert authority.get_host("kvm1").updated_at == before.updated_at


def test_an_entry_omitting_fields_its_codec_defaults_equals_the_stored_defaults(
    authority, host_writes, moves
) -> None:
    _register(authority, "kvm1", pool_id="gpu", port=22, user="root")
    host_writes.clear()
    moves.clear()

    outcome = _apply(authority, _document(_entry("kvm1", pool_id="gpu", key_path="/keys/id")))

    assert outcome.diff.unchanged == ["kvm1"]
    assert host_writes == [] and moves == []


def test_an_entry_naming_no_key_for_a_host_holding_a_key_file_is_refused(authority) -> None:
    _register(authority, "kvm1", address="192.0.2.10")

    outcome = _apply(authority, _document(_entry("kvm1", address="198.51.100.1")))

    assert _codes(outcome) == [("hosts[0].connection", "invalid_connection")]
    assert "kvm1" in outcome.problems[0].message
    assert authority.get_host("kvm1").connection.public["address"] == "192.0.2.10"


def test_an_entry_naming_no_key_keeps_a_stored_protected_key(authority) -> None:
    _register(authority, "kvm1", token="s3cret")

    outcome = _apply(authority, _document(_entry("kvm1", address="198.51.100.1")))

    assert outcome.valid and outcome.diff.updated == ["kvm1"]
    stored = authority.lookup("kvm1").connection
    assert stored.public["address"] == "198.51.100.1"
    assert stored.protected["token"].ciphertext == "terc3s"


def test_an_entry_naming_no_key_for_a_new_host_is_refused(authority) -> None:
    outcome = _apply(authority, _document(_entry("kvm1")))

    assert _codes(outcome) == [("hosts[0].connection", "invalid_connection")]
    assert authority.get_host("kvm1") is None


def test_an_empty_hosts_list_writes_nothing_and_reports_every_host_not_named(
    authority, host_writes
) -> None:
    _register(authority, "kvm2")
    _register(authority, "kvm1")
    host_writes.clear()

    outcome = _apply(authority, "hosts: []\n")

    assert outcome.valid
    assert outcome.diff.model_dump() == {"created": [], "updated": [], "unchanged": []}
    assert outcome.not_named == ("kvm1", "kvm2")
    assert host_writes == []


def test_a_new_host_is_registered_as_its_entry_states(authority, moves) -> None:
    outcome = _apply(
        authority, _document(_entry("kvm1", pool_id="gpu", enabled=False, key_path="/keys/id"))
    )

    assert outcome.diff.created == ["kvm1"]
    host = authority.get_host("kvm1")
    assert (host.pool_id, host.enabled) == ("gpu", False)
    assert host.connection.public == {"address": "192.0.2.10", "port": 22, "user": "root", "key_path": "/keys/id"}
    # Placed as a move from no pool, as a registration is.
    assert moves == [("kvm1", None, "gpu")]


# --- "A host definitions document retains the hosts it does not name" ----------


def test_a_document_that_stops_naming_a_host_leaves_it_and_reports_it(authority) -> None:
    _register(authority, "kvm1", pool_id="gpu", enabled=False)

    outcome = _apply(authority, _document(_entry("kvm2", key_path="/keys/id")))

    assert outcome.valid and outcome.diff.created == ["kvm2"]
    assert outcome.not_named == ("kvm1",)
    kvm1 = authority.get_host("kvm1")
    assert (kvm1.pool_id, kvm1.enabled) == ("gpu", False)


# --- Two-stage validation and every refusal ------------------------------------


def test_a_structural_problem_stops_the_stored_state_check(authority) -> None:
    """The scenario "A document has structural and stored-state problems" of the
    physical-provisioning requirement "A host definitions document is validated
    whole and carries no credential"."""
    document = _document(
        {**_entry("kvm1", key_path="/keys/id"), "rack": "r1"},
        _entry("kvm2", pool_id="no-such-pool", key_path="/keys/id"),
    )

    outcome = _apply(authority, document)

    assert _codes(outcome) == [("hosts[0].rack", "unknown_field")]
    assert (outcome.diff.created, outcome.not_named) == ([], ())
    assert authority.get_host("kvm2") is None


def test_a_hook_refusal_and_an_unknown_pool_are_both_reported_and_nothing_applies(
    authority, refused_hosts
) -> None:
    _register(authority, "kvm1", pool_id="gpu")
    refused_hosts.add("kvm1")

    outcome = _apply(
        authority,
        _document(
            _entry("kvm3", key_path="/keys/id"),
            _entry("kvm2", pool_id="no-such-pool", key_path="/keys/id"),
            _entry("kvm1", pool_id="other", key_path="/keys/id"),
        ),
    )

    assert _codes(outcome) == [
        ("hosts[1].pool_id", "unknown_pool"),
        ("hosts[2].pool_id", "pool_change_refused"),
    ]
    assert "kvm1" in outcome.problems[1].message
    assert authority.get_host("kvm3") is None
    assert authority.get_host("kvm1").pool_id == "gpu"


def test_a_refused_unplacing_leaves_every_host_the_document_names(authority, refused_hosts) -> None:
    """The ``resource-pool-management`` scenario "A host definitions entry omits
    the pool of a placed host", with a hook refusing it."""
    _register(authority, "kvm1", pool_id="gpu")
    _register(authority, "kvm2", pool_id="default")
    refused_hosts.add("kvm1")

    outcome = _apply(
        authority,
        _document(
            _entry("kvm2", pool_id="default", address="198.51.100.2", key_path="/keys/id"),
            _entry("kvm1", key_path="/keys/id"),
        ),
    )

    assert _codes(outcome) == [("hosts[1].pool_id", "pool_change_refused")]
    assert authority.get_host("kvm1").pool_id == "gpu"
    assert authority.get_host("kvm2").connection.public["address"] == "192.0.2.10"


def test_a_refused_connection_change_is_reported_as_a_refused_pool_change(engine) -> None:
    """A placed host given a new connection in place meets the
    connection-change hooks, and their refusal is one of the document's
    problems, coded as a pool-change hook's is."""
    def refuse(db, host_id, pool_id):
        raise ConnectionChangeRefusedError(f"{host_id} may not be reached there from {pool_id}")

    guarded = HostAuthority(
        sessionmaker(bind=engine), codecs=ConnectionCodecs([_KeyedCodec()]), connection_change_hooks=(refuse,)
    )
    _register(guarded, "kvm1", pool_id="gpu")

    outcome = _apply(
        guarded, _document(_entry("kvm1", pool_id="gpu", address="198.51.100.1", key_path="/keys/id"))
    )

    assert _codes(outcome) == [("hosts[0].pool_id", "pool_change_refused")]
    assert "kvm1" in outcome.problems[0].message
    assert guarded.get_host("kvm1").connection.public["address"] == "192.0.2.10"


def test_an_unserved_kind_or_version_is_a_connection_refusal(authority) -> None:
    document = _document(
        {"host_id": "a", "connection": {"kind": "redfish", "version": 1, "public": {}}},
        {"host_id": "b", "connection": {"kind": "fake", "version": 3, "public": {"address": "x"}}},
    )

    outcome = _apply(authority, document)

    assert _codes(outcome) == [
        ("hosts[0].connection", "invalid_connection"),
        ("hosts[1].connection", "invalid_connection"),
    ]


# --- "The host registry exports a canonical host definitions document" --------


def _store_row(engine, host_id, *, kind, version, public=None) -> None:
    """A host stored as no current write would store it — at a kind or version
    this composition does not serve, or in an older normal form — so it is set
    up directly."""
    with sessionmaker(bind=engine)() as db:
        db.add(
            Host(
                host_id=host_id,
                connection_kind=kind,
                connection_version=version,
                connection_public=public or {"address": "192.0.2.99"},
                connection_protected={},
                enabled=True,
            )
        )
        db.commit()


def test_a_host_stored_in_an_older_normal_form_equals_its_canonical_entry(
    authority, engine, host_writes
) -> None:
    """Equality reads the stored connection through its codec too, so a row
    lacking a field the codec now fills is unchanged by an entry stating it,
    and by an unedited export."""
    _store_row(engine, "kvm1", kind="fake", version=2, public={"address": "192.0.2.99", "key_path": "/keys/id"})
    host_writes.clear()

    stated = _apply(
        authority, _document(_entry("kvm1", address="192.0.2.99", port=22, key_path="/keys/id"))
    )
    exported = render_host_definitions(authority.host_definitions())
    reimported = _apply(authority, exported)

    assert stated.diff.unchanged == ["kvm1"] and reimported.diff.unchanged == ["kvm1"]
    assert yaml.safe_load(exported)["hosts"][0]["connection"]["public"] == {
        "address": "192.0.2.99", "port": 22, "user": "root", "key_path": "/keys/id"
    }
    assert host_writes == []


def test_an_unedited_export_imports_as_every_host_unchanged(authority, moves, host_writes) -> None:
    _register(authority, "kvm2", pool_id="gpu", port=2222, user="ubuntu")
    _register(authority, "kvm1", enabled=False)
    _register(authority, "bm1", pool_id="default", token="s3cret")
    host_writes.clear()
    moves.clear()

    exported = render_host_definitions(authority.host_definitions())
    outcome = _apply(authority, exported)
    entries = yaml.safe_load(exported)["hosts"]

    assert [entry["host_id"] for entry in entries] == ["bm1", "kvm1", "kvm2"]
    assert [(entry["pool_id"], entry["enabled"]) for entry in entries] == [
        ("default", True), (None, False), ("gpu", True)
    ]
    assert outcome.valid
    assert outcome.diff.unchanged == ["bm1", "kvm1", "kvm2"]
    assert (outcome.diff.created, outcome.diff.updated, outcome.not_named) == ([], [], ())
    assert host_writes == [] and moves == []


def test_an_exported_host_holding_a_protected_key_states_no_key(authority) -> None:
    _register(authority, "bm1", token="s3cret")

    exported = render_host_definitions(authority.host_definitions())
    entry = yaml.safe_load(exported)["hosts"][0]

    assert "key_path" not in entry["connection"]["public"]
    assert "secrets" not in entry["connection"]
    assert "terc3s" not in exported and "s3cret" not in exported
    assert _apply(authority, exported).diff.unchanged == ["bm1"]
    assert authority.lookup("bm1").connection.protected["token"].ciphertext == "terc3s"


def test_a_host_at_an_unserved_version_is_not_exported_and_is_left_on_import(
    authority, engine
) -> None:
    _register(authority, "kvm1")
    _store_row(engine, "legacy", kind="fake", version=1)

    exported = render_host_definitions(authority.host_definitions())
    outcome = _apply(authority, exported)

    assert [entry["host_id"] for entry in yaml.safe_load(exported)["hosts"]] == ["kvm1"]
    assert outcome.valid and outcome.not_named == ("legacy",)
    with sessionmaker(bind=engine)() as db:
        assert db.get(Host, "legacy").connection_version == 1


def test_a_host_its_codec_now_refuses_is_exported_and_its_import_reports_it(
    authority, engine
) -> None:
    """Only an unserved kind or version leaves a host out of the export; one
    stored at a served version its codec refuses is stated as stored, and the
    import names it rather than passing over it."""
    _register(authority, "kvm1")
    _store_row(engine, "keyless", kind="fake", version=2, public={"address": "192.0.2.99"})

    exported = render_host_definitions(authority.host_definitions())
    outcome = _apply(authority, exported)

    assert [entry["host_id"] for entry in yaml.safe_load(exported)["hosts"]] == ["keyless", "kvm1"]
    assert _codes(outcome) == [("hosts[0].connection", "invalid_connection")]


def test_a_host_no_entry_can_name_is_exported_and_its_import_reports_it(authority) -> None:
    """A host registered under an empty id is stated too; the import refuses
    the entry at its location rather than the export failing."""
    _register(authority, "")
    _register(authority, "kvm1")

    exported = render_host_definitions(authority.host_definitions())

    assert [entry["host_id"] for entry in yaml.safe_load(exported)["hosts"]] == ["", "kvm1"]
    assert _codes(_apply(authority, exported)) == [("hosts[0].host_id", "invalid_value")]


def test_a_host_of_an_unserved_kind_is_not_exported_and_every_other_host_is(
    authority, engine
) -> None:
    _register(authority, "kvm1")
    _register(authority, "kvm2")
    _store_row(engine, "bmc1", kind="redfish", version=1)

    exported = render_host_definitions(authority.host_definitions())

    assert [entry["host_id"] for entry in yaml.safe_load(exported)["hosts"]] == ["kvm1", "kvm2"]


# --- The route service's import and export ------------------------------------


def test_an_applying_import_with_a_problem_is_refused_and_applies_nothing(authority) -> None:
    service = HostRouteService(authority, {})

    with pytest.raises(ProvisioningRouteError) as refused:
        service.import_definitions(
            HostDefinitionsImportRequest(
                yaml_text=_document(
                    _entry("kvm1", key_path="/keys/id"), _entry("kvm2", pool_id="no-such-pool", key_path="/k")
                )
            )
        )

    response = HostDefinitionsImportResponse.model_validate(refused.value.detail)
    assert refused.value.status_code == 422
    assert response.applied is False
    assert [problem.code for problem in response.problems] == ["unknown_pool"]
    assert response.diff.created == ["kvm1"]
    assert authority.get_host("kvm1") is None


def test_a_validate_only_import_with_a_problem_answers_it_without_refusing(authority) -> None:
    response = HostRouteService(authority, {}).import_definitions(
        HostDefinitionsImportRequest(
            yaml_text=_document(_entry("kvm1", pool_id="no-such-pool", key_path="/k")), validate_only=True
        )
    )

    assert (response.applied, [p.code for p in response.problems]) == (False, ["unknown_pool"])


def test_a_validate_only_import_reports_its_plan_and_applies_nothing(authority) -> None:
    _register(authority, "kvm1", pool_id="gpu")
    _register(authority, "legacy")
    service = HostRouteService(authority, {})

    response = service.import_definitions(
        HostDefinitionsImportRequest(
            yaml_text=_document(_entry("kvm1", key_path="/keys/id"), _entry("kvm2", key_path="/keys/id")),
            validate_only=True,
        )
    )

    assert (response.applied, response.problems) == (False, [])
    assert (response.diff.created, response.diff.updated) == (["kvm2"], ["kvm1"])
    assert response.not_named == ["legacy"]
    assert authority.get_host("kvm2") is None
    assert authority.get_host("kvm1").pool_id == "gpu"


def test_a_clean_applying_import_commits(authority) -> None:
    service = HostRouteService(authority, {})

    response = service.import_definitions(
        HostDefinitionsImportRequest(yaml_text=_document(_entry("kvm1", pool_id="gpu", key_path="/keys/id")))
    )

    assert response.applied is True and response.diff.created == ["kvm1"]
    assert authority.get_host("kvm1").pool_id == "gpu"


def test_the_route_service_exports_what_imports_unchanged(authority) -> None:
    _register(authority, "kvm1", pool_id="gpu")
    service = HostRouteService(authority, {})

    response = service.import_definitions(HostDefinitionsImportRequest(yaml_text=service.export_definitions()))

    assert (response.applied, response.diff.unchanged) == (True, ["kvm1"])


class _RacedAuthority(HostAuthority):
    """Another request registers each host an entry creates, in its own session,
    after the import evaluated the entry and before the import commits."""

    def put_host_in_session(self, db, host_id, connection, **stated):
        change = super().put_host_in_session(db, host_id, connection, **stated)
        if change == "created":
            _register(self, host_id, address="192.0.2.99", key_path="/keys/other")
        return change


@pytest.fixture
def file_engine(tmp_path):
    """A file database, so each session has a connection of its own; the
    in-memory engine shares one across sessions."""
    engine = _with_pools(create_engine(f"sqlite:///{tmp_path / 'hosts.db'}"))
    yield engine
    engine.dispose()


def test_an_import_meeting_a_concurrent_registration_is_a_conflict_and_can_be_resubmitted(
    file_engine,
) -> None:
    authority = _RacedAuthority(sessionmaker(bind=file_engine), codecs=ConnectionCodecs([_KeyedCodec()]))
    service = HostRouteService(authority, {})
    request = HostDefinitionsImportRequest(yaml_text=_document(_entry("kvm1", key_path="/keys/id")))

    with pytest.raises(ProvisioningRouteError) as refused:
        service.import_definitions(request)

    assert refused.value.status_code == 409
    assert authority.get_host("kvm1").connection.public["address"] == "192.0.2.99"

    response = service.import_definitions(request)

    assert (response.applied, response.diff.updated) == (True, ["kvm1"])
    assert authority.get_host("kvm1").connection.public["address"] == "192.0.2.10"


class _RacedCodec(_KeyedCodec):
    """Another request registers a host while an entry creating it is being
    built: after the import found no such host, and before it flushes one."""

    def __init__(self) -> None:
        self.rival: HostAuthority | None = None

    def build(self, public, secrets, *, previous=None):
        if previous is None and self.rival is not None:
            rival, self.rival = self.rival, None
            _register(rival, "kvm1", address="192.0.2.99", key_path="/keys/other")
        return super().build(public, secrets, previous=previous)


def test_an_import_placing_a_host_registered_meanwhile_is_a_conflict(file_engine) -> None:
    """A new host stating a pool is flushed during reconciliation, so the
    hooks can read it; meeting a concurrent registration there is the same
    conflict as meeting it at commit."""
    codec = _RacedCodec()
    factory = sessionmaker(bind=file_engine)
    authority = HostAuthority(factory, codecs=ConnectionCodecs([codec]))
    codec.rival = HostAuthority(factory, codecs=ConnectionCodecs([_KeyedCodec()]))
    service = HostRouteService(authority, {})
    request = HostDefinitionsImportRequest(
        yaml_text=_document(_entry("kvm1", pool_id="gpu", key_path="/keys/id"))
    )

    with pytest.raises(ProvisioningRouteError) as refused:
        service.import_definitions(request)

    assert refused.value.status_code == 409
    assert authority.get_host("kvm1").connection.public["address"] == "192.0.2.99"

    response = service.import_definitions(request)

    assert (response.applied, response.diff.updated) == (True, ["kvm1"])
    assert authority.get_host("kvm1").pool_id == "gpu"
