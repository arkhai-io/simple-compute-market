"""Unit tests for the run-log inspection helpers used by resume.

Covers two pure-Python functions in ``market_buyer.groups._deal``:

- ``load_negotiation_resume_point(run_id)`` rebuilds the
  ``NegotiationResumePoint`` from a JSONL run-log: seller url, listing
  id, neg id, transcript, last seller price, rounds completed.
- ``is_negotiation_complete(run_id)`` says whether the log already
  contains an ``agreed`` outcome.

Both read on-disk JSONL via the ``RunLog`` API. We point the runs
directory at ``tmp_path`` with ``XDG_STATE_HOME`` so the tests are
hermetic — no global mutation, no real ``~/.local/state``.

The tests deliberately exercise the resume contract from the
producer side too: they use ``RunLog`` to write events and then read
back through the helpers, so a future schema change in the JSONL
shape breaks tests immediately rather than at runtime.
"""

from __future__ import annotations

import pytest
import typer

from market_buyer.run_log import RunLog
from market_buyer.groups._deal import (
    is_negotiation_complete,
    load_deal_context,
    load_negotiation_resume_point,
)


@pytest.fixture(autouse=True)
def _isolated_runs_dir(tmp_path, monkeypatch):
    """Pin the run-log directory at tmp_path for every test."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    yield


# ---------------------------------------------------------------------------
# load_negotiation_resume_point
# ---------------------------------------------------------------------------


def test_load_resume_point_recovers_neg_id_and_seller_price():
    log = RunLog.start(seller_url="http://seller:8001", listing_id="L-1")
    log.event(
        "negotiation_round",
        round=0,
        our_message={"action": "initial", "proposal": {"fields": {"amount": 50}}},
        their_reply={"negotiation_id": "neg-9", "action": "counter", "proposal": {"fields": {"amount": 90}}},
    )

    point = load_negotiation_resume_point(log.run_id)

    assert point.seller_url == "http://seller:8001"
    assert point.listing_id == "L-1"
    assert point.negotiation_id == "neg-9"
    assert point.last_seller_proposal["fields"]["amount"] == 90
    assert point.rounds_completed == 1
    # Transcript is two NegotiationRound entries (us + them) per round.
    assert len(point.transcript) == 2
    assert point.transcript[0].sender == "us"
    assert point.transcript[1].sender == "them"
    assert point.transcript[1].proposal["fields"]["amount"] == 90


def test_load_resume_point_uses_latest_seller_counter_across_rounds():
    """When the log has multiple counter rounds, last_seller_proposal
    is the most recent counter (not the first)."""
    log = RunLog.start(seller_url="http://s", listing_id="L")
    log.event("negotiation_round", round=0,
              our_message={"action": "initial", "proposal": {"fields": {"amount": 30}}},
              their_reply={"negotiation_id": "neg-A", "action": "counter", "proposal": {"fields": {"amount": 95}}})
    log.event("negotiation_round", round=1,
              our_message={"action": "counter", "proposal": {"fields": {"amount": 60}}},
              their_reply={"action": "counter", "proposal": {"fields": {"amount": 80}}})
    log.event("negotiation_round", round=2,
              our_message={"action": "counter", "proposal": {"fields": {"amount": 70}}},
              their_reply={"action": "counter", "proposal": {"fields": {"amount": 75}}})

    point = load_negotiation_resume_point(log.run_id)

    assert point.last_seller_proposal["fields"]["amount"] == 75
    assert point.rounds_completed == 3
    # 3 rounds * 2 entries = 6 transcript items
    assert len(point.transcript) == 6


def test_load_resume_point_terminal_seller_reply_does_not_overwrite_price():
    """When the seller's last reply was terminal (accept/exit),
    last_seller_proposal should reflect the previous counter — the
    round-loop needs a `their_proposed_price` to feed the strategy."""
    log = RunLog.start(seller_url="http://s", listing_id="L")
    log.event("negotiation_round", round=0,
              our_message={"action": "initial", "proposal": {"fields": {"amount": 50}}},
              their_reply={"negotiation_id": "neg-T", "action": "counter", "proposal": {"fields": {"amount": 80}}})
    # Suppose the buyer crashed mid-write of round 1: the reply was
    # an accept echo with price=70, but no run_ended yet.
    log.event("negotiation_round", round=1,
              our_message={"action": "counter", "proposal": {"fields": {"amount": 70}}},
              their_reply={"action": "accept", "proposal": {"fields": {"amount": 70}}})

    point = load_negotiation_resume_point(log.run_id)

    # The accept-reply has price=70 but action=accept, so we don't
    # treat it as a counter. last_seller_proposal stays at the prior 80.
    assert point.last_seller_proposal["fields"]["amount"] == 80
    assert point.negotiation_id == "neg-T"


def test_load_resume_point_picks_up_negotiation_id_from_run_ended():
    """When the run ended cleanly with negotiation_id but never had
    explicit negotiation_round events (rare; fast accept), the
    negotiation_id can still be recovered from run_ended."""
    log = RunLog.start(seller_url="http://s", listing_id="L")
    # No rounds, but run_ended carries the neg_id
    log.event("negotiation_round", round=0,
              our_message={"action": "initial", "proposal": {"fields": {"amount": 50}}},
              their_reply={"negotiation_id": "neg-from-end", "action": "counter", "proposal": {"fields": {"amount": 60}}})
    log.end("agreed", negotiation_id="neg-from-end", agreed_amount=60, rounds=0)

    point = load_negotiation_resume_point(log.run_id)
    assert point.negotiation_id == "neg-from-end"
    assert point.last_status == "agreed"


def test_load_resume_point_missing_run_log_raises():
    with pytest.raises(typer.BadParameter, match="No run-log"):
        load_negotiation_resume_point("does-not-exist")


def test_load_resume_point_missing_negotiation_id_raises():
    """A log with no rounds and no neg_id can't be resumed."""
    log = RunLog.start(seller_url="http://s", listing_id="L")
    # No negotiation_round events written.
    with pytest.raises(typer.BadParameter, match="negotiation_id"):
        load_negotiation_resume_point(log.run_id)


