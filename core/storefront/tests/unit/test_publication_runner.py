from __future__ import annotations

from typing import Any

from core_storefront.publication_runner import (
    close_stale_publication_listings,
    open_publication_keys,
    publish_round,
    publish_source_by_name,
)
from core_storefront.publication_sources import PublicationSource


def _source(
    *,
    candidate: dict[str, Any] | None = None,
    open_keys: set[str] | None = None,
) -> PublicationSource:
    candidate = candidate or {"resource_id": "r1", "price": "1"}
    return PublicationSource(
        name="test",
        open_keys=lambda _db: open_keys or set(),
        close_stale=lambda _db, _url, _key: ["stale-1"],
        available_candidates=lambda _db: [candidate],
        skip_keys=lambda c: {str(c["resource_id"])},
        offer_resource=lambda c: {"resource_id": c["resource_id"]},
        record_published=lambda _db, c, listing_id: c.__setitem__("listing_id", listing_id),
        reopen_existing=lambda *_args: None,
        reopen_error_label="reopen test",
    )


def test_lifecycle_helpers_union_sources() -> None:
    first = _source(open_keys={"a"})
    second = _source(open_keys={"b"})

    assert open_publication_keys([first, second], "db.sqlite") == {"a", "b"}
    assert close_stale_publication_listings(
        [first],
        db_path="db.sqlite",
        base_url="http://seller",
        private_key=None,
    ) == {"test": ["stale-1"]}


def test_publish_round_is_schema_opaque() -> None:
    candidate = {"resource_id": "r1", "price": "1"}
    source = _source(candidate=candidate)

    published, failed, skipped = publish_round(
        [source],
        db_path="db.sqlite",
        base_url="http://seller",
        private_key=None,
        build_payload=lambda _source, _candidate, _offer: ([{"escrow": "e"}], [{"demand": "d"}], 60),
        publish_offer=lambda offer, _escrows, _demands, _duration: {
            "status": "published",
            "listing_id": f"listing-{offer['resource_id']}",
        },
    )

    assert failed == []
    assert skipped == []
    assert published[0]["response"]["listing_id"] == "listing-r1"
    assert candidate["listing_id"] == "listing-r1"


def test_publish_round_skips_covered_candidate() -> None:
    published, failed, skipped = publish_round(
        [_source()],
        db_path="db.sqlite",
        base_url="http://seller",
        private_key=None,
        build_payload=lambda *_args: ([{}], [], None),
        publish_offer=lambda *_args: {"status": "published"},
        skip_ids={"r1"},
    )

    assert published == []
    assert failed == []
    assert skipped == [{"resource_id": "r1", "price": "1"}]


def test_publish_source_by_name_loads_source(monkeypatch) -> None:
    import core_storefront.publication_runner as runner

    monkeypatch.setattr(
        runner,
        "build_publication_source",
        lambda name, **kwargs: _source(candidate={"resource_id": name, **kwargs}),
    )

    published, failed, skipped = publish_source_by_name(
        "loaded",
        source_kwargs={"price": "2"},
        db_path="db.sqlite",
        base_url="http://seller",
        private_key=None,
        build_payload=lambda *_args: ([{}], [], None),
        publish_offer=lambda offer, *_args: {
            "status": "published",
            "listing_id": offer["resource_id"],
        },
    )

    assert failed == []
    assert skipped == []
    assert published[0]["response"]["listing_id"] == "loaded"
