"""Both listing entry points reach the composed listing service with what was asked."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from typer.testing import CliRunner

import apicredits_storefront.container as container
from apicredits_storefront import cli, server
from apicredits_storefront.controllers.listings_controller import (
    ListingsController,
    PublishFromQuotaRequest,
)


class _ListingService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def publish_from_quota(self, **request):
        self.calls.append(request)
        return {"status": "created", "listing_id": "L-1"}


async def test_the_publish_route_passes_the_submitted_settlement_clauses():
    service = _ListingService()
    controller = ListingsController.__new__(ListingsController)
    controller._listing_svc = service
    clauses = [{"mechanism": "arkhai.payments.v1", "asset": "usd"}]

    await controller.publish_from_quota(
        PublishFromQuotaRequest(
            resource_id="svc-quota", service_name="Acme", settlement_clauses=clauses
        )
    )

    assert service.calls[0]["settlement_clauses"] == clauses


def test_the_publish_command_uses_the_storefronts_composed_listing_service(monkeypatch):
    service = _ListingService()
    signer = SimpleNamespace(identity="seller")
    # The command sets these on the container; monkeypatch restores them.
    monkeypatch.setattr(container, "resolved_marketplace_signer", None)
    monkeypatch.setattr(container, "resolved_sqlite_client", None)
    monkeypatch.setattr(
        server,
        "_build_api_credit_services",
        lambda domain: SimpleNamespace(
            listing_service=service, marketplace_signer=signer, sqlite_client=object()
        ),
    )

    result = CliRunner().invoke(
        cli.app,
        ["publish", "--resource-id", "svc-quota", "--service-name", "Acme"],
    )

    assert result.exit_code == 0, result.output
    assert service.calls[0]["resource_id"] == "svc-quota"


class _GuardedPublication:
    def refusal(self, listing):
        return "blocked"

    async def publish(self, db, listing):
        raise AssertionError("a refused listing is never published")


class _PausedListings:
    def __init__(self) -> None:
        self.paused = True

    async def load_listing(self, *, listing_id):
        return {"listing_id": listing_id, "listing_resource": {}}

    async def set_listing_paused(self, *, listing_id, paused):
        self.paused = paused


async def test_resuming_a_listing_its_publication_guard_refuses_leaves_it_paused(monkeypatch):
    monkeypatch.setattr(container, "QUOTA_PUBLICATION", _GuardedPublication())
    listings = _PausedListings()
    controller = ListingsController.__new__(ListingsController)
    controller._db = listings

    with pytest.raises(HTTPException) as refused:
        await controller.resume_listing("L-1")

    assert (refused.value.status_code, refused.value.detail) == (409, "blocked")
    assert listings.paused is True
