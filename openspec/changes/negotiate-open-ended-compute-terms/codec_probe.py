"""Replay nested terms through publication, carrier models and buyer checks."""

from __future__ import annotations

import asyncio
import base64
import json
from copy import deepcopy
from types import SimpleNamespace

from market_arkhai_payments import ArkhaiPaymentsConfig, PaymentApproval, PaymentSettlementData
from market_arkhai_payments.fixtures import dispute_lifecycle
from market_arkhai_payments.settlement_config import (
    arkhai_payments_option_builder, arkhai_payments_preflight,
)
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.selection import AuthoritySelection
from market_deal_lifecycle.terms import decode_terms, encode_terms
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_settlement_runtime import SettlementPublicationClause
from registry_client.models import ListingRequest, ListingSummary

# Deterministic development identities and accounts; never use on a public network.
PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"
SELLER = Ed25519Signer(bytes(range(32)))
SERVICE = Ed25519Signer(bytes(range(1, 33)))


def probe():
    config = ArkhaiPaymentsConfig(
        enabled=True, service_url="http://127.0.0.1:9", service_identity=SERVICE.identity,
        fee_bps=250, development_auth=True,
    )
    authority = DisputeEntry.model_validate({
        **dispute_lifecycle(DISPUTE)["adjudication"]["dispute"],
        "advertisement": {"mechanisms": ["arkhai.payments.v1"],
                          "minimum_dispute_window_seconds": 60,
                          "minimum_case_hold_seconds": None},
    })
    readiness = asyncio.run(arkhai_payments_preflight(config, {}, "seller"))
    clause = SettlementPublicationClause.model_validate({
        "mechanism": "arkhai.payments.v1", "asset": "USD/6", "rate": "2.5", "per": "hour",
        "mechanism_input": {
            "payee_account": PAYEE, "asset": "USD/6", "window": "P7D",
            "dispute_window_seconds": 604800, "delivery_deadline_seconds": 1200,
        },
    })
    built = arkhai_payments_option_builder(config, readiness, {
        "publication_clause": clause, "dispute_authorities": (authority,),
        "dispute_interfaces": frozenset({authority.interface}), "compute": True,
    }, "seller")
    option = SettlementOption.model_validate(built["settlement_options"][0])
    assert encode_terms(decode_terms(option.lifecycle)) == option.lifecycle
    publication = ListingRequest(
        listing_id="example-terms", listing_resource={"region": "example"}, accepted_escrows=[],
        settlement_options=built["settlement_options"], storefront_url="https://seller.example/",
    ).to_dict()
    discovered = ListingSummary.from_dict({
        **json.loads(json.dumps(publication)),
        "publisher_principals": TrustedIdentitySet(identities=(SELLER.identity,)).model_dump(mode="json"),
    }).to_dict()
    assert discovered["settlement_options"] == publication["settlement_options"]
    recovered = SettlementOption.model_validate(discovered["settlement_options"][0])
    assert encode_terms(decode_terms(recovered.lifecycle)) == option.lifecycle
    print("hosted once builder -> registry carrier models -> shared codec: PASS")

    # This projects rights only, not a supported hosted rate option or mandate.
    early = {
        "version": 1, "entitlements": {
            "payer": {"notice_seconds": 0, "settles_through": "started_period"},
            "payee": {"notice_seconds": 120, "settles_through": "last_boundary"},
        }, "settles_through": "last_boundary", "premature_stop_penalty": "100",
    }
    lifecycle = {**option.lifecycle, "early_termination": early}
    structural = {"price": option.price, "settlement": option.settlement, "lifecycle": lifecycle}
    recurring = SettlementOption(option_id=derive_settlement_option_id(**structural), **structural)
    nested = SettlementOption.model_validate_json(recurring.model_dump_json())
    assert encode_terms(decode_terms(nested.lifecycle)) == lifecycle
    changed = deepcopy(structural)
    changed["lifecycle"]["early_termination"]["entitlements"]["payee"]["notice_seconds"] = 121
    assert derive_settlement_option_id(**changed) != recurring.option_id
    print("early_termination/adjudication nested round-trip and term-sensitive ID: PASS (structural only)")

    agreement = Agreement(
        negotiation_id="example-negotiation", listing_id="example-terms", listing_hash="a" * 64,
        buyer={"scheme": "ed25519", "identifier": "example-buyer"},
        seller=SELLER.identity.model_dump(mode="json"), settlement=recovered,
        settlement_params={"payer_account": PAYER}, amount=5000000, asset="USD/6",
        duration_seconds=7200, start_utc="2026-11-06T12:00:00Z",
        accepted_at="2026-11-06T11:59:00Z",
    )
    raw = agreement.model_dump_json().encode()
    stored = Agreement.model_validate_json(raw)
    assert encode_terms(decode_terms(stored.settlement.lifecycle)) == option.lifecycle
    data = PaymentSettlementData.for_agreement(json.loads(raw), config)
    approval = PaymentApproval(config, PAYER)
    checked, _ = approval.check(raw, data.to_wire())
    assert checked["settlement"]["lifecycle"] == option.lifecycle
    print("accepted Agreement -> shared buyer mandate commitment check: PASS (no approval I/O)")

    alkahest = {"settlement": {"schema": "alkahest.v1"}}
    valid = SettlementOption(option_id=derive_settlement_option_id(**alkahest), **alkahest)
    policy = AuthoritySelection({}, contexts={})
    assert policy(valid, {}) == 0
    invalid = {**alkahest, "lifecycle": option.lifecycle}
    invalid = SettlementOption(option_id=derive_settlement_option_id(**invalid), **invalid)
    assert policy(invalid, {}) is None
    print("Alkahest without lifecycle admitted; with lifecycle refused: PASS")
    return SimpleNamespace(
        agreement=agreement, agreement_bytes=base64.b64encode(raw).decode(),
        settlement_data=data.to_wire(),
    ), approval, publication


if __name__ == "__main__":
    probe()
