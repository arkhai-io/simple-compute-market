"""The workflow's graph is one table: every exit and remedy names a node of it, and
every node is reached from design and leads on until the change is done. Its
Mermaid rendering draws every node, exit, join, and guard, and the hand-laid diagram
the change-workflow architecture shows, with the source its export embeds, draws
the table's boxes and edges."""

from __future__ import annotations

import collections
import dataclasses
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from change_workflow import graph
from change_workflow.common import STEPS
from change_workflow.graph import (ARCHIVE_CLEANUP, CLOSEOUT_TRIAGE, DESIGN, NODES, OWNER,
                                   TABLE, WAIT, Node)

ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE = Path("openspec/specs/change-workflow/architecture.md")
DIAGRAMS = Path("docs/development/diagrams")
SOURCE = DIAGRAMS / "change-workflow-graph.drawio"
EXPORT = DIAGRAMS / "change-workflow-graph.svg"
# The legend of guards, which an edge names by number, `G6` or `G7 · G8`.
_LEGEND = "guards"
_GUARD = re.compile(r"^G(\d+): (.*)$")
_GUARDS = re.compile(r"^G\d+(?: · G\d+)*$")

EXITS = [(declaration.node, exit_) for declaration in TABLE for exit_ in declaration.exits]

Drawn = tuple[dict[str, tuple[str, ...]], collections.Counter]


def _lines(value: str) -> tuple[str, ...]:
    return tuple(re.sub(r"</?b>", "", line).strip() for line in value.split("<br>"))


def drawn(source: str) -> Drawn:
    """What a draw.io file draws: its boxes by id, each the lines of its text, and
    its edges, each its source, target, and label, the legend's guards written out
    for their numbers."""
    cells = ET.fromstring(source).iter("mxCell")
    vertices, edges = {}, []
    for cell in cells:
        if cell.get("vertex") == "1":
            vertices[cell.get("id")] = _lines(cell.get("value", ""))
        elif cell.get("edge") == "1":
            edges.append((cell.get("source"), cell.get("target"), cell.get("value", "")))
    legend = {match[1]: match[2] for line in vertices.pop(_LEGEND, ())
              if (match := _GUARD.match(line))}
    drawn_edges: collections.Counter = collections.Counter()
    for source_, target, value in edges:
        pieces: list[str] = []
        for line in (_lines(value) if value else ()):
            pieces += ([legend.get(number[1:], number) for number in line.split(" · ")]
                       if _GUARDS.match(line) else [line])
        drawn_edges[(source_, target, tuple(pieces))] += 1
    return vertices, drawn_edges


def expected(table=TABLE) -> Drawn:
    boxes, edges = graph.drawing(table)
    return boxes, collections.Counter((e.source, e.target, e.pieces) for e in edges)


def drift(source: str, table=TABLE) -> str | None:
    """How the diagram drawn in `source` departs from the table: each box or edge
    one draws and the other does not."""
    (boxes, edges), (want_boxes, want_edges) = drawn(source), expected(table)
    problems = [f"box {id_} reads {boxes.get(id_)!r} where the table has {text!r}"
                for id_, text in want_boxes.items() if boxes.get(id_) != text]
    problems += [f"box {id_} is no node of the table" for id_ in boxes.keys() - want_boxes]
    problems += [f"no edge draws {edge}" for edge in want_edges - edges]
    problems += [f"the edge {edge} is not the table's" for edge in edges - want_edges]
    if not problems:
        return None
    return (f"{SOURCE} departs from the table: " + "; ".join(problems) + "; redraw it, "
            f"with `make change-graph` printing the table, and export {EXPORT} from it")


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
    assert [d.node for d in TABLE if not d.exits] == [graph.DONE]
    assert [e.target for e in NODES[ARCHIVE_CLEANUP].exits] == [graph.DONE]
    # No step runs once the change is done.
    assert NODES[graph.DONE].runs is None


def _entry(node: Node) -> list[str]:
    return [guard.condition for guard in NODES[node].entry]


