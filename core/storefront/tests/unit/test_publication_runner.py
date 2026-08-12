from __future__ import annotations

from typing import Any

from core_storefront.publication_runner import (
    PublicationSourceSelection,
    build_publication_source_selection,
    close_stale_publication_listings,
    open_publication_keys,
    publish_round,
    publish_source_by_name,
    run_publication_command_by_name,
    run_publication_cycle,
    run_publication_cycle_by_name,
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
        close_stale=lambda _db, _url: ["stale-1"],
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
    assert close_stale_publication_listings([first],
    db_path="db.sqlite",
    base_url="http://seller", ) == {"test": ["stale-1"]}


def test_publish_round_is_schema_opaque() -> None:
    candidate = {"resource_id": "r1", "price": "1"}
    source = _source(candidate=candidate)

    published, failed, skipped = publish_round([source],
    db_path="db.sqlite",
    base_url="http://seller", build_payload=lambda _source, _candidate, _offer: ([{"escrow": "e"}], [{"demand": "d"}], 60),
    publish_offer=lambda offer, _escrows, _demands, _duration: {
        "status": "published",
        "listing_id": f"listing-{offer['resource_id']}",
    },)

    assert failed == []
    assert skipped == []
    assert published[0]["response"]["listing_id"] == "listing-r1"
    assert candidate["listing_id"] == "listing-r1"


def test_publish_round_skips_covered_candidate() -> None:
    published, failed, skipped = publish_round([_source()],
    db_path="db.sqlite",
    base_url="http://seller", build_payload=lambda *_args: ([{}], [], None),
    publish_offer=lambda *_args: {"status": "published"},
    skip_ids={"r1"},)

    assert published == []
    assert failed == []
    assert skipped == [{"resource_id": "r1", "price": "1"}]


def test_run_publication_cycle_closes_stale_and_skips_open_keys() -> None:
    source = _source(open_keys={"r1"})

    result = run_publication_cycle([source],
    db_path="db.sqlite",
    base_url="http://seller", build_payload=lambda *_args: ([{}], [], None),
    publish_offer=lambda *_args: {"status": "published"},)

    assert result.closed == {"test": ["stale-1"]}
    assert result.published == []
    assert result.failed == []
    assert result.skipped == [{"resource_id": "r1", "price": "1"}]


def test_run_publication_cycle_by_name_builds_selected_sources(monkeypatch) -> None:
    import core_storefront.publication_runner as runner

    monkeypatch.setattr(
        runner,
        "build_publication_source",
        lambda name, **kwargs: _source(candidate={"resource_id": name, **kwargs}),
    )

    result = run_publication_cycle_by_name(["vms"],
    source_kwargs_by_name={"vms": {"price": "2"}},
    db_path="db.sqlite",
    base_url="http://seller", build_payload=lambda *_args: ([{}], [], None),
    publish_offer=lambda offer, *_args: {
        "status": "published",
        "listing_id": offer["resource_id"],
    },)

    assert result.failed == []
    assert result.skipped == []
    assert result.published[0]["response"]["listing_id"] == "vms"


def test_publication_source_selection_wraps_command_cycle(monkeypatch) -> None:
    import core_storefront.publication_runner as runner

    monkeypatch.setattr(
        runner,
        "build_publication_source",
        lambda name, **kwargs: _source(
            candidate={"resource_id": name, **kwargs},
            open_keys={"already-open"},
        ),
    )

    selection = PublicationSourceSelection(
        source_names=("vms",),
        source_kwargs_by_name={"vms": {"price": "3"}},
    )

    assert [source.name for source in selection.build_sources()] == ["test"]
    assert selection.open_keys("db.sqlite") == {"already-open"}

    result = selection.run_cycle(db_path="db.sqlite",
    base_url="http://seller", build_payload=lambda *_args: ([{}], [], None),
    publish_offer=lambda offer, *_args: {
        "status": "published",
        "listing_id": offer["resource_id"],
    },)

    assert result.closed == {"test": ["stale-1"]}
    assert result.failed == []
    assert result.skipped == []
    assert result.published[0]["resource"] == {
        "resource_id": "vms",
        "price": "3",
        "listing_id": "vms",
    }


def test_build_publication_source_selection_composes_named_sources(monkeypatch) -> None:
    import core_storefront.publication_runner as runner

    monkeypatch.setattr(
        runner,
        "build_publication_source",
        lambda name, **kwargs: _source(candidate={"resource_id": name, **kwargs}),
    )

    def run(source_names: tuple[str, ...]) -> list[str]:
        selection = build_publication_source_selection(
            source_names,
            source_kwargs_by_name={
                "vms": {"price": "vm-price"},
                "bare_metal": {"price": "bm-price"},
            },
        )
        result = selection.run_command(db_path="db.sqlite",
        base_url="http://seller", build_payload=lambda *_args: ([{}], [], None),
        publish_offer=lambda offer, *_args: {
            "status": "published",
            "listing_id": offer["resource_id"],
        },
        close_stale=False,
        skip_open=False,)
        return [item["response"]["listing_id"] for item in result.published]

    assert run(("vms",)) == ["vms"]
    assert run(("bare_metal",)) == ["bare_metal"]
    assert run(("vms", "bare_metal")) == ["vms", "bare_metal"]


def test_publication_command_result_exposes_summary_counts(monkeypatch) -> None:
    import core_storefront.publication_runner as runner

    monkeypatch.setattr(
        runner,
        "build_publication_source",
        lambda name, **kwargs: _source(candidate={"resource_id": name, **kwargs}),
    )

    result = run_publication_command_by_name(["vms"],
    source_kwargs_by_name={"vms": {"price": "4"}},
    db_path="db.sqlite",
    base_url="http://seller", build_payload=lambda *_args: ([{}], [], None),
    publish_offer=lambda offer, *_args: {
        "status": "published",
        "listing_id": offer["resource_id"],
    },)

    assert result.published_count == 1
    assert result.failed_count == 0
    assert result.skipped_count == 0
    assert result.closed_count == 1
    assert result.has_publications is True
    assert result.has_failures is False
    assert result.no_new_listings is False
    assert result.published[0]["response"]["listing_id"] == "vms"


def test_publication_command_no_new_when_only_skipped() -> None:
    selection = PublicationSourceSelection(source_names=())
    command = selection.command(db_path="db.sqlite",
    base_url="http://seller", build_payload=lambda *_args: ([{}], [], None),
    publish_offer=lambda *_args: {"status": "published"},)

    result = command.run()

    assert result.published_count == 0
    assert result.failed_count == 0
    assert result.skipped_count == 0
    assert result.no_new_listings is True


def test_publish_source_by_name_loads_source(monkeypatch) -> None:
    import core_storefront.publication_runner as runner

    monkeypatch.setattr(
        runner,
        "build_publication_source",
        lambda name, **kwargs: _source(candidate={"resource_id": name, **kwargs}),
    )

    published, failed, skipped = publish_source_by_name("loaded",
    source_kwargs={"price": "2"},
    db_path="db.sqlite",
    base_url="http://seller", build_payload=lambda *_args: ([{}], [], None),
    publish_offer=lambda offer, *_args: {
        "status": "published",
        "listing_id": offer["resource_id"],
    },)

    assert failed == []
    assert skipped == []
    assert published[0]["response"]["listing_id"] == "loaded"
