"""The host authority against a real SQLite database.

A fake codec stands in for a connection kind: the authority must validate
through it and store what it produces, never interpreting a connection itself,
and never letting a protected value reach a response.
"""

from __future__ import annotations

import pytest
from market_resource_pools.db import Base as PoolsBase
from market_resource_pools.db import ResourcePool
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning.hosts import (
    ConnectionCodecs,
    ConnectionEnvelope,
    ProtectedValue,
)
from compute_provisioning_contracts import ConnectionSubmission, HostCreate, HostUpdate
from compute_provisioning.hosts.db import Base as HostsBase
from compute_provisioning.hosts.db import Host
from compute_provisioning.hosts.service import (
    ConnectionChangeRefusedError,
    HostAuthority,
    HostNotFoundError,
    InventoryHost,
    PoolChangeRefusedError,
)


class _Codec:
    """A connection kind whose one secret is 'protected' by reversing it."""

    kind, version = "fake", 1

    def build(self, public, secrets, *, previous=None):
        if "address" not in public:
            raise ValueError("fake connection needs an address")
        protected = {}
        if "token" in secrets:
            protected["token"] = ProtectedValue("reverse-v1", secrets["token"][::-1])
        elif previous is not None and "token" in previous.protected:
            protected["token"] = previous.protected["token"]
        return ConnectionEnvelope(kind="fake", version=1, public=dict(public), protected=protected)

    def validate(self, envelope):
        return envelope


def _connection(address: str = "192.0.2.10", **secrets: str) -> ConnectionSubmission:
    return ConnectionSubmission(kind="fake", public={"address": address}, secrets=secrets)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    PoolsBase.metadata.create_all(engine)
    HostsBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for pool_id in ("default", "gpu"):
            db.add(ResourcePool(id=pool_id, label=pool_id, provider="test", policy_tags={}))
        db.commit()
    return factory


@pytest.fixture
def moves():
    return []


@pytest.fixture
def authority(session_factory, moves):
    def record_move(db, host_id, current, new):
        if new == "refused":
            raise PoolChangeRefusedError("move refused")
        moves.append((host_id, current, new))

    return HostAuthority(
        session_factory,
        codecs=ConnectionCodecs([_Codec()]),
        pool_change_hooks=(record_move,),
    )


def test_a_registered_host_keeps_only_the_protected_form_of_its_secret(
    authority, session_factory
) -> None:
    registered = authority.register_host(
        HostCreate(host_id="h1", connection=_connection(token="s3cret"))
    )

    assert registered.connection.protected == {"token": "reverse-v1"}
    with session_factory() as db:
        assert db.get(Host, "h1").connection_protected == {
            "token": {"scheme": "reverse-v1", "ciphertext": "terc3s"}
        }


def test_no_ordinary_read_carries_a_protected_value(authority) -> None:
    reads = [authority.register_host(HostCreate(host_id="h1", connection=_connection(token="s3cret")))]
    reads.append(authority.get_host("h1"))
    reads.extend(authority.list_hosts(enabled_only=False))
    reads.append(authority.update_host("h1", HostUpdate(enabled=True)))
    reads.append(authority.disable_host("h1"))
    reads.append(authority.enable_host("h1"))
    reads.extend(authority.apply_inventory(
        [InventoryHost(host_id="h2", connection=_connection(token="other"))]
    ))

    for view in reads:
        rendered = view.model_dump_json() + repr(view)
        assert "terc3s" not in rendered and "s3cret" not in rendered
        assert "rehto" not in rendered and "other" not in rendered
        assert set(view.connection.protected.values()) == {"reverse-v1"}


def test_lookup_hands_executors_the_protected_envelope(authority) -> None:
    authority.register_host(HostCreate(host_id="h1", connection=_connection(token="s3cret")))

    execution_host = authority.lookup("h1")

    assert execution_host.host_id == "h1"
    assert execution_host.connection.protected["token"].ciphertext == "terc3s"
    assert authority.lookup("missing") is None


