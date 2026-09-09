from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from core_storefront.registry_publication import (
    close_listing_in_registries,
    ensure_json_obj,
    publish_listing_to_registries,
)


@dataclass
class ListingRequest:
    listing_id: str
    offer: dict[str, Any]
    accepted_escrows: list[dict[str, Any]]
    settlement_options: list[dict[str, Any]]
    demands: list[dict[str, Any]]
    max_duration_seconds: int | None
    storefront_url: str | None


@dataclass
class UpdateListingRequest:
    updates: dict[str, Any]


class FakeRegistryClient:
    urls = ["http://r1", "http://r2"]

    def __init__(self) -> None:
        self.published: dict[str, ListingRequest] | None = None
        self.publish_results: list[dict[str, Any]] | None = None
        self.updated: tuple[str, dict[str, UpdateListingRequest]] | None = None

    async def __aenter__(self) -> "FakeRegistryClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def publish_listing_per_registry(
        self,
        payloads: dict[str, ListingRequest],
    ) -> list[dict[str, Any]]:
        self.published = payloads
        if self.publish_results is not None:
            return self.publish_results
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
                "storefront_url": "http://seller",
            },
            enabled=True,
            registry_client_factory=lambda: client,
            listing_request_factory=ListingRequest,
            storefront_url="http://seller",
            record_publications=lambda listing_id, results: _record(
                recorded,
                listing_id,
                results,
            ),
            on_published=lambda **kwargs: events.append(kwargs),
        )

    result = asyncio.run(run())

    assert result == {
        "status": "published",
        "listing_id": "L1",
        "registry_results": [
            {
                "registry_url": "http://r1",
                "success": True,
                "registry_assigned_id": "L1",
                "error_type": None,
                "status_code": None,
            },
            {
                "registry_url": "http://r2",
                "success": True,
                "registry_assigned_id": "L1",
                "error_type": None,
                "status_code": None,
            },
        ],
    }
    assert client.published is not None
    assert client.published["http://r1"].offer == {"gpu_model": "H200"}
    assert client.published["http://r1"].storefront_url == "http://seller"
    assert recorded[0][0] == "L1"
    assert events[0]["offer_resource"] == {"gpu_model": "H200"}


def test_publish_listing_preserves_mixed_target_order_and_aggregate_success() -> None:
    client = FakeRegistryClient()
    client.publish_results = [
        {
            "registry_url": "http://r1",
            "success": False,
            "response": None,
            "error": "connection refused",
            "error_type": "ConnectError",
            "status_code": None,
            "payload": {"listing_id": "L-mixed"},
            "registry_assigned_id": None,
        },
        {
            "registry_url": "http://r2",
            "success": True,
            "response": {"listing_id": "L-mixed"},
            "error": None,
            "error_type": None,
            "status_code": None,
            "payload": {"listing_id": "L-mixed"},
            "registry_assigned_id": "L-mixed",
        },
    ]
    recorded: list[tuple[str, list[dict[str, Any]]]] = []

    async def run() -> dict[str, Any]:
        return await publish_listing_to_registries(
            {
                "listing_id": "L-mixed",
                "offer_resource": {},
                "accepted_escrows": [],
                "storefront_url": "http://seller",
            },
            enabled=True,
            registry_client_factory=lambda: client,
            listing_request_factory=ListingRequest,
            storefront_url="http://seller",
            record_publications=lambda listing_id, results: _record(
                recorded,
                listing_id,
                results,
            ),
        )

    result = asyncio.run(run())

    assert result["status"] == "published"
    assert result["registry_results"] == [
        {
            "registry_url": "http://r1",
            "success": False,
            "registry_assigned_id": None,
            "error_type": "ConnectError",
            "status_code": None,
        },
        {
            "registry_url": "http://r2",
            "success": True,
            "registry_assigned_id": "L-mixed",
            "error_type": None,
            "status_code": None,
        },
    ]
    assert recorded == [("L-mixed", client.publish_results)]


