"""Each capacity reconciliation starts with its source pass and ends by converging,
publishes only the domain's own listings, and never republishes one its guard refuses."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from core_storefront.capacity import CapacityDelta
from market_capacity_publication import (
    CapacityBindingError,
    CapacityProjection,
    CapacityReconcileContext,
    RegistryDivergence,
)

from arkhai_api_selling.publication import QuotaPublication, QuotaPublicationHooks
from tests.bundles import EXAMPLE


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["reserved", "released", None])
async def test_every_reconciliation_ends_by_converging_the_registries(
    monkeypatch, kind
):
    db = object()
    calls: list[str] = []
    publication = QuotaPublication(EXAMPLE, capacity=object(), registry=lambda: None)

    async def record(name):
        async def step(*args, **_kwargs):
            assert args[0] is db
            calls.append(name)
            return ()

        return step

    monkeypatch.setattr(publication, "close_on_source_mismatch", await record("source"))
    monkeypatch.setattr(publication, "close_after_capacity_change", await record("close"))
    monkeypatch.setattr(publication, "reopen_after_capacity_change", await record("reopen"))
    monkeypatch.setattr(publication, "converge", await record("converge"))

    await publication.reconciler(lambda: db)(
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
    assert calls[-1] == "converge"
    assert calls.count("converge") == 1


def _candidate(listing_resource, mode="example"):
    binding = SimpleNamespace(offering_mode=mode)
    return SimpleNamespace(payload={"listing_resource": listing_resource}, binding=binding)


def test_a_candidate_must_be_the_domains_listing_under_its_offering_mode():
    hooks = QuotaPublicationHooks(EXAMPLE, db=object())

    hooks.validate_candidate(_candidate('{"product": "Example", "quota": "quota-a"}'))
    with pytest.raises(CapacityBindingError, match="not the domain's"):
        hooks.validate_candidate(_candidate({"gpu_model": "H200"}))
    with pytest.raises(CapacityBindingError, match="mode differs"):
        hooks.validate_candidate(_candidate({"product": "Example"}, mode="other"))


class _DivergedRuntime:
    def __init__(self, divergences) -> None:
        self._divergences = divergences
        self.repaired: list[str] = []

    async def publication_divergence(self):
        return self._divergences

    async def converge(self, divergences):
        self.repaired = [divergence.listing_id for divergence in divergences]
        return {"repaired": tuple(self.repaired), "unrepaired": ()}


class _Listings:
    async def load_listing(self, *, listing_id):
        return {"listing_id": listing_id, "listing_resource": {"product": listing_id}}


async def test_divergence_repair_never_republishes_an_open_listing_its_guard_refuses():
    guarded = replace(
        EXAMPLE,
        publication_guards=(lambda resource: "blocked" if resource["product"] == "L-blocked" else None,),
    )
    runtime = _DivergedRuntime(
        (
            RegistryDivergence("L-blocked", "open", ("https://registry.example",)),
            RegistryDivergence("L-open", "open", ("https://registry.example",)),
            RegistryDivergence("L-closed", "closed", ("https://registry.example",)),
        )
    )

    class _Publication(QuotaPublication):
        def runtime(self, db):
            return runtime

    result = await _Publication(guarded, capacity=object(), registry=lambda: None).converge(_Listings())

    assert runtime.repaired == ["L-open", "L-closed"]
    assert result == {"repaired": ("L-open", "L-closed"), "unrepaired": ("L-blocked",)}