def test_execution_hosts_carry_each_enabled_hosts_full_envelope_in_id_order(authority) -> None:
    authority.register_host(HostCreate(host_id="h2", connection=_connection(token="s3cret")))
    authority.register_host(
        HostCreate(
            host_id="h1",
            connection=ConnectionSubmission(
                kind="fake", public={"address": "192.0.2.11", "key_path": "/keys/h1"}
            ),
        )
    )

    hosts = authority.execution_hosts()

    assert [host.host_id for host in hosts] == ["h1", "h2"]
    key_file, embedded = hosts
    assert key_file.connection.public["key_path"] == "/keys/h1"
    assert key_file.connection.protected == {}
    assert embedded.connection.protected["token"] == ProtectedValue("reverse-v1", "terc3s")
    # The ordinary listing of the same host still names the value by scheme.
    (listed,) = [host for host in authority.list_hosts() if host.host_id == "h2"]
    assert listed.connection.protected == {"token": "reverse-v1"}
    assert "terc3s" not in listed.model_dump_json()


def test_execution_hosts_leave_out_a_disabled_host_unless_asked(authority) -> None:
    authority.register_host(HostCreate(host_id="h1", connection=_connection()))
    authority.register_host(HostCreate(host_id="h2", connection=_connection(), enabled=False))

    assert [host.host_id for host in authority.execution_hosts()] == ["h1"]
    assert [host.host_id for host in authority.execution_hosts(enabled_only=False)] == ["h1", "h2"]


def test_execution_hosts_of_an_empty_registry_are_none(authority) -> None:
    assert authority.execution_hosts() == []


def test_a_connection_its_codec_refuses_is_not_stored(authority) -> None:
    with pytest.raises(ValueError, match="needs an address"):
        authority.register_host(
            HostCreate(host_id="h1", connection=ConnectionSubmission(kind="fake", public={}))
        )
    with pytest.raises(ValueError, match="not supported"):
        authority.register_host(
            HostCreate(host_id="h1", connection=ConnectionSubmission(kind="ssh", public={}))
        )
    assert authority.get_host("h1") is None


def test_an_update_without_the_secret_keeps_the_stored_one(authority) -> None:
    authority.register_host(HostCreate(host_id="h1", connection=_connection(token="s3cret")))

    host = authority.update_host("h1", HostUpdate(connection=_connection("198.51.100.1")))

    assert host.connection.public["address"] == "198.51.100.1"
    assert authority.lookup("h1").connection.protected["token"].ciphertext == "terc3s"


def test_updates_leave_omitted_fields_alone(authority) -> None:
    authority.register_host(
        HostCreate(host_id="h1", connection=_connection("192.0.2.20"), pool_id="gpu")
    )

    host = authority.update_host("h1", HostUpdate(enabled=False))

    assert (host.enabled, host.pool_id) == (False, "gpu")
    assert host.connection.public["address"] == "192.0.2.20"


def test_no_write_records_a_gpu_field(authority, session_factory) -> None:
    """A host describes no hardware: create, update, and import write rows with
    no GPU column, and a request parsed from a body carrying the GPU fields is
    applied as if they were absent. The request models drop the fields before
    the authority sees them, and an inventory entry cannot carry them."""
    gpu_fields = {"gpu_count": 8, "gpu_model": "H200"}
    authority.register_host(HostCreate.model_validate(
        {"host_id": "h1", "connection": _connection(), **gpu_fields}
    ))
    authority.update_host("h1", HostUpdate.model_validate({**gpu_fields, "enabled": False}))
    authority.apply_inventory([InventoryHost(host_id="h2", connection=_connection("192.0.2.11"))])

    with session_factory() as db:
        rows = db.execute(text("SELECT * FROM hosts ORDER BY host_id")).mappings().all()
    assert [(row["host_id"], bool(row["enabled"])) for row in rows] == [
        ("h1", False), ("h2", True),
    ]
    assert not set(gpu_fields) & {column for row in rows for column in row}


def test_hosts_name_existing_pools_and_a_move_runs_its_hooks(authority, moves) -> None:
    """A host placed as it is registered moves from no pool, so the hooks see
    it as they see a host moved in later."""
    authority.register_host(HostCreate(host_id="h1", connection=_connection(), pool_id="gpu"))
    with pytest.raises(ValueError, match="does not exist"):
        authority.register_host(HostCreate(host_id="h2", connection=_connection(), pool_id="none"))
    assert authority.get_host("h2") is None

    assert authority.update_host("h1", HostUpdate(pool_id="default")).pool_id == "default"
    assert moves == [("h1", None, "gpu"), ("h1", "gpu", "default")]
    with pytest.raises(ValueError, match="does not exist"):
        authority.update_host("h1", HostUpdate(pool_id="none"))


