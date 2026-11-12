"""Exact rate/setup derivation and buyer agreement checks at the pure boundary."""

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest
from market_core.schemas import derive_settlement_option_id

from market_arkhai_payments import MandatePolicyError, PaymentApproval, PaymentSettlementData, transaction_id
from market_arkhai_payments.canonical import wire_json
from payment_terms import BUYER, PAYEE, DISPUTE, config
from rate_terms import NOW, rate_agreement, rate_data


def test_rate_and_setup_derive_per_part_permissions_and_absolute_ends():
    raw = rate_agreement()
    before = deepcopy(raw)
    mandate = wire_json(rate_data(raw).mandate)
    rate, setup = mandate["parts"][1], mandate["parts"][0]
    assert setup == {
        "kind": "once", "asset": "USD/2", "amount": "25",
        "end": {"at": NOW, "partialPeriod": "returned"},
        "hold": {"afterStop": "P7D"}, "maxHoldExtension": None,
        "authorities": {"stop": [], "reverse": [PAYEE, DISPUTE], "extend": [DISPUTE]},
    }
    assert rate == {
        "kind": "rate", "asset": "USD/2", "amount": "100", "period": "PT60S",
        "reserveAhead": "PT2M", "end": {"at": NOW + 3600, "partialPeriod": "charged"},
        "hold": {"afterStop": "P7D"}, "maxHoldExtension": None,
        "authorities": {
            "start": [PAYEE], "reverse": [PAYEE, DISPUTE], "extend": [DISPUTE],
            "stop": [
                {"account": BUYER, "notice": "PT5M", "partialPeriod": "charged"},
                {"account": PAYEE, "notice": "PT30S", "partialPeriod": "charged"},
                {"account": DISPUTE, "notice": "PT0S", "partialPeriod": "chosen"},
            ],
        },
    }
    assert mandate["expires"] == NOW + 60
    assert raw == before
    without_setup = wire_json(rate_data(rate_agreement(setup=None, payee_notice=None)).mandate)
    assert len(without_setup["parts"]) == 1
    assert [entry["account"] for entry in without_setup["parts"][0]["authorities"]["stop"]] == [BUYER, DISPUTE]


@pytest.mark.parametrize("field,value", [
    ("amount", "101"), ("period", "PT2M"), ("reserveAhead", "PT3M"),
    ("end", {"at": NOW + 3601, "partialPeriod": "charged"}),
    ("hold", {"afterStop": "P6D"}),
    ("authorities", {"start": [BUYER], "stop": [], "reverse": [PAYEE], "extend": []}),
])
def test_buyer_rederives_exact_rate_terms_before_approving(field, value):
    raw = rate_agreement(treatment="last_boundary")
    data = rate_data(raw)
    approval = PaymentApproval(config(), BUYER)
    assert approval.check(json.dumps(raw), data.to_wire())[1] == data
    changed = wire_json(data.mandate)
    changed["parts"][1][field] = value
    # The transaction hash is valid for the changed mandate; only exact
    # re-derivation against the Agreement can detect this changed bargain.
    changed_data = {"mandate": changed, "transaction_id": transaction_id(changed)}
    with pytest.raises(MandatePolicyError, match="differs"):
        approval.check(json.dumps(raw), changed_data)


def test_default_buyer_refuses_charged_ends_and_missing_rate_hook_stays_closed():
    raw = rate_agreement()
    with pytest.raises(MandatePolicyError, match="does not return the final partial period"):
        PaymentApproval(config(), BUYER).check(json.dumps(raw), rate_data(raw).to_wire())
    with pytest.raises(ValueError):
        PaymentSettlementData.for_agreement(raw, config())


@pytest.mark.parametrize("mutation", ["fractional_start", "short_runway", "bond"])
def test_unencodable_rate_terms_refuse(mutation):
    raw = rate_agreement()
    if mutation == "fractional_start":
        raw["start_utc"] = "2027-01-15T08:00:00.500000Z"
    elif mutation == "short_runway":
        raw["duration_seconds"] = 100
    else:
        raw["settlement"]["lifecycle"]["bond"] = {"amount": "1"}
    with pytest.raises((MandatePolicyError, ValueError)):
        rate_data(raw)


@pytest.mark.parametrize("start_offset,minimum", [(0, 150), (3600, 90)])
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_runway_meets_both_approval_expiry_and_a_later_service_start(start_offset, minimum, delta):
    raw = rate_agreement()
    raw["start_utc"] = datetime.fromtimestamp(NOW + start_offset, timezone.utc).isoformat().replace("+00:00", "Z")
    raw["duration_seconds"] = minimum + delta
    if delta < 0:
        with pytest.raises(MandatePolicyError, match="runway"):
            rate_data(raw)
    else:
        assert rate_data(raw).mandate.parts[1].root.end.at == NOW + start_offset + minimum + delta


def test_entitlement_object_order_does_not_change_derived_permission_order():
    raw = rate_agreement()
    before = rate_data(raw)
    option = raw["settlement"]
    terms = option["lifecycle"]["early_termination"]
    terms["entitlements"] = dict(reversed(list(terms["entitlements"].items())))
    option["option_id"] = derive_settlement_option_id(**{k: v for k, v in option.items() if k != "option_id"})
    assert rate_data(raw) == before
