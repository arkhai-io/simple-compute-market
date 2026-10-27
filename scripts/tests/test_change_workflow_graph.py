"""The workflow's graph is one table: every exit and remedy names a node of it, and
every node is reached from design and leads on until the change is done."""

from __future__ import annotations

import pytest

from change_workflow import graph
from change_workflow.common import STEPS
from change_workflow.graph import (ARCHIVE_CLEANUP, DESIGN, NODES, OWNER, TABLE, WAIT,
                                   Node)

EXITS = [(declaration.node, exit_) for declaration in TABLE for exit_ in declaration.exits]


def test_each_node_is_declared_once() -> None:
    assert len(NODES) == len(TABLE)


@pytest.mark.parametrize("source,exit_", EXITS, ids=lambda value: getattr(value, "label", ""))
def test_every_exit_names_a_node(source: Node, exit_: graph.Exit) -> None:
    assert exit_.target in NODES, f"{source.label} exits to {exit_.target.label}"


def test_every_join_waits_on_nodes() -> None:
    joins = {exit_.join for _, exit_ in EXITS if exit_.join}

    assert joins
    for join in joins:
        for what, node in join.waits_for:
            assert node in NODES, f"{what} is supplied by {node.label}"


def test_every_guards_remedy_is_a_node_or_the_owner() -> None:
    # A remedy no step runs is waiting: the clone's bootstrap finishes by itself.
    for source, exit_ in EXITS:
        for guard in exit_.guards:
            assert guard.remedy in NODES or guard.remedy in (OWNER, WAIT), (
                f"{source.label} → {exit_.target.label}: {guard.condition}")


def test_every_node_is_reachable_from_design() -> None:
    # A node is reached by an exit to it, as a guard's remedy on an exit, or as a
    # supplier of the join an exit waits on: each is a way the computation names it.
    reached, frontier = {DESIGN}, [DESIGN]
    while frontier:
        for exit_ in NODES[frontier.pop()].exits:
            remedies = [g.remedy for g in exit_.guards if isinstance(g.remedy, Node)]
            suppliers = [node for _, node in exit_.join.waits_for] if exit_.join else []
            for node in [exit_.target, *remedies, *suppliers]:
                if node not in reached:
                    reached.add(node)
                    frontier.append(node)

    assert reached == set(NODES)


def test_every_node_has_an_exit_but_the_one_that_finishes_the_change() -> None:
    assert [d.node for d in TABLE if not d.exits] == [ARCHIVE_CLEANUP]


def test_every_logged_step_is_a_step_the_wrapper_runs() -> None:
    assert {d.runs for d in TABLE if d.runs} <= set(STEPS)


def test_a_return_and_another_round_are_chosen_among_a_triages_exits() -> None:
    assert [e.target for e in graph.exits(graph.DESIGN_TRIAGE, when=graph.RETURN)] == [DESIGN]
    assert not graph.exits(graph.CLOSEOUT_TRIAGE, when=graph.RETURN)
    assert [e.target for e in graph.exits(graph.PRE_CLOSEOUT_TRIAGE,
                                          when=graph.ANOTHER_ROUND)] == [
        graph.PRE_CLOSEOUT_REVIEW]


def test_the_phases_read_from_the_table() -> None:
    assert graph.phase_steps("planning") == ("plan",)
    assert set(graph.phase_steps("closeout")) == {"closeout", "review", "triage", "validate",
                                                   "archive-cleanup"}
    assert graph.review_phase("pre-closeout") == "implementation"
    assert graph.review_phase("owner") is None


def test_a_node_names_its_step_and_a_reviews_kind() -> None:
    assert graph.PRE_CLOSEOUT_REVIEW.label == "review:pre-closeout"
    assert graph.PRE_CLOSEOUT_REVIEW.result("why") == {
        "step": "review", "kind": "pre-closeout", "reason": "why"}
    # A triage triages whatever records await it, so its result names no kind.
    assert graph.CLOSEOUT_TRIAGE.result("why") == {"step": "triage", "reason": "why"}
