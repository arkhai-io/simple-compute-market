"""This release's models read each deal shape a storefront of the same release serves.

A storefront's lifecycle route answers a read or list with the model's JSON dump
in canonical form, and the seller client validates the decoded body with these
models, so a once-only, rate, ending and ended deal must each come back exactly
as it was served. That every field is dumped is ``test_models.py``'s to show.
"""

import json

import pytest

from market_deal_lifecycle_contracts import models as m
from market_identity import Ed25519Signer, canonical_json

REVERSE = m.PaymentEvent(
    negotiation_id="n", commitment_ref="c", part="0", kind="reverse", actor="payee", at=100,
    amount="20", cause="payee", sequence=1, authority_record_ref="c:events:1",
)
STOP = m.PaymentEvent(
    negotiation_id="n", commitment_ref="c", part="0", kind="stop", actor="payer", at=160,
    cause="payer", sequence=2, authority_record_ref="c:events:2", settles_through="started_period",
)
RUNNING_PART = m.PaymentPartObservation(part="0", started_at=100, evidence_ref="c:snapshot:1:150")
STOPPED_PART = m.PaymentPartObservation(part="0", started_at=100, final_stop=STOP, evidence_ref="c:snapshot:2:170")
# A public deterministic development seed; never use on a public network.
BUYER = Ed25519Signer(bytes([1]) * 32).identity
END = m.RecordedEnd(ended_at=160, actor=BUYER, cause="payer", source="c:events:2")


def read(*, events, parts, progress, recorded_end=None, state="running") -> m.LifecycleRead:
    return m.LifecycleRead(
        negotiation_id="n", commitment_ref="c",
        delivery=m.DeliveryView(progress=progress, recorded_end=recorded_end),
        authority=m.AuthorityView(outcome=m.Accepted(records=events), state=state, events=events,
                                  parts=parts, payouts={"0": None}),
    )


def summary(*, state, parts=(), ending=()) -> m.DealSummary:
    return m.DealSummary(
        negotiation_id="n", commitment_ref="c", domain="vms", mechanism="arkhai.payments.v1",
        entitlements={"payer": {"notice_seconds": 0}}, state=state, ending=list(ending), parts=list(parts),
        has_open_extension=False, open_cases=["case"] if "case_open" in ending else [],
    )


def served(model):
    """The body a storefront's lifecycle route answers with, as a client decodes it."""
    return json.loads(canonical_json(model.model_dump(mode="json")))


READS = {
    "once-only": read(events=[REVERSE], parts=[], progress="active"),
    "rate": read(events=[], parts=[RUNNING_PART], progress="active"),
    "ending": read(events=[STOP], parts=[STOPPED_PART], progress="tearing_down", recorded_end=END,
                   state="ending"),
    "ended": read(events=[STOP], parts=[STOPPED_PART], progress="released", recorded_end=END, state="ended"),
}
PAGES = {
    "once-only": m.DealPage(deals=[summary(state="running")]),
    "rate": m.DealPage(deals=[summary(state="running", parts=[RUNNING_PART])]),
    "ending": m.DealPage(deals=[summary(state="ending", parts=[RUNNING_PART],
                                        ending=["payment_running", "case_open"])],
                         continuation="n"),
    "ending, dispute unobserved": m.DealPage(deals=[summary(state="ending", parts=[STOPPED_PART],
                                                            ending=["case_unobserved"])]),
    "ended": m.DealPage(deals=[summary(state="ended", parts=[STOPPED_PART])]),
}


@pytest.mark.parametrize("shape", sorted(READS))
def test_a_served_read_is_read_back_exactly(shape):
    assert m.LifecycleRead.model_validate(served(READS[shape])) == READS[shape]


@pytest.mark.parametrize("shape", sorted(PAGES))
def test_a_served_page_is_read_back_exactly(shape):
    assert m.DealPage.model_validate(served(PAGES[shape])) == PAGES[shape]
