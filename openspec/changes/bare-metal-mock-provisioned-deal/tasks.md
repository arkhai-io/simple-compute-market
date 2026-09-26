# Tasks — bare-metal mock-provisioned deal

Design decided; not yet planned. Unblocked: `bare-metal-publication-reads-pool-declarations`,
which built the bare-metal end-to-end lane this change's scenario runs on, is complete.

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
      and integration suites, and the permanent documentation destinations. Include
      Section 3's migrated requirements in the plan.

## 3. Migrated deal requirements (added 2026-09-26; plan against in 1.5)

Verification of requirements migrated from `bare-metal-buyer-domain` and
`market-platform-bare-metal-10-storefront-composition` when those were archived. Each
is a scenario assertion in the mock-provisioned deal or a focused test beside it, and
each has a delta in `specs/buyer-orchestration/spec.md` or
`specs/test-compatibility/spec.md`.

- [ ] 3.1 **Demand is exact and buyer-bounded.** `market bare-metal buy` with a
      private key, an `access_ref`, or any site/pool/resource/host/executor/price/
      deadline override fails before negotiation and records no run event; a valid
      demand emits the canonical `bare_metal.v1` envelope with no seller-owned field.
      The scenario's existing forbidden-flag list is the starting point.
- [ ] 3.2 **A provisioning route offered to the buyer is refused.** A listing,
      response, configuration value, or argument attempting to make a provisioning
      URL, site credential, provider identifier, or direct executor operation
      authoritative is rejected; the buyer uses only the recorded storefront authority.
- [ ] 3.3 **Result and evidence decode strictly.** Public result/evidence carrying a
      password, bearer token, private key, connection endpoint, raw executor result,
      provider field, or unrecognized property is rejected and never displayed,
      persisted, or captured in a diagnostic; access data returned without a valid
      response proof from the recorded storefront is rejected and not cached.
- [ ] 3.4 **Teardown is authenticated and idempotent.** Repeating `teardown --from`
      after a lost response resumes or returns the same operation with no second
      physical teardown; status distinguishes requested, running, complete,
      failed/operator-action, and lease-already-expired; a run principal that does not
      authorize the agreement's teardown is refused and not retried elsewhere;
      capacity is released exactly once at the site.
- [ ] 3.5 **Restart recovery.** Holding the storefront's loops with the pause control,
      restart the storefront after settlement commit and again after teardown
      acceptance; on resume the buyer retrieves the same operation with no second
      obligation, mechanism selection, or teardown. Duplicate polling and duplicate
      result reads are idempotent.
- [ ] 3.6 **Pause survives restart.** An authenticated pause remains active across a
      storefront restart and new negotiations are refused until an authenticated
      resume. (From `bare-metal-10`'s pre-fulfillment protocol requirement, the only
      part of it that outlived fulfillment being composed.)

## 2. Closeout

- [ ] 2.1 The closeout task defined in `openspec/README.md#plan-closeout-requirements`,
      expanded when the plan is written.
