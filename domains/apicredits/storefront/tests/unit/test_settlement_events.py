"""The API-credit storefront's servicing-event callback writes a ``claims``
stage event. That the composition hands it to its worker is shown in
``tests/integration/test_settlement_events.py``."""

from __future__ import annotations

import json
import logging

from apicredits_storefront.settlement_composition import record_servicing_event


def test_a_servicing_event_is_recorded_as_a_claims_stage_event(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="stage"):
        record_servicing_event(
            "settlement_retry",
            {"obligation_ref": "obligation-1", "operation": "fulfill", "error": "boom"},
        )

    [entry] = [json.loads(r.getMessage()) for r in caplog.records if r.name == "stage"]
    assert (entry["stage"], entry["event"], entry["obligation_ref"]) == (
        "claims",
        "settlement_retry",
        "obligation-1",
    )
