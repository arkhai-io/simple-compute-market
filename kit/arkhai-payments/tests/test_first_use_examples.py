"""The kit's in-process first-use examples stay runnable as documented.

``make first-use`` and ``make first-use-rate`` run these examples against the
kit's invocation-owned authority fixture. Running each ``main`` here holds them
to the adapter, the presets and the fixtures as they are, rather than leaving a
first use that only fails when someone follows the instructions.
"""

import asyncio
import json
import runpy
from pathlib import Path

from market_arkhai_payments.contracts import get_contract

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def run(name: str, capsys) -> dict:
    example = runpy.run_path(str(EXAMPLES / f"{name}.py"), run_name=name)
    asyncio.run(example["main"]())
    return json.loads(capsys.readouterr().out)


def test_the_rate_first_use_is_labelled_lane_double_evidence(capsys):
    observations = run("rate", capsys)
    assert observations["evidence_class"] == "lane-double evidence"
    assert observations["double_selector"] == "in-process" and observations["livemode"] is False
    assert observations["contract"] == get_contract().metadata
    assert observations["buyer_waivers"] == []
    assert [(step["control"], step.get("seconds")) for step in observations["control_trace"]] == [
        ("lose_response", None), ("advance_clock", 1), ("advance_clock", 29),
    ]
    setup, rate = observations["mandate"]["mandate"]["parts"]
    assert (setup["kind"], setup["asset"], setup["amount"]) == ("once", "USD/6", "250000")
    assert (rate["kind"], rate["asset"], rate["amount"]) == ("rate", "USD/6", "1000000")
    assert (observations["lost_start_response"], observations["same_key_retry"]) == ("unknown", "accepted")
    assert observations["ended"]["state"] == "ended"


def test_the_once_lifecycle_first_use_runs(capsys):
    observations = run("lifecycle", capsys)
    assert (observations["initial"], observations["replay"]) == ("unknown", "accepted")
    assert observations["recorded_reverses"] == 1 and observations["total_voluntary_reverses"] == 2
    # The lost refund answer is retried, and the replay after a crash refunds nothing twice.
    assert observations["unreported_refund_reconciliation"] == ["RefundUnavailable", "Refunded", "Refunded"]
