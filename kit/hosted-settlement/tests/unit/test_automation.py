from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from hosted_settlement_client import FundingMode, FundingProfile
from market_hosted_settlement import (
    AuthorizationReservationConflict,
    AuthorizationReservationJournal,
    AutomationCandidate,
    AutomationPolicyRefused,
    OffSessionPolicy,
    ReservationState,
    evaluate_off_session_policy,
)
from market_identity import Identity, IdentityScheme


BUYER = Identity(scheme=IdentityScheme.ED25519, identifier="Yg" + "E" * 41)
SELLER = Identity(scheme=IdentityScheme.ED25519, identifier="cw" + "I" * 41)


def _policy(**updates) -> OffSessionPolicy:
    values = {
        "enabled": True,
        "authority_id": "hosted-a",
        "environment": "test",
        "funding_profile": FundingProfile.CARD,
        "currency": "usd",
        "max_purchase_minor_units": 75,
        "max_aggregate_minor_units": 100,
        "window_seconds": 3600,
        "seller_principals": (SELLER,),
    }
    values.update(updates)
    return OffSessionPolicy(**values)


def _candidate(*, amount: int = 60) -> AutomationCandidate:
    return AutomationCandidate(
        authority_id="hosted-a",
        environment="test",
        funding_profile=FundingProfile.CARD,
        currency="usd",
        amount=amount,
        seller_principal=SELLER,
        mode=FundingMode.SAVED_INSTRUMENT,
        binding_ready=True,
        instrument_ready=True,
        mandate_or_consent_ready=True,
    )


def _fingerprint(byte: str) -> str:
    return "sha256:" + byte * 64


def test_policy_is_disabled_by_default_and_every_exact_bound_is_enforced() -> None:
    disabled = evaluate_off_session_policy(
        OffSessionPolicy(),
        _candidate(),
        aggregate_reserved_minor_units=0,
    )
    assert (disabled.allowed, disabled.reason) == (False, "disabled")

    assert evaluate_off_session_policy(
        _policy(), _candidate(), aggregate_reserved_minor_units=40
    ).allowed
    bounded = evaluate_off_session_policy(
        _policy(), _candidate(), aggregate_reserved_minor_units=41
    )
    assert (bounded.allowed, bounded.reason) == (
        False,
        "aggregate_bound_exceeded",
    )
    with pytest.raises(ValueError, match="every exact bound"):
        OffSessionPolicy(enabled=True)


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"authority_id": "other"}, "authority_mismatch"),
        ({"environment": "live"}, "environment_mismatch"),
        ({"funding_profile": FundingProfile.US_ACH_DEBIT}, "profile_mismatch"),
        ({"amount": 76}, "purchase_bound_exceeded"),
        ({"seller_principal": BUYER}, "seller_excluded"),
        ({"mode": FundingMode.INTERACTIVE}, "mode_not_saved"),
        ({"binding_ready": False}, "binding_unready"),
        ({"instrument_ready": False}, "instrument_unready"),
        ({"mandate_or_consent_ready": False}, "consent_unready"),
    ],
)
def test_policy_rejects_each_exact_candidate_bound(updates, reason: str) -> None:
    decision = evaluate_off_session_policy(
        _policy(),
        _candidate().model_copy(update=updates),
        aggregate_reserved_minor_units=0,
    )
    assert (decision.allowed, decision.reason) == (False, reason)


def test_journal_exact_retry_changed_reuse_and_release(tmp_path) -> None:
    journal = AuthorizationReservationJournal((tmp_path / "journal.json").absolute())
    first = journal.reserve(
        policy=_policy(),
        candidate=_candidate(),
        marketplace_operation_id="op-1",
        input_fingerprint=_fingerprint("a"),
        expires_at_unix=2000,
        now_unix=1000,
    )
    retry = journal.reserve(
        policy=_policy(),
        candidate=_candidate(),
        marketplace_operation_id="op-1",
        input_fingerprint=_fingerprint("a"),
        expires_at_unix=2000,
        now_unix=1001,
    )
    assert retry == first
    with pytest.raises(AuthorizationReservationConflict):
        journal.reserve(
            policy=_policy(),
            candidate=_candidate(),
            marketplace_operation_id="op-1",
            input_fingerprint=_fingerprint("b"),
            expires_at_unix=2000,
            now_unix=1001,
        )
    journal.release(
        marketplace_operation_id="op-1",
        input_fingerprint=_fingerprint("a"),
    )
    assert journal.snapshot()[0].state is ReservationState.RELEASED


def test_authorized_spend_counts_after_obligation_expiry_for_policy_window(tmp_path) -> None:
    journal = AuthorizationReservationJournal((tmp_path / "journal.json").absolute())
    journal.reserve(
        policy=_policy(),
        candidate=_candidate(),
        marketplace_operation_id="op-1",
        input_fingerprint=_fingerprint("a"),
        expires_at_unix=1010,
        now_unix=1000,
    )
    journal.record_authorized(
        marketplace_operation_id="op-1",
        input_fingerprint=_fingerprint("a"),
        funding_authorization_ref="fauth-safe-1",
    )
    with pytest.raises(AutomationPolicyRefused) as caught:
        journal.reserve(
            policy=_policy(),
            candidate=_candidate(),
            marketplace_operation_id="op-2",
            input_fingerprint=_fingerprint("b"),
            expires_at_unix=2000,
            now_unix=1100,
        )
    assert caught.value.decision.reason == "aggregate_bound_exceeded"


def test_expired_unacknowledged_reservation_no_longer_consumes_capacity(tmp_path) -> None:
    journal = AuthorizationReservationJournal((tmp_path / "journal.json").absolute())
    journal.reserve(
        policy=_policy(),
        candidate=_candidate(),
        marketplace_operation_id="op-1",
        input_fingerprint=_fingerprint("a"),
        expires_at_unix=1010,
        now_unix=1000,
    )
    second = journal.reserve(
        policy=_policy(),
        candidate=_candidate(),
        marketplace_operation_id="op-2",
        input_fingerprint=_fingerprint("b"),
        expires_at_unix=2000,
        now_unix=1100,
    )
    assert second.state is ReservationState.RESERVED


def test_concurrent_aggregate_reservation_admits_only_one(tmp_path) -> None:
    path = (tmp_path / "journal.json").absolute()

    def reserve(index: int) -> str:
        journal = AuthorizationReservationJournal(path)
        try:
            journal.reserve(
                policy=_policy(),
                candidate=_candidate(),
                marketplace_operation_id=f"op-{index}",
                input_fingerprint=_fingerprint(str(index)),
                expires_at_unix=2000,
                now_unix=1000,
            )
        except AutomationPolicyRefused:
            return "refused"
        return "reserved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, (1, 2)))
    assert sorted(results) == ["refused", "reserved"]
    assert path.read_text().count("instrument") == 0
