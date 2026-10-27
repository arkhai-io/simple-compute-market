"""The consume refusals are the API-credits service's recorded refusal bodies."""

import json
from pathlib import Path

from arkhai_api_contracts.models import ConsumeRefusal
from arkhai_api_contracts.refusals import CONSUME_REFUSALS

BASELINE = Path(__file__).resolve().parents[5] / "domains" / "apicredits" / "service" / "tests" / "fixtures" / "baseline"
REFUSALS = json.loads((BASELINE / "refusals.json").read_text(encoding="utf-8"))
RECORDED = {name: refusal for name, refusal in REFUSALS.items() if name.startswith("consume_")}


def test_every_recorded_consume_refusal_is_a_refusal_body_with_a_declared_reason():
    for name, refusal in RECORDED.items():
        body = refusal["body"]
        assert set(body) == set(ConsumeRefusal.model_fields), name
        assert ConsumeRefusal.model_validate(body).error in CONSUME_REFUSALS, name


def test_every_declared_reason_is_recorded():
    assert sorted(refusal["body"]["error"] for refusal in RECORDED.values()) == sorted(CONSUME_REFUSALS)
