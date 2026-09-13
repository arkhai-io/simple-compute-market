"""Publishing a source another listing already holds is a conflict, not a fault.

A listing's publication binding is unique on its derivation key -- site,
offering mode, contract, and source identity (pool, resource, GPU count). A
second listing against the same source breaches that, and the database reports
it as `UNIQUE constraint failed: storefront_listing_bindings.derivation_key`.

Letting that reach the caller was wrong twice over. It arrived as a `500`, so a
conflicting request looked like a server fault; and it named a column rather
than the thing the caller did, which is why a real collision between two test
scenarios read as a mystery for several rounds instead of "you already
published this resource".
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from market_storefront.services.listing_service import (
    ListingService as _RealService,
    ListingSourceAlreadyBound,
)


class _Binding(SimpleNamespace):
    pass


def _binding() -> _Binding:
    return _Binding(
        derivation_key="deadbeef",
        source_envelope_json=(
            '{"kind":"compute.listing_source","payload":'
            '{"resource_id":"compute-e2e-deal-001","site_id":"default"}}'
        ),
    )


class _Service:
    """The describer under test, with only the collaborator it uses."""

    def __init__(self, holder: str | None, *, raises: bool = False) -> None:
        async def _lookup(_key: str) -> str | None:
            if raises:
                raise sqlite3.OperationalError("database is locked")
            return holder

        self._db = SimpleNamespace(listing_id_for_derivation_key=_lookup)

    # Bound from the real service so the test exercises production code rather
    # than a copy of it.
    _describe_source_conflict = _RealService._describe_source_conflict


class TestDescribingTheConflict:
    async def test_names_the_listing_that_holds_the_source(self):
        service = _Service(holder="listing-already-here")
        message = await service._describe_source_conflict(
            _binding(),
            sqlite3.IntegrityError(
                "UNIQUE constraint failed: "
                "storefront_listing_bindings.derivation_key"
            ),
        )
        assert message is not None
        assert "listing-already-here" in message, (
            "the caller needs to know which of its listings holds the source"
        )
        assert "compute-e2e-deal-001" in message, (
            "the source itself is what the caller has to change"
        )
        assert "derivation_key" not in message, (
            "a column name tells the caller which index complained, not what "
            "they did wrong"
        )

    async def test_unrelated_integrity_errors_are_not_reported_as_conflicts(self):
        """Only this constraint is the caller's to fix.

        The driver reports every integrity breach the same way, so matching on
        the exception type would turn unrelated database faults into confident
        advice about resource ids.
        """
        service = _Service(holder="listing-already-here")
        assert await service._describe_source_conflict(
            _binding(),
            sqlite3.IntegrityError("NOT NULL constraint failed: listings.status"),
        ) is None

    async def test_still_describes_when_the_holder_cannot_be_resolved(self):
        """A failed lookup must not replace the conflict with a second error.

        Reporting is best-effort: the caller is better served by "another
        listing holds this source" than by the lookup's own failure.
        """
        service = _Service(holder=None, raises=True)
        message = await service._describe_source_conflict(
            _binding(),
            sqlite3.IntegrityError(
                "UNIQUE constraint failed: "
                "storefront_listing_bindings.derivation_key"
            ),
        )
        assert message is not None
        assert "another listing" in message


class TestTheStatusCode:
    async def test_a_bound_source_is_a_409_not_a_500(self):
        """The controller's mapping is the contract callers see."""
        from market_storefront.controllers import listings_controller as lc

        class _Svc:
            async def create_listing(self, _body):
                raise ListingSourceAlreadyBound(
                    "this publication source is already bound to "
                    "listing 'other': {...}"
                )

        controller = object.__new__(lc.ListingsController)
        controller._listing_svc = _Svc()

        with pytest.raises(HTTPException) as raised:
            await lc.ListingsController.create_listing(controller, object())

        assert raised.value.status_code == 409, (
            "a caller publishing an already-bound source made a conflicting "
            "request; a 500 would report it as the storefront's fault"
        )
        assert "already bound" in str(raised.value.detail)
