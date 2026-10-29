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
- Compose foundation's neutral authorization protocol with spot's rate adapter. Activate
  before billing start, with one end-service-owned operation key and a delivery
  checkpoint reference. Consume the unified path's admission/disclosure guarantees.
- Keep funding renewable until expiry, read payments at expiry, and end on the bare timer only when
  unreachable/unverifiable. Consume foundation self-penalty dispute filings for unentitled ends;
  buyer end_delivery and authority stops do not become seller self-penalties.
- Reconcile earlier evidence through dispute-adapter revised requests and verified
  prior ruling effects, never seller-direct stop/reverse or local end-pricing arithmetic. Payments compute each
  stopper's partial-period term; setup once ends at activation.
- Supply retained seller evidence export and immutable command envelopes for
  stateless operator authority recovery through injected adapters, never an
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
Seller exceptional_end is a journaled dispute filing, not direct payment effects.
Mediation alone mechanically rules qualifying payee self-penalty; seller entries
exist only for entitlements such as spot notice, and spot emergency files that case.
No seller restitution entry or several-stop-entries payments dependency is needed.
end_delivery supplies signed receipt evidence only; buyer half owns payment stop
and same-key outage retry, and billing continues until that stop lands.

This change owns no payment arithmetic, mandate codec, authority policy, buyer-half
implementation, site renewal or hosted deployment. Started-period settlement is
expressed by payment terms, not corrected locally. Notice belongs to the selected
explicit stop entry; no waiver or payer early release is assumed. Servicing latency
and reserve-ahead sizing are seller
risk recommendations, not buyer billing promises or codec gates.

## Impact

Planned code: kit/deal-servicing state, loop, adapter composition and recovery runner;
both storefront composition roots and domain physical ports; seller lifecycle
contracts/client export and audited local recovery command; compute delivery's
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
three additional matrix rows without duplicating diagrams.
