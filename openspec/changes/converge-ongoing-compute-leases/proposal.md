## Why

Once a deal can be billed per period, nothing in either compute storefront keeps it
converged after commitment. A storefront verifies approval before delivery and then
stops watching: no loop follows the transaction's funding, no stop at the payment
authority reaches the lease, a failed or late delivery leaves money and hardware in
different states, and evidence that arrives after an end has nowhere to go. Both
compute storefronts need durable servicing across outages, failed delivery and late
evidence, and a buyer's protection has to rest on authority records, held earnings and
kept signed bytes even when the seller is dishonest or absent.

## What Changes

- The foundation's end service in `kit/deal-servicing` gains independent physical and
  authority queues in one loop-controller step: physical work, bounded authority work,
  then a second physical pass for ends that became due.
- Each deal carries two durable completion facts — physical, proved by capacity
  release, and financial, scoped to an end revision — and the seller's lifecycle read
  and list expose them, the gaps between them, pending work and repair reasons. End
  intent is not release proof; an audited administrator acknowledgement can close the
  physical fact when no authenticated release proof will come.
- The foundation's delivery authorization protocol is composed with spot's rate
  adapter: the lease is activated before billing starts, end service alone journals
  the billing-start key, and the delivery path's checkpoint keeps a reference to it.
- Funding is a renewable timer: at expiry the loop reads the payment authority and
  ends on the bare timer only when the authority is unreachable or unverifiable. Ends
  the terms do not entitle are filed as the seller's self-penalty through the dispute
  adapter; a buyer's `end_delivery` and an authority's stop are never seller
  self-penalties.
- Earlier evidence becomes revision-bound dispute work through the dispute adapter's
  mapping and verified prior ruling effects, never a seller-direct stop or reverse and
  never local end-pricing arithmetic; the payment authority computes each stopper's
  partial-period term, and setup is owed from approval and returns only on the
  seller's non-delivery.
- Operator recovery is stateless: a seller-authenticated evidence export and an
  immutable command envelope drive the injected adapters, with no offline second
  storefront database writer. The site-report ingestion and the buyer's stop, hint,
  end-now and fallback paths are the foundation's and are consumed as they are.
- This change owns the complete rate lane matrix, including spot's prepared
  maximum-term and emergency entry points and the delivery path's rate drives. Lane
  pause and resume qualify network effects; production-application integration
  rebuilds prove durable restart.

## Capabilities

### Modified Capabilities

- `deal-lifecycle`: end-service queues, completion, timer classification, hook and
  effect integration, diagnostics and recovery commands; the foundation introduces
  this capability.
- `settlement-servicing`: adapter-mediated lifecycle journals admitted without a
  ledger.
- `market-composition`: the neutral storefront loop and coherent startup and
  withdrawal.
- `test-compatibility`: the consolidated rate matrix, restart jurisdiction and lane
  time.

### New Capabilities

None.

## Dependencies and scope

Depends on `agreed-evidence-and-early-termination` (lifecycle and adapter
contracts), `spot-deals-through-arkhai-payments` (rate mechanics) and
`unify-compute-delivery-path` (the delivery path, hook seam, activation and
undelivered handoff), each as a whole change. Scenario execution needs the runnable
payment and mediation doubles from `add-arkhai-payments-lane-double`. Hosted
enablement is `activate-per-period-compute-servicing`'s.

The seller's exceptional end is a journaled dispute filing, not a direct payment
effect; mediation alone rules the qualifying payee self-penalty mechanically; seller
stop entries exist only for entitlements such as spot's notice, and a spot emergency
files the same case. `end_delivery` supplies signed receipt evidence only; the buyer
half owns the payment stop and its same-key retry, and billing continues until that
stop lands.

This change owns no payment arithmetic, mandate codec, authority policy, buyer-half
implementation, site renewal or hosted deployment. Started-period settlement is a
payment term, not a local correction. Notice belongs to the selected stop entry, with
no waiver and no payer early release. Servicing latency and reserve-ahead sizing are
the seller's risk choices, not buyer billing promises or codec gates.

## Impact

`kit/deal-servicing`'s state, loop, adapter composition and recovery runner; both
storefront composition roots and their domain physical ports; the seller lifecycle
contracts and client (the evidence export and the audited local recovery command);
the compute delivery path's reference to the shared start journal; both lanes'
scenario stages and fixtures. Mechanism and dispute operations stay in the injected
`kit/arkhai-payments` and `kit/arkhai-mediation` adapters. No runtime changes at
this design stage.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — composition and authority boundaries
- [x] Existing subsystem specification: `deal-lifecycle` (foundation prerequisite),
  `settlement-servicing`, `market-composition`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- End-service behaviour and the guarantee's limits — `deal-lifecycle` spec and
  architecture companion.
- The adapter-journal exception to retryable settlement — `settlement-servicing`
  spec.
- Composition ownership and startup coherence — `market-composition` spec.
- Scenario jurisdiction and lane time — `test-compatibility` spec.
- Neutral ownership and mechanism-owned adapter continuation — `ARCHITECTURE.md`.
- At closeout: Goal 8 and campaign dependency currency, and the nine diagram pairs
  promoted to `docs/development/diagrams/`; the three further matrix rows are
  qualified without duplicate diagrams.
