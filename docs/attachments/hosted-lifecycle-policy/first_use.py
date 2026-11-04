"""Offline first use of hosted publication, approval and verified snapshots.

Uses public deterministic development accounts/keys, never for a public network.
No server, environment credential, shared seed or external deployment is used.
"""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone

from market_arkhai_mediation.contract import INTERFACE
from market_arkhai_payments import (
    ArkhaiPaymentsConfig, PaymentApproval, PaymentSettlementData, ReceiptIdentity,
    derive_part_terms, mandate_policy_for_agreement, transaction_id, verify_snapshot,
)
from market_arkhai_payments.fixtures import FakePaymentsClient, dispute_lifecycle, sign_snapshot
from market_arkhai_payments.settlement_config import (
    arkhai_payments_option_builder, arkhai_payments_preflight, validate_payment_lifecycle,
)
from market_core.schemas import Agreement
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.terms import LifecycleTerms
from market_identity import Ed25519Signer
from market_settlement_runtime import SettlementPublicationClause
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy

PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"
SERVICE = Ed25519Signer(bytes([7]) * 32)
NEXT = Ed25519Signer(bytes([8]) * 32)
NOW = 1_800_000_000


def refused(label, action):
    try:
        action()
    except ValueError as exc:
        print(label + ": refused (" + str(exc).splitlines()[0] + ")")
    else:
        raise RuntimeError(label + " unexpectedly accepted")