def test_load_resume_point_missing_seller_url_raises():
    """A log without seller_url in run_started can't be resumed (we
    don't know who to POST to)."""
    log = RunLog.start(listing_id="L-1")  # no seller_url
    log.event("negotiation_round", round=0,
              our_message={"action": "initial", "proposal": {"fields": {"amount": 50}}},
              their_reply={"negotiation_id": "neg-1", "action": "counter", "proposal": {"fields": {"amount": 80}}})
    with pytest.raises(typer.BadParameter, match="seller_url"):
        load_negotiation_resume_point(log.run_id)


# ---------------------------------------------------------------------------
# is_negotiation_complete
# ---------------------------------------------------------------------------


def test_is_negotiation_complete_false_for_mid_stream_run():
    log = RunLog.start(seller_url="http://s", listing_id="L")
    log.event("negotiation_round", round=0,
              our_message={"action": "initial", "proposal": {"fields": {"amount": 50}}},
              their_reply={"negotiation_id": "neg-1", "action": "counter", "proposal": {"fields": {"amount": 90}}})
    assert is_negotiation_complete(log.run_id) is False


def test_is_negotiation_complete_true_for_agreed_negotiation_completed():
    """`market buy`-style log ends with negotiation_completed agreed."""
    log = RunLog.start()
    log.event("negotiation_completed", status="agreed", agreed_amount=80)
    assert is_negotiation_complete(log.run_id) is True


def test_is_negotiation_complete_true_for_agreed_run_ended():
    """`market negotiate`-style log ends with run_ended status=agreed."""
    log = RunLog.start()
    log.end("agreed", negotiation_id="neg-1", agreed_amount=70, rounds=2)
    assert is_negotiation_complete(log.run_id) is True


def test_is_negotiation_complete_false_for_exited_negotiation():
    log = RunLog.start()
    log.event("negotiation_completed", status="exited", reason="ceiling")
    log.end("exited")
    assert is_negotiation_complete(log.run_id) is False


def test_is_negotiation_complete_false_for_missing_log():
    """Non-existent run-id is treated as 'not complete' rather than
    raising — the caller in `buy --from` then triggers the resume
    path which raises with a clearer error."""
    assert is_negotiation_complete("ghost-run") is False


# ---------------------------------------------------------------------------
# load_deal_context
# ---------------------------------------------------------------------------


def test_load_deal_context_recovers_accepted_proposal_and_demands():
    recipient = "0x" + "ab" * 20
    token = "0x" + "cd" * 20
    proposal = {
        "chain_name": "anvil",
        "escrow_address": "0x" + "ef" * 20,
        "fields": {"token": token},
        "literal_fields": {"token": token},
        "demands": [{
            "chain_name": "anvil",
            "arbiter": "0x" + "12" * 20,
            "demand_data": {"recipient": recipient},
        }],
        "expiration_unix": 1_800_000_000,
    }
    provision = {"duration_seconds": 3600, "ssh_public_key": "ssh-ed25519 AAAA"}
    log = RunLog.start(seller_url="http://s", listing_id="L")
    log.event(
        "negotiation_completed",
        status="agreed",
        agreed_amount=80,
        negotiation_id="neg-1",
        listing_id="L",
        accepted_escrow_proposal=proposal,
        accepted_provision_terms=provision,
    )

    deal = load_deal_context(log.run_id)

    assert deal.accepted_escrow_proposal == proposal
    assert deal.accepted_provision_terms == provision
    assert deal.seller_wallet_address == recipient
    assert deal.token_contract == token
