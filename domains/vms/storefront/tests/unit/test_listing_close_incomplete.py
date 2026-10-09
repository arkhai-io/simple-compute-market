"""A seller's close that does not reach local state is reported as retryable.

The close is local first: when the listing write fails, no registry has been
told, and the listing is unchanged. The caller learns it can retry rather than
seeing a server fault.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException

from market_storefront.controllers import listings_controller as lc


class _Service:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def close_listing(self, listing_id: str):
        raise self._error


def _controller(error: Exception) -> lc.ListingsController:
    controller = object.__new__(lc.ListingsController)
    controller._listing_svc = _Service(error)
    return controller


async def test_a_local_database_failure_is_reported_as_retryable():
    controller = _controller(sqlite3.OperationalError("database is locked"))

    with pytest.raises(HTTPException) as exc_info:
        await lc.ListingsController.close_listing(controller, "listing-1")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error"] == "listing_close_incomplete"


async def test_an_unexpected_failure_remains_a_server_fault():
    controller = _controller(RuntimeError("boom"))

    with pytest.raises(HTTPException) as exc_info:
        await lc.ListingsController.close_listing(controller, "listing-1")

    assert exc_info.value.status_code == 500
