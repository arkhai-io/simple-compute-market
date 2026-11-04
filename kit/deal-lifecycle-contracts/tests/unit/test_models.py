"""The lifecycle wire is closed and preserves every public record on replay."""

import base64

import pytest
from pydantic import TypeAdapter, ValidationError

from market_deal_lifecycle_contracts import models as m


RAW = b'{"signed": true}\n'
ITEM = dict(evidence_id="e1", kind="acceptance", classification="independent",
            recorded_at=100, body=base64.b64encode(RAW).decode())
PAYMENT = dict(negotiation_id="n", commitment_ref="c", part="p", actor="account",
               at=100, amount="20", cause="case", case_ref="case", extension_ref="ext",
               sequence=1, authority_record_ref="r")
DISPUTE = dict(negotiation_id="n", commitment_ref="c", case_ref="case", actor="account",
               at=100, sequence=1, record_ref="r")
HOLD = dict(part="p", status="held", reason="extended", extension_ref="ext")
FILING = dict(case_ref="case", parts=[HOLD], record_ref="r")


def roundtrip(model, data):
    adapter = TypeAdapter(model)
    value = adapter.validate_python(data)
    replay = adapter.validate_json(adapter.dump_json(value))
    assert replay == value
    return value


@pytest.mark.parametrize("kind", ["start", "stop", "reverse", "dispute", "delivery_end", "append"])
def test_commands_roundtrip(kind):
    roundtrip(m.LifecycleCommand, dict(negotiation_id="n", kind=kind, operation_key="op", at=100))


@pytest.mark.parametrize("kind", ["start", "stop", "collect", "reverse", "award", "return", "extend", "lift"])
def test_payment_events_roundtrip(kind):
    roundtrip(m.PaymentEvent, dict(PAYMENT, kind=kind))


@pytest.mark.parametrize("kind", ["filed", "appended", "ruled", "closed"])
def test_dispute_events_roundtrip(kind):
    roundtrip(m.DisputeEvent, dict(DISPUTE, kind=kind, items=[ITEM]))


@pytest.mark.parametrize("kind", ["reverse", "award", "stop", "delivery_end"])
def test_effects_roundtrip(kind):
    data = dict(effect_id="effect", kind=kind, at=100, applied=False)
    if kind != "delivery_end":
        data.update(part="p", amount="20", settles_through="last_boundary")
    roundtrip(m.Effect, data)


@pytest.mark.parametrize("status", ["accepted", "rejected", "pending", "unknown"])
def test_outcomes_roundtrip(status):
    data = dict(status=status)
    if status == "accepted":
        data.update(records=[dict(PAYMENT, kind="reverse"), dict(DISPUTE, kind="filed")], filing=FILING)
    else:
        data["reason"] = "authority unavailable"
    roundtrip(m.LifecycleOutcome, data)


@pytest.mark.parametrize("kind", ["commit", "hint"])
def test_peer_messages_roundtrip(kind):
    data = dict(kind=kind, negotiation_id="n", operation_key="op", payload={"opaque": True})
    if kind == "commit":
        data["commitment_ref"] = "c"
    roundtrip(m.PeerMessage, data)


def test_evidence_case_and_read_roundtrip():
    assert roundtrip(m.EvidenceItem, ITEM).body == RAW
    roundtrip(m.CasePayload, dict(negotiation_id="n", commitment_ref="c",
              agreement=base64.b64encode(b'{"agreement": 1}').decode(), items=[ITEM],
              request={"opaque": "adapter request"}))
    roundtrip(m.LifecycleRead, dict(negotiation_id="n", commitment_ref="c",
              authority=dict(outcome={"status": "accepted"}, state="ending",
                             cases=[dict(case_ref="case", state="filed", record_ref="r")],
                             extensions=[dict(part="p", extension_ref="ext", case_ref="case", until=None)]),
              delivery=dict(progress="tearing_down", site_reports=[ITEM])))
    roundtrip(m.DealPage, dict(deals=[dict(negotiation_id="n", commitment_ref="c", domain="d",
              mechanism="m", entitlements={}, state="running", has_open_extension=False, open_cases=[])]))
    roundtrip(m.ListDealsRequest, {"limit": 1})
    roundtrip(m.SubmitResponse, {"outcome": {"status": "pending", "reason": "pending"}})


@pytest.mark.parametrize("model,data,field", [
    (m.LifecycleCommand, dict(negotiation_id="n", kind="stop", operation_key="op"), "kind"),
    (m.PaymentEvent, dict(PAYMENT, kind="stop"), "kind"),
    (m.DisputeEvent, dict(DISPUTE, kind="filed"), "kind"),
    (m.PeerMessage, dict(kind="hint", negotiation_id="n", operation_key="op"), "kind"),
    (m.LifecycleOutcome, {"status": "accepted"}, "status"),
    (m.Effect, dict(kind="delivery_end", effect_id="e", at=100, applied=True), "kind"),
])
def test_unknown_kinds_are_refused(model, data, field):
    with pytest.raises(ValidationError):
        TypeAdapter(model).validate_python(dict(data, **{field: "unknown_kind"}))


@pytest.mark.parametrize("kind", ["extend", "lift"])
def test_extensions_require_the_case_and_extension_reference(kind):
    with pytest.raises(ValidationError):
        m.PaymentEvent(**dict(PAYMENT, kind=kind, extension_ref=None))
    with pytest.raises(ValidationError):
        m.PaymentEvent(**dict(PAYMENT, kind=kind, case_ref=None))
