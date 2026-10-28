"""An unattended step's outcome conforms to its schema."""

from __future__ import annotations

from pathlib import Path

import pytest

from change_workflow.common import StepError
from change_workflow.log import record_outcome
from change_workflow.outcome import harness_schema, load_schema, outcome_problems
from change_workflow_fixtures import COMMIT, VALID, clock, log_file

# Step outcomes as a workflow log carries them, without the fields the wrapper adds
# around them.
EXAMPLE_OUTCOMES = [
    {"outcome": "returned", "next": {"step": "design"},
     "message": "The patch has no provider field; refusing it needs a decision the "
                "design does not make.",
     "evidence": "the section's notes"},
    {"outcome": "question",
     "message": "Helm part failed: a retained volume carries resource-policy keep. Remedy: "
                "delete it.",
     "awaiting": "environmental remedy"},
]
REQUIRED = {"finished": ["next"], "question": ["awaiting"],
            "returned": ["next", "evidence"], "blocked": ["blocked_on"],
            "stopped": ["reason", "denials"]}


@pytest.mark.parametrize("outcome", EXAMPLE_OUTCOMES, ids=lambda o: o["outcome"])
def test_the_designs_example_outcomes_conform(outcome: dict) -> None:
    assert outcome_problems(outcome) == []


@pytest.mark.parametrize("kind", sorted(VALID))
def test_each_outcome_conforms_with_its_own_fields(kind: str) -> None:
    assert outcome_problems(VALID[kind]) == []


@pytest.mark.parametrize("kind,field", [(kind, field) for kind, fields in REQUIRED.items()
                                        for field in fields + ["message"]])
def test_each_outcome_requires_its_fields(kind: str, field: str) -> None:
    outcome = {key: value for key, value in VALID[kind].items() if key != field}

    assert outcome_problems(outcome) == [f"outcome has no {field}"]


def test_an_unknown_outcome_is_rejected() -> None:
    problems = outcome_problems({"outcome": "done", "message": "All done."})

    assert problems == ["outcome.outcome is 'done', not one of finished, question, returned, "
                        "blocked, stopped"]


def test_a_field_the_schema_does_not_define_is_rejected() -> None:
    outcome = {**VALID["finished"], "verdict": "fine"}

    assert outcome_problems(outcome) == [
        "outcome has verdict, which the schema does not define"]


def test_a_return_names_no_phase_beside_its_target() -> None:
    outcome = {**VALID["returned"], "return_to": "design"}

    assert outcome_problems(outcome) == [
        "outcome has return_to, which the schema does not define"]


def test_a_schema_keyword_the_check_cannot_enforce_fails_loudly() -> None:
    schema = {**load_schema(), "oneOf": []}

    with pytest.raises(StepError, match="oneOf"):
        outcome_problems(VALID["finished"], schema)


@pytest.mark.parametrize("type_", ["number", ["string", "null"]])
def test_a_schema_type_the_check_cannot_enforce_fails_loudly(type_) -> None:
    schema = {**load_schema(), "properties": {"message": {"type": type_}}}

    with pytest.raises(StepError, match="does not enforce"):
        outcome_problems({"message": "m"}, schema)


def test_a_plans_outcome_may_carry_the_rounds_its_cadence_maps(tmp_path: Path) -> None:
    planned = {**VALID["finished"], "rounds": [[[1, 2]], [[3], ["6a"]]]}

    line = record_outcome(log_file(tmp_path), "plan", planned, session="s", commit=COMMIT,
                          clock=clock)

    assert outcome_problems(planned) == []
    assert line["rounds"] == [[[1, 2]], [[3], ["6a"]]]


@pytest.mark.parametrize("rounds,problem", [
    ([], "fewer than 1"), ([[]], "fewer than 1"), ([[[]]], "fewer than 1"),
    ([[[True]]], "none of its allowed forms"), ([[[""]]], "none of its allowed forms"),
    ([[1, 2]], "not of type array"),
])
def test_a_malformed_mapping_of_rounds_is_rejected(rounds, problem: str) -> None:
    problems = outcome_problems({**VALID["finished"], "rounds": rounds})

    assert any(problem in found for found in problems), problems


