"""Sync and async storefront clients expose the same lifecycle-advance contract.

`docs/development/TESTING.md` requires this check to live with the owning
*service*, not the client package, because the service owns the
contract-validation boundary. The advance controls are how a scenario drives a
paused storefront, and a scenario using the sync client would not notice an
async-only method until it called it.
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


def test_lifecycle_dry_run_exists_on_both_clients() -> None:
    """The read half of an advance is as load-bearing as the advance.

    A scenario checks what a held loop is about to do, then does it. A
    dry-run available on only one client flavour would be found by whichever
    scenario reached for the other one.
    """
    assert callable(getattr(StorefrontClient, "admin_dry_run_lifecycle_cycle", None))
    assert callable(
        getattr(SyncStorefrontClient, "admin_dry_run_lifecycle_cycle", None)
    )
    assert (
        inspect.signature(StorefrontClient.admin_dry_run_lifecycle_cycle)
        == inspect.signature(SyncStorefrontClient.admin_dry_run_lifecycle_cycle)
    )
    assert (
        inspect.signature(StorefrontClient.admin_dry_run_lifecycle_cycle)
        == inspect.signature(StorefrontClient.admin_run_lifecycle_cycle)
    ), "a caller switching between the two should not have to switch arguments"


def test_pause_and_resume_remain_paired() -> None:
    """Pause gained a `loops` field; both variants parse it through one model."""
    for name in ("admin_pause", "admin_resume"):
        assert (
            inspect.signature(getattr(StorefrontClient, name))
            == inspect.signature(getattr(SyncStorefrontClient, name))
        ), name


def _public_operations(cls: type) -> dict[str, list[tuple[str, object, object, str]]]:
    """Each public method as (name, kind, default, annotation) per parameter.

    Annotations are compared as text with surrounding quotes removed: under
    postponed evaluation one variant may spell an annotation ``"'str | None'"``
    and the other ``'str | None'``, which name the same type.
    """

    def annotation(value: object) -> str:
        if value is inspect.Parameter.empty:
            return ""
        return str(value).strip("'\"")

    return {
        name: [
            (p.name, p.kind, p.default, annotation(p.annotation))
            for p in inspect.signature(member).parameters.values()
        ]
        for name, member in vars(cls).items()
        if not name.startswith("_") and callable(member)
    }


def test_every_public_operation_matches_between_the_clients() -> None:
    """The whole public surface, not only the lifecycle controls.

    A method added to one variant, or a parameter renamed on one and not the
    other, would otherwise surface only when a caller of the other variant
    reached it.
    """
    async_ops = _public_operations(StorefrontClient)
    sync_ops = _public_operations(SyncStorefrontClient)

    assert set(async_ops) == set(sync_ops)
    assert async_ops == sync_ops
