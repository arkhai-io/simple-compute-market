# Tasks

## Status: discuss phase only — no implementation tasks yet

This change captures design decisions and open questions carried forward
from POOLS-7 Section 11's code review (see `design.md`). Nothing here has
an implementation plan yet. Before any task list is written:

1. Resolve the open question in `design.md`: does `offering_type` need to
   exist on the wire today, or is domain-boundary routing sufficient
   until a shared cross-domain capacity endpoint exists?
2. Confirm the final `requirements` shape with whatever
   `pools-8-capacity-projection-and-listing-hints` lands for claim
   construction, so the shape isn't designed twice.
3. Decide the `capacity.probe(requirement=...)` vs. `capacity.probe(claim=...)`
   question in `design.md`'s unresolved-questions section — additive
   parameter, or a rename with a compatibility window.
4. Scope the `"required_attributes"` wire-key rename precisely (every
   consumer named in `proposal.md`'s Impact section) before committing to
   a rename timeline — this is the one piece of this change with real
   external-compatibility risk; everything else is additive.

Once those are resolved, this file gets a real plan phase: sections for
the domain-layer `requirements` parser (VM first), the shared
matching-contract confirmation (should not need to change), the
`offering_type` field (if accepted), and the staged wire-key
compatibility migration (if accepted).

That plan must end with the seven-part closeout task defined in
`openspec/README.md#plan-closeout-requirements`. No closeout section appears here
because that requirement attaches when implementation is planned, and this change
has no implementation plan yet.