def test_publish_listing_all_failure_is_structured_and_redacted() -> None:
    client = FakeRegistryClient()
    credential = "Bearer should-never-be-returned"
    client.publish_results = [
        {
            "registry_url": "http://r1",
            "success": False,
            "response": None,
            "error": f"request rejected with Authorization: {credential}",
            "error_type": "RegistryClientError",
            "status_code": 401,
            "payload": {"listing_id": "L-failed"},
            "registry_assigned_id": None,
        },
        {
            "registry_url": "http://r2",
            "success": False,
            "response": None,
            "error": "connection failed",
            "error_type": "ConnectError",
            "status_code": None,
            "payload": {"listing_id": "L-failed"},
            "registry_assigned_id": None,
        },
    ]

    async def run() -> dict[str, Any]:
        return await publish_listing_to_registries(
            {
                "listing_id": "L-failed",
                "offer_resource": {},
                "accepted_escrows": [],
                "storefront_url": "http://seller",
            },
            enabled=True,
            registry_client_factory=lambda: client,
            listing_request_factory=ListingRequest,
            storefront_url="http://seller",
        )

    result = asyncio.run(run())

    assert result["status"] == "error"
    assert result["registry_results"] == [
        {
            "registry_url": "http://r1",
            "success": False,
            "registry_assigned_id": None,
            "error_type": "RegistryClientError",
            "status_code": 401,
        },
        {
            "registry_url": "http://r2",
            "success": False,
            "registry_assigned_id": None,
            "error_type": "ConnectError",
            "status_code": None,
        },
    ]
    assert credential not in repr(result)


def test_publish_listing_setup_failure_is_categorized_and_redacted(caplog) -> None:
    marker = "PRIVATE_TEST_MARKER"

    def fail_factory():
        raise RuntimeError(marker)

    async def run() -> dict[str, Any]:
        return await publish_listing_to_registries(
            {
                "listing_id": "L-setup-failed",
                "offer_resource": {},
                "accepted_escrows": [],
                "storefront_url": "http://seller",
            },
            enabled=True,
            registry_client_factory=fail_factory,
            listing_request_factory=ListingRequest,
            storefront_url="http://seller",
        )

    with caplog.at_level("WARNING"):
        result = asyncio.run(run())

    assert result == {
        "status": "error",
        "listing_id": "L-setup-failed",
        "message": "registry publication setup failed (RuntimeError)",
        "failure_stage": "setup",
        "error_type": "RuntimeError",
        "status_code": None,
    }
    assert marker not in repr(result)
    assert marker not in caplog.text


def test_publish_listing_context_failure_retains_known_receipts(caplog) -> None:
    marker = "PRIVATE_CONTEXT_MARKER"

    class FailingExitRegistryClient(FakeRegistryClient):
        async def __aexit__(self, *args: Any) -> None:
            raise RuntimeError(marker)

    client = FailingExitRegistryClient()

    async def run() -> dict[str, Any]:
        return await publish_listing_to_registries(
            {
                "listing_id": "L-context-failed",
                "offer_resource": {},
                "accepted_escrows": [],
                "storefront_url": "http://seller",
            },
            enabled=True,
            registry_client_factory=lambda: client,
            listing_request_factory=ListingRequest,
            storefront_url="http://seller",
        )

    with caplog.at_level("WARNING"):
        result = asyncio.run(run())

    assert result["status"] == "error"
    assert result["failure_stage"] == "context"
    assert result["message"] == "registry publication context failed (RuntimeError)"
    assert [item["registry_url"] for item in result["registry_results"]] == [
        "http://r1",
        "http://r2",
    ]
    assert all(item["success"] for item in result["registry_results"])
    assert marker not in repr(result)
    assert marker not in caplog.text


