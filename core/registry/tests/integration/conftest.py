"""In-process registry integration fixtures with canonical marketplace signers.

Each test runs the registry's served application over its own database, built by
the registry's migration chain, with the admission core's replay store bound to
it through an engine of its own, as startup binds it.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import injected_time
import pytest
import pytest_asyncio
from market_authenticated_requests.sqlalchemy_support import sqlalchemy_replay_store
from market_core import RegistryDescriptor
from market_identity import (
    Ed25519Signer,
    Eip191Signer,
    MarketRequest,
    TrustedIdentitySet,
    build_public_request,
    sign_market_request,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from registry_client import RegistryClient, request_route
from core_registry.api import admission
from core_registry.api.descriptor_routes import DESCRIPTOR_OPERATION
from core_registry.db.database import get_db
from core_registry.db.migrations import migrate_database
from core_registry.main import api, app

MAKER_SECRET = bytes.fromhex(
    "5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
)
TAKER_SECRET = bytes.fromhex(
    "7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"
)
ED25519_SECRET = bytes(range(32))
MAKER_ADDRESS = "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"
TAKER_ADDRESS = "0x90f79bf6eb2c4f870365e785982e1f101e93b906"
DESCRIPTOR_PATH = "/.well-known/arkhai/registry-descriptor.json"


@pytest.fixture
def maker_signer() -> Eip191Signer:
    return Eip191Signer(MAKER_SECRET)


@pytest.fixture
def taker_signer() -> Eip191Signer:
    return Eip191Signer(TAKER_SECRET)


@pytest.fixture
def ed25519_signer() -> Ed25519Signer:
    return Ed25519Signer(ED25519_SECRET)


@pytest.fixture
def registry_database(tmp_path: Path) -> str:
    """The URL of a database the registry's migration chain built."""

    url = f"sqlite:///{tmp_path / 'served-registry.db'}"
    migrate_database(url)
    return url


@pytest.fixture
def db_engine(registry_database: str):
    engine = create_engine(registry_database, connect_args={"check_same_thread": False})
    yield engine
    engine.dispose()


@pytest.fixture
def db_sessions(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)


@pytest.fixture
def db_session(db_sessions):
    """A session for a test's own setup and inspection; each request the
    application serves opens and closes its own, as in production."""

    session = db_sessions()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def registry_authority(monkeypatch, registry_database: str):
    signer = Ed25519Signer(bytes(range(1, 33)))
    replay_engine = create_engine(registry_database)
    admission.bind(signer=signer, store=sqlalchemy_replay_store(replay_engine))
    api.state.registry_descriptor = RegistryDescriptor.model_validate(
        {
            "access": {"posture": "public"},
            "authority": {
                "name": "test-registry",
                "principals": [signer.identity.model_dump(mode="json")],
            },
            "baseUrl": "http://test",
            "displayName": "Test Registry",
            "operatorIdentity": "test-operator",
            "schema": {"id": "compute.market", "version": "1"},
        }
    )
    monkeypatch.setattr(
        "core_registry.config.settings.registry_authority_id",
        "test-registry",
    )
    yield signer
    del api.state.registry_descriptor
    replay_engine.dispose()


@pytest.fixture(autouse=True)
def serve_requests_from_the_test_database(db_sessions):
    def override_get_db():
        session = db_sessions()
        try:
            yield session
        finally:
            session.close()

    api.dependency_overrides[get_db] = override_get_db
    yield
    api.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def sign_raw_marketplace_requests(monkeypatch, registry_authority):
    """Sign a test's raw request as a seller would, under the version 3 profile.

    A request already carrying a request identity -- one the typed client signed,
    or a test's own -- is sent as it is, and so is one marked ``X-Test-Unsigned``.
    The descriptor read is sent as its public operation.
    """

    caller = Ed25519Signer(ED25519_SECRET)
    audience = TrustedIdentitySet(identities=(registry_authority.identity,))
    original = httpx.AsyncClient.request

    async def signed_request(client, method, url, **kwargs):
        method = method.upper()
        headers = dict(kwargs.pop("headers", None) or {})
        if headers.pop("X-Test-Unsigned", None) or "Market-Request-ID" in headers:
            return await original(client, method, url, headers=headers, **kwargs)
        for unused in ("data", "files"):
            if kwargs.get(unused) is not None:
                raise AssertionError(f"a raw registry request carries no {unused}")
            kwargs.pop(unused, None)
        target = httpx.URL(str(url), params=kwargs.pop("params", None))
        if target.path == DESCRIPTOR_PATH and method == "GET":
            headers.update(build_public_request(method="GET", operation=DESCRIPTOR_OPERATION).headers)
            return await original(client, method, str(target), headers=headers, **kwargs)
        try:
            operation, resource = request_route(method, target.path)
        except (KeyError, ValueError):
            return await original(client, method, str(target), headers=headers, **kwargs)
        document = kwargs.pop("json", None)
        content = kwargs.pop("content", None)
        if document is not None:
            body = json.dumps(document, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        else:
            body = content or b""
        now = injected_time.now()
        signed = sign_market_request(
            signer=caller,
            request=MarketRequest(
                method=method,
                role="seller",
                operation=operation,
                resource=resource,
                request_id=uuid.uuid4().hex,
                origin=now,
            ),
            body=body,
            created=now,
            query="?" + target.query.decode() if target.query else "",
            audience=audience,
        )
        headers.update(signed.headers)
        return await original(client, method, str(target), headers=headers, content=body, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "request", signed_request)


@pytest_asyncio.fixture
async def registry_client(
    maker_signer,
    registry_authority,
) -> RegistryClient:
    async with RegistryClient(
        "http://test",
        transport=httpx.ASGITransport(app=app),
        signer=maker_signer,
        caller_role="seller",
        expected_registries=TrustedIdentitySet(
            identities=(registry_authority.identity,)
        ),
        registry_authority="test-registry",
    ) as client:
        yield client


def _make_publisher(db_session, signer, storefront_url: str):
    from core_registry.db.models import Publisher, PublisherIdentity

    publisher = Publisher(storefront_url=storefront_url)
    publisher.identities.append(
        PublisherIdentity(
            scheme=signer.identity.scheme.value,
            identifier=signer.identity.identifier,
            status="primary",
        )
    )
    db_session.add(publisher)
    db_session.commit()
    db_session.refresh(publisher)
    return publisher


@pytest.fixture
def maker_publisher(db_session, maker_signer):
    return _make_publisher(db_session, maker_signer, "http://localhost:8001/")


@pytest.fixture
def taker_publisher(db_session, taker_signer):
    return _make_publisher(db_session, taker_signer, "http://localhost:8003/")


@pytest.fixture
def open_order(db_session, maker_publisher):
    from core_registry.db.models import Listing, OrderStatusEnum

    order = Listing(
        listing_id="integ-open-order-1",
        publisher_id=maker_publisher.publisher_id,
        listing_resource={
            "gpu_model": "A100",
            "region": "us-west",
            "quantity": 1,
            "sla": 99.0,
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "USDC"},
            }
        ],
        max_duration_seconds=3600,
        status=OrderStatusEnum.open,
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order


@pytest.fixture
def authenticated_open_order(db_session, maker_publisher):
    from core_registry.db.models import Listing, OrderStatusEnum

    order = Listing(
        listing_id="integ-auth-order-1",
        publisher_id=maker_publisher.publisher_id,
        listing_resource={
            "gpu_model": "A100",
            "region": "us-west",
            "quantity": 1,
            "sla": 99.0,
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "USDC"},
            }
        ],
        max_duration_seconds=3600,
        status=OrderStatusEnum.open,
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order
