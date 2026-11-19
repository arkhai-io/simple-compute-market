"""Each capacity reconciliation starts with its source pass and ends by
converging the registries, then retiring the listings it does not hold."""

from __future__ import annotations

import pytest
from core_storefront.capacity import CapacityDelta
from market_capacity_publication import CapacityProjection, CapacityReconcileContext

from apicredits_storefront.services import publication_service
from apicredits_storefront.services.capacity_client import _capacity_reconciler


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["reserved", "released", None])
async def test_every_reconciliation_ends_by_converging_then_sweeping_the_registries(
    monkeypatch, kind
):
    db = object()
    calls: list[str] = []

    async def record(name):
        async def step(*args, **_kwargs):
            assert args[0] is db
            calls.append(name)
            return ()

        return step

    monkeypatch.setattr(
        publication_service,
        "close_token_listings_on_source_mismatch",
        await record("source"),
    )
    monkeypatch.setattr(
        publication_service,
        "close_token_listings_after_capacity_change",
        await record("close"),
    )
    monkeypatch.setattr(
        publication_service,
        "reopen_token_listings_after_capacity_change",
        await record("reopen"),
    )
    monkeypatch.setattr(publication_service, "converge_registries", await record("converge"))
    monkeypatch.setattr(publication_service, "retire_unheld_listings", await record("retire"))

    await _capacity_reconciler(lambda: db)(
        CapacityReconcileContext(
            projections=(CapacityProjection("tokens", ()),),
            availability={},
            delta=None
            if kind is None
            else CapacityDelta(kind=kind, version=1, site="tokens"),
        )
    )

    # A pool move is fed as a release, so the source pass cannot wait for a
    # consuming event.
    assert calls[0] == "source"
    # Convergence repairs what the storefront records; the sweep then closes
    # what it does not hold, so it runs last.
    assert calls[-2:] == ["converge", "retire"]
    assert calls.count("converge") == 1
    assert calls.count("retire") == 1
