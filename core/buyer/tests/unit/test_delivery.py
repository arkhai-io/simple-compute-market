"""The buyer's own copy goes where the buyer configured, and never fails a run."""

from __future__ import annotations

import io
import json

import pytest
from market_delivery import ConfiguredSink, DeliveryError, DeliverySinkSet

import core_buyer.delivery as delivery

SELLER_CONTACT = {"telegram": "@capacity_broker"}


def _projection():
    return {
        "obligation_ref": "a" * 64,
        "mechanism": "contact-exchange.v1",
        "revealed": True,
        "introduction": {"channel": "telegram", "terms": "Net-30"},
        "counterparty_contact": dict(SELLER_CONTACT),
    }


def test_the_buyer_delivers_the_sellers_half(tmp_path) -> None:
    target = tmp_path / "introductions.jsonl"
    config = tmp_path / "buyer.toml"
    config.write_text(
        "[delivery]\nenabled = ['file']\n\n[delivery.file]\npath = "
        f"'{target}'\n",
        encoding="utf-8",
    )

    sinks = delivery.load_buyer_delivery_sinks(str(config))
    outcomes = delivery.deliver_introduction(
        _projection(), sinks=sinks, agreement_ref="neg-1"
    )

    assert [outcome.delivered for outcome in outcomes] == [True]
    written = json.loads(target.read_text(encoding="utf-8").strip())
    assert written["contact"] == SELLER_CONTACT
    assert written["role"] == "buyer"
    assert written["agreement_ref"] == "neg-1"


def test_no_delivery_configured_delivers_nothing(tmp_path) -> None:
    config = tmp_path / "buyer.toml"
    config.write_text("[registry]\nurls = []\n", encoding="utf-8")

    sinks = delivery.load_buyer_delivery_sinks(str(config))

    assert sinks.sinks == ()
    assert delivery.deliver_introduction(_projection(), sinks=sinks) == ()


def test_a_failing_sink_is_reported_and_is_not_an_error() -> None:
    def explode(event):
        raise DeliveryError("the configured endpoint returned status 500")

    outcomes = delivery.deliver_introduction(
        _projection(),
        sinks=DeliverySinkSet(sinks=(ConfiguredSink(name="hook", sink=explode),)),
    )
    stream = io.StringIO()
    delivery.report_delivery(outcomes, (), stream=stream)

    assert outcomes[0].delivered is False
    assert stream.getvalue() == (
        "delivery: delivery to hook failed: "
        "the configured endpoint returned status 500\n"
    )


def test_reporting_carries_no_contact_payload() -> None:
    def leaky(event):
        raise RuntimeError(f"could not reach {event.contact['telegram']}")

    outcomes = delivery.deliver_introduction(
        _projection(),
        sinks=DeliverySinkSet(sinks=(ConfiguredSink(name="hook", sink=leaky),)),
    )
    stream = io.StringIO()
    delivery.report_delivery(outcomes, ("one sink was skipped",), stream=stream)

    printed = stream.getvalue()
    assert "@capacity_broker" not in printed
    assert "one sink was skipped" in printed
    assert "RuntimeError" in printed


def test_an_operator_mistake_fails_when_the_set_is_built(tmp_path) -> None:
    config = tmp_path / "buyer.toml"
    config.write_text(
        "[delivery]\nenabled = ['pigeon']\n\n[delivery.pigeon]\nloft = '4'\n",
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="not installed"):
        delivery.load_buyer_delivery_sinks(str(config))
