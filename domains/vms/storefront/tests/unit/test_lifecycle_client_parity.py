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


def _public_operations(
    cls: type,
) -> dict[str, tuple[list[tuple[str, object, object, str]], str]]:
    """Each public method as its parameters -- (name, kind, default,
    annotation) each -- and its return annotation.

    Annotations are compared as text with surrounding quotes removed: under
    postponed evaluation one variant may spell an annotation ``"'str | None'"``
    and the other ``'str | None'``, which name the same type. An async
    method's return annotation names what awaiting it yields, so it is
    compared directly with the sync variant's.
    """

    def annotation(value: object) -> str:
        if value is inspect.Parameter.empty:
            return ""
        return str(value).strip("'\"")

    operations = {}
    for name, member in vars(cls).items():
        if name.startswith("_") or not callable(member):
            continue
        signature = inspect.signature(member)
        operations[name] = (
            [
                (p.name, p.kind, p.default, annotation(p.annotation))
                for p in signature.parameters.values()
            ],
            annotation(signature.return_annotation),
        )
    return operations


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


def test_both_clients_address_the_publication_loop_alike() -> None:
    """The loop name reaches the same route and signed operation from either
    variant, for the step and for its dry run."""
    import asyncio

    sent: dict[str, list[tuple]] = {"async": [], "sync": []}

    def recorder(variant: str, *, awaitable: bool):
        def record(path, body, **kwargs):
            sent[variant].append((path, body, kwargs))
            return {}

        async def record_async(path, body, **kwargs):
            return record(path, body, **kwargs)

        return record_async if awaitable else record

    async_client = object.__new__(StorefrontClient)
    async_client._authenticated_post = recorder("async", awaitable=True)
    sync_client = object.__new__(SyncStorefrontClient)
    sync_client._authenticated_post = recorder("sync", awaitable=False)

    for method in ("admin_run_lifecycle_cycle", "admin_dry_run_lifecycle_cycle"):
        asyncio.run(getattr(async_client, method)("publication"))
        getattr(sync_client, method)("publication")

    assert sent["async"] == sent["sync"]
    assert [path for path, _, _ in sent["async"]] == [
        "/api/v1/admin/lifecycle/publication/run-cycle",
        "/api/v1/admin/lifecycle/publication/dry-run",
    ]
