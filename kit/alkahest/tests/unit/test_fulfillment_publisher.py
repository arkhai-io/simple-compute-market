"""The Alkahest fulfillment publisher's outcomes, over a doubled chain client.

The chain client is the external boundary: these tests decide what it raises
or returns and check how the publisher reports it, which is the whole of the
publisher's own logic.
"""

from __future__ import annotations

import asyncio

import pytest

from market_alkahest import AlkahestFulfillmentPublisher, FulfillmentPublication
from market_alkahest.txlock import chain_tx_lock


class StringObligation:
    def __init__(self, *, returns=None, raises: Exception | None = None) -> None:
        self.returns = returns
        self.raises = raises
        self.calls: list[tuple[str, str]] = []

    async def do_obligation(self, item, ref_uid=None, schema=None):
        self.calls.append((item, ref_uid))
        if self.raises is not None:
            raise self.raises
        return self.returns


class Client:
    def __init__(self, obligation: StringObligation) -> None:
        self.string_obligation = obligation


DIGEST = "sha256:" + "ab" * 32
ESCROW = "0x" + "11" * 32


async def test_a_published_attestation_reports_its_uid_and_submits_exactly_the_data():
    obligation = StringObligation(returns="0xattestation")
    publisher = AlkahestFulfillmentPublisher(Client(obligation))

    result = await publisher.publish(condition_anchor=ESCROW, data=DIGEST)

    assert result == FulfillmentPublication("published", reference="0xattestation")
    assert obligation.calls == [(DIGEST, ESCROW)]


@pytest.mark.parametrize(
    "message",
    [
        "execution reverted: escrow not open",
        "transaction reverted",
        "insufficient funds for gas * price + value",
        "nonce too low",
    ],
)
async def test_a_refusal_or_revert_is_rejected(message):
    publisher = AlkahestFulfillmentPublisher(
        Client(StringObligation(raises=RuntimeError(message)))
    )

    result = await publisher.publish(condition_anchor=ESCROW, data=DIGEST)

    assert result.outcome == "rejected"
    assert result.reference is None


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("receipt not received"),
        RuntimeError("connection reset by peer"),
        RuntimeError("already known"),
    ],
)
async def test_a_failure_that_may_follow_the_submission_is_unknown(error):
    publisher = AlkahestFulfillmentPublisher(
        Client(StringObligation(raises=error))
    )

    result = await publisher.publish(condition_anchor=ESCROW, data=DIGEST)

    assert result.outcome == "outcome_unknown"


async def test_an_empty_uid_after_the_call_is_unknown():
    publisher = AlkahestFulfillmentPublisher(
        Client(StringObligation(returns=""))
    )

    result = await publisher.publish(condition_anchor=ESCROW, data=DIGEST)

    assert result.outcome == "outcome_unknown"


async def test_nothing_is_submitted_without_an_anchor_data_or_client():
    obligation = StringObligation(returns="0xattestation")
    publisher = AlkahestFulfillmentPublisher(Client(obligation))

    no_anchor = await publisher.publish(condition_anchor="", data=DIGEST)
    no_data = await publisher.publish(condition_anchor=ESCROW, data="")
    no_client = await AlkahestFulfillmentPublisher(object()).publish(
        condition_anchor=ESCROW, data=DIGEST
    )

    assert [no_anchor.outcome, no_data.outcome, no_client.outcome] == [
        "not_submitted",
        "not_submitted",
        "not_submitted",
    ]
    assert obligation.calls == []


def test_a_reference_is_reported_exactly_when_published():
    with pytest.raises(ValueError):
        FulfillmentPublication("published")
    with pytest.raises(ValueError):
        FulfillmentPublication("rejected", reference="0xattestation")


async def test_publication_waits_for_the_wallets_other_submissions():
    # Materialize, collect, and reclaim submit from the same wallet under this
    # lock; a publication that did not take it could reuse their nonce.
    obligation = StringObligation(returns="0xattestation")
    publisher = AlkahestFulfillmentPublisher(Client(obligation))
    held = chain_tx_lock(None)

    async with held:
        pending = asyncio.create_task(
            publisher.publish(condition_anchor=ESCROW, data=DIGEST)
        )
        # Yield to the loop until the task has run as far as it can.
        for _ in range(10):
            await asyncio.sleep(0)
        assert not pending.done()
        assert obligation.calls == [], "publication must wait for the held lock"
    result = await pending

    assert result.outcome == "published"
    assert obligation.calls == [(DIGEST, ESCROW)]
