from __future__ import annotations

from core_storefront.publication_sources import PublicationSource


def test_publication_source_collects_core_hooks() -> None:
    source = PublicationSource(
        name="demo",
        open_keys=lambda _db_path: {"open-1"},
        close_stale=lambda _db_path, _base_url, _private_key: ["closed-1"],
        available_candidates=lambda _db_path: [{"id": "candidate-1"}],
        skip_keys=lambda candidate: {str(candidate["id"])},
        offer_resource=lambda candidate: {"resource_id": candidate["id"]},
        record_published=lambda _db_path, _candidate, _listing_id: None,
        reopen_existing=lambda *args: None,
        reopen_error_label="reopen demo listing",
    )

    assert source.open_keys("db.sqlite") == {"open-1"}
    assert source.close_stale("db.sqlite", "http://seller", None) == ["closed-1"]
    assert source.available_candidates("db.sqlite") == [{"id": "candidate-1"}]
    assert source.skip_keys({"id": "candidate-1"}) == {"candidate-1"}
    assert source.offer_resource({"id": "candidate-1"}) == {
        "resource_id": "candidate-1",
    }
    assert source.pricing_resource(
        {"id": "candidate-1"},
        {"resource_id": "candidate-1"},
    ) == {"id": "candidate-1"}


def test_publication_source_can_price_from_offer_payload() -> None:
    source = PublicationSource(
        name="demo",
        open_keys=lambda _db_path: set(),
        close_stale=lambda _db_path, _base_url, _private_key: [],
        available_candidates=lambda _db_path: [],
        skip_keys=lambda _candidate: set(),
        offer_resource=lambda candidate: {"resource_id": candidate["id"]},
        record_published=lambda _db_path, _candidate, _listing_id: None,
        reopen_existing=lambda *args: None,
        reopen_error_label="reopen demo listing",
        pricing_resource=lambda _candidate, offer: offer,
    )

    assert source.pricing_resource(
        {"id": "candidate-1"},
        {"resource_id": "candidate-1"},
    ) == {"resource_id": "candidate-1"}