def test_the_entry_guards_are_the_tables() -> None:
    # The archive both ways: no entry returns an archived change to an earlier
    # phase, and none takes a change not archived past it.
    for node in (DESIGN, graph.PLAN, graph.ROUND):
        assert _entry(node) == ["the change is not archived"]
    for node in (graph.CLOSEOUT_REVIEW, ARCHIVE_CLEANUP):
        assert _entry(node) == ["the change is archived"]
    awaits = "a review of its kind, or a validation after it, awaits triage"
    assert _entry(CLOSEOUT_TRIAGE) == ["the change is archived", awaits]
    for node in (graph.DESIGN_TRIAGE, graph.IMPLEMENTATION_TRIAGE, graph.PRE_CLOSEOUT_TRIAGE):
        assert _entry(node) == [awaits]
    # Closeout is the step that archives.
    assert _entry(graph.CLOSEOUT) == []
    assert _entry(graph.VALIDATE) == ["it carries a target that is a node"]
    assert _entry(graph.DONE) == ["reached only by archive cleanup's exit"]
    (validated,) = NODES[graph.PRE_CLOSEOUT_REVIEW].entry
    assert validated.waivable and validated.check is None
    assert not any(guard.waivable for d in TABLE for guard in d.entry
                   if d.node != graph.PRE_CLOSEOUT_REVIEW)


ACTIVE = graph.Standing(archived=False, awaiting=frozenset({"design"}))
ARCHIVED = graph.Standing(archived=True, awaiting=frozenset())


@pytest.mark.parametrize("target,standing,refused", [
    ({"step": "design"}, ACTIVE, None),
    ({"step": "design"}, ARCHIVED, "design's entry guard (the change is not archived)"),
    ({"step": "archive-cleanup"}, ACTIVE, "archive-cleanup's entry guard (the change is "
                                          "archived) is not met: the change is not archived"),
    ({"step": "triage", "kind": "design"}, ACTIVE, None),
    ({"step": "triage", "kind": "implementation"}, ACTIVE,
     "no implementation review, and no validation after it, awaits triage"),
    ({"step": "validate", "target": {"step": "archive-cleanup"}}, ACTIVE,
     "archive-cleanup's entry guard"),
    ({"step": "review", "kind": "pre-closeout"}, ACTIVE, None),
    ({"step": "done"}, ARCHIVED, "reached only by archive cleanup's exit"),
], ids=str)
def test_a_direction_is_refused_by_an_unwaivable_entry_guard_of_a_node_it_names(
        target: dict, standing: graph.Standing, refused: str | None) -> None:
    found = graph.entry_refusal(target, standing, directed=True)

    assert found is None if refused is None else refused in (found or "")


def test_a_steps_exit_is_checked_against_its_targets_entry_guards_alone() -> None:
    # Archive cleanup's exit enters done; a validation's own exit is checked on its
    # target, not the target it nests, since that review may not be published yet.
    assert graph.entry_refusal({"step": "done"}, ARCHIVED, directed=False) is None
    assert graph.entry_refusal({"step": "validate", "target": {"step": "triage",
                                                               "kind": "implementation"}},
                               ACTIVE, directed=False) is None


def test_a_target_names_its_node() -> None:
    assert graph.node_of({"step": "triage", "kind": "pre-closeout"}) == graph.PRE_CLOSEOUT_TRIAGE
    assert graph.node_of({"step": "implement", "sections": [[5]]}) == graph.ROUND
    assert graph.node_of({"step": "validate", "target": {"step": "round"}}) == graph.VALIDATE
    assert graph.node_of({"step": "done"}) == graph.DONE
    with pytest.raises(graph.TargetError, match="kind of review it triages"):
        graph.node_of({"step": "triage", "kind": None})
    with pytest.raises(graph.TargetError, match="an object naming its step"):
        graph.node_of("review:design")


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


def test_a_node_names_its_step_and_its_kind() -> None:
    assert graph.PRE_CLOSEOUT_REVIEW.label == "review:pre-closeout"
    assert graph.PRE_CLOSEOUT_REVIEW.result("why") == {
        "step": "review", "kind": "pre-closeout", "reason": "why"}
    # A triage names the kind of review it triages.
    assert graph.CLOSEOUT_TRIAGE.result("why") == {"step": "triage", "kind": "closeout",
                                                   "reason": "why"}
    assert graph.CLOSEOUT.result("why") == {"step": "closeout", "reason": "why"}


# The diagram.

def _node_id(node: Node) -> str:
    return node.label.replace(":", "_").replace("-", "_")