def test_a_host_written_without_a_pool_is_unplaced(authority, session_factory, moves) -> None:
    """No write supplies a pool it was not given: a created host and a new
    inventory entry naming none are stored in no pool."""
    created = authority.register_host(HostCreate(host_id="h1", connection=_connection()))
    imported = authority.apply_inventory(
        [InventoryHost(host_id="h2", connection=_connection())]
    )

    assert created.pool_id is None
    assert [host.pool_id for host in imported] == [None]
    with session_factory() as db:
        assert {host.host_id: host.pool_id for host in db.query(Host)} == {
            "h1": None, "h2": None,
        }
    assert authority.lookup("h1").pool_id is None
    assert authority.lookup("h2").pool_id is None
    assert moves == []


def test_an_update_omitting_the_pool_keeps_it_and_an_explicit_none_unplaces(
    authority, moves
) -> None:
    authority.register_host(HostCreate(host_id="h1", connection=_connection(), pool_id="gpu"))

    assert authority.update_host("h1", HostUpdate(enabled=False)).pool_id == "gpu"
    assert authority.update_host("h1", HostUpdate(pool_id=None)).pool_id is None
    assert moves == [("h1", None, "gpu"), ("h1", "gpu", None)]
    # Unplacing an unplaced host is not a move, and placing it again is one.
    authority.update_host("h1", HostUpdate(pool_id=None))
    assert authority.update_host("h1", HostUpdate(pool_id="default")).pool_id == "default"
    assert moves == [("h1", None, "gpu"), ("h1", "gpu", None), ("h1", None, "default")]


def test_an_inventory_entry_states_a_pool_unplaces_or_says_nothing(authority, moves) -> None:
    """A stated pool places or moves its host and ``None`` unplaces it, each
    through the hooks; an entry stating none leaves an existing host where it
    is."""
    authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection(), pool_id="gpu")]
    )

    kept = authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection("192.0.2.99"))]
    )
    assert (kept[0].pool_id, kept[0].connection.public["address"]) == ("gpu", "192.0.2.99")

    unplaced = authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection(), pool_id=None)]
    )
    assert unplaced[0].pool_id is None
    assert moves == [("kvm1", None, "gpu"), ("kvm1", "gpu", None)]


def test_a_hook_refusing_an_unplacing_leaves_the_host_and_the_import(
    authority, session_factory
) -> None:
    """Unplacing is a move like any other: a hook refusing it refuses the
    whole update, or the whole import with every host it names."""
    authority.register_host(HostCreate(host_id="h1", connection=_connection(), pool_id="gpu"))

    def refuse_unplacing(db, host_id, current, new):
        if new is None:
            raise PoolChangeRefusedError("unplacing refused")

    guarded = HostAuthority(
        session_factory,
        codecs=ConnectionCodecs([_Codec()]),
        pool_change_hooks=(refuse_unplacing,),
    )

    with pytest.raises(PoolChangeRefusedError, match="unplacing refused"):
        guarded.update_host("h1", HostUpdate(pool_id=None))
    with pytest.raises(PoolChangeRefusedError, match="unplacing refused"):
        guarded.apply_inventory([
            InventoryHost(host_id="h2", connection=_connection()),
            InventoryHost(host_id="h1", connection=_connection("192.0.2.99"), pool_id=None),
        ])

    h1 = guarded.get_host("h1")
    assert (h1.pool_id, h1.connection.public["address"]) == ("gpu", "192.0.2.10")
    assert guarded.get_host("h2") is None


def test_a_hook_refusing_a_placement_registers_nothing(authority, session_factory) -> None:
    """A host placed as it is registered or imported is refused as a move would
    be: nothing of it is stored."""
    with session_factory() as db:
        db.add(ResourcePool(id="refused", label="refused", provider="test", policy_tags={}))
        db.commit()

    with pytest.raises(PoolChangeRefusedError, match="refused"):
        authority.register_host(
            HostCreate(host_id="h1", connection=_connection(), pool_id="refused")
        )
    with pytest.raises(PoolChangeRefusedError, match="refused"):
        authority.apply_inventory(
            [InventoryHost(host_id="h2", connection=_connection(), pool_id="refused")]
        )

    assert authority.get_host("h1") is None
    assert authority.get_host("h2") is None


