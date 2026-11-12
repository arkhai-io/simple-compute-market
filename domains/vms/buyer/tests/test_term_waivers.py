"""A VM run's default-refusal waivers reach the accepted Agreement's disclosure
before approval, and a resumed or recovered run reads them from its run log."""

from __future__ import annotations

import uuid

import pytest
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id

from arkhai_vms_buyer.deal_helpers import recorded_waivers
from arkhai_vms_buyer.run_log import RunLog
from arkhai_vms_buyer.settlement_composition import (
    disclose_accepted_agreement,
    listing_acceptance_validator,
)
from identity_helpers import BUYER_SIGNER, SELLER_SIGNER

_PROFILE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
# A fictional authority and accounts: the origin is a reserved name that
# resolves nowhere, and the accounts are placeholders for no real payer.
_DISPUTE = {
    "interface": "arkhai.mediation.v1", "origin": "https://mediation.invalid",
    "account": "11111111-1111-4111-8111-111111111111", "record_key": "fixture-record", "params": {},
}


def _no_deadline_option() -> SettlementOption:
    body = {
        "price": {"asset": "USD/6", "rates": [{"field": "amount", "per": "hour", "value": "1000000"}]},
        "settlement": {"schema": "arkhai.payments.v1",
                       "payee_account": "22222222-2222-4222-8222-222222222222"},
        "lifecycle": {"adjudication": {"version": 1, "dispute": _DISPUTE,
                                       "dispute_window_seconds": 120, "case_hold_max_seconds": None}},
    }
    return SettlementOption(option_id=derive_settlement_option_id(**body), **body)


def _agreement(option: SettlementOption) -> Agreement:
    return Agreement(
        negotiation_id="negotiation-1", listing_id="listing-1", listing_hash="0" * 64,
        buyer=BUYER_SIGNER.identity.model_dump(mode="json"),
        seller=SELLER_SIGNER.identity.model_dump(mode="json"),
        settlement=option, settlement_params={"payer_account": "buyer-account"},
        amount=1_000_000, asset=option.price_asset, duration_seconds=3600,
        start_utc="2030-01-01T00:00:00Z", accepted_at="2030-01-01T00:00:00Z",
    )


def test_the_accepted_disclosure_marks_the_refusal_the_run_waived(capsys):
    disclose_accepted_agreement(
        _agreement(_no_deadline_option()), waivers=frozenset({"no_delivery_deadline"}),
    )

    shown = capsys.readouterr().err
    assert ("Default buyer policy: a default buyer refuses this option: no delivery deadline; "
            "waived by --allow-no-delivery-deadline") in shown
    assert "Waivers in force: --allow-no-delivery-deadline (no delivery deadline)" in shown


def test_an_accepted_disclosure_without_waivers_names_none(capsys):
    disclose_accepted_agreement(_agreement(_no_deadline_option()))

    shown = capsys.readouterr().err
    assert "a default buyer refuses this option: no delivery deadline\n" in shown
    assert "Waivers in force" not in shown


def test_each_listing_s_validator_carries_the_run_s_waivers():
    validate = listing_acceptance_validator(None, waivers=frozenset({"no_penalty"}))(
        {"listing_id": "L-1"},
    )
    assert validate.keywords["waivers"] == frozenset({"no_penalty"})


@pytest.mark.parametrize(("recorded", "waivers"), [
    (["--allow-no-penalty", "--allow-charged-term-end"], frozenset({"no_penalty", "charged_term_end"})),
    ([], frozenset()),
    (None, frozenset()),
], ids=["two", "none", "not-recorded"])
def test_a_resumed_run_reads_the_waivers_its_run_log_recorded(tmp_path, monkeypatch, recorded, waivers):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    run = RunLog.start(
        profile_id=_PROFILE_ID, principal=BUYER_SIGNER.identity, command="market buy",
        **({"compute_term_waivers": recorded} if recorded is not None else {}),
    )

    assert recorded_waivers(run.run_id, signer=BUYER_SIGNER) == waivers


def test_a_run_log_recording_an_unknown_waiver_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    run = RunLog.start(
        profile_id=_PROFILE_ID, principal=BUYER_SIGNER.identity, command="market buy",
        compute_term_waivers=["--allow-everything"],
    )

    with pytest.raises(ValueError, match="unknown recorded waivers"):
        recorded_waivers(run.run_id, signer=BUYER_SIGNER)
