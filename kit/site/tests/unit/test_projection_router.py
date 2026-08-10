from fastapi import FastAPI
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_site.db import Base
from market_site.ledger import CapacityLedgerService
from market_site.router import make_capacity_router


def _client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ledger = CapacityLedgerService(sessionmaker(bind=engine))
    ledger.register_resource(
        resource_id="host-a",
        pool_id="pool-a",
        total_units=8,
        resource_type="compute.vm",
        resource_subtype="h100",
        attributes={"region": "eu", "vm_host": "host-a"},
    )
    app = FastAPI()
    app.include_router(make_capacity_router(lambda: ledger), prefix="/api/v1")
    return TestClient(app)


def test_public_reservation_hides_private_accounting_identity():
    client = _client()
    response = client.post(
        "/api/v1/capacity/reservations",
        json={"claim": {"units": 1}, "deal_ref": {}},
    )
    assert response.status_code == 200
    reservation = response.json()["reservation"]
    assert reservation["capacity_reservation_id"]
    assert "resource_id" not in reservation
    assert "capacity_bucket_id" not in reservation
    assert "backing_resource_id" not in reservation
    # vm_host is real, physical-placement data (populated from the
    # matched resource's attributes at reserve() time -- see
    # openspec/specs/site-capacity/spec.md's opaque-reservation
    # requirement) and must not leak across this boundary either, even
    # though it's domain-specific (VM) rather than a generic accounting
    # identifier like the three above.
    assert "vm_host" not in reservation


def test_projection_versions_are_independent_and_snapshots_are_canonical():
    client = _client()
    pools = client.get("/api/v1/capacity/site-resource-pools").json()
    capacity = client.get("/api/v1/capacity/site-capacity-buckets").json()
    assert pools["revision"] == 1
    assert capacity["revision"] == 1
    assert pools["resource_pools"][0]["resources"][0]["physical_resource_id"] == "host-a"
    assert capacity["capacity_buckets"][0]["resource_count"] == 1
    assert capacity["capacity_buckets"][0]["capacity_group_key"]


def test_resource_pool_projection_uses_authoritative_inventory_provider():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ledger = CapacityLedgerService(sessionmaker(bind=engine))
    ledger.register_resource(resource_id="bucket-host", pool_id="pool-a", total_units=8)
    inventory = [{
        "resource_id": "host-from-repository",
        "pool_id": "pool-a",
        "resource_type": "compute.gpu",
        "capacity": {"gpu_count": 8},
        "attributes": {"vm_host": "host-from-repository"},
        "enabled": True,
    }]
    app = FastAPI()
    app.include_router(
        make_capacity_router(
            lambda: ledger,
            get_resource_inventory=lambda: inventory,
        ),
        prefix="/api/v1",
    )
    response = TestClient(app).get("/api/v1/capacity/site-resource-pools")
    assert response.status_code == 200
    resources = response.json()["resource_pools"][0]["resources"]
    assert [row["physical_resource_id"] for row in resources] == ["host-from-repository"]


@pytest.mark.parametrize("value", [0, -1, "not-a-number", True])
def test_public_reservation_rejects_invalid_unit_claims(value):
    client = _client()
    response = client.post(
        "/api/v1/capacity/reservations",
        json={"claim": {"units": value}, "deal_ref": {}},
    )
    assert response.status_code == 422


def test_get_pool_directory_surfaces_pool_metadata_on_the_projection():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ledger = CapacityLedgerService(sessionmaker(bind=engine))
    ledger.register_resource(
        resource_id="host-a", pool_id="pool-a", total_units=8,
        attributes={"vm_host": "host-a"},
    )
    app = FastAPI()
    app.include_router(
        make_capacity_router(
            lambda: ledger,
            get_pool_directory=lambda: {
                "pool-a": {"label": "Pool A", "enabled": True, "mechanism": "ansible"},
            },
        ),
        prefix="/api/v1",
    )
    response = TestClient(app).get("/api/v1/capacity/site-resource-pools")
    assert response.status_code == 200
    row = response.json()["resource_pools"][0]
    assert row["pool_metadata"] == {"label": "Pool A", "enabled": True, "mechanism": "ansible"}


def test_omitting_get_pool_directory_reproduces_todays_response_exactly():
    """No `get_pool_directory` argument -- the exact shape callers already
    depend on today -- must be byte-identical, not merely close."""
    client = _client()
    response = client.get("/api/v1/capacity/site-resource-pools")
    assert response.status_code == 200
    row = response.json()["resource_pools"][0]
    assert "pool_metadata" not in row
