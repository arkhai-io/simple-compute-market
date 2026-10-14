# Tasks — share site projection state

Design phase; not planned. Carved out of `kit-owned-listing-and-fulfillment-lifecycles`
on 2026-10-14 as the prerequisite of `unbacked-bare-metal-listings`.

## 1. Design

- [x] 1.1 **Decision gate.** Record the carve-out and its direction. Decided with the
      maintainer: bare metal shares VM's projection state and publication loop through
      the kit, as a prerequisite change, rather than adding a version watch to bare
      metal's publication ("A prerequisite, carved out of the kit lifecycle change";
      "Bare metal publishes on the same loop controller as VM").
- [ ] 1.2 **Decision gate.** Decide each open question in `design.md` and record the
      decision there.
- [ ] 1.3 Plan the implementation, naming the files each decision touches, the
      focused, integration, and end-to-end suites, and the permanent documentation
      destinations.

## 2. Closeout

- [ ] 2.1 The closeout task defined in
      `openspec/README.md#plan-closeout-requirements`, written out in full when this
      change is planned.
