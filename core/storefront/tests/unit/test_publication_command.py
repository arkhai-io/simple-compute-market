from __future__ import annotations

from typing import Any

from core_storefront.publication_command import (
    StorefrontPublicationCommandCallbacks,
    StorefrontPublicationCommandConfig,
    build_storefront_publication_command,
    run_storefront_publication_command,
)
from core_storefront.publication_runner import PublicationSourceSelection
from core_storefront.publication_sources import PublicationSource


def _source(candidate: dict[str, Any] | None = None) -> PublicationSource:
    candidate = candidate or {"resource_id": "r1"}
    return PublicationSource(
        name="test",
        open_keys=lambda _db: {"open-r1"},
        close_stale=lambda _db, _url, _key: ["stale-1"],
        available_candidates=lambda _db: [candidate],
        skip_keys=lambda c: {str(c["resource_id"])},
        offer_resource=lambda c: {"resource_id": c["resource_id"]},
        record_published=lambda _db, c, listing_id: c.__setitem__("listing_id", listing_id),
        reopen_existing=lambda *_args: None,
        reopen_error_label="reopen test",
    )


def test_build_storefront_publication_command_wraps_selection() -> None:
    selection = PublicationSourceSelection(source_names=())
    config = StorefrontPublicationCommandConfig(
        db_path="db.sqlite",
        base_url="http://seller",
        private_key=None,
    )
    callbacks = StorefrontPublicationCommandCallbacks(
        build_payload=lambda *_args: ([{}], [], None),
        publish_offer=lambda *_args: {"status": "published"},
    )

    command = build_storefront_publication_command(
        selection,
        config=config,
        callbacks=callbacks,
    )

    assert command.selection is selection
    assert command.db_path == "db.sqlite"
    assert command.base_url == "http://seller"


def test_run_storefront_publication_command_uses_config_flags(monkeypatch) -> None:
    import core_storefront.publication_runner as runner

    monkeypatch.setattr(
        runner,
        "build_publication_source",
        lambda name, **kwargs: _source({"resource_id": name, **kwargs}),
    )
    selection = PublicationSourceSelection(
        source_names=("vms",),
        source_kwargs_by_name={"vms": {"price": "2"}},
    )
    config = StorefrontPublicationCommandConfig(
        db_path="db.sqlite",
        base_url="http://seller",
        private_key=None,
        close_stale=False,
        skip_open=False,
    )
    callbacks = StorefrontPublicationCommandCallbacks(
        build_payload=lambda *_args: ([{}], [], None),
        publish_offer=lambda offer, *_args: {
            "status": "published",
            "listing_id": offer["resource_id"],
        },
    )

    result = run_storefront_publication_command(
        selection,
        config=config,
        callbacks=callbacks,
    )

    assert result.closed == {}
    assert result.failed == []
    assert result.skipped == []
    assert result.published[0]["response"]["listing_id"] == "vms"
    assert result.published[0]["resource"] == {
        "resource_id": "vms",
        "price": "2",
        "listing_id": "vms",
    }


def test_run_storefront_publication_command_honors_skip_ids(monkeypatch) -> None:
    import core_storefront.publication_runner as runner

    monkeypatch.setattr(
        runner,
        "build_publication_source",
        lambda name, **_kwargs: _source({"resource_id": name}),
    )
    result = run_storefront_publication_command(
        PublicationSourceSelection(source_names=("vms",)),
        config=StorefrontPublicationCommandConfig(
            db_path="db.sqlite",
            base_url="http://seller",
            private_key=None,
            close_stale=False,
            skip_open=False,
        ),
        callbacks=StorefrontPublicationCommandCallbacks(
            build_payload=lambda *_args: ([{}], [], None),
            publish_offer=lambda *_args: {"status": "published"},
        ),
        skip_ids={"vms"},
    )

    assert result.published == []
    assert result.failed == []
    assert result.skipped == [{"resource_id": "vms"}]