def test_a_hook_refusing_a_move_leaves_the_host_where_it_was(authority, session_factory) -> None:
    authority.register_host(HostCreate(host_id="h1", connection=_connection(), pool_id="default"))
    with session_factory() as db:
        db.add(ResourcePool(id="refused", label="refused", provider="test", policy_tags={}))
        db.commit()

    with pytest.raises(PoolChangeRefusedError, match="refused"):
        authority.update_host("h1", HostUpdate(pool_id="refused"))

    assert authority.get_host("h1").pool_id == "default"


def test_assigning_a_host_its_current_pool_is_not_a_move(authority, moves) -> None:
    authority.register_host(HostCreate(host_id="h1", connection=_connection(), pool_id="gpu"))

    authority.update_host("h1", HostUpdate(pool_id="gpu"))
    authority.apply_inventory(
        [InventoryHost(host_id="h1", connection=_connection(), pool_id="gpu")]
    )

    assert moves == [("h1", None, "gpu")]


def test_a_placed_hosts_new_connection_runs_the_connection_change_hooks(
    session_factory,
) -> None:
    """An update or an inventory giving a placed host a new connection in
    place runs the connection-change hooks with its pool and the new
    connection in the session; an unplaced host, and a write that also moves
    the host, run none, since the pool-change hooks see a move."""
    seen = []

    def record(db, host_id, pool_id):
        address = db.get(Host, host_id).connection().public["address"]
        seen.append((host_id, pool_id, address))

    hooked = HostAuthority(
        session_factory,
        codecs=ConnectionCodecs([_Codec()]),
        connection_change_hooks=(record,),
    )
    hooked.register_host(HostCreate(host_id="h1", connection=_connection(), pool_id="gpu"))
    hooked.register_host(HostCreate(host_id="h2", connection=_connection()))

    hooked.update_host("h1", HostUpdate(connection=_connection("198.51.100.1")))
    hooked.apply_inventory([InventoryHost(host_id="h1", connection=_connection("198.51.100.2"))])
    hooked.update_host("h2", HostUpdate(connection=_connection("198.51.100.3")))
    hooked.update_host(
        "h1", HostUpdate(connection=_connection("198.51.100.4"), pool_id="default")
    )
    hooked.update_host("h1", HostUpdate(enabled=False))

    assert seen == [
        ("h1", "gpu", "198.51.100.1"),
        ("h1", "gpu", "198.51.100.2"),
    ]


def test_a_refused_connection_change_leaves_the_host_and_the_import(session_factory) -> None:
    """A connection-change hook's refusal rolls back the whole update, or the
    whole import with every host it names."""

    def refuse(db, host_id, pool_id):
        raise ConnectionChangeRefusedError(f"{host_id} refused in {pool_id}")

    guarded = HostAuthority(
        session_factory,
        codecs=ConnectionCodecs([_Codec()]),
        connection_change_hooks=(refuse,),
    )
    guarded.register_host(HostCreate(host_id="h1", connection=_connection(), pool_id="gpu"))

    with pytest.raises(PoolChangeRefusedError, match="h1 refused in gpu"):
        guarded.update_host("h1", HostUpdate(connection=_connection("198.51.100.1")))
    with pytest.raises(ConnectionChangeRefusedError):
        guarded.apply_inventory([
            InventoryHost(host_id="h2", connection=_connection()),
            InventoryHost(host_id="h1", connection=_connection("198.51.100.2")),
        ])

    assert guarded.get_host("h1").connection.public["address"] == "192.0.2.10"
    assert guarded.get_host("h2") is None


def test_listing_filters_disabled_hosts_and_searches_by_id(authority) -> None:
    for host_id in ("kvm1", "kvm2", "bm1"):
        authority.register_host(HostCreate(host_id=host_id, connection=_connection()))
    authority.disable_host("kvm2")

    assert [h.host_id for h in authority.list_hosts()] == ["bm1", "kvm1"]
    assert [h.host_id for h in authority.list_hosts(enabled_only=False)] == ["bm1", "kvm1", "kvm2"]
    assert [h.host_id for h in authority.list_hosts(search="KVM")] == ["kvm1"]
    assert authority.enable_host("kvm2").enabled is True
    with pytest.raises(HostNotFoundError):
        authority.disable_host("missing")


