from __future__ import annotations

from typing import Any

import pytest

from core_storefront.publication_runner import (
    PublicationSourceSelection,
    close_stale_publication_listings,
    open_publication_keys,
    publish_round,
    run_publication_cycle,
)
from core_storefront.publication_sources import PublicationSource


def _source(
    *,
    name: str = "test",
    candidate: dict[str, Any] | None = None,
    open_keys: set[str] | None = None,
) -> PublicationSource:
    candidate = candidate or {"resource_id": name, "price": "1"}
    return PublicationSource(
        name=name,
        open_keys=lambda _db: open_keys or set(),
        close_stale=lambda _db, _url: [f"stale-{name}"],
        available_candidates=lambda _db: [candidate],
        skip_keys=lambda value: {str(value["resource_id"])},
        offer_resource=lambda value: {"resource_id": value["resource_id"]},
        record_published=lambda _db, value, listing_id: value.__setitem__(
            "listing_id", listing_id
        ),
        reopen_existing=lambda *_args: None,
        reopen_error_label=f"reopen {name}",
    )


def _payload(*_args):
    return ([{"escrow": "e"}], [{"demand": "d"}], 60)


def _publish(offer, *_args):
    return {
        "status": "published",
        "listing_id": f"listing-{offer['resource_id']}",
    }


def test_lifecycle_helpers_union_frozen_sources() -> None:
    first = _source(name="first", open_keys={"a"})
    second = _source(name="second", open_keys={"b"})

    assert open_publication_keys((first, second), "db.sqlite") == {"a", "b"}
    assert close_stale_publication_listings(
        (first, second),
        db_path="db.sqlite",
        base_url="http://seller",
    ) == {"first": ["stale-first"], "second": ["stale-second"]}


def test_publish_round_is_schema_opaque() -> None:
    candidate = {"resource_id": "r1", "price": "1"}

    published, failed, skipped = publish_round(
        (_source(candidate=candidate),),
        db_path="db.sqlite",
        base_url="http://seller",
        build_payload=_payload,
        publish_offer=_publish,
    )

    assert failed == []
    assert skipped == []
    assert published[0]["response"]["listing_id"] == "listing-r1"
    assert candidate["listing_id"] == "listing-r1"


def test_publish_round_skips_covered_candidate() -> None:
    published, failed, skipped = publish_round(
        (_source(candidate={"resource_id": "r1", "price": "1"}),),
        db_path="db.sqlite",
        base_url="http://seller",
        build_payload=_payload,
        publish_offer=_publish,
        skip_ids={"r1"},
    )

    assert published == []
    assert failed == []
    assert skipped == [{"resource_id": "r1", "price": "1"}]


def test_selection_reuses_exact_prebuilt_sources_across_cycle() -> None:
    source = _source(name="vms")
    selection = PublicationSourceSelection(sources=(source,))

    assert selection.build_sources() == (source,)
    assert selection.source_names == ("vms",)
    result = selection.run_cycle(
        db_path="db.sqlite",
        base_url="http://seller",
        build_payload=_payload,
        publish_offer=_publish,
    )

    assert result.closed == {"vms": ["stale-vms"]}
    assert result.published[0]["response"]["listing_id"] == "listing-vms"


def test_two_domains_publish_in_registry_order_and_isolate_skips() -> None:
    vm = _source(name="vms", candidate={"resource_id": "vm-1"})
    bare = _source(name="bare_metal", candidate={"resource_id": "host-1"})
    selection = PublicationSourceSelection(sources=(vm, bare))

    result = selection.command(
        db_path="db.sqlite",
        base_url="http://seller",
        build_payload=_payload,
        publish_offer=_publish,
    ).run(skip_ids={"vm-1"}, close_stale=False, skip_open=False)

    assert result.skipped == [{"resource_id": "vm-1"}]
    assert [item["response"]["listing_id"] for item in result.published] == [
        "listing-host-1"
    ]


def test_selection_rejects_duplicate_source_names() -> None:
    with pytest.raises(ValueError, match="unique"):
        PublicationSourceSelection(
            sources=(_source(name="same"), _source(name="same"))
        )


def test_empty_prebuilt_selection_has_no_new_listings() -> None:
    result = PublicationSourceSelection(sources=()).command(
        db_path="db.sqlite",
        base_url="http://seller",
        build_payload=_payload,
        publish_offer=_publish,
    ).run()

    assert result.published_count == 0
    assert result.failed_count == 0
    assert result.skipped_count == 0
    assert result.no_new_listings is True


def test_run_publication_cycle_closes_stale_and_skips_open_keys() -> None:
    result = run_publication_cycle(
        (_source(open_keys={"test"}),),
        db_path="db.sqlite",
        base_url="http://seller",
        build_payload=_payload,
        publish_offer=_publish,
    )

    assert result.closed == {"test": ["stale-test"]}
    assert result.published == []
    assert result.failed == []
    assert result.skipped == [{"resource_id": "test", "price": "1"}]