def main():
    authority = dispute_lifecycle(DISPUTE)["adjudication"]["dispute"]
    authority["interface"] = INTERFACE
    entry = DisputeEntry.model_validate({
        **authority,
        "advertisement": {"mechanisms": ["arkhai.payments.v1"],
                          "minimum_dispute_window_seconds": 60,
                          "minimum_case_hold_seconds": 60},
    })
    disputes = RegistryDisputePolicy.from_document({"Dispute": [entry.model_dump(mode="json")]})
    config = ArkhaiPaymentsConfig(
        enabled=True, service_url="http://127.0.0.1:9", development_auth=True,
        service_identity=SERVICE.identity, fee_bps=250,
    )
    ready = asyncio.run(arkhai_payments_preflight(config, {}, "seller"))
    if not ready.ready:
        raise RuntimeError("offline payment policy is not ready")
    clause = SettlementPublicationClause.model_validate({
        "mechanism": "arkhai.payments.v1", "asset": "USD/2", "per": "unit", "rate": "100",
        "mechanism_input": {"payee_account": PAYEE, "asset": "USD/2", "window": "P7D",
                            "dispute_window_seconds": 604800, "case_hold_max_seconds": 7200},
    })
    resources = {"publication_clause": clause, "dispute_authorities": disputes.for_publication(),
                 "dispute_interfaces": frozenset({INTERFACE})}

    def build(**changes):
        return arkhai_payments_option_builder(config, ready, {**resources, **changes}, "seller")

    option = build()["settlement_options"][0]
    print("publication: ready, option-owned adjudication, first compatible authority")
    if build(dispute_authorities=())["settlement_options"]:
        raise RuntimeError("empty dispute policy published an option")
    print("empty authority policy: no hosted option")
    incompatible = entry.model_copy(update={"advertisement": entry.advertisement.model_copy(
        update={"mechanisms": ["example.payment.v1"]})})
    refused("wrong mechanism advertisement", lambda: build(dispute_authorities=(incompatible,)))
    refused("uninstalled dispute interface", lambda: build(dispute_interfaces=frozenset()))
    short = clause.model_copy(update={"mechanism_input": {**clause.mechanism_input, "case_hold_max_seconds": 0}})
    refused("zero cap below minimum", lambda: build(publication_clause=short))
    validate_payment_lifecycle(option, authorities=(entry,), dispute_interfaces=frozenset({INTERFACE}))
    impostor = entry.model_copy(update={"origin": "https://another-dispute.example"})
    refused("unaccepted full authority identity", lambda: validate_payment_lifecycle(
        option, authorities=(impostor,), dispute_interfaces=frozenset({INTERFACE})))

    instant = datetime.fromtimestamp(NOW, timezone.utc).isoformat()
    agreement = Agreement(
        negotiation_id="offline-lifecycle", listing_id="offline-listing", listing_hash="a" * 64,
        buyer=SERVICE.identity.model_dump(mode="json"), seller=NEXT.identity.model_dump(mode="json"),
        settlement=option, settlement_params={"payer_account": PAYER}, amount="100", asset="USD/2",
        duration_seconds=3600, accepted_at=instant, start_utc=instant,
        provision_terms={"kind": "example.v1", "version": 1, "payload": {}},
    )
    terms = agreement.model_dump(mode="json", exclude_none=True)
    data = PaymentSettlementData.for_agreement(terms, config)
    policy = mandate_policy_for_agreement(terms, config)
    print("prepaid term end:", derive_part_terms(policy, kind="once")["end"])
    print("setup end:", derive_part_terms(policy, kind="once", setup=True)["end"])
    early = policy.lifecycle.model_dump(mode="json", exclude_none=True)
    early["early_termination"] = {"version": 1, "entitlements": {
        "payer": {"notice_seconds": 0, "settles_through": "started_period"},
        "payee": {"notice_seconds": 120, "settles_through": "last_boundary"}},
        "settles_through": "last_boundary"}
    rate_policy = policy.model_copy(update={"lifecycle": LifecycleTerms.model_validate(early)})
    print("rate stop entries:", derive_part_terms(rate_policy, kind="rate")["authorities"]["stop"])
    print("setup beside rate rights:", derive_part_terms(rate_policy, kind="once", setup=True)["authorities"]["stop"])
    fake = FakePaymentsClient(signer=SERVICE)
    approval = PaymentApproval(config, PAYER, client_for_owner=fake)
    approval.approve(agreement.model_dump_json(exclude_none=True), data.to_wire())
    tampered = deepcopy(data.to_wire()["mandate"])
    tampered["parts"][0]["authorities"]["stop"].append(
        {"account": PAYEE, "notice": "PT0S", "partialPeriod": "charged"})
    refused("unentitled seller stop", lambda: approval.check(
        agreement.model_dump_json(exclude_none=True),
        {"mandate": tampered, "transaction_id": transaction_id(tampered)}))
    print("buyer approval: exact mandate accepted")

    signed = fake.get_transaction(data.transaction_id)
    expected = dict(mandate=data.mandate, agreement_json=terms, livemode=False)
    if not verify_snapshot(signed, config.receipt_trust, **expected):
        raise RuntimeError("valid snapshot refused")
    body = signed.snapshot.model_dump(mode="json", by_alias=True, exclude_none=True)
    edited = signed.model_dump(mode="json", by_alias=True, exclude_none=True)
    edited["snapshot"]["observedAt"] += 1
    normalized = signed.model_dump(mode="json", by_alias=True, exclude_none=True)
    normalized["snapshot"]["observedAt"] = str(normalized["snapshot"]["observedAt"])
    if (verify_snapshot(normalized, config.receipt_trust, **expected)
            or verify_snapshot(edited, config.receipt_trust, **expected)
            or verify_snapshot(sign_snapshot(NEXT, body), config.receipt_trust, **expected)
            or verify_snapshot(signed, config.receipt_trust, minimum_sequence=1, **expected)
            or verify_snapshot(signed, config.receipt_trust, **{**expected, "livemode": True})):
        raise RuntimeError("invalid snapshot accepted")
    rotation_at = signed.snapshot.observedAt - 1
    history = (ReceiptIdentity(identity=SERVICE.identity, valid_until=rotation_at, retiring=True),
               ReceiptIdentity(identity=NEXT.identity, valid_from=rotation_at))
    rotated = sign_snapshot(NEXT, body)
    if not verify_snapshot(rotated, history, **expected):
        raise RuntimeError("current-key attestation refused")
    if rotated.snapshot.receipt != signed.snapshot.receipt:
        raise RuntimeError("rotation rewrote the receipt")
    print("snapshots: valid accepted; tampered, wrong-key, mode-changed and regressing refused")
    print("rotation: bounded identity history accepted; original receipt retained")
    print("cleanup: no external resources created")


if __name__ == "__main__":
    main()
