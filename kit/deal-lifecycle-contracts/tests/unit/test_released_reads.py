"""A once-only deal's lifecycle read and list stay valid for release 0.1.0's clients."""

import pytest
from pydantic import ValidationError

from market_deal_lifecycle_contracts import models as m

import released_0_1_0 as released

REVERSE = m.PaymentEvent(
    negotiation_id="n", commitment_ref="c", part="0", kind="reverse", actor="payee", at=100,
    amount="20", cause="payee", sequence=1, authority_record_ref="c:events:1",
)
DELIVERY = m.DeliveryView(progress="active")


def once_read() -> m.LifecycleRead:
    return m.LifecycleRead(
        negotiation_id="n", commitment_ref="c", delivery=DELIVERY,
        authority=m.AuthorityView(outcome=m.Accepted(records=[REVERSE]), state="running",
                                  events=[REVERSE], payouts={"0": None}),
    )


def once_page() -> m.DealPage:
    return m.DealPage(deals=[m.DealSummary(
        negotiation_id="n", commitment_ref="c", domain="vm", mechanism="arkhai.payments.v1",
        entitlements={}, state="running", has_open_extension=False, open_cases=[],
    )])


def test_a_once_deal_read_validates_against_the_released_model():
    wire = once_read().model_dump(mode="json")
    assert "parts" not in wire["authority"] and "settles_through" not in wire["authority"]["events"][0]
    released.LifecycleRead.model_validate(wire)
    # A reader of this version restores the omitted defaults exactly.
    assert m.LifecycleRead.model_validate(wire) == once_read()


def test_a_once_deal_list_validates_against_the_released_model():
    wire = once_page().model_dump(mode="json")
    assert "parts" not in wire["deals"][0]
    released.DealPage.model_validate(wire)
    assert m.DealPage.model_validate(wire) == once_page()


def test_a_rate_observation_is_carried_and_released_clients_cannot_read_it():
    stop = REVERSE.model_copy(update={"kind": "stop", "amount": None, "settles_through": "last_boundary"})
    observed = m.PaymentPartObservation(part="1", final_stop=stop, evidence_ref="c:snapshot:2:100")
    read = once_read().model_copy(update={"authority": once_read().authority.model_copy(update={
        "parts": [observed], "events": [stop],
    })})
    wire = read.model_dump(mode="json")
    assert wire["authority"]["parts"][0]["final_stop"]["settles_through"] == "last_boundary"
    assert m.LifecycleRead.model_validate(wire) == read
    with pytest.raises(ValidationError):
        released.LifecycleRead.model_validate(wire)