def test_the_diagram_draws_every_node_exit_join_and_guard() -> None:
    rendering = graph.mermaid()
    edges = [line.strip() for line in rendering.splitlines() if "-->" in line]
    joins = {exit_.join for _, exit_ in EXITS if exit_.join}

    boxes = {line.split("[", 1)[0].strip(): line for line in rendering.splitlines()
             if line.endswith('"]')}
    for node, declaration in NODES.items():
        box = boxes[_node_id(node)]
        assert box.startswith(f'    {_node_id(node)}["{node.label}')
        assert all(f"<br/>entry: {guard.condition}" + (" (waivable)" if guard.waivable else "")
                   in box for guard in declaration.entry)
    assert rendering.count('{{"join"}}') == len(joins)
    assert len(edges) == len(EXITS) + len(joins)
    for source, exit_ in EXITS:
        target = f"join_{_node_id(exit_.target)}" if exit_.join else _node_id(exit_.target)
        supplied = [what for what, node in exit_.join.waits_for
                    if node == source] if exit_.join else []
        held = [" (held)" for guard in exit_.guards if guard.held]
        pieces = [*supplied, *([exit_.when] if exit_.when else []), *held,
                  *(f"{guard.condition} ⇒ {getattr(guard.remedy, 'label', guard.remedy)}"
                    + (f", {guard.otherwise}" if guard.otherwise else "")
                    for guard in exit_.guards)]
        assert any(edge.startswith(f"{_node_id(source)} -->") and edge.endswith(f" {target}")
                   and all(piece in edge for piece in pieces) for edge in edges), (
            f"no edge draws {source.label} → {exit_.target.label} with {pieces}")


def test_the_diagrams_ids_are_distinct_and_its_labels_need_no_escaping() -> None:
    labels = [node.label for node in NODES] + [
        guard.condition for declaration in TABLE for guard in declaration.entry] + [
        text for _, exit_ in EXITS
        for text in [exit_.when or "", *(guard.condition for guard in exit_.guards),
                     *(guard.otherwise or "" for guard in exit_.guards)]]

    assert len({_node_id(node) for node in NODES}) == len(NODES)
    assert not [label for label in labels if '"' in label or "|" in label]


def test_the_documented_diagram_draws_the_table() -> None:
    problem = drift((ROOT / SOURCE).read_text("utf-8"))

    assert problem is None, problem


def test_the_export_embeds_the_diagram_it_draws() -> None:
    # A draw.io export carries its source, so it opens in draw.io too.
    exported = ET.parse(ROOT / EXPORT).getroot().get("content")

    assert exported is not None
    assert drawn(exported) == drawn((ROOT / SOURCE).read_text("utf-8"))


def test_the_architecture_shows_the_export_and_names_its_source() -> None:
    document = (ROOT / ARCHITECTURE).read_text("utf-8")
    to_diagrams = "../../../" + DIAGRAMS.as_posix()

    assert f"]({to_diagrams}/{EXPORT.name})" in document
    assert f"]({to_diagrams}/{SOURCE.name})" in document
    assert "```mermaid" not in document


def test_a_table_with_an_added_exit_no_longer_matches_the_diagram() -> None:
    table = [dataclasses.replace(d, exits=d.exits + (graph.Exit(DESIGN, when=graph.RETURN),))
             if d.node == CLOSEOUT_TRIAGE else d for d in TABLE]

    problem = drift((ROOT / SOURCE).read_text("utf-8"), table)

    assert problem is not None
    assert "no edge draws ('triage_closeout', 'design', ('a return',))" in problem
    assert "make change-graph" in problem


def test_a_drift_names_each_box_and_edge_that_differs() -> None:
    source = ('<mxfile><mxCell id="design" vertex="1" value="&lt;b&gt;design&lt;/b&gt;"/>'
              '<mxCell id="extra" vertex="1" value="x"/>'
              '<mxCell id="guards" vertex="1" value="G1: a guard"/>'
              '<mxCell edge="1" source="design" target="extra" value="advance&lt;br&gt;G1"/>'
              '</mxfile>')

    problem = drift(source)

    assert problem is not None
    assert "box design reads ('design',) where the table has" in problem
    assert "box extra is no node of the table" in problem
    assert "the edge ('design', 'extra', ('advance', 'a guard')) is not the table's" in problem
    assert "no edge draws ('design', 'review_design', ())" in problem


def test_make_change_graph_prints_the_rendering() -> None:
    # A make that runs these tests passes its flags down through MAKEFLAGS; none
    # may reach the target run here.
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL")}
    printed = subprocess.run(["make", "-s", "--no-print-directory", "change-graph"], cwd=ROOT,
                             env=environment, capture_output=True, text=True, check=True)

    assert printed.stdout == graph.mermaid()
