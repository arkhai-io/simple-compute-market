"""Integration tests for stable publisher and principal discovery."""

from __future__ import annotations

import pytest
from market_identity import Identity

from registry_client import RegistryClientError
from registry_client.models import Publisher, PublisherListResponse


class TestListPublishers:
    async def test_empty_registry_returns_empty_list(self, registry_client):
        result = await registry_client.list_publishers()
        assert isinstance(result, PublisherListResponse)
        assert result.publishers == []

    async def test_publisher_appears_after_create(
        self,
        registry_client,
        maker_publisher,
    ):
        result = await registry_client.list_publishers()
        assert maker_publisher.publisher_id in [
            publisher.publisher_id for publisher in result.publishers
        ]

    async def test_all_items_are_publisher(
        self,
        registry_client,
        maker_publisher,
        taker_publisher,
    ):
        result = await registry_client.list_publishers()
        assert len(result.publishers) == 2
        assert all(isinstance(publisher, Publisher) for publisher in result.publishers)

    async def test_resolve_by_complete_principal(
        self,
        registry_client,
        maker_publisher,
        maker_signer,
    ):
        result = await registry_client.list_publishers(principal=maker_signer.identity)
        assert result.publishers[0].publisher_id == maker_publisher.publisher_id

    async def test_unknown_principal_returns_empty(
        self,
        registry_client,
        maker_publisher,
    ):
        unknown = Identity(scheme="eip191", identifier="0x" + "de" * 20)
        result = await registry_client.list_publishers(principal=unknown)
        assert result.publishers == []


class TestGetPublisher:
    async def test_returns_entity(self, registry_client, maker_publisher):
        publisher = await registry_client.get_publisher(maker_publisher.publisher_id)
        assert publisher.publisher_id == maker_publisher.publisher_id
        assert publisher.storefront_url == "http://localhost:8001/"

    async def test_identity_binding_is_canonical(
        self,
        registry_client,
        maker_publisher,
        maker_signer,
    ):
        publisher = await registry_client.get_publisher(maker_publisher.publisher_id)
        assert len(publisher.identities) == 1
        assert publisher.identities[0].principal == maker_signer.identity
        assert publisher.identities[0].status == "primary"

    async def test_404_raises(self, registry_client):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.get_publisher(999999)
        assert exc_info.value.status_code == 404
