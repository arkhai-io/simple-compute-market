"""The storefront's bundle, through the selling library's evidence producer, authorizes the pinned issuance requests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from arkhai_api_selling.issuance import prepare_issuance_request, settlement_evidence
from arkhai_apicredits.negotiation.terms import make_api_credits_provision_terms
from market_core.schemas import Agreement
from market_identity import Identity

from apicredits_storefront.container import SELLING_CONTRIBUTIONS
from tests.integration.credit_negotiation import SELLER_PRINCIPAL, payment_option

PINS = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "pins" / "issuance_pins.json"


def _cases():
    return json.loads(PINS.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_production_evidence_yields_the_pinned_request(case):
    inputs, expected = case["inputs"], case["expected"]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    agreement = Agreement(
        negotiation_id=inputs["negotiation_id"],
        listing_id="L-pin",
        listing_hash="0" * 64,
        buyer=Identity.model_validate(inputs["owner"]).model_dump(mode="json"),
        seller=SELLER_PRINCIPAL.model_dump(mode="json"),
        settlement=payment_option(),
        amount=inputs["quantity"] * 100,
        asset="USD/2",
        duration_seconds=0,
        start_utc=now,
        accepted_at=now,
        provision_terms=make_api_credits_provision_terms(
            quantity=inputs["quantity"],
            key_mode=inputs["key"]["mode"],
            key_id=inputs["key"].get("key_id"),
        ).model_dump(mode="json"),
    )
    evidence = settlement_evidence(
        SELLING_CONTRIBUTIONS,
        agreement,
        agreement.model_dump_json(exclude_none=True).encode(),
        reference=inputs["obligation_ref"],
        status="verified",
        source={"obligation_ref": inputs["obligation_ref"]},
        order={
            "listing_resource": {
                "service_name": inputs["service"],
                "resource_id": inputs["resource_id"],
                "capacity_site_id": "quota",
            }
        },
    )

    prepared = prepare_issuance_request(SELLING_CONTRIBUTIONS, evidence=evidence)

    assert prepared.fulfillment_id == expected["fulfillment_id"]
    assert prepared.request_digest == expected["request_digest"]
