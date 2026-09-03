from __future__ import annotations

import inspect
import time

import httpx
import pytest
from market_core import RegistryDescriptor
from market_identity import Ed25519Signer

from registry_client import RegistryClient, RegistryClientError, SyncRegistryClient
from src.db.models import PublisherReplayReservation
from src.main import app


async def test_typed_client_reads_authority_authenticated_descriptor(
    registry_client,
    registry_authority,
) -> None:
    descriptor = await registry_client.get_registry_descriptor()

    assert isinstance(descriptor, RegistryDescriptor)
    assert descriptor.base_url == "http://test"
    assert descriptor.schema_identity.id == "vms.compute"
    assert descriptor.authority.name == "test-registry"
    assert descriptor.authority.principals[0].identifier == (
        registry_authority.identity.identifier
    )


async def test_client_bootstraps_trust_from_descriptor_possession_proof(
    maker_signer,
) -> None:
    descriptor = await RegistryClient.bootstrap_registry_descriptor(
        "http://test",
        signer=maker_signer,
        caller_role="buyer",
        transport=httpx.ASGITransport(app=app),
    )

    assert descriptor.authority.name == "test-registry"


async def test_bootstrap_rejects_response_signer_outside_descriptor(
    maker_signer,
) -> None:
    advertised = Ed25519Signer(bytes(range(2, 34)))
    app.state.registry_descriptor = RegistryDescriptor.model_validate(
        {
            "access": {"posture": "public"},
            "authority": {
                "name": "test-registry",
                "principals": [advertised.identity.model_dump(mode="json")],
            },
            "baseUrl": "http://test",
            "displayName": "Impersonated Registry",
            "operatorIdentity": "test-operator",
            "schema": {"id": "vms.compute", "version": "1"},
        }
    )

    with pytest.raises(RegistryClientError, match="wrong_principal"):
        await RegistryClient.bootstrap_registry_descriptor(
            "http://test",
            signer=maker_signer,
            caller_role="buyer",
            transport=httpx.ASGITransport(app=app),
        )


def test_registry_clients_keep_descriptor_method_parity() -> None:
    assert inspect.signature(
        RegistryClient.get_registry_descriptor
    ) == inspect.signature(SyncRegistryClient.get_registry_descriptor)
    async_bootstrap = inspect.signature(
        RegistryClient.bootstrap_registry_descriptor
    ).parameters
    sync_bootstrap = inspect.signature(
        SyncRegistryClient.bootstrap_registry_descriptor
    ).parameters
    assert [
        (name, parameter.kind, parameter.default)
        for name, parameter in async_bootstrap.items()
    ] == [
        (name, parameter.kind, parameter.default)
        for name, parameter in sync_bootstrap.items()
    ]


async def test_descriptor_remains_readable_before_key_acquisition(
    registry_client,
    registry_authority,
) -> None:
    app.state.registry_descriptor = RegistryDescriptor.model_validate(
        {
            "access": {
                "posture": "key-gated",
                "acquisitionPointer": "https://registry.example/access",
            },
            "authority": {
                "name": "test-registry",
                "principals": [registry_authority.identity.model_dump(mode="json")],
            },
            "baseUrl": "https://registry.example",
            "displayName": "Private Registry",
            "operatorIdentity": "test-operator",
            "schema": {"id": "vms.compute", "version": "1"},
        }
    )

    descriptor = await registry_client.get_registry_descriptor()

    assert descriptor.access.posture == "key-gated"
    assert descriptor.access.acquisition_pointer == ("https://registry.example/access")


async def test_exact_descriptor_request_replay_returns_recorded_body(
    registry_client,
    db_session,
) -> None:
    request_id = "descriptor-replay"
    timestamp = int(time.time())

    first = await registry_client.get_registry_descriptor(
        request_id=request_id,
        timestamp=timestamp,
    )
    second = await registry_client.get_registry_descriptor(
        request_id=request_id,
        timestamp=timestamp,
    )

    assert second == first
    assert db_session.query(PublisherReplayReservation).count() == 1
