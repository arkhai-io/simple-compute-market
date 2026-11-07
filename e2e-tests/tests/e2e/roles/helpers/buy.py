"""A one-shot `market buy` stepped to `ready` with fulfillment convergence held.

A compute-lane scenario holds its provisioning service's fulfillment
convergence for the whole module, so a fulfillment becomes `active` only when a
stage advances convergence. A buy run in the foreground would block on its
settlement poll until a convergence cycle no one steps, so the buy runs in the
background and the helper steps the deal from the buyer's own run-log events and
the storefront's stage events, each wait bounded and each on an effect of the
buy's own requests (`docs/development/TESTING.md#the-discipline-every-scenario-follows`).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import pytest

from tests.e2e.roles.buyer_cli import MarketRun
from tests.e2e.roles.helpers.compute_deal import (
    advance_fulfillment_to,
    wait_for_stage_event,
)

log = logging.getLogger(__name__)

#: Discovery, every negotiation round, and the escrow's chain transaction.
ESCROW_TIMEOUT_SECONDS = 120.0
#: The buyer's signed settle request, which dispatches the fulfillment before
#: it answers.
SUBMIT_TIMEOUT_SECONDS = 60.0
STAGE_EVENT_TIMEOUT_SECONDS = 30.0
DRAIN_TIMEOUT_SECONDS = 30.0
#: The buyer's next settlement polls once the fulfillment is active.
READY_TIMEOUT_SECONDS = 60.0
EXIT_TIMEOUT_SECONDS = 20.0

#: Run-log fields safe to print into CI output, and sufficient to say what the
#: buy did. The whole event carries proposals, accepted terms and tenant
#: credentials; an assertion message is not the place for those.
_REPORTABLE_EVENT_FIELDS = (
    "event",
    "status",
    "reason",
    "error",
    "listing_id",
    "seller_url",
    "negotiation_id",
    "round",
    "rounds",
    "agreed_amount",
    "attempts",
)


def run_log_digest(run: MarketRun) -> str:
    """Summarize a `market buy` run-log for a failure message.

    `market buy` reports one aggregate reason for a buy that agreed with
    nobody, and stdout carries no per-candidate detail. The run-log does: the
    negotiation events say whether the buyer opened, what the seller answered,
    and what the outcome was. Read without waiting, since a failure being
    reported is not a reason to wait for a log that may never appear.
    """
    events = run.events_or_empty()
    if not events:
        return "run-log: none written"
    lines = []
    for event in events:
        fields = {
            key: event[key]
            for key in _REPORTABLE_EVENT_FIELDS
            if key in event and event[key] is not None
        }
        lines.append(" ".join(f"{k}={v!r}" for k, v in fields.items()))
    return "run-log events:\n  " + "\n  ".join(lines)


def _agreed_negotiation_id(run: MarketRun) -> str:
    """The negotiation the buy agreed, from its last agreed negotiation event.

    A buy may negotiate with several candidates before one agrees; the escrow
    it created is for the last agreement.
    """
    agreed = [
        event
        for event in run.events_or_empty()
        if event.get("event") == "negotiation_completed"
        and event.get("status") == "agreed"
        and event.get("negotiation_id")
    ]
    assert agreed, "the run-log records no agreed negotiation with an id"
    return str(agreed[-1]["negotiation_id"])


def buy_to_ready(
    buyer_cli,
    buy_args: Sequence[str],
    *,
    storefront_admin_client,
    storefront_client,
    provisioning_client,
    provisioning_test_client,
) -> tuple[MarketRun, dict[str, Any]]:
    """Run `market buy <buy_args>` in the background and step it to `ready`.

    The buy creates its escrow and submits its settlement, which dispatches the
    fulfillment; the helper then confirms the storefront logged that dispatch
    for the buy's negotiation, reads the fulfillment from the buyer-signed
    settle status, drains the mock provisioning job queue, advances
    convergence to `active`, and waits for the buy to end `ready` and exit 0.
    Returns the run and its terminal `run_ended` event.

    Requires the module to hold fulfillment convergence, and its lane's mock
    create rule armed without a pause. A step that stalls fails naming the step,
    with the buy's run-log events. However it ends, a buy still running is
    terminated and reaped before the helper returns, so a failed stage leaves no
    buyer polling the stack.
    """
    run = buyer_cli.run(["buy", *buy_args], background=True)
    step = "the run-log's escrow_created event"
    try:
        escrow = run.wait_for_event("escrow_created", timeout=ESCROW_TIMEOUT_SECONDS)
        escrow_uid = escrow.get("escrow_uid")
        assert escrow_uid, f"escrow_created carries no escrow_uid: {escrow!r}"

        step = "the run-log's settlement_submitted event"
        run.wait_for_event("settlement_submitted", timeout=SUBMIT_TIMEOUT_SECONDS)

        step = "the run-log's agreed negotiation"
        negotiation_id = _agreed_negotiation_id(run)

        step = "the storefront's provision/job_submitted event for the buy's negotiation"
        wait_for_stage_event(
            storefront_admin_client,
            "provision",
            "job_submitted",
            negotiation_id=negotiation_id,
            timeout=STAGE_EVENT_TIMEOUT_SECONDS,
        )

        step = "the fulfillment id in the buyer's settle status"
        status = storefront_client.get_settle_status(str(escrow_uid))
        fulfillment_id = status.fulfillment_id
        assert fulfillment_id, f"the settle status names no fulfillment: {status!r}"

        step = "draining the mock provisioning job queue"
        provisioning_test_client.drain(timeout=DRAIN_TIMEOUT_SECONDS)

        step = f"advancing fulfillment {fulfillment_id} to active"
        advance_fulfillment_to(provisioning_client, fulfillment_id, "active")

        step = "the run-log's run_ended event with status ready"
        terminal = run.wait_for_event("run_ended", timeout=READY_TIMEOUT_SECONDS)
        assert terminal.get("status") == "ready", (
            f"the buy ended {terminal.get('status')!r}, reason {terminal.get('reason')!r}"
        )

        step = "the buy's exit"
        returncode = run.wait(timeout=EXIT_TIMEOUT_SECONDS)
        assert returncode == 0, f"`market buy` exited {returncode} after ending ready"

        log.info(
            "[buy] run %s ready: escrow=%s negotiation=%s fulfillment=%s",
            run.run_id, escrow_uid, negotiation_id, fulfillment_id,
        )
        return run, terminal
    except (Exception, pytest.fail.Exception) as exc:
        # Reading a running process's streams would wait for it to exit, so
        # they are reported only for a buy that has already exited.
        streams = (
            f"stdout (tail): {run.stdout()[-1500:]}\nstderr (tail): {run.stderr()[-1500:]}\n"
            if run.exited else ""
        )
        raise AssertionError(
            f"`market buy` stalled at {step}: {exc}\n{streams}{run_log_digest(run)}"
        ) from exc
    finally:
        if not run.exited:
            run.terminate()