# An exit is a target naming a node of the workflow graph.

@pytest.mark.parametrize("target", [
    {"step": "plan"}, {"step": "review", "kind": "pre-closeout"},
    {"step": "triage", "kind": "implementation"}, {"step": "round"},
    {"step": "implement", "sections": [["5"], [6]]},
    {"step": "validate", "target": {"step": "closeout"}},
    {"step": "validate", "target": {"step": "triage", "kind": "implementation"}},
    {"step": "done"},
], ids=lambda target: str(target))
def test_an_object_next_naming_a_node_is_accepted(target: dict) -> None:
    assert outcome_problems({**VALID["finished"], "next": target}) == []


def test_a_finished_step_saying_what_comes_next_in_words_is_refused() -> None:
    # What follows, in words, is the message's: `next` is only ever a target.
    assert outcome_problems({**VALID["finished"], "next": "the plan's next round"}) == [
        "outcome.next is not of type object"]


@pytest.mark.parametrize("target,problem", [
    ({"step": "review"}, "a review is a node only with the kind of review it is"),
    ({"step": "triage"}, "a triage is a node only with the kind of review it triages"),
    ({"step": "review", "kind": "owner"}, "review:owner is no node"),
    ({"step": "triage", "kind": "validation"}, "triage:validation is no node"),
    ({"step": "validate"}, "a validation names the target it is for"),
    ({"step": "validate", "target": {"step": "review"}}, "kind of review it is"),
    ({"step": "validate", "target": {"step": "validate", "target": {"step": "plan"}}},
     "other than another validation"),
    ({"step": "implement"}, "an implementation names its sessions"),
    ({"step": "plan", "kind": "design"}, "only a review or a triage names a kind"),
    ({"step": "plan", "sections": [[1]]}, "only an implementation names sections"),
    ({"step": "deploy"}, "'deploy' is no node"),
], ids=lambda value: str(value))
def test_an_object_next_naming_no_node_is_refused(target: dict, problem: str) -> None:
    problems = outcome_problems({**VALID["finished"], "next": target})

    assert len(problems) == 1 and problems[0].startswith("outcome.next names no node")
    assert problem in problems[0]


def test_an_empty_kind_is_refused_by_the_schema() -> None:
    problems = outcome_problems({**VALID["finished"], "next": {"step": "review", "kind": ""}})

    assert problems and "outcome.next" in problems[0] and "shorter than 1" in problems[0]


def test_a_return_names_the_step_it_returns_to() -> None:
    returned = {"outcome": "returned", "message": "Needs a decision.",
                "evidence": "the section's notes", "next": {"step": "design"}}

    assert outcome_problems(returned) == []
    # A return names its target as a node, never as words.
    assert outcome_problems({**returned, "next": "back to design"}) == [
        "outcome.next is not of type object"]
    assert outcome_problems({key: value for key, value in returned.items()
                             if key != "next"}) == ["outcome has no next"]
    # A phase is not a step: a return to planning names the plan.
    problems = outcome_problems({**returned, "next": {"step": "planning"}})
    assert len(problems) == 1 and problems[0].startswith("outcome.next names no node")


def test_a_triage_names_the_records_it_triaged_as_strings() -> None:
    triaged = {**VALID["finished"], "next": {"step": "plan"}, "triaged": ["13-design"]}

    assert outcome_problems(triaged) == []
    assert outcome_problems({**triaged, "triaged": [13]}) == [
        "outcome.triaged[0] is not of type string"]


def test_claude_code_is_given_no_top_level_combinator() -> None:
    schema = load_schema()
    given = harness_schema(schema)

    assert not {"allOf", "anyOf", "oneOf"} & given.keys()
    assert given == {key: value for key, value in schema.items() if key != "allOf"}
