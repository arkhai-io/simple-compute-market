"""The kit's publication cycle driver, report, and registry convergence step."""

from __future__ import annotations

import asyncio
import logging
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_storefront.publication_runner import NoSettlementOption, PublicationPayload
from core_storefront.publication_sources import PublicationSource

from market_capacity_publication import (
    PAYLOAD_UNBUILDABLE,
    SETTLEMENT_MECHANISM_UNKNOWN,
    PublicationCycleDriver,
    PublicationCycleStopped,
    PublicationCycleReport,
    RefusedCandidates,
    RegistryDivergence,
    SiteDerivationLog,
    converge_registries,
    record_payload_refusal,
    site_derivations,
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


def _cycle_report(*actions, dry_run=False):
    report = PublicationCycleReport(dry_run=dry_run)
    for action, details in actions:
        report.record(action, **details)
    return report


REGIONLESS = ("hold", {"site_id": "site-a", "pool_id": "p1", "reason": "pool_region_missing"})
REFUSED = ("refuse", {"site_id": "site-a", "pool_id": "p2", "reason": "no_settlement_option"})
REPORTED = ("report", {"site_id": "site-b", "pool_id": "p3", "reason": "listing_shapes_not_applicable"})


class TestSiteDerivations:
    def test_each_site_lists_its_holds_refusals_and_reports_without_action_or_site(self):
        report = _cycle_report(
            REGIONLESS, REFUSED, REPORTED, ("publish", {"listing_id": "x"}),
            ("hold", {"site_id": "unconfigured", "reason": "anything"}),
        )

        summary = site_derivations(report, ["site-a", "site-b", "site-c"])

        assert summary == {
            "site-a": {
                "holds": [{"pool_id": "p1", "reason": "pool_region_missing"}],
                "refusals": [{"pool_id": "p2", "reason": "no_settlement_option"}],
                "reports": [],
            },
            "site-b": {
                "holds": [],
                "refusals": [],
                "reports": [{"pool_id": "p3", "reason": "listing_shapes_not_applicable"}],
            },
            "site-c": {"holds": [], "refusals": [], "reports": []},
        }


class TestSiteDerivationLog:
    LOGGER = "market_capacity_publication.cycle"

    def _records(self, caplog):
        return [
            (record.levelname, record.getMessage())
            for record in caplog.records
            if record.name == self.LOGGER
        ]

    def test_a_site_is_absent_until_a_cycle_records_it(self):
        log = SiteDerivationLog()

        assert log.latest() == {}
        log.record("vm", _cycle_report(), ["site-a"])
        assert log.latest() == {"site-a": {"holds": [], "refusals": [], "reports": []}}

    def test_a_preview_records_and_logs_nothing(self, caplog):
        caplog.set_level(logging.INFO, logger=self.LOGGER)
        log = SiteDerivationLog()
        log.record("vm", _cycle_report(REGIONLESS), ["site-a"])
        caplog.clear()

        log.record("vm", _cycle_report(dry_run=True), ["site-a"])
        log.record("vm", _cycle_report(REFUSED, dry_run=True), ["site-a", "site-b"])

        assert self._records(caplog) == []
        assert log.latest() == {
            "site-a": {
                "holds": [{"pool_id": "p1", "reason": "pool_region_missing"}],
                "refusals": [],
                "reports": [],
            }
        }

    def test_an_entry_is_logged_once_when_it_appears_and_once_when_it_clears(self, caplog):
        caplog.set_level(logging.INFO, logger=self.LOGGER)
        log = SiteDerivationLog()

        for _ in range(3):
            log.record("vm", _cycle_report(REGIONLESS), ["site-a"])
        appeared = self._records(caplog)
        caplog.clear()
        log.record("vm", _cycle_report(), ["site-a"])
        cleared = self._records(caplog)

        assert len(appeared) == 1
        (level, message), = appeared
        assert level == "WARNING"
        assert "site-a" in message and "pool_region_missing" in message and "p1" in message
        (level, message), = cleared
        assert level == "INFO" and "cleared" in message and "pool_region_missing" in message
        assert log.latest()["site-a"]["holds"] == []

    def test_a_standing_entry_stays_reported_every_cycle(self):
        log = SiteDerivationLog()

        for _ in range(2):
            log.record("vm", _cycle_report(REGIONLESS), ["site-a"])

        assert log.latest()["site-a"]["holds"] == [
            {"pool_id": "p1", "reason": "pool_region_missing"}
        ]

    def test_two_sources_keep_their_derivations_apart(self, caplog):
        caplog.set_level(logging.INFO, logger=self.LOGGER)
        log = SiteDerivationLog()
        log.record("vm", _cycle_report(REGIONLESS), ["site-a"])
        log.record("bare_metal", _cycle_report(REFUSED), ["site-a"])
        caplog.clear()

        # Each source records its own clean or standing derivation; neither
        # clears nor raises the other's entry.
        log.record("vm", _cycle_report(REGIONLESS), ["site-a"])
        log.record("bare_metal", _cycle_report(REFUSED), ["site-a"])

        assert self._records(caplog) == []
        assert log.latest()["site-a"] == {
            "holds": [{"pool_id": "p1", "reason": "pool_region_missing"}],
            "refusals": [{"pool_id": "p2", "reason": "no_settlement_option"}],
            "reports": [],
        }

    def test_a_site_held_whole_keeps_its_pool_entries_and_logs_no_clearing(self, caplog):
        caplog.set_level(logging.INFO, logger=self.LOGGER)
        log = SiteDerivationLog()
        legacy = ("report", {"site_id": "site-a", "reason": "legacy_producer_backing"})
        log.record("vm", _cycle_report(REGIONLESS, legacy), ["site-a"])
        caplog.clear()
        unknown = ("hold", {"site_id": "site-a", "reason": "site_projection_unknown",
                            "error": "connection refused"})

        log.record("vm", _cycle_report(unknown), ["site-a"])
        log.record("vm", _cycle_report(unknown), ["site-a"])
        while_held = log.latest()["site-a"]
        held = self._records(caplog)
        caplog.clear()
        log.record("vm", _cycle_report(REGIONLESS, legacy), ["site-a"])
        read_again = self._records(caplog)

        assert while_held == {
            "holds": [
                {"reason": "site_projection_unknown", "error": "connection refused"},
                {"pool_id": "p1", "reason": "pool_region_missing"},
            ],
            "refusals": [],
            "reports": [{"reason": "legacy_producer_backing"}],
        }
        ((level, message),) = held
        assert level == "WARNING" and "site_projection_unknown" in message
        ((level, message),) = read_again
        assert level == "INFO" and "cleared" in message and "site_projection_unknown" in message
        assert log.latest()["site-a"] == {
            "holds": [{"pool_id": "p1", "reason": "pool_region_missing"}],
            "refusals": [],
            "reports": [{"reason": "legacy_producer_backing"}],
        }

    def test_a_standing_entry_whose_error_text_changes_is_not_logged_again(self, caplog):
        caplog.set_level(logging.INFO, logger=self.LOGGER)
        log = SiteDerivationLog()

        for error in ("connection refused", "timed out", "connection reset"):
            log.record(
                "vm",
                _cycle_report(("hold", {"site_id": "site-a", "reason": "site_projection_unknown",
                                        "error": error})),
                ["site-a"],
            )

        assert len(self._records(caplog)) == 1
        (hold,) = log.latest()["site-a"]["holds"]
        assert hold["error"] == "connection reset"

    def test_a_logged_entry_summarizes_structured_detail(self, caplog):
        caplog.set_level(logging.INFO, logger=self.LOGGER)
        log = SiteDerivationLog()
        findings = [{"tier": "pool_hint", "problems": [{"message": "x"}]}] * 2
        reported = ("report", {"site_id": "site-a", "pool_id": "p1",
                               "reason": "listing_shape_inadmissible", "findings": findings,
                               "keys": ["min_price", "token"]})

        log.record("vm", _cycle_report(reported), ["site-a"])

        ((_, message),) = self._records(caplog)
        assert "findings=2 item(s)" in message and "keys=min_price; token" in message
        assert "pool_hint" not in message

    def test_what_latest_returns_cannot_change_what_was_recorded(self):
        log = SiteDerivationLog()
        log.record("vm", _cycle_report(REGIONLESS), ["site-a"])

        log.latest()["site-a"]["holds"].clear()

        assert log.latest()["site-a"]["holds"]


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


def _source(candidates) -> PublicationSource:
    return PublicationSource(
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


async def test_cancelling_a_cycle_mid_callback_lets_its_worker_thread_finish():
    """A callback waiting on a coroutine the loop never completes fails as soon
    as the cycle is cancelled, and so does any later call, so the runner's
    thread unwinds instead of waiting forever."""
    driver = PublicationCycleDriver()
    waiting = asyncio.Event()
    unwound = threading.Event()
    refused: list[type[BaseException]] = []

    async def never_completes() -> None:
        waiting.set()
        await asyncio.Event().wait()

    def candidates(_db_path: str) -> list[dict]:
        try:
            driver.call(never_completes())
        except PublicationCycleStopped:
            try:
                driver.call(never_completes())
            except PublicationCycleStopped as again:
                refused.append(type(again))
            unwound.set()
            raise
        return []

    cycle = asyncio.create_task(
        driver.run(
            [_source(candidates)],
            db_path="unused.db",
            base_url="https://seller.example",
            build_payload=lambda *_args: PublicationPayload(),
            publish_listing=lambda *_args, **_kwargs: {"listing_id": "never"},
        )
    )
    await asyncio.wait_for(waiting.wait(), timeout=5)
    cycle.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cycle

    assert await asyncio.to_thread(unwound.wait, 5), "the worker thread is still waiting"
    assert refused == [PublicationCycleStopped]


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


# -- payload refusals ---------------------------------------------------------

_SOURCE = {"site_id": "site-a", "pool_id": "pool-1", "physical_resource_id": "r1"}


def _recorded(refusal, *, listing_open):
    report = PublicationCycleReport()
    record_payload_refusal(report, _SOURCE, refusal, listing_open=listing_open)
    (action,) = report.actions
    return action


@pytest.mark.parametrize("listing_open", [True, False])
def test_a_refusal_configuration_rules_out_is_refused_whether_or_not_a_listing_is_open(
    listing_open,
):
    action = _recorded(
        NoSettlementOption("ruled out", mechanisms=("contact.v1",)),
        listing_open=listing_open,
    )

    assert action == {
        "action": "refuse",
        **_SOURCE,
        "reason": "no_settlement_option",
        "mechanisms": ["contact.v1"],
        "error": "ruled out",
    }


def test_an_unknown_mechanism_holds_an_open_listing():
    action = _recorded(
        NoSettlementOption(
            "unreached", mechanisms=("alkahest.v1", "contact.v1"), unknown=("alkahest.v1",)
        ),
        listing_open=True,
    )

    assert (action["action"], action["reason"], action["mechanisms"]) == (
        "hold",
        SETTLEMENT_MECHANISM_UNKNOWN,
        ["alkahest.v1"],
    )


def test_an_unknown_mechanism_with_no_open_listing_is_refused():
    action = _recorded(
        NoSettlementOption("unreached", mechanisms=("alkahest.v1",), unknown=("alkahest.v1",)),
        listing_open=False,
    )

    assert (action["action"], action["reason"]) == ("refuse", SETTLEMENT_MECHANISM_UNKNOWN)


def test_another_payload_failure_is_refused_with_its_text_as_detail():
    action = _recorded(ValueError("clause unreadable"), listing_open=True)

    assert action == {
        "action": "refuse",
        **_SOURCE,
        "reason": PAYLOAD_UNBUILDABLE,
        "error": "clause unreadable",
    }


def test_a_refusal_reaches_its_sites_derivation_and_its_error_text_is_not_its_identity(
    caplog,
):
    """The entry is recorded under its site, and a standing refusal whose text
    changes is not logged as a new entry."""
    log = SiteDerivationLog()
    for detail in ("first answer", "second answer"):
        report = PublicationCycleReport()
        record_payload_refusal(
            report,
            _SOURCE,
            NoSettlementOption(detail, mechanisms=("contact.v1",)),
            listing_open=False,
        )
        with caplog.at_level(logging.WARNING):
            log.record("bare_metal", report, ["site-a"])

    (refusal,) = log.latest()["site-a"]["refusals"]
    assert refusal["reason"] == "no_settlement_option"
    assert len([r for r in caplog.records if "refusals" in r.getMessage()]) == 1


# -- refused candidates ---------------------------------------------------------


class _Binding:
    def __init__(self, listing_id):
        self.listing_id = listing_id


class _Listings:
    """The storefront persistence a refused candidate's listing is found in."""

    def __init__(self, listings=None, keys=None):
        self.listings = listings or {}
        self.keys = keys or {}

    async def load_listing_binding_by_derivation(self, *, derivation_key):
        listing_id = self.keys.get(derivation_key)
        return None if listing_id is None else _Binding(listing_id)

    async def load_listing(self, *, listing_id):
        return self.listings.get(listing_id)


_CANDIDATE = {"key": "key-1", **_SOURCE}


def _refusals(report, listings, close=None):
    closed: list[list[str]] = []

    async def reconciliation_close(listing_ids):
        closed.append(listing_ids)
        if close is not None:
            return close(listing_ids)
        return {"closed": tuple(listing_ids), "failed_closes": ()}

    refusals = RefusedCandidates(
        report,
        # Each coroutine runs to completion here, as the driver runs it on the
        # cycle's event loop for a callback on the runner's thread.
        call=asyncio.run,
        listings=listings,
        derivation_key=lambda candidate: candidate["key"],
        derivation_source=lambda candidate: {
            key: candidate[key] for key in ("site_id", "pool_id", "physical_resource_id")
        },
        reconciliation_close=reconciliation_close,
    )
    return refusals, closed


_OPEN = _Listings(listings={"L1": {"status": "open"}}, keys={"key-1": "L1"})


def test_a_refusal_is_recorded_under_its_site_and_returned_to_the_runner():
    report = PublicationCycleReport()
    refusals, _ = _refusals(report, _OPEN)
    refusal = NoSettlementOption("ruled out", mechanisms=("contact.v1",))
    # A cycle's candidates live for the whole cycle, as the runner holds every
    # one it fails, so the refusals are tracked by identity; these are held too.
    unreadable = dict(_CANDIDATE)
    published = dict(_CANDIDATE)

    assert refusals.refuse(_CANDIDATE, refusal) is refusal
    assert refusals.refuse(unreadable, ValueError("unreadable")) == "unreadable"
    assert [(item["action"], item["reason"], item["site_id"]) for item in report.actions] == [
        ("refuse", "no_settlement_option", "site-a"),
        ("refuse", PAYLOAD_UNBUILDABLE, "site-a"),
    ]
    assert refusals.refused(_CANDIDATE) and refusals.refused(unreadable)
    assert refusals.refused(published) is False


@pytest.mark.parametrize(
    ("listings", "action"),
    [(_OPEN, "hold"), (_Listings(), "refuse"), (
        _Listings(listings={"L1": {"status": "closed"}}, keys={"key-1": "L1"}), "refuse"
    )],
    ids=["open-listing-held", "no-listing", "closed-listing"],
)
def test_an_unknown_mechanism_holds_only_an_open_listing(listings, action):
    report = PublicationCycleReport()
    refusals, _ = _refusals(report, listings)

    refusals.refuse(
        _CANDIDATE,
        NoSettlementOption("unreached", mechanisms=("alkahest.v1",), unknown=("alkahest.v1",)),
    )

    ((recorded, reason),) = [(item["action"], item["reason"]) for item in report.actions]
    assert (recorded, reason) == (action, SETTLEMENT_MECHANISM_UNKNOWN)


def test_the_close_hook_closes_the_open_listing_through_reconciliation():
    report = PublicationCycleReport()
    refusals, closed = _refusals(report, _OPEN)

    refusals.close_candidate_listing("db", "url", _CANDIDATE, "no_settlement_option")

    assert closed == [["L1"]]
    assert report.actions == [
        {"action": "close", "listing_id": "L1", "reason": "no_settlement_option"}
    ]


def test_a_preview_records_the_close_and_applies_none():
    report = PublicationCycleReport(dry_run=True)
    refusals, closed = _refusals(report, _OPEN)

    refusals.close_candidate_listing("db", "url", _CANDIDATE, "no_settlement_option")

    assert closed == []
    assert report.of("close") == [
        {"action": "close", "listing_id": "L1", "reason": "no_settlement_option"}
    ]


@pytest.mark.parametrize(
    "listings",
    [
        _Listings(),
        _Listings(listings={"L1": {"status": "closed", "closed_by": "seller"}}, keys={"key-1": "L1"}),
    ],
    ids=["no-listing", "seller-closed"],
)
def test_the_close_hook_leaves_a_candidate_with_no_open_listing(listings):
    report = PublicationCycleReport()
    refusals, closed = _refusals(report, listings)

    refusals.close_candidate_listing("db", "url", _CANDIDATE, "no_settlement_option")

    assert closed == [] and report.actions == []


def test_a_close_the_runtime_cannot_apply_is_a_failure():
    report = PublicationCycleReport()
    refusals, _ = _refusals(
        report, _OPEN, close=lambda ids: {"closed": (), "failed_closes": tuple(ids)}
    )

    refusals.close_candidate_listing("db", "url", _CANDIDATE, "no_settlement_option")

    assert report.actions == [
        {"action": "fail", "listing_id": "L1", "reason": "local_close_failed"}
    ]


def test_a_close_that_raises_is_reported_and_raised():
    def broken(_ids):
        raise RuntimeError("database locked")

    report = PublicationCycleReport()
    refusals, _ = _refusals(report, _OPEN, close=broken)

    with pytest.raises(RuntimeError, match="database locked"):
        refusals.close_candidate_listing("db", "url", _CANDIDATE, "no_settlement_option")

    assert report.actions == [
        {"action": "fail", "source": _SOURCE, "reason": "close failed: database locked"}
    ]
