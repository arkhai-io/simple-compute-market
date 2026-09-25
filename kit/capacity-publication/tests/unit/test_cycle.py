"""The kit's publication cycle driver, report, and registry convergence step."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_storefront.publication_runner import PublicationPayload
from core_storefront.publication_sources import PublicationSource

from market_capacity_publication import (
    PublicationCycleDriver,
    PublicationCycleReport,
    RegistryDivergence,
    converge_registries,
)


def test_the_report_counts_each_action_in_the_order_taken():
    report = PublicationCycleReport(dry_run=True)
    report.record("publish", listing_id="a")
    report.record("close", listing_id="b", reason="source_gone")
    report.record("publish", listing_id="c")

    assert report.of("publish") == [
        {"action": "publish", "listing_id": "a"},
        {"action": "publish", "listing_id": "c"},
    ]
    assert report.as_dict() == {
        "dry_run": True,
        "actions": [
            {"action": "publish", "listing_id": "a"},
            {"action": "close", "listing_id": "b", "reason": "source_gone"},
            {"action": "publish", "listing_id": "c"},
        ],
        "counts": {"close": 1, "publish": 2},
    }


def test_a_callback_cannot_call_back_before_a_cycle_runs():
    driver = PublicationCycleDriver()

    async def never() -> None:  # pragma: no cover - never awaited
        return None

    coroutine = never()
    with pytest.raises(RuntimeError, match="not running"):
        driver.call(coroutine)
    coroutine.close()


async def test_callbacks_run_off_the_loop_and_call_back_onto_it():
    """The runner runs on a worker thread; each coroutine a callback hands to
    the driver runs on the cycle's own loop, and its result returns to the
    callback."""
    driver = PublicationCycleDriver()
    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}

    async def on_loop(value: str) -> str:
        seen["coroutine"] = threading.get_ident()
        await asyncio.sleep(0)
        return value.upper()

    def candidates(_db_path: str) -> list[dict]:
        seen["callback"] = threading.get_ident()
        return [{"key": driver.call(on_loop("k1"))}]

    published: list[dict] = []
    source = PublicationSource(
        name="test",
        open_keys=lambda _db_path: set(),
        close_stale=lambda _db_path, _base_url: [],
        available_candidates=candidates,
        skip_keys=lambda candidate: {candidate["key"]},
        listing_resource=lambda candidate: dict(candidate),
        record_published=lambda *_args: None,
        reopen_existing=lambda *_args, **_kwargs: None,
        reopen_error_label="reopen",
    )

    result = await driver.run(
        [source],
        db_path="unused.db",
        base_url="https://seller.example",
        build_payload=lambda *_args: PublicationPayload(),
        publish_listing=lambda listing_resource, *_args, **_kwargs: (
            published.append(listing_resource) or {"listing_id": "listing-1"}
        ),
    )

    assert published == [{"key": "K1"}]
    assert [item["response"]["listing_id"] for item in result.published] == [
        "listing-1"
    ]
    assert seen["callback"] != loop_thread
    assert seen["coroutine"] == loop_thread


def _runtime(divergences, unrepaired=()):
    runtime = MagicMock()
    runtime.publication_divergence = AsyncMock(return_value=tuple(divergences))
    runtime.converge = AsyncMock(
        return_value={"repaired": (), "unrepaired": tuple(unrepaired)}
    )
    return runtime


async def test_convergence_reports_each_divergence_and_what_stays_unrepaired():
    divergences = [
        RegistryDivergence("listing-1", "closed", ("https://r1",)),
        RegistryDivergence("listing-2", "open", ("https://r1", "https://r2")),
    ]
    runtime = _runtime(divergences, unrepaired=("listing-2",))
    report = PublicationCycleReport()

    await converge_registries(runtime, report)

    runtime.converge.assert_awaited_once_with(tuple(divergences))
    assert report.actions == [
        {
            "action": "converge",
            "listing_id": "listing-1",
            "status": "closed",
            "registries": ["https://r1"],
        },
        {
            "action": "converge",
            "listing_id": "listing-2",
            "status": "open",
            "registries": ["https://r1", "https://r2"],
        },
        {"action": "fail", "listing_id": "listing-2", "reason": "registry_not_converged"},
    ]


async def test_a_dry_run_reports_divergence_and_sends_nothing():
    runtime = _runtime([RegistryDivergence("listing-1", "open", ("https://r1",))])
    report = PublicationCycleReport(dry_run=True)

    await converge_registries(runtime, report)

    runtime.converge.assert_not_awaited()
    assert [item["action"] for item in report.actions] == ["converge"]


async def test_nothing_diverged_means_nothing_is_sent():
    runtime = _runtime([])
    report = PublicationCycleReport()

    await converge_registries(runtime, report)

    runtime.converge.assert_not_awaited()
    assert report.actions == []
