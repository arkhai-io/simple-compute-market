from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from async_provisioning_service.api.auth import AgentAuthMiddleware, _registry_cache
from async_provisioning_service.api.routes import health_router, router
from async_provisioning_service.db.database import get_db
from async_provisioning_service.db.models import Base


@pytest.fixture(autouse=True)
def clear_registry_cache():
    _registry_cache.clear()
    yield
    _registry_cache.clear()


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def app_factory(db_session):
    def _build(*, auth_enabled=True, registry_url="http://registry.test"):
        app = FastAPI()
        app.add_middleware(
            AgentAuthMiddleware,
            registry_url=registry_url,
            enabled=auth_enabled,
        )
        app.include_router(health_router)
        app.include_router(router, prefix="/api/v1")

        def override_get_db():
            try:
                yield db_session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        return app

    return _build


@pytest.fixture
def client_factory(app_factory):
    def _build(**kwargs):
        return TestClient(app_factory(**kwargs))

    return _build
