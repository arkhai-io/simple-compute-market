"""Integration tests for the publishers API."""

from __future__ import annotations

import pytest

from registry_client import RegistryClientError
from registry_client.models import Publisher, PublisherListResponse
from tests.integration.conftest import MAKER_ADDRESS


class TestListPublishers:
    async def test_empty_registry_returns_empty_list(self, registry_client):
        result = await registry_client.list_publishers()
        assert isinstance(result, PublisherListResponse)
        assert result.publishers == []

    async def test_publisher_appears_after_create(self, registry_client, maker_publisher):
        result = await registry_client.list_publishers()
        assert maker_publisher.publisher_id in [p.publisher_id for p in result.publishers]

    async def test_all_items_are_publisher(self, registry_client, maker_publisher, taker_publisher):
        result = await registry_client.list_publishers()
        assert len(result.publishers) == 2
        assert all(isinstance(p, Publisher) for p in result.publishers)

    async def test_resolve_by_identifier(self, registry_client, maker_publisher):
        result = await registry_client.list_publishers(identifier=MAKER_ADDRESS)
        assert len(result.publishers) == 1
        assert result.publishers[0].publisher_id == maker_publisher.publisher_id

    async def test_resolve_by_identifier_is_case_insensitive(self, registry_client, maker_publisher):
        result = await registry_client.list_publishers(identifier=MAKER_ADDRESS.upper())
        assert len(result.publishers) == 1

    async def test_unknown_identifier_returns_empty(self, registry_client, maker_publisher):
        result = await registry_client.list_publishers(identifier="0x" + "de" * 20)
        assert result.publishers == []


class TestGetPublisher:
    async def test_returns_entity(self, registry_client, maker_publisher):
        publisher = await registry_client.get_publisher(maker_publisher.publisher_id)
        assert isinstance(publisher, Publisher)
        assert publisher.publisher_id == maker_publisher.publisher_id
        assert publisher.storefront_url == "http://localhost:8001/"

    async def test_identities_populated(self, registry_client, maker_publisher):
        publisher = await registry_client.get_publisher(maker_publisher.publisher_id)
        assert len(publisher.identities) == 1
        assert publisher.identities[0].scheme == "eip191"
        assert publisher.identities[0].identifier == MAKER_ADDRESS.lower()

    async def test_404_raises(self, registry_client):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.get_publisher(999999)
        assert exc_info.value.status_code == 404
