"""Seller-side delivery rides the reveal without ever gating it."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from market_delivery import (
    ConfiguredSink,
    DeliveryConfigurationError,
    DeliveryError,
    build_delivery_sinks,
    load_delivery_config,
)

from arkhai_bare_metal_storefront.delivery import (
    build_introduction_delivery,
    load_storefront_delivery_sinks,
    redeliver_introduction,
    storefront_delivery_section,
)

from test_http_introductions import (
    BUYER_SIGNER,
    _BUYER_CONTACT,
    _SELLER_CONTACT,
    _accept_and_start,
    _app,
    _headers,
    _insert_contact_listing,
    _runtime,
)


def _recording_sink(received, *, name="recorder", timeout_seconds=10.0):
    return ConfiguredSink(
        name=name,
        sink=lambda event: received.append(event),
        timeout_seconds=timeout_seconds,
    )


async def _await_delivery(received: list, *, expected: int = 1) -> None:
    """Background dispatch is fire-and-forget; give it a bounded moment."""

    for _ in range(200):
        if len(received) >= expected:
            return
        await asyncio.sleep(0.01)


def _start_again(client, negotiation_id: str, obligation_ref: str):
    """Post the same start once more -- a repeat, not an authorized replay."""

    body = {
        "negotiation_id": negotiation_id,
        "obligation_ref": obligation_ref,
        "contact_payload": dict(_BUYER_CONTACT),
    }
    return client.post(
        "/api/v1/introductions",
        json=body,
        headers=_headers(
            BUYER_SIGNER, "buyer", "introduction_start", obligation_ref, body
        ),
    )


async def test_the_reveal_tells_the_seller_its_own_half(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    received: list = []
    object.__setattr__(
        runtime,
        "introduction_delivery",
        build_introduction_delivery((_recording_sink(received),)),
    )
    option = await _insert_contact_listing(runtime)

    with TestClient(_app(runtime)) as client:
        negotiation_id, obligation_ref, projection = _accept_and_start(client, option)
        assert projection["counterparty_contact"] == _SELLER_CONTACT
        await _await_delivery(received)

    (event,) = received
    assert event.role == "seller"
    assert event.contact == _BUYER_CONTACT
    assert event.obligation_ref == obligation_ref
    assert event.agreement_ref == negotiation_id
    assert event.counterparty.startswith("eip191:")
    assert event.context["channel"] == "telegram"
    status = await runtime.settlement_runtime.get_status(negotiation_id)
    assert status.status == "complete"


async def test_every_sink_failing_leaves_the_reveal_and_the_deal_intact(
    tmp_path,
) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))

    def explode(event):
        raise DeliveryError("the operator's endpoint returned status 500")

    object.__setattr__(
        runtime,
        "introduction_delivery",
        build_introduction_delivery(
            (ConfiguredSink(name="broken", sink=explode),)
        ),
    )
    option = await _insert_contact_listing(runtime)

    with TestClient(_app(runtime)) as client:
        negotiation_id, obligation_ref, projection = _accept_and_start(client, option)

    assert projection["revealed"] is True
    assert projection["counterparty_contact"] == _SELLER_CONTACT
    status = await runtime.settlement_runtime.get_status(negotiation_id)
    assert status.status == "complete"
    record = await runtime.db.load_contact_introduction(obligation_ref=obligation_ref)
    assert record is not None


async def test_a_hanging_sink_does_not_extend_the_counterparty_request(
    tmp_path,
) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    release = threading.Event()

    def hangs(event):
        release.wait(30)

    object.__setattr__(
        runtime,
        "introduction_delivery",
        build_introduction_delivery(
            (ConfiguredSink(name="hangs", sink=hangs, timeout_seconds=5.0),)
        ),
    )
    option = await _insert_contact_listing(runtime)

    try:
        with TestClient(_app(runtime)) as client:
            started = time.monotonic()
            _, _, projection = _accept_and_start(client, option)
            elapsed = time.monotonic() - started
            assert projection["revealed"] is True
            # The counterparty's request is finished while the sink it
            # triggered is still blocked: delivery is not on that path.
            assert elapsed < 5
            assert not release.is_set()
            release.set()
    finally:
        release.set()


async def test_a_repeat_start_announces_one_introduction_once(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    received: list = []
    object.__setattr__(
        runtime,
        "introduction_delivery",
        build_introduction_delivery((_recording_sink(received),)),
    )
    option = await _insert_contact_listing(runtime)

    with TestClient(_app(runtime)) as client:
        negotiation_id, obligation_ref, _ = _accept_and_start(client, option)
        await _await_delivery(received)
        first = len(received)
        again = _start_again(client, negotiation_id, obligation_ref)
        assert again.status_code == 200, again.text
        await asyncio.sleep(0.2)

    assert first == 1
    assert len(received) == 1


async def test_redelivery_sends_the_same_introduction_again(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    option = await _insert_contact_listing(runtime)
    with TestClient(_app(runtime)) as client:
        _, obligation_ref, _ = _accept_and_start(client, option)

    received: list = []
    outcomes = await redeliver_introduction(
        runtime.db, obligation_ref, (_recording_sink(received),)
    )

    assert [outcome.delivered for outcome in outcomes] == [True]
    assert received[0].contact == _BUYER_CONTACT
    assert received[0].role == "seller"

    with pytest.raises(ValueError, match="not been revealed"):
        await redeliver_introduction(runtime.db, "f" * 64, (_recording_sink([]),))


def test_delivery_configuration_is_read_from_this_storefronts_environment(
    monkeypatch, tmp_path
) -> None:
    target = tmp_path / "introductions.jsonl"
    monkeypatch.setenv(
        "BARE_METAL_STOREFRONT_DELIVERY",
        json.dumps({"enabled": ["file"], "file": {"path": str(target)}}),
    )

    sinks = load_storefront_delivery_sinks(storefront_delivery_section())

    assert [sink.name for sink in sinks.sinks] == ["file"]
    assert build_introduction_delivery(sinks.sinks) is not None


def test_no_delivery_configured_installs_no_dispatch(monkeypatch) -> None:
    monkeypatch.delenv("BARE_METAL_STOREFRONT_DELIVERY", raising=False)

    sinks = load_storefront_delivery_sinks(storefront_delivery_section())

    assert sinks.sinks == ()
    assert build_introduction_delivery(sinks.sinks) is None


def test_an_operator_mistake_fails_before_any_deal_exists(monkeypatch) -> None:
    monkeypatch.setenv(
        "BARE_METAL_STOREFRONT_DELIVERY",
        json.dumps({"enabled": ["pigeon"], "pigeon": {}}),
    )

    with pytest.raises(DeliveryConfigurationError, match="not installed"):
        load_storefront_delivery_sinks(storefront_delivery_section())


async def test_a_credentialed_sink_stays_out_of_every_public_surface(tmp_path) -> None:
    config = load_delivery_config(
        {
            "enabled": ["webhook"],
            "webhook": {"url": "https://hooks.invalid/T0/secret-token"},
        }
    )
    built = build_delivery_sinks(config)

    runtime = _runtime(str(tmp_path / "storefront.db"))
    object.__setattr__(
        runtime, "introduction_delivery", build_introduction_delivery(built.sinks)
    )
    composition = runtime.settlement_composition
    readiness = await composition.readiness(clauses=())
    published = json.dumps(
        {
            "readiness": [item.model_dump(mode="json") for item in readiness],
            "runtime": repr(runtime),
            "sinks": [sink.name for sink in built.sinks],
        },
        default=str,
    )

    assert "secret-token" not in published
