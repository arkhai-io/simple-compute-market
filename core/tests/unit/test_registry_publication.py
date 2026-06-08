from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from market_core.registry_publication import (
    close_listing_in_registries,
    ensure_json_obj,
    publish_listing_to_registries,
)


@dataclass
class ListingRequest:
    listing_id: str
    offer: dict[str, Any]
    accepted_escrows: list[dict[str, Any]]
    demands: list[dict[str, Any]]
    max_duration_seconds: int | None
    storefront_url: str | None


@dataclass
class UpdateListingRequest:
    updates: dict[str, Any]
    private_key: str


class FakeRegistryClient:
    urls = ["http://r1", "http://r2"]

    def __init__(self) -> None:
        self.published: dict[str, ListingRequest] | None = None
        self.updated: tuple[str, dict[str, UpdateListingRequest]] | None = None

    async def __aenter__(self) -> "FakeRegistryClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def publish_listing_per_registry(
        self,
        payloads: dict[str, ListingRequest],
        *,
        private_key: str,
    ) -> list[dict[str, Any]]:
        assert private_key == "0xkey"
        self.published = payloads
        return [
            {
                "registry_url": url,
                "success": True,
                "response": {"listing_id": request.listing_id},
                "error": None,
                "payload": {"listing_id": request.listing_id},
                "registry_assigned_id": request.listing_id,
            }
            for url, request in payloads.items()
        ]

    async def update_listing_per_registry(
        self,
        listing_id: str,
        payloads: dict[str, UpdateListingRequest],
    ) -> list[dict[str, Any]]:
        self.updated = (listing_id, payloads)
        return [
            {
                "registry_url": url,
                "success": True,
                "response": {"listing_id": listing_id},
                "error": None,
                "payload": request.updates,
                "registry_assigned_id": listing_id,
            }
            for url, request in payloads.items()
        ]


def test_ensure_json_obj_decodes_strings() -> None:
    assert ensure_json_obj('{"gpu_model": "H200"}', {}) == {"gpu_model": "H200"}
    assert ensure_json_obj("not-json", {}) == {}
    assert ensure_json_obj(None, []) == []


def test_publish_listing_to_registries_builds_payload_and_records_results() -> None:
    client = FakeRegistryClient()
    recorded: list[tuple[str, list[dict[str, Any]]]] = []
    events: list[dict[str, Any]] = []

    async def run() -> dict[str, Any]:
        return await publish_listing_to_registries(
            {
                "listing_id": "L1",
                "offer_resource": '{"gpu_model": "H200"}',
                "accepted_escrows": "[]",
                "demands": "[]",
                "max_duration_seconds": 3600,
            },
            enabled=True,
            registry_client_factory=lambda: client,
            listing_request_factory=ListingRequest,
            private_key="0xkey",
            storefront_url="http://seller",
            record_publications=lambda listing_id, results: _record(
                recorded,
                listing_id,
                results,
            ),
            on_published=lambda **kwargs: events.append(kwargs),
        )

    result = asyncio.run(run())

    assert result == {"status": "published", "listing_id": "L1"}
    assert client.published is not None
    assert client.published["http://r1"].offer == {"gpu_model": "H200"}
    assert client.published["http://r1"].storefront_url == "http://seller"
    assert recorded[0][0] == "L1"
    assert events[0]["offer_resource"] == {"gpu_model": "H200"}


def test_close_listing_in_registries_updates_selected_targets() -> None:
    client = FakeRegistryClient()
    recorded: list[tuple[str, list[dict[str, Any]]]] = []

    async def run() -> dict[str, Any]:
        return await close_listing_in_registries(
            "L1",
            enabled=True,
            registry_client_factory=lambda: client,
            update_listing_request_factory=UpdateListingRequest,
            private_key="0xkey",
            select_target_registries=lambda _listing_id, _fallback: _select(
                ["http://r2"]
            ),
            record_publications=lambda listing_id, results: _record(
                recorded,
                listing_id,
                results,
            ),
        )

    result = asyncio.run(run())

    assert result["status"] == "closed"
    assert client.updated is not None
    assert client.updated[0] == "L1"
    assert list(client.updated[1]) == ["http://r2"]
    assert client.updated[1]["http://r2"].updates == {"status": "closed"}
    assert recorded[0][0] == "L1"


async def _record(
    sink: list[tuple[str, list[dict[str, Any]]]],
    listing_id: str,
    results: list[dict[str, Any]],
) -> None:
    sink.append((listing_id, results))


async def _select(urls: list[str]) -> list[str]:
    return urls
