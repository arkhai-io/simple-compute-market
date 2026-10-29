## Why

Rate-part mechanics alone do not end delivery when funding or a stop ends a deal.
VM and bare-metal storefronts need the same durable servicing of committed deals,
including failed delivery, restart, and a seller that learns late that service ended.
The buyer's protection must survive a dishonest or absent storefront: it rests on
the buyer's stop, held money, the dispute authority, and kept signed bytes, not a
seller's promise to keep a timer alive.

## What Changes

- Extend end service in `kit/deal-servicing` with rate-part servicing in both
  compute compositions. Its internal physical queue realizes the earliest final
  request; its authority-work queue drives observations and journaled lifecycle
  commands through injected payment and dispute adapters. Neither queue blocks the
  other's progress.
- Persist delivery/authority replay state and two separate completion facts.
  Report physical recovery still due and authority work still due; never infer
  financial completion from an ended lease.
- Implement the rate-part authorization hook in the unified delivery path, using
  the payment adapter's verified evidence before start and disclosure. Funding is
  a renewable local timer, not a lease truncation or a payee-advanced horizon.
- Journal `exceptional_end(at)` with an unentitled final request, including
  failed or never-started delivery at the deal's start. The dispute authority stops
  now and reverses earnings since the evidenced end; holds use
  `{afterStop: dispute_window}` and accepted cases extend protection.
- Compose the existing buyer flow: payer stop first, then `end_delivery {at}`;
  on payment-authority failure, `buyer_end(at)` and kept request/acknowledgement
  evidence. Site-signed `lease_ended` evidence is retained and returned to the buyer.
- Qualify the scenarios in both lanes against the in-lane payment and mediation
  doubles. Production remains gated by the hosted contract deployment, not a
  billing horizon.

## Capabilities

### Modified Capabilities

- `settlement-servicing`: rate-part end-service queues, completion, admission and recovery.
- `market-composition`: storefront-side servicing ownership and startup coherence.
- `test-compatibility`: both-domain, deterministically driven convergence scenarios.

### New Capabilities

None.

## Dependencies and scope

Implementation gates:
1. `agreed-evidence-and-early-termination`: lifecycle contracts, end service,
   evidence stores, buyer end flow, and dispute adapter.
2. `spot-deals-through-arkhai-payments`: rate-part mandate/mechanics, presets,
   option publication, verified snapshots, cumulative correction targets, half-open
   arithmetic, started-period treatment, notice command and identity re-anchoring.
3. `unify-compute-delivery-path`: one state machine, authorization phases,
   lease port, activation and undelivered path.

Scenario execution also requires `add-arkhai-payments-lane-double`'s payment
and mediation doubles. Production enablement belongs to
`activate-per-period-compute-servicing`. No dependency on the superseded
settle, publish/preempt or buyer-termination changes remains.

This change does not implement a payment ledger, adapter arithmetic, new wire
terms, the buyer half, or a site's renewable deadline. Seller site policies are
recommendations for its own operations, not guarantees to buyers. Presets may
charge a setup `once` part; there is no required minimum spend.

## Impact

Planned code: `kit/deal-servicing` (state, queues, loop), both storefront
compositions and their domain delivery ports, and both lanes' servicing scenarios.
Mechanism-specific operations remain in `kit/arkhai-payments`; dispute
requests remain in `kit/arkhai-mediation`, injected through lifecycle protocols.
No runtime changes are made by this design-stage change.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — storefront servicing and authority boundaries
- [x] Existing subsystem specification: `settlement-servicing`,
  `market-composition`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

Queues, generation-scoped completion, admission, funding timers, recovery and
exposure limits go to the settlement-servicing spec and architecture companion.
Composition ownership and startup coherence go to market-composition; scenario
evidence classes go to test-compatibility. Architecture describes the neutral kit,
authority-only money movement and seller-owned liveness. The closeout updates
Goal 8 and the campaign index and promotes the reconciled scenario diagrams.
