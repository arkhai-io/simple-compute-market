from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from core_storefront.publication_runner import (
    NO_SETTLEMENT_OPTION,
    NoSettlementOption,
    PublicationSourceSelection,
    PublicationPayload,
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
    closed: list[tuple[dict[str, Any], str]] | None = None,
) -> PublicationSource:
    candidate = candidate or {"resource_id": name, "price": "1"}
    hooks: dict[str, Any] = {}
    if closed is not None:
        hooks["close_candidate_listing"] = (
            lambda _db, _url, value, reason: closed.append((value, reason))
        )
    return PublicationSource(
        name=name,
        open_keys=lambda _db: open_keys or set(),
        close_stale=lambda _db, _url: [f"stale-{name}"],
        available_candidates=lambda _db: [candidate],
        skip_keys=lambda value: {str(value["resource_id"])},
        listing_resource=lambda value: {"resource_id": value["resource_id"]},
        record_published=lambda _db, value, listing_id: value.__setitem__(
            "listing_id", listing_id
        ),
        reopen_existing=lambda *_args, **_kwargs: None,
        reopen_error_label=f"reopen {name}",
        **hooks,
    )


def _payload(*_args):
    return ([{"escrow": "e"}], [{"demand": "d"}], 60)


def _publish(listing_resource, *_args):
    return {
        "status": "published",
        "listing_id": f"listing-{listing_resource['resource_id']}",
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
        publish_listing=_publish,
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
        publish_listing=_publish,
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
        publish_listing=_publish,
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
        publish_listing=_publish,
    ).run(skip_ids={"vm-1"}, close_stale=False, skip_open=False)

    assert result.skipped == [{"resource_id": "vm-1"}]
    assert [item["response"]["listing_id"] for item in result.published] == [
        "listing-host-1"
    ]


def test_selection_rejects_duplicate_source_names() -> None:
    with pytest.raises(ValueError, match="unique"):
        PublicationSourceSelection(sources=(_source(name="same"), _source(name="same")))


def test_empty_prebuilt_selection_has_no_new_listings() -> None:
    result = (
        PublicationSourceSelection(sources=())
        .command(
            db_path="db.sqlite",
            base_url="http://seller",
            build_payload=_payload,
            publish_listing=_publish,
        )
        .run()
    )

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
        publish_listing=_publish,
    )

    assert result.closed == {"test": ["stale-test"]}
    assert result.published == []
    assert result.failed == []
    assert result.skipped == [{"resource_id": "test", "price": "1"}]


def test_typed_payload_keeps_settlement_options_independent() -> None:
    captured: dict[str, Any] = {}

    def publish(listing_resource, accepted_escrows, demands, maximum, **kwargs):
        captured.update(
            listing_resource=listing_resource,
            accepted_escrows=accepted_escrows,
            demands=demands,
            maximum=maximum,
            **kwargs,
        )
        return {"status": "published", "listing_id": "listing-test"}

    published, failed, skipped = publish_round(
        (_source(),),
        db_path="db.sqlite",
        base_url="http://seller",
        build_payload=lambda *_args: PublicationPayload(
            accepted_escrows=({"escrow": "alkahest"},),
            settlement_options=({"option_id": "rated"},),
            publication_clauses=({"mechanism": "example.payment.v1"},),
            demands=({"demand": "compute"},),
            max_duration_seconds=60,
        ),
        publish_listing=publish,
    )

    assert failed == []
    assert skipped == []
    assert published[0]["settlement_options"] == [{"option_id": "rated"}]
    assert captured["accepted_escrows"] == [{"escrow": "alkahest"}]
    assert captured["settlement_options"] == [{"option_id": "rated"}]
    assert captured["publication_clauses"] == [{"mechanism": "example.payment.v1"}]


def test_an_unchanged_existing_listing_is_skipped_not_failed_or_duplicated() -> None:
    candidate = {"resource_id": "r1", "price": "1"}
    source = _source(candidate=candidate)
    published_calls: list[Any] = []
    source = PublicationSource(
        name=source.name,
        open_keys=source.open_keys,
        close_stale=source.close_stale,
        available_candidates=source.available_candidates,
        skip_keys=source.skip_keys,
        listing_resource=source.listing_resource,
        record_published=source.record_published,
        reopen_existing=lambda *_args, **_kwargs: {"status": "unchanged"},
        reopen_error_label=source.reopen_error_label,
    )

    published, failed, skipped = publish_round(
        (source,),
        db_path="db.sqlite",
        base_url="http://seller",
        build_payload=_payload,
        publish_listing=lambda *args, **kwargs: published_calls.append(args) or {},
    )

    assert (published, failed, skipped) == ([], [], [candidate])
    assert published_calls == []


def _refusing_round(refusal, source):
    published_calls: list[Any] = []
    result = publish_round(
        (source,),
        db_path="db.sqlite",
        base_url="http://seller",
        build_payload=lambda *_args: refusal,
        publish_listing=lambda *args, **kwargs: published_calls.append(args) or {},
    )
    return result, published_calls


def test_a_candidate_whose_mechanisms_configuration_rules_out_closes_its_listing() -> None:
    candidate = {"resource_id": "r1"}
    closed: list[tuple[dict[str, Any], str]] = []
    refusal = NoSettlementOption("no option", mechanisms=("contact.v1",))

    (published, failed, skipped), published_calls = _refusing_round(
        refusal, _source(candidate=candidate, closed=closed)
    )

    assert refusal.ruled_out_by_configuration is True
    assert closed == [(candidate, NO_SETTLEMENT_OPTION)]
    assert (published, failed, skipped) == ([], [(candidate, "no option")], [])
    assert published_calls == []


def test_a_candidate_with_no_clause_at_all_closes_its_listing() -> None:
    closed: list[tuple[dict[str, Any], str]] = []

    _refusing_round(NoSettlementOption("no clause"), _source(closed=closed))

    assert [reason for _candidate, reason in closed] == [NO_SETTLEMENT_OPTION]


def test_a_candidate_with_an_unknown_mechanism_leaves_its_listing() -> None:
    candidate = {"resource_id": "r1"}
    closed: list[tuple[dict[str, Any], str]] = []
    refusal = NoSettlementOption(
        "unreachable", mechanisms=("alkahest.v1", "contact.v1"), unknown=("alkahest.v1",)
    )

    (published, failed, skipped), published_calls = _refusing_round(
        refusal, _source(candidate=candidate, closed=closed)
    )

    assert refusal.ruled_out_by_configuration is False
    assert closed == []
    assert (published, failed, skipped) == ([], [(candidate, "unreachable")], [])
    assert published_calls == []


def test_another_payload_failure_leaves_the_listing() -> None:
    closed: list[tuple[dict[str, Any], str]] = []

    (_published, failed, _skipped), _calls = _refusing_round(
        "clause unreadable", _source(closed=closed)
    )

    assert closed == []
    assert [reason for _candidate, reason in failed] == ["clause unreadable"]


def test_a_failing_close_is_reported_as_the_candidates_failure() -> None:
    def close(*_args: Any) -> None:
        raise RuntimeError("database locked")

    source = replace(_source(), close_candidate_listing=close)

    (_published, failed, _skipped), _calls = _refusing_round(
        NoSettlementOption("no option"), source
    )

    assert [reason for _candidate, reason in failed] == [
        "close listing with no settlement option: database locked"
    ]


def test_an_unknown_mechanism_must_be_one_the_candidate_could_publish() -> None:
    with pytest.raises(ValueError, match="could publish"):
        NoSettlementOption("x", mechanisms=("contact.v1",), unknown=("alkahest.v1",))
