"""The host authority against a real SQLite database.

A fake codec stands in for a connection kind: the authority must validate
through it and store what it produces, never interpreting a connection itself,
and never letting a protected value reach a response.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from market_resource_pools.db import Base as PoolsBase
from market_resource_pools.db import ResourcePool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning.hosts import (
    ConnectionCodecs,
    ConnectionEnvelope,
    ConnectionSubmission,
    HostCreate,
    HostUpdate,
    ProtectedValue,
)
from compute_provisioning.hosts.db import Base as HostsBase
from compute_provisioning.hosts.db import Host
from compute_provisioning.hosts.service import (
    HostAuthority,
    HostNotFoundError,
    InventoryHost,
    host_response,
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


class _Derivation:
    def __init__(self) -> None:
        self.derived: list[list[str]] = []

    @contextmanager
    def serialized(self):
        yield

    def derive_in_session(self, db, host_ids=None):
        self.derived.append(list(host_ids or []))
        return []


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
def derivation():
    return _Derivation()


@pytest.fixture
def moves():
    return []


@pytest.fixture
def authority(session_factory, derivation, moves):
    def record_move(db, host_id, current, new):
        if new == "refused":
            raise ValueError("move refused")
        moves.append((host_id, current, new))

    return HostAuthority(
        session_factory,
        codecs=ConnectionCodecs([_Codec()]),
        capacity_derivation=derivation,
        pool_change_hooks=(record_move,),
    )


def test_a_registered_host_keeps_only_the_protected_form_of_its_secret(authority) -> None:
    host = authority.register_host(
        HostCreate(host_id="h1", connection=_connection(token="s3cret"))
    )

    assert host.pool_id == "default"
    assert host.connection_protected == {"token": {"scheme": "reverse-v1", "ciphertext": "terc3s"}}
    response = host_response(host)
    assert response.connection.protected == {"token": "reverse-v1"}
    assert "terc3s" not in response.model_dump_json()
    assert "s3cret" not in response.model_dump_json()


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

    assert host.connection().public["address"] == "198.51.100.1"
    assert host.connection().protected["token"].ciphertext == "terc3s"


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


def test_a_hook_refusing_a_move_leaves_the_host_where_it_was(authority, session_factory) -> None:
    authority.register_host(HostCreate(host_id="h1", connection=_connection()))
    with session_factory() as db:
        db.add(ResourcePool(id="refused", label="refused", provider="test", policy_tags={}))
        db.commit()

    with pytest.raises(ValueError, match="refused"):
        authority.update_host("h1", HostUpdate(pool_id="refused"))

    assert authority.get_host("h1").pool_id == "default"


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


def test_an_inventory_upserts_its_hosts_and_derives_their_capacity(authority, derivation) -> None:
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
    assert again[0].connection().public["address"] == "192.0.2.99"
    assert (again[0].gpu_count, again[0].pool_id) == (4, "default")
    assert authority.get_host("untouched") is not None
    assert derivation.derived == [["kvm1", "kvm2"], ["kvm1"]]


def test_an_inventory_naming_an_unknown_pool_applies_nothing(authority, session_factory) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        authority.apply_inventory([
            InventoryHost(host_id="kvm1", connection=_connection()),
            InventoryHost(host_id="kvm2", connection=_connection(), pool_id="none"),
        ])

    with session_factory() as db:
        assert db.query(Host).count() == 0