def test_the_hosts_taking_new_delivery_are_the_registered_enabled_ones(
    authority, session_factory
) -> None:
    for host_id in ("kvm1", "kvm2"):
        authority.register_host(HostCreate(host_id=host_id, connection=_connection()))

    def deliverable() -> frozenset[str]:
        with session_factory() as db:
            return authority.deliverable_host_ids(db)

    assert deliverable() == {"kvm1", "kvm2"}

    authority.disable_host("kvm2")
    assert deliverable() == {"kvm1"}

    authority.enable_host("kvm2")
    assert deliverable() == {"kvm1", "kvm2"}
    # An id with no record is never reported, whatever names it.
    assert "never-registered" not in deliverable()


def test_the_report_reads_the_callers_session(file_session_factory) -> None:
    """A disable the caller's own transaction has written but not committed is
    already what its decision sees; another session sees it only on commit."""
    authority = HostAuthority(file_session_factory, codecs=ConnectionCodecs([_Codec()]))
    authority.register_host(HostCreate(host_id="kvm1", connection=_connection()))

    with file_session_factory() as caller:
        caller.query(Host).filter(Host.host_id == "kvm1").update({"enabled": False})
        assert authority.deliverable_host_ids(caller) == frozenset()
        with file_session_factory() as other:
            assert authority.deliverable_host_ids(other) == {"kvm1"}
        caller.rollback()


def test_an_inventory_upserts_its_hosts_and_leaves_the_rest(authority) -> None:
    authority.register_host(HostCreate(host_id="untouched", connection=_connection()))
    entries = [
        InventoryHost(host_id="kvm1", connection=_connection(), pool_id="gpu"),
        InventoryHost(host_id="kvm2", connection=_connection("192.0.2.11")),
    ]

    first = authority.apply_inventory(entries)
    again = authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection("192.0.2.99"))]
    )

    assert [h.host_id for h in first] == ["kvm1", "kvm2"]
    assert again[0].connection.public["address"] == "192.0.2.99"
    assert again[0].pool_id == "gpu"
    assert authority.get_host("untouched") is not None


def test_an_inventory_resubmitting_a_secret_replaces_the_stored_one(authority) -> None:
    """A rotated embedded key changes no public field, pool, or scheme, yet the
    reimport stores it; an entry submitting no secret keeps the stored one."""
    authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection(token="old"), pool_id="gpu")]
    )

    authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection(token="new"), pool_id="gpu")]
    )
    assert authority.lookup("kvm1").connection.protected["token"].ciphertext == "wen"

    authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection(), pool_id="gpu")]
    )
    assert authority.lookup("kvm1").connection.protected["token"].ciphertext == "wen"


def test_an_inventory_moving_a_host_runs_the_pool_change_hooks(authority, moves) -> None:
    """An imported inventory moves an existing host as an update does: the
    pool-change hooks see the move, so no subscriber's rule is bypassed."""
    authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection(), pool_id="gpu")]
    )
    assert moves == [("kvm1", None, "gpu")]

    authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection(), pool_id="default")]
    )

    assert moves == [("kvm1", None, "gpu"), ("kvm1", "gpu", "default")]
    assert authority.get_host("kvm1").pool_id == "default"


def test_a_hook_refusing_an_inventory_move_applies_nothing(
    authority, session_factory
) -> None:
    """The import is one transaction: one refused move leaves every host it
    names as it was, including hosts it would have created or reconnected."""
    authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection("192.0.2.10"))]
    )
    with session_factory() as db:
        db.add(ResourcePool(id="refused", label="refused", provider="test", policy_tags={}))
        db.commit()

    with pytest.raises(PoolChangeRefusedError, match="refused"):
        authority.apply_inventory([
            InventoryHost(host_id="kvm2", connection=_connection("192.0.2.11")),
            InventoryHost(
                host_id="kvm1",
                connection=_connection("192.0.2.99"),
                pool_id="refused",
            ),
        ])

    kvm1 = authority.get_host("kvm1")
    assert kvm1.pool_id is None
    assert kvm1.connection.public["address"] == "192.0.2.10"
    assert authority.get_host("kvm2") is None


@pytest.fixture
def file_session_factory(tmp_path):
    """Sessions on separate connections to one file, so a session sees only
    what another has committed."""
    engine = create_engine(f"sqlite:///{tmp_path / 'hosts.db'}")
    PoolsBase.metadata.create_all(engine)
    HostsBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for pool_id in ("default", "gpu"):
            db.add(ResourcePool(id=pool_id, label=pool_id, provider="test", policy_tags={}))
        db.commit()
    yield factory
    engine.dispose()


