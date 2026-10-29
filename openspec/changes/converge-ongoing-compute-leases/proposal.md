## Why

Rate mechanics alone do not converge delivery and payment after commitment. Both
compute storefronts need durable servicing across outages, failed delivery and late
evidence. Buyer protection rests on authority records, held earnings and kept signed
bytes even when the seller is dishonest or absent.

## What Changes

- Extend the foundation's end service in kit/deal-servicing with independent physical
  and authority queues in one controller step: physical, authority, second physical
  pass for newly due ends.
- Persist separate physical and revision-scoped financial completion. End intent
  is not release proof; lifecycle diagnostics and audited administrator recovery
  expose unfinished work without inventing money movement.
- Implement the neutral rate authorization hook through adapter decisions. Activate
  before billing start, with one end-service-owned operation key and a delivery
  checkpoint reference. Consume the unified path's admission/disclosure guarantees.
- Keep funding renewable until expiry, then classify against verified authority
  records before self-filing. Consume foundation self-filing for unentitled ends;
  buyer end_delivery and authority stops do not become seller self-penalties.
- Reconcile earlier evidence through revision-bound authority filings, not assumed
  append amendment or storefront end-refund arithmetic. Payments compute each
  stopper's partial-period term; setup once ends at activation.
- Supply stateless operator authority recovery through injected adapters, never an
  offline second storefront database writer. Consume foundation site-report ingestion
  and buyer stop/hint/end-now/fallback paths without reimplementing them.
- Own the complete rate lane matrix, including spot's prepared maximum-term and
  on-demand emergency entry points. Lane pause/resume qualifies network effects;
  production-application integration rebuilds prove durable restart.

## Capabilities

### Modified Capabilities

- `deal-lifecycle`: end-service queues, completion, timer classification, hook/effect
  integration, diagnostics and recovery commands; foundation introduces this capability.
- `settlement-servicing`: admit adapter-mediated lifecycle journals without a ledger.
- `market-composition`: neutral storefront loop and coherent startup/withdrawal.
- `test-compatibility`: consolidated rate matrix, restart jurisdiction and lane time.

### New Capabilities

None.

## Dependencies and scope

Foundation lifecycle/adapter contracts and spot's rate mechanics gate implementation.
Unify is a **section-level** dependency: its path/hook/activation sections (tasks 1–3)
feed converge implementation (tasks 1–3); rate qualification then feeds unify 4.4
and converge 4. Neither implementation waits for the other's archive. The campaign
index must record this in Notes, not retain a whole-change archive cycle. Double
runnable sections gate scenario execution only. Reverify contracts at each section
handoff. Hosted enablement belongs to activate-per-period-compute-servicing.

This change owns no payment arithmetic, mandate codec, authority policy, buyer-half
implementation, site renewal or hosted deployment. Started-period settlement is
expressed by payment terms, not corrected locally. Each party has one notice;
exposure_seconds is retired. Servicing latency and reserve-ahead sizing are seller
risk recommendations, not buyer billing promises or codec gates.

## Impact

Planned code: kit/deal-servicing state, loop, hook protocol and recovery runner;
both storefront composition roots and domain physical ports; compute delivery's
reference to the shared start journal; both lanes' scenario stages/fixtures.
Mechanism and dispute operations remain in injected kit/arkhai-payments and
kit/arkhai-mediation adapters. No runtime changes are made at this design stage.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — composition and authority boundaries
- [x] Existing subsystem specification: deal-lifecycle (foundation prerequisite),
  settlement-servicing, market-composition and test-compatibility
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

End-service behavior and guarantee limits go to deal-lifecycle spec/architecture.
The adapter-journal exception goes to settlement-servicing. Composition ownership
and startup coherence go to market-composition; scenario jurisdiction and time go
to test-compatibility. Repository architecture describes neutral ownership and
mechanism-owned adapter continuation. Closeout updates Goal 8/campaign dependencies
and promotes the nine illustrative diagram pairs; qualification also covers the
two additional matrix rows without duplicating diagrams.