def test_mixed_publish_retains_receipts_when_persistence_fails(caplog) -> None:
    client = FakeRegistryClient()
    marker = "PRIVATE_PERSISTENCE_MARKER"
    client.publish_results = [
        {
            "registry_url": "http://r1",
            "success": True,
            "response": {"listing_id": "L-persistence"},
            "error": None,
            "error_type": None,
            "status_code": None,
            "payload": {"listing_id": "L-persistence"},
            "registry_assigned_id": "L-persistence",
        },
        {
            "registry_url": "http://r2",
            "success": False,
            "response": None,
            "error": "request rejected",
            "error_type": "RegistryClientError",
            "status_code": 403,
            "payload": {"listing_id": "L-persistence"},
            "registry_assigned_id": None,
        },
    ]

    async def fail_record(
        _listing_id: str,
        _results: list[dict[str, Any]],
    ) -> None:
        raise RuntimeError(marker)

    async def run() -> dict[str, Any]:
        return await publish_listing_to_registries(
            {
                "listing_id": "L-persistence",
                "offer_resource": {},
                "accepted_escrows": [],
                "storefront_url": "http://seller",
            },
            enabled=True,
            registry_client_factory=lambda: client,
            listing_request_factory=ListingRequest,
            storefront_url="http://seller",
            record_publications=fail_record,
        )

    with caplog.at_level("WARNING"):
        result = asyncio.run(run())

    assert result["status"] == "error"
    assert result["failure_stage"] == "persistence"
    assert result["error_type"] == "RuntimeError"
    assert result["message"] == (
        "registry publication persistence failed (RuntimeError)"
    )
    assert [item["registry_url"] for item in result["registry_results"]] == [
        "http://r1",
        "http://r2",
    ]
    assert [item["success"] for item in result["registry_results"]] == [True, False]
    assert marker not in repr(result)
    assert marker not in caplog.text


def test_successful_publish_retains_receipts_when_event_callback_fails(caplog) -> None:
    client = FakeRegistryClient()
    marker = "PRIVATE_EVENT_MARKER"

    def fail_event(**_kwargs: Any) -> None:
        raise RuntimeError(marker)

    async def run() -> dict[str, Any]:
        return await publish_listing_to_registries(
            {
                "listing_id": "L-event",
                "offer_resource": {},
                "accepted_escrows": [],
                "storefront_url": "http://seller",
            },
            enabled=True,
            registry_client_factory=lambda: client,
            listing_request_factory=ListingRequest,
            storefront_url="http://seller",
            on_published=fail_event,
        )

    with caplog.at_level("WARNING"):
        result = asyncio.run(run())

    assert result["status"] == "error"
    assert result["failure_stage"] == "event"
    assert result["error_type"] == "RuntimeError"
    assert result["message"] == "registry publication event failed (RuntimeError)"
    assert [item["registry_url"] for item in result["registry_results"]] == [
        "http://r1",
        "http://r2",
    ]
    assert all(item["success"] for item in result["registry_results"])
    assert marker not in repr(result)
    assert marker not in caplog.text


def test_publish_listing_rejects_legacy_seller_locator() -> None:
    client = FakeRegistryClient()

    async def run() -> dict[str, Any]:
        return await publish_listing_to_registries(
            {
                "listing_id": "L1",
                "seller": "http://seller",
                "offer_resource": {},
            },
            enabled=True,
            registry_client_factory=lambda: client,
            listing_request_factory=ListingRequest,
            storefront_url="http://seller",
        )

    result = asyncio.run(run())

    assert result["status"] == "error"
    assert "storefront_url is required" in result["message"]
    assert client.published is None


def test_close_listing_in_registries_updates_selected_targets() -> None:
    client = FakeRegistryClient()
    recorded: list[tuple[str, list[dict[str, Any]]]] = []

    async def run() -> dict[str, Any]:
        return await close_listing_in_registries(
            "L1",
            enabled=True,
            registry_client_factory=lambda: client,
            update_listing_request_factory=UpdateListingRequest,
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
