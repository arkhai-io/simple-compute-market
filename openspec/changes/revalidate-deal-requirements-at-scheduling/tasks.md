# Tasks

## Status: discuss phase only — no implementation tasks yet

This change records a gap found while tracing an e2e capacity failure
(2026-08-11), together with the questions that decide its shape. Nothing here
has an implementation plan. Before a task list is written, resolve, in
`design.md`'s "Open Questions":

1. Which attributes of an admitted claim are commercially binding, and whether
   that set is structural or domain-declared.
2. Where the binding requirements live — the reservation row, the schedule
   request, or the existing opaque `deal_ref` mapping the scheduler already reads
   under a `requirements` key.
3. How a reservation admitted before this change is treated, so an absent
   requirement set reads as unconstrained rather than as an empty one.
4. Whether `resize_reservation`'s supersede carries the requirements forward.

Question 1 should be settled against `structured-capacity-requirements`'
vocabulary rather than ahead of it, so the binding set is named once.

Once those are resolved, this file gets a real plan: sections for what an
admitted reservation records, the scheduler's eligibility input, the distinct
shortfall outcome, the pre-existing-reservation compatibility path, and the
closeout task defined in `openspec/README.md#plan-closeout-requirements`.
