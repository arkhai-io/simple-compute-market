## Why

`AGENTS.md`'s "Diagrams" rule keeps each diagram's `.drawio` source beside its `.svg`
export, and the change-workflow README says the graph diagram's SVG is exported from
its source in draw.io and never edited by hand. Nothing in the repository renders a
`.drawio` file: no target or script exports one, and no development environment
provides a renderer. So an export is either made by hand in draw.io desktop, outside
any recorded step, or edited by hand — and the graph diagram's export has been: its
visible drawing was hand-written SVG while its embedded source carried the same
edits. The tests hold the graph's source to the workflow table and the export's
embedded copy to the source, but not the visible drawing, so a hand edit that draws
otherwise than the source passes every check. `merge-after-archive`'s closeout review
found this (its finding F2); the owner directed that diagrams be re-rendered from
their sources rather than hand-edited, and that the rendering support be its own
change. A re-render of the graph's export was tried there and not committed, since
neither renderer tried kept the labels as plain text, so this change re-renders it.

## What Changes

- A make target renders each `.drawio` source in the repository to the `.svg` beside
  it, with the source embedded, so an export is reproducible by any session or
  developer.
- A pinned renderer: draw.io desktop's own export command, run headless, either
  installed in the development environment or from a container image pinned by
  digest.
- Re-render every diagram whose export was edited by hand, the change-workflow
  diagrams first, and the graph's among them. Until then the change-workflow README's
  statement that the graph's export is never edited by hand is untrue of it.
- State: **proposed; design not started.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None expected until design settles it, so `.openspec.yaml` sets `skip_specs`.
`change-workflow`'s CW-66kx changes if design makes the rendered export, not only its
embedded source, what a test holds to the table; design then adds that delta and
clears `skip_specs`.

## Non-Goals

- Do not lay diagrams out automatically: layouts stay hand-laid in the `.drawio`
  source, as `AGENTS.md`'s "Diagrams" rule says.
- Do not change what any diagram draws.

## Open questions

- The renderer: draw.io desktop's CLI (an Electron app, needing a virtual display
  headless) installed in the development environment, or a container image wrapping
  it, pinned by digest — and what the unattended steps' table must admit to run it.
  The container `rlespinasse/drawio-desktop-headless` (v1.75.0) renders an export
  whose labels are PNG images rather than text: the graph's SVG grew from 59 KB to
  1.9 MB, its text no longer selectable or searchable. An export from the online
  draw.io keeps its labels as `foreignObject` text but pairs each with a PNG fallback
  in a `<switch>`: 969 KB, about 839 KB of it PNGs. The renderer and its settings
  must be shown to keep labels as text at a size near the hand-kept export's, or
  that trade-off accepted.
- Whether a check compares each committed `.svg` with a fresh rendering of its
  source, and where it runs, given that the renderer is heavier than the rest of
  `make test`; or whether only the export target exists.
- Whether active changes' diagrams (`converge-ongoing-compute-leases`) are rendered
  by this change or by their own when they next edit them.

## Dependencies and Related Changes

- Follows `merge-after-archive` (archived), whose closeout review's finding F2 this
  owns: `openspec/changes/archive/2026-11-10-merge-after-archive/tasks.md`, task 5.3's
  note.

## Impact

The root `Makefile` or the change workflow's make fragment, the development
environment or a pinned container image, every `diagrams/*.svg` under `docs/` and
`openspec/`, and possibly `scripts/tests/test_change_workflow_graph.py`. No runtime
behaviour changes. Should design place the target in the change workflow's make
fragment, the target is a new public interface of the workflow engine, added
compatibly; design names it, and any other engine interface it changes, with its
compatibility (CW-c2tw).

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — to be confirmed in design
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- How a diagram is rendered, and the target that renders it — `AGENTS.md`'s
  "Diagrams" and the change-workflow README's paragraph on the graph diagram.
