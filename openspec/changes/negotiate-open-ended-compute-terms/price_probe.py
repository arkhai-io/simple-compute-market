"""Replay the partial quote/retention seam without claiming live rate support."""

from __future__ import annotations

import base64
import json
import runpy
from copy import deepcopy
from pathlib import Path

from arkhai_vms_buyer.negotiation_amounts import retained_pricing_record
from arkhai_vms_buyer.settlement_composition import accepted_listing_record
from core_buyer.settlement import SelectedSettlementOption
from market_arkhai_payments import create_arkhai_payments_registration
from market_core.schemas import (
    Agreement, PriceBasis, SettlementOption, SettlementSelection, agreed_price,
    derive_settlement_option_id, settlement_option_params,
)
from market_identity import (
    RequestEnvelope, TrustedIdentitySet, canonical_body_hash, sign_request, verify_request,
)


def must_refuse(call, fragment):
    try:
        call()
    except ValueError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(f"expected refusal: {fragment}")


def main():
    source = runpy.run_path(str(Path(__file__).with_name("codec_probe.py")))
    outcome, _, publication = source["probe"]()
    agreement = outcome.agreement
    option = agreement.settlement
    seller = source["SELLER"]
    trust = TrustedIdentitySet(identities=(seller.identity,))
    publication["rate_structure"] = {"example": [{"asset": "USD/6", "rate": "2.5", "per": "hour"}]}
    request = sign_request(signer=seller, envelope=RequestEnvelope(
        principal=seller.identity, role="seller", method="POST", operation="listing.publish",
        resource="listings", request_id="example-pricing-proof", timestamp=1793966340,
        body_hash=canonical_body_hash(publication),
    ))
    listing = {
        **deepcopy(publication), "publisher_principals": trust.model_dump(mode="json"),
        "publisher_publication": {
            "body_base64": base64.b64encode(json.dumps(publication).encode()).decode(),
            "request": request.model_dump(mode="json"),
        },
    }
    selected = SelectedSettlementOption(
        option=option,
        selection=SettlementSelection(option_id=option.option_id, settlement={"schema": option.settlement_schema}),
        registration=create_arkhai_payments_registration(),
    )
    snapshot = accepted_listing_record({**listing, "_selected_settlement": selected}, None)
    assert retained_pricing_record(listing) == snapshot
    stored = json.loads(json.dumps(snapshot))
    proof = stored["publisher_publication"]
    body = json.loads(base64.b64decode(proof["body_base64"]))
    checked = verify_request(
        proof["request"], body=body, now=proof["request"]["timestamp"], max_skew=0,
        expected_principals=trust, expected_role="seller", expected_method="POST",
        expected_operation="listing.publish", expected_resource="listings",
    )
    assert checked.verified, checked.code
    assert body["rate_structure"] == stored["rate_structure"]
    assert body["settlement_options"] == stored["settlement_options"]
    listing["rate_structure"]["example"][0]["rate"] = "99"
    listing["publisher_publication"]["request"]["operation"] = "listing.update"
    assert snapshot == stored
    print("VM acceptance record -> JSON recovery -> historical seller proof; source edits isolated: PASS")

    total = lambda selected: PriceBasis(unit="total")
    quote = agreed_price(agreement, stored, project_billing=total)
    assert (quote.amount, quote.unit, quote.period) == (5000000, "total", None)
    assert agreed_price(Agreement.model_validate_json(agreement.model_dump_json()), stored, project_billing=total) == quote
    assert quote.model_dump(mode="json")["amount"] == "5000000"
    must_refuse(lambda: agreed_price(agreement, stored), "billing projection")
    changed = deepcopy(stored)
    changed["listing_id"] = "another-listing"
    must_refuse(lambda: agreed_price(agreement, changed, project_billing=total), "identity differs")
    changed = deepcopy(stored)
    changed["settlement_options"] = []
    must_refuse(lambda: agreed_price(agreement, changed, project_billing=total), "exact selected option")
    fallback = agreement.model_dump(mode="json")
    fallback.update(settlement=None, asset=None, amount="123")
    assert agreed_price(fallback).amount == 123
    print("monetary prepaid/recovery/fallback; explicit projection and snapshot correspondence refusals: PASS")

    # Proposed neutral fixtures, not hosted rate options or derived mandates.
    for period, seconds, amount in (("PT15M", 900, 625000), ("PT1M", 60, 41667)):
        fields = {
            "price": option.price,
            "settlement": {"schema": "example.billing.v1", "period": period},
        }
        recurring = SettlementOption(option_id=derive_settlement_option_id(**fields), **fields)
        raw = agreement.model_dump(mode="json")
        raw.update(settlement=recurring.model_dump(mode="json"), amount=str(amount))
        project = lambda selected: PriceBasis(
            unit="per_period", period=settlement_option_params(selected)["period"], period_seconds=seconds,
        )
        quote = agreed_price(raw, project_billing=project)
        assert (quote.amount, quote.unit, quote.period, quote.period_seconds) == (amount, "per_period", period, seconds)
        assert quote.amount != amount * raw["duration_seconds"]
    for fields in ({"unit": "per_period"}, {"unit": "total", "period": "PT1M"},
                   {"unit": "per_period", "period": "PT1M", "period_seconds": 0}):
        must_refuse(lambda: PriceBasis(**fields), "")
    invalid = agreement.model_dump(mode="json")
    invalid["amount"] = str(2**256)
    must_refuse(lambda: agreed_price(invalid, project_billing=total), "less than or equal")
    print("injected sub-hour period labels preserve accepted money; inconsistent basis/overflow refused: PASS")
    print("LIMIT: no production billing projection wiring, transcript-price verification, reader migration or rate execution")


if __name__ == "__main__":
    main()
