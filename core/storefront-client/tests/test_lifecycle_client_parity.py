"""Sync and async clients expose the same lifecycle-advance contract.

`docs/development/TESTING.md` requires a parity check whenever a client package
exposes both variants: a new method must be added to both in the same change.
The advance controls are how a scenario drives a paused storefront, and a
scenario using the sync client would not notice the async-only method until it
called it.
"""

from __future__ import annotations

import inspect

from storefront_client.client import StorefrontClient, SyncStorefrontClient


def test_lifecycle_advance_exists_on_both_clients() -> None:
    assert callable(getattr(StorefrontClient, "admin_run_lifecycle_cycle", None))
    assert callable(getattr(SyncStorefrontClient, "admin_run_lifecycle_cycle", None))


def test_lifecycle_advance_signatures_match() -> None:
    assert (
        inspect.signature(StorefrontClient.admin_run_lifecycle_cycle)
        == inspect.signature(SyncStorefrontClient.admin_run_lifecycle_cycle)
    )


def test_pause_and_resume_remain_paired() -> None:
    """Pause gained a `loops` field; both variants parse it through one model."""
    for name in ("admin_pause", "admin_resume"):
        assert (
            inspect.signature(getattr(StorefrontClient, name))
            == inspect.signature(getattr(SyncStorefrontClient, name))
        ), name
