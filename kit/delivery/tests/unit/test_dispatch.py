"""Dispatch is bounded, non-fatal, and says nothing about what it carried."""

from __future__ import annotations

import threading
import time

from market_delivery import (
    ConfiguredSink,
    DeliveryError,
    deliver,
    deliver_async,
    describe_outcomes,
    introduction_delivery_event,
)

SECRET = "@seller-private-handle"


def _event():
    return introduction_delivery_event(
        {
            "obligation_ref": "c" * 64,
            "revealed": True,
            "introduction": {"channel": "telegram"},
            "counterparty_contact": {"telegram": SECRET},
        },
        role="buyer",
    )


def test_no_sinks_is_not_an_error() -> None:
    assert deliver((), _event()) == ()


def test_every_sink_runs_even_when_its_neighbour_fails() -> None:
    seen = []

    def good(event):
        seen.append(event.obligation_ref)

    def bad(event):
        raise RuntimeError("nope")

    outcomes = deliver(
        (
            ConfiguredSink(name="bad", sink=bad),
            ConfiguredSink(name="good", sink=good),
        ),
        _event(),
    )

    assert seen == ["c" * 64]
    assert [(o.sink, o.delivered) for o in outcomes] == [("bad", False), ("good", True)]


def test_an_arbitrary_failure_is_reported_by_class_alone() -> None:
    def leaky(event):
        raise RuntimeError(f"failed while sending {SECRET}")

    (outcome,) = deliver((ConfiguredSink(name="leaky", sink=leaky),), _event())

    assert outcome.delivered is False
    assert outcome.failure == "RuntimeError"
    assert SECRET not in outcome.describe()


def test_a_sink_authored_failure_keeps_its_own_safe_message() -> None:
    def careful(event):
        raise DeliveryError("the configured endpoint returned status 500")

    (outcome,) = deliver((ConfiguredSink(name="careful", sink=careful),), _event())

    assert outcome.failure == "the configured endpoint returned status 500"
    assert describe_outcomes([outcome]) == (
        "delivery to careful failed: the configured endpoint returned status 500",
    )


def test_a_hanging_sink_is_abandoned_at_its_bound() -> None:
    release = threading.Event()

    def hangs(event):
        release.wait(30)

    started = time.monotonic()
    outcomes = deliver(
        (ConfiguredSink(name="hangs", sink=hangs, timeout_seconds=0.2),), _event()
    )
    elapsed = time.monotonic() - started
    release.set()

    assert elapsed < 5
    assert outcomes[0].delivered is False
    assert "timed out" in outcomes[0].failure


def test_concurrent_sinks_cost_the_slowest_not_the_sum() -> None:
    def slow(event):
        time.sleep(0.3)

    sinks = tuple(
        ConfiguredSink(name=f"slow-{index}", sink=slow, timeout_seconds=2.0)
        for index in range(4)
    )
    started = time.monotonic()
    outcomes = deliver(sinks, _event())
    elapsed = time.monotonic() - started

    assert all(outcome.delivered for outcome in outcomes)
    assert elapsed < 1.0


def test_outcomes_name_the_deal_and_never_the_payload() -> None:
    (outcome,) = deliver(
        (ConfiguredSink(name="quiet", sink=lambda event: None),), _event()
    )

    assert outcome.obligation_ref == "c" * 64
    assert outcome.describe() == "delivered to quiet"


async def test_the_async_form_runs_the_same_bounded_dispatch() -> None:
    seen = []
    outcomes = await deliver_async(
        (ConfiguredSink(name="async", sink=lambda event: seen.append(1)),), _event()
    )

    assert seen == [1]
    assert outcomes[0].delivered is True
    assert await deliver_async((), _event()) == ()
