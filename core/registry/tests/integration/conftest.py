"""In-process registry integration fixtures with canonical marketplace signers."""

from __future__ import annotations
import time
import uuid

import httpx
import pytest
import pytest_asyncio
from market_identity import Ed25519Signer, Eip191Signer, TrustedIdentitySet

from registry_client import RegistryClient
from src.db.database import get_db
from src.main import app

MAKER_SECRET = bytes.fromhex(
    "5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
)
TAKER_SECRET = bytes.fromhex(
    "7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"
)
ED25519_SECRET = bytes(range(32))
MAKER_ADDRESS = "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"
TAKER_ADDRESS = "0x90f79bf6eb2c4f870365e785982e1f101e93b906"


@pytest.fixture
def maker_signer() -> Eip191Signer:
    return Eip191Signer(MAKER_SECRET)


@pytest.fixture
def taker_signer() -> Eip191Signer:
    return Eip191Signer(TAKER_SECRET)


@pytest.fixture
def ed25519_signer() -> Ed25519Signer:
    return Ed25519Signer(ED25519_SECRET)

@pytest.fixture(autouse=True)
def registry_authority(monkeypatch):
    signer = Ed25519Signer(bytes(range(1, 33)))
    app.state.registry_authority_signer = signer
    monkeypatch.setattr(
        "src.config.settings.registry_authority_id",
        "test-registry",
    )
    yield signer
    del app.state.registry_authority_signer

@pytest.fixture(autouse=True)
def sign_raw_marketplace_requests(monkeypatch, registry_authority, db_session):
    from market_identity import (
        EMPTY_BODY,
        RequestEnvelope,
        canonical_body_hash,
        sign_request,
    )

    caller = Ed25519Signer(bytes(range(32)))
    original = httpx.AsyncClient.request

    def context(method: str, path: str):
        parts = [part for part in path.split("/") if part]
        if path == "/filter-spec":
            return "filter.get", "filter-spec"
        if path == "/api/v1/listings/validate-publish":
            return "listing.validate", "listings"
        if path == "/api/v1/system/health":
            return "health.read", "health"
        if path == "/api/v1/system/stats":
            return "system.stats.read", "system"
        if parts[:1] == ["listings"]:
            if len(parts) == 1:
                return (
                    "listing.publish" if method == "POST" else "listing.list",
                    "listings",
                )
            return {
                "GET": ("listing.get", parts[1]),
                "PUT": ("listing.update", parts[1]),
                "DELETE": ("listing.delete", parts[1]),
            }.get(method)
        if parts[:1] == ["publishers"]:
            if len(parts) == 1:
                return "publisher.list", "publishers"
            if len(parts) == 2:
                return "publisher.get", parts[1]
            if parts[2] == "identity-rotations":
                if len(parts) == 3:
                    return "publisher.identity.rotate", parts[1]
                if len(parts) == 4:
                    return "publisher.identity.rotation.read", f"{parts[1]}:{parts[3]}"
                if len(parts) == 5 and parts[4] == "retire":
                    return "publisher.identity.retire", f"{parts[1]}:{parts[3]}"
        return None

    async def signed_request(client, method, url, **kwargs):
        method = method.upper()
        headers = dict(kwargs.get("headers") or {})
        if headers.pop("X-Test-Unsigned", None):
            kwargs["headers"] = headers
            return await original(client, method, url, **kwargs)
        if "X-Market-Signature" in headers:
            return await original(client, method, url, **kwargs)
        route = context(method, httpx.URL(url).path)
        if route is None:
            return await original(client, method, url, **kwargs)
        operation, resource = route
        if method == "GET":
            body = {
                "query": sorted(
                    [
                        list(item)
                        for item in httpx.QueryParams(
                            kwargs.get("params") or {}
                        ).multi_items()
                    ]
                )
            }
            if_match = httpx.Headers(headers).get("If-Match")
            if if_match is not None:
                body["if_match"] = (
                    if_match.strip().removeprefix("W/").strip().strip('"')
                )
        else:
            body = kwargs.get("json", EMPTY_BODY)
        authenticated = sign_request(
            signer=caller,
            envelope=RequestEnvelope(
                role="seller",
                principal=caller.identity,
                method=method,
                operation=operation,
                resource=resource,
                request_id=uuid.uuid4().hex,
                timestamp=int(time.time()),
                body_hash=canonical_body_hash(body),
            ),
        )
        headers.update(
            {
                "X-Market-Signature-Version": authenticated.protocol,
                "X-Market-Identity-Scheme": authenticated.principal.scheme.value,
                "X-Market-Identity-Identifier": authenticated.principal.identifier,
                "X-Market-Role": authenticated.role,
                "X-Market-Request-ID": authenticated.request_id,
                "X-Market-Timestamp": str(authenticated.timestamp),
                "X-Market-Signature": authenticated.proof.value,
            }
        )
        kwargs["headers"] = headers
        return await original(client, method, url, **kwargs)
    from src.db.database import get_db

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(httpx.AsyncClient, "request", signed_request)
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def registry_client(
    db_session,
    maker_signer,
    registry_authority,
) -> RegistryClient:
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
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
    app.dependency_overrides.clear()


def _make_publisher(db_session, signer, storefront_url: str):
    from src.db.models import Publisher, PublisherIdentity

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
    from src.db.models import Listing, OrderStatusEnum

    order = Listing(
        listing_id="integ-open-order-1",
        publisher_id=maker_publisher.publisher_id,
        offer_resource={
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
    from src.db.models import Listing, OrderStatusEnum

    order = Listing(
        listing_id="integ-auth-order-1",
        publisher_id=maker_publisher.publisher_id,
        offer_resource={
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