def test_a_session_scoped_write_is_seen_only_once_its_caller_commits(file_session_factory) -> None:
    authority = HostAuthority(file_session_factory, codecs=ConnectionCodecs([_Codec()]))

    with authority.session() as db:
        assert authority.put_host_in_session(db, "h1", _connection(), pool_id="gpu") == "created"
        db.flush()
        assert authority.get_host("h1") is None
        db.commit()

    assert authority.get_host("h1").pool_id == "gpu"


def test_a_hook_refusing_a_session_scoped_move_commits_nothing(file_session_factory) -> None:
    def refuse(db, host_id, current, new):
        # Registration places a host as a move from no pool, so only the move
        # under test is refused.
        if current is not None:
            raise PoolChangeRefusedError("move refused")

    authority = HostAuthority(
        file_session_factory, codecs=ConnectionCodecs([_Codec()]), pool_change_hooks=(refuse,)
    )
    authority.register_host(HostCreate(host_id="h1", connection=_connection(), pool_id="gpu"))

    with authority.session() as db:
        authority.put_host_in_session(db, "h2", _connection())
        with pytest.raises(PoolChangeRefusedError, match="move refused"):
            authority.put_host_in_session(db, "h1", _connection("192.0.2.99"), pool_id="default")

    h1 = authority.get_host("h1")
    assert (h1.pool_id, h1.connection.public["address"]) == ("gpu", "192.0.2.10")
    assert authority.get_host("h2") is None


def test_a_session_scoped_write_states_only_what_it_is_given(authority, moves) -> None:
    """``enabled`` and the pool are replaced only when stated; an equal host is
    reported unchanged and runs no hook."""
    authority.register_host(HostCreate(host_id="h1", connection=_connection(), pool_id="gpu", enabled=False))
    moves.clear()

    with authority.session() as db:
        assert authority.put_host_in_session(db, "h1", _connection()) == "unchanged"
        assert authority.put_host_in_session(db, "h1", _connection(), pool_id="gpu", enabled=False) == "unchanged"
        assert authority.put_host_in_session(db, "h1", _connection(), enabled=True) == "updated"
        db.commit()

    h1 = authority.get_host("h1")
    assert (h1.pool_id, h1.enabled) == ("gpu", True)
    assert moves == []


def test_a_session_scoped_write_runs_the_hooks_on_the_host_as_it_will_be(session_factory) -> None:
    """A new host stating a pool is placed as a move from no pool, a moved
    host's new connection is in the session when the pool-change hooks run,
    and a placed host given a new connection in place runs the
    connection-change hooks: the checks a host definitions document's entries
    meet are the ones a registration, a move, and an update meet."""
    seen = []

    def on_move(db, host_id, current, new):
        address = db.get(Host, host_id).connection().public["address"]
        seen.append(("move", host_id, current, new, address))

    def on_connection(db, host_id, pool_id):
        address = db.get(Host, host_id).connection().public["address"]
        seen.append(("connection", host_id, pool_id, address))

    hooked = HostAuthority(
        session_factory,
        codecs=ConnectionCodecs([_Codec()]),
        pool_change_hooks=(on_move,),
        connection_change_hooks=(on_connection,),
    )

    with hooked.session() as db:
        assert hooked.put_host_in_session(db, "h1", _connection(), pool_id="gpu") == "created"
        assert hooked.put_host_in_session(db, "h2", _connection()) == "created"
        db.commit()
    with hooked.session() as db:
        hooked.put_host_in_session(db, "h1", _connection("198.51.100.1"), pool_id="gpu")
        hooked.put_host_in_session(db, "h1", _connection("198.51.100.2"), pool_id="default")
        hooked.put_host_in_session(db, "h2", _connection("198.51.100.3"))
        db.commit()

    assert seen == [
        ("move", "h1", None, "gpu", "192.0.2.10"),
        ("connection", "h1", "gpu", "198.51.100.1"),
        ("move", "h1", "gpu", "default", "198.51.100.2"),
    ]


def test_an_inventory_naming_an_unknown_pool_applies_nothing(authority, session_factory) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        authority.apply_inventory([
            InventoryHost(host_id="kvm1", connection=_connection()),
            InventoryHost(host_id="kvm2", connection=_connection(), pool_id="none"),
        ])

    with session_factory() as db:
        assert db.query(Host).count() == 0
