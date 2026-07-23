from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.middleware.auth import StorefrontAuthMiddleware
from market_site.db import Base
from market_site.ledger import CapacityLedgerService
from market_site.router import make_capacity_router


def _client() -> TestClient:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ledger = CapacityLedgerService(sessionmaker(bind=engine))
    ledger.register_resource(
        resource_id="resource-1",
        resource_type="bare_metal",
        total_units=2,
    )
    app = FastAPI()
    app.add_middleware(
        StorefrontAuthMiddleware,
        principal_keys={"seller-a": "secret-a", "seller-b": "secret-b"},
    )
    app.include_router(make_capacity_router(lambda: ledger), prefix="/api/v1")
    return TestClient(app)


def _headers(secret: str, *, agent_id: str | None = None) -> dict[str, str]:
    headers = {"X-Admin-Key": secret}
    if agent_id is not None:
        headers["X-Agent-ID"] = agent_id
    return headers


def test_reservation_http_reads_and_mutations_are_owner_isolated() -> None:
    client = _client()
    created = client.post(
        "/api/v1/capacity/reservations",
        headers=_headers("secret-a", agent_id="seller-b"),
        json={"claim": {"units": 1}, "deal_ref": {}},
    )
    assert created.status_code == 200
    reservation_id = created.json()["reservation"]["capacity_reservation_id"]

    assert client.get(
        f"/api/v1/capacity/reservations/{reservation_id}",
        headers=_headers("secret-b"),
    ).status_code == 404
    assert client.get(
        "/api/v1/capacity/reservations",
        headers=_headers("secret-b"),
    ).json() == {"reservations": [], "total": 0}
    non_owner_release = client.post(
        "/api/v1/capacity/releases",
        headers=_headers("secret-b"),
        json={"capacity_reservation_id": reservation_id},
    )
    assert non_owner_release.status_code == 200
    assert non_owner_release.json() == {"reservation": None}

    owner_view = client.get(
        f"/api/v1/capacity/reservations/{reservation_id}",
        headers=_headers("secret-a"),
    )
    assert owner_view.status_code == 200
    assert "owner_principal" not in owner_view.json()["reservation"]
