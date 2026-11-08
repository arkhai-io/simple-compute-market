"""A buyer purchase's command runs in the background from its commit to its end.

``Purchase03`` starts the domain's purchase command in the background and waits
only for its commit, stopping a run that never commits; ``Purchase09`` waits for
the command to end once the settlement reads ready and hands what it recorded to
the domain's driver. Against a fake run and driver, since the command and the
services it reaches are the end-to-end lanes'.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from tests.e2e.roles.helpers.buyer_purchase_stages import (
    Purchase03_Bought,
    Purchase09_PurchaseRunEnded,
    PurchaseState,
)


def _driver() -> MagicMock:
    driver = MagicMock()
    driver.buy_arguments.return_value = ["buy"]
    driver.committed_event = "settlement_submitted"
    driver.buy_timeout_seconds = 12.0
    driver.buy_command = "market buy"
    return driver


def _bought_state() -> PurchaseState:
    return PurchaseState(
        domain_identity="purchase", seller_listing_id="listing", purchase_option_id="option", _settlement_imminent=True,
    )


def test_the_purchase_command_runs_in_the_background_until_its_commit():
    cli, driver, state = MagicMock(), _driver(), _bought_state()
    run = cli.run.return_value
    Purchase03_Bought().test_p03_the_buyer_buys_through_its_cli(cli, driver, state)
    cli.run.assert_called_once_with(["buy"], background=True)
    assert [call.args for call in run.wait_for_event.call_args_list] == [
        ("payment_approved",), ("settlement_submitted",),
    ]
    run.terminate.assert_not_called()
    assert state.purchase_run is run


def test_a_purchase_command_that_never_commits_is_stopped():
    cli, driver, state = MagicMock(), _driver(), _bought_state()
    run = cli.run.return_value
    run.wait_for_event.side_effect = AssertionError("market exited rc=3")
    with pytest.raises(AssertionError, match="rc=3"):
        Purchase03_Bought().test_p03_the_buyer_buys_through_its_cli(cli, driver, state)
    run.terminate.assert_called_once_with()
    assert state.purchase_run is None


def test_a_payer_that_does_not_approve_is_named():
    cli, driver, state = MagicMock(), _driver(), _bought_state()
    state.payer_account = "acct_payer"
    run = cli.run.return_value
    run.run_id = "run-1"
    run.wait_for_event.side_effect = AssertionError("no payment_approved within 12s")
    with pytest.raises(AssertionError, match="run-1 recorded no payment approved by payer acct_payer"):
        Purchase03_Bought().test_p03_the_buyer_buys_through_its_cli(cli, driver, state)
    run.terminate.assert_called_once_with()


def _delivered_state(run) -> PurchaseState:
    return PurchaseState(
        domain_identity="purchase", purchase_run=run, negotiation_id="negotiation", settlement_id="transaction",
        fulfillment_id="fulfillment", settlement_status="ready",
    )


def test_the_ended_run_is_handed_to_the_driver():
    driver = _driver()
    run = MagicMock(run_id="run", returncode=0)
    ended = {"event": "run_ended", "run_id": "run", "negotiation_id": "negotiation",
             "status": "ready"}
    run.read_events.return_value = [{"event": "run_started", "run_id": "run"}, ended]
    state = _delivered_state(run)
    Purchase09_PurchaseRunEnded().test_p09_the_buyers_purchase_command_ended_successfully(
        driver, state,
    )
    driver.check_run_ended.assert_called_once_with(ended, state)


def test_a_purchase_command_still_running_after_delivery_fails_naming_it():
    driver = _driver()
    run = MagicMock(run_id="run")
    run.wait.side_effect = subprocess.TimeoutExpired("market", 30.0)
    run.events_or_empty.return_value = [{"event": "settlement_poll"}]
    with pytest.raises(AssertionError, match="market buy run run was still running"):
        Purchase09_PurchaseRunEnded().test_p09_the_buyers_purchase_command_ended_successfully(
            driver, _delivered_state(run),
        )
    driver.check_run_ended.assert_not_called()


def test_a_run_ended_for_another_negotiation_fails():
    driver = _driver()
    run = MagicMock(run_id="run", returncode=0)
    run.read_events.return_value = [
        {"event": "run_ended", "run_id": "run", "negotiation_id": "another"},
    ]
    with pytest.raises(AssertionError):
        Purchase09_PurchaseRunEnded().test_p09_the_buyers_purchase_command_ended_successfully(
            driver, _delivered_state(run),
        )
    driver.check_run_ended.assert_not_called()
