"""The host authority against a real SQLite database.

A fake codec stands in for a connection kind: the authority must validate
through it and store what it produces, never interpreting a connection itself,
and never letting a protected value reach a response.
"""

from __future__ import annotations

import pytest
from market_resource_pools.db import Base as PoolsBase
from market_resource_pools.db import ResourcePool
from sqlalchemy import create_engine
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
    reads.append(authority.update_host("h1", HostUpdate(gpu_count=2)))
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
        HostCreate(host_id="h1", connection=_connection(), gpu_count=2, gpu_model="H100")
    )

    host = authority.update_host("h1", HostUpdate(gpu_count=4))

    assert (host.gpu_count, host.gpu_model) == (4, "H100")
    assert authority.update_host("h1", HostUpdate(gpu_model="A100")).gpu_model == "A100"


def test_hosts_name_existing_pools_and_a_move_runs_its_hooks(authority, moves) -> None:
    authority.register_host(HostCreate(host_id="h1", connection=_connection(), pool_id="gpu"))
    with pytest.raises(ValueError, match="does not exist"):
        authority.register_host(HostCreate(host_id="h2", connection=_connection(), pool_id="none"))

    assert authority.update_host("h1", HostUpdate(pool_id="default")).pool_id == "default"
    assert moves == [("h1", "gpu", "default")]
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
    assert moves == [("h1", "gpu", None)]
    # Unplacing an unplaced host is not a move, and placing it again is one.
    authority.update_host("h1", HostUpdate(pool_id=None))
    assert authority.update_host("h1", HostUpdate(pool_id="default")).pool_id == "default"
    assert moves == [("h1", "gpu", None), ("h1", None, "default")]


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
    assert moves == [("kvm1", "gpu", None)]


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

    assert moves == []


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


def test_an_inventory_upserts_its_hosts_and_records_their_gpus(authority) -> None:
    authority.register_host(HostCreate(host_id="untouched", connection=_connection()))
    entries = [
        InventoryHost(host_id="kvm1", connection=_connection(), gpu_count=2, pool_id="gpu"),
        InventoryHost(host_id="kvm2", connection=_connection("192.0.2.11")),
    ]

    first = authority.apply_inventory(entries)
    again = authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection("192.0.2.99"), gpu_count=4)]
    )

    assert [h.host_id for h in first] == ["kvm1", "kvm2"]
    assert again[0].connection.public["address"] == "192.0.2.99"
    assert (again[0].gpu_count, again[0].pool_id) == (4, "gpu")
    assert authority.get_host("untouched") is not None


def test_an_inventory_moving_a_host_runs_the_pool_change_hooks(authority, moves) -> None:
    """An imported inventory moves an existing host as an update does: the
    pool-change hooks see the move, so no subscriber's rule is bypassed."""
    authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection(), pool_id="gpu")]
    )
    assert moves == []

    authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection(), pool_id="default")]
    )

    assert moves == [("kvm1", "gpu", "default")]
    assert authority.get_host("kvm1").pool_id == "default"


def test_a_hook_refusing_an_inventory_move_applies_nothing(
    authority, session_factory
) -> None:
    """The import is one transaction: one refused move leaves every host it
    names as it was, including hosts it would have created or reconnected."""
    authority.apply_inventory(
        [InventoryHost(host_id="kvm1", connection=_connection("192.0.2.10"), gpu_count=1)]
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
                gpu_count=8,
                pool_id="refused",
            ),
        ])

    kvm1 = authority.get_host("kvm1")
    assert (kvm1.pool_id, kvm1.gpu_count) == (None, 1)
    assert kvm1.connection.public["address"] == "192.0.2.10"
    assert authority.get_host("kvm2") is None


def test_an_inventory_naming_an_unknown_pool_applies_nothing(authority, session_factory) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        authority.apply_inventory([
            InventoryHost(host_id="kvm1", connection=_connection()),
            InventoryHost(host_id="kvm2", connection=_connection(), pool_id="none"),
        ])

    with session_factory() as db:
        assert db.query(Host).count() == 0
