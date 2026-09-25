# Tasks — bare-metal mock-provisioned deal

Design decided; not yet planned. Blocked on `bare-metal-publication-reads-pool-declarations`,
which builds the bare-metal end-to-end lane this change's scenario runs on.

## 1. Design

- [x] 1.1 **Decision gate.** Decide where the bare-metal mock results live — in the mock
      Ansible service, or contributed by the bare-metal adapter — and record it in
      `design.md`.
- [x] 1.2 **Decision gate.** Establish which typed client drives the buyer's side of
      bare-metal fulfillment, result, access, and teardown, and record it.
- [x] 1.3 **Decision gate.** Decide whether the release-qualified real-host scenario stays
      parked or is removed, and record the consequence for the permanent protected-lane
      requirement.
- [x] 1.4 **Decision gate.** Decide which loops the lifecycle pause holds and which get a
      step, and record it.
- [ ] 1.5 Plan the implementation, naming the files each decision touches, the focused
      and integration suites, and the permanent documentation destinations.

## 2. Closeout

- [ ] 2.1 The closeout task defined in `openspec/README.md#plan-closeout-requirements`,
      expanded when the plan is written.
