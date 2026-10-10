from dataclasses import replace

import pytest

from market_core import SettlementEvidence, SettlementStageTable


@pytest.mark.parametrize(
    "entries, message",
    [
        ([("example.v1", object()), ("example.v1", object())], "duplicate"),
        ([("", object())], "non-empty, trimmed"),
        ([(" ", object())], "non-empty, trimmed"),
        ([(" example.v1", object())], "non-empty, trimmed"),
        ([("example.v1", None)], "has no stage"),
    ],
)
def test_stage_table_rejects_ambiguous_or_incomplete_entries(entries, message):
    with pytest.raises(ValueError, match=message):
        SettlementStageTable(entries)


@pytest.mark.parametrize("pair_input", [False, True])
def test_stage_table_keeps_its_snapshot_when_composition_input_changes(pair_input):
    stage = object()
    entries = [("example.v1", stage)] if pair_input else {"example.v1": stage}
    table = SettlementStageTable(entries)
    entries.clear()

    assert table["example.v1"] is stage
    assert list(table) == ["example.v1"]
    assert len(table) == 1
    with pytest.raises(TypeError):
        table["example.v1"] = object()
    with pytest.raises(TypeError):
        del table["example.v1"]
    assert table["example.v1"] is stage


@pytest.mark.parametrize(
    "changed",
    [
        {"negotiation_id": "another-negotiation"},
        {"mechanism": "another.v1"},
        {"settlement_ref": "another-reference"},
        {"settlement_ref": None},
    ],
)
def test_evidence_identity_validation_refuses_retargeted_or_lost_identity(changed):
    accepted = {
        "negotiation_id": "negotiation-1",
        "mechanism": "example.v1",
        "settlement_ref": "reference-1",
    }
    evidence = SettlementEvidence(**accepted, status="domain-approved", evidence={})
    evidence.validate_identity(**accepted)
    with pytest.raises(ValueError, match="changed its"):
        replace(evidence, **changed).validate_identity(**accepted)
