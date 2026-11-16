"""The seller-preemption first use stays runnable as documented.

The example is the operator's entry point to the seller's notice on a lane-only
fixture; running its ``main`` here holds it to the seller half, the payments
fixtures and the typed lifecycle client as they are, rather than leaving a first
use that only fails when someone follows the instructions.
"""

import json
import runpy
from pathlib import Path

from market_arkhai_payments.contracts import get_contract

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "preempt_first_use.py"


def test_the_preemption_first_use_runs_on_its_lane_profile(tmp_path, capsys):
    example = runpy.run_path(str(EXAMPLE), run_name="preempt_first_use")
    output = tmp_path / "observations.json"
    example["main"](output, EXAMPLE.with_name("preempt.lane.toml"))
    observations = json.loads(output.read_text())
    assert observations["evidence_class"] == "lane-double evidence"
    assert observations["contract"] == get_contract().metadata
    assert [(step["control"], step["product"]) for step in observations["control_trace"]] == [
        ("fund", "spot"), ("fund", "on-demand"), ("lose_response", "spot"),
    ]
    assert observations["default_buyer"] == {"approved": ["on-demand", "spot"], "waivers": []}
    refusal = observations["charged_default_buyer"]
    assert "payee stop does not return" in refusal and "term end does not return" in refusal
    assert observations["charged_waived_buyer"]["approved"]
    assert observations["lost_response"]["outcome"]["status"] == "unknown"
    assert observations["same_key_retry"]["outcome"]["status"] == "accepted"
    assert observations["on_demand_refusal"]["outcome"]["status"] == "rejected"
    assert observations["wrong_actor"] == "403"
    assert json.loads(capsys.readouterr().out) == observations
