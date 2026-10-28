"""The change-workflow architecture's diagram of the graph, held to the table.

The architecture shows `change-workflow-graph.svg`, laid out by hand in draw.io and
exported with its source embedded, so it also opens in draw.io; the source,
`change-workflow-graph.drawio` beside it, is what is held to the table: each box by
its id with the lines of its text, and each edge by its source, target, and label,
an edge's guard numbers written out from the drawing's legend (`drawn`). Layout is
never compared, so the drawing can be rearranged freely. The export is never edited
by hand: draw.io draws its visible part from the source it embeds, and a test holds
that copy equal to the source, so an export not redone after the source changed is
caught there.

`make change-graph` reports where the source departs from the table (`drift`), which
is what whoever redraws it after a change to the table needs. See
openspec/specs/change-workflow/architecture.md, "Routing is code, with the model as
backstop".
"""

from __future__ import annotations

import collections
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence

from change_workflow import graph
from change_workflow.common import ROOT

DIAGRAMS = Path("docs/development/diagrams")
SOURCE = DIAGRAMS / "change-workflow-graph.drawio"
EXPORT = DIAGRAMS / "change-workflow-graph.svg"
# The legend of guards, which an edge names by number, `G6` or `G7 · G8`.
_LEGEND = "guards"
_GUARD = re.compile(r"^G(\d+): (.*)$")
_GUARDS = re.compile(r"^G\d+(?: · G\d+)*$")

Drawn = tuple[dict[str, tuple[str, ...]], collections.Counter]


def _lines(value: str) -> tuple[str, ...]:
    return tuple(re.sub(r"</?b>", "", line).strip() for line in value.split("<br>"))


def drawn(source: str) -> Drawn:
    """What a draw.io file draws: its boxes by id, each the lines of its text, and
    its edges, each its source, target, and label, the legend's guards written out
    for their numbers."""
    vertices, edges = {}, []
    for cell in ET.fromstring(source).iter("mxCell"):
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


def expected(table: Sequence[graph.Declaration] = graph.TABLE) -> Drawn:
    """What the table says the diagram draws, in `drawn`'s terms."""
    boxes, edges = graph.drawing(table)
    return boxes, collections.Counter((e.source, e.target, e.pieces) for e in edges)


def drift(source: str, table: Sequence[graph.Declaration] = graph.TABLE) -> list[str]:
    """How the diagram drawn in `source` departs from the table: each box or edge
    one draws and the other does not; empty when it draws the table."""
    (boxes, edges), (want_boxes, want_edges) = drawn(source), expected(table)
    problems = [f"box {id_} reads {boxes.get(id_)!r} where the table has {text!r}"
                for id_, text in want_boxes.items() if boxes.get(id_) != text]
    problems += [f"box {id_} is no node of the table" for id_ in boxes.keys() - want_boxes]
    problems += [f"no edge draws {edge}" for edge in want_edges - edges]
    problems += [f"the edge {edge} is not the table's" for edge in edges - want_edges]
    return problems


def main(source: Path = ROOT / SOURCE,
         table: Sequence[graph.Declaration] = graph.TABLE) -> int:
    problems = drift(source.read_text("utf-8"), table)
    shown = source.relative_to(ROOT) if source.is_relative_to(ROOT) else source
    if not problems:
        print(f"{shown} draws the table.")
        return 0
    print(f"{shown} departs from the table; redraw it, and export its SVG from it "
          "with the source embedded:")
    print("".join(f"- {problem}\n" for problem in problems), end="")
    return 1


if __name__ == "__main__":
    sys.exit(main())
