## Why

Seller-initiated interruption ships in part: an interruptible VM listing, a storefront admin endpoint that shortens the capacity lease, and Alkahest splitter plumbing whose money side returns `splitter_declaration_pending`. Bare metal separately has a buyer teardown route. Nothing describes what happens after an agreement is committed in terms both payment mechanisms and every domain can share:

- Seller reclaim, buyer stop, funding exhaustion, and exceptional ends such as failed hardware are handled as separate features, and the hosted and Alkahest paths diverge.
- It is undefined which steps are protocol and which are dealings between the parties after commitment.
- An agreement does not state how a dispute about it is decided, and the evidence a dispute would need is not kept.

## What Changes

- **The protocol is what a party must do to continue:** discovery, negotiation, and the mechanism's commitment act. Everything after commitment is lifecycle, visible to arbitration only through evidence. Settle moves out of core as the buyer's `commit` handoff.
- **The committed agreement is the mechanism's:** Alkahest's arbiter and `DemandData`, the hosted payments mandate, or a countersigned Agreement. The buyer verifies it is the derivation of the negotiated terms before committing. There is no universal agreement digest.
- **Clauses name their adjudicator.** For deals through the official Arkhai registry the default is optimistic, Arkhai-adjudicated; a deferred dispute authority automates some cases later.
- **An early-termination clause in each settlement option's `params`.** Entitlements per initiator are the mechanism's stop authorities; exceptional ends are disputes, conceded by the seller in the cooperative case; buyer stops settle through the seller's declared exposure; notice is posted at the authority. The listing-wide interruptible flag is replaced by a registry field derived from options.
- **One lifecycle interface on each side of the mechanism.** A mechanism-neutral event model (`commit`, `start`, `notice`, `stop`, `dispute`, `concede`), a buyer half and a seller half, and adapters per mechanism and per arbiter or oracle. A new kit holds the neutral layer; the seller's own capability is seller-authenticated routes the CLI, strategy runner, and admin route call.
- **The authority's record decides.** Parties act at the authority with their own credentials; funds move only after a seller action that begins service; courtesy notices are hints.
- **End service at T** consumes lifecycle events: a maximum-term lease as backstop, terminate when *T* has passed, truncate at full precision otherwise. Bare metal's teardown route becomes a caller.
- **Each party keeps its evidence:** commitment envelopes always, other records by regime, in a store separate from replay state. A dispute is one exportable case payload.
- **Hosted first; a neutral trustless alternative stays possible.** Alkahest is at the user's own risk until a specialized arbiter exists.

## Capabilities

### New Capabilities

- `deal-lifecycle`: the lifecycle event model, the early-termination clause codec, the buyer and seller halves and their routes, the evidence store, the dispute case payload, and end service.

### Modified Capabilities

- `negotiation-protocol`: the protocol ends at commitment; the settle route leaves core; the buyer verifies the committed form against the negotiated terms (modifies the exact-release-condition requirement); acceptance envelopes are kept.
- `buyer-orchestration`: the `commit` handoff replaces settle; buyer stop, dispute, and read through the buyer half.
- `settlement-servicing`: lifecycle adapters resolve through the role table, not the escrow-client port; "Signed heartbeat evidence" is modified to keep signatures.
- `settlement-configuration`: option builders emit the clause only where the part shape and arbiter can end early; stop and start authorities derive from entitlements.
- `storefront-publication`: listings carry the clause per option; the listing-wide flag is removed.
- `registry-discovery` and `cli-query-language`: a filterable field derived from options.
- `vm-storefront-fulfillment`: "Full settlement convergence ownership" is modified, since end service writes the lease.
- `site-capacity`: terminate versus truncate under end service, at full precision.

## Dependencies and Related Changes

- `spot-deals-through-arkhai-payments` depends on this change and implements the hosted rate part against its kit, with the amendments recorded in its proposal.
- `automate-seller-spot` depends on both and is rescoped to the strategy runner.
- `version-accepted-artifacts`: exact stored bytes for the evidence store.
- `move-escrow-into-alkahest`: the Alkahest adapter is ordered with it.
- The hosted payments contract must provide the items in design.md, "Dependencies on the hosted payments service", vendored through `kit/arkhai-payments/schema/SOURCE.md`; SCM must verify snapshot proofs before reading snapshot state as evidence.
- Issue #269 tracks hosted rate parts.

## Non-Goals

- An automated dispute authority, a managed metering gateway, or a specialized Alkahest arbiter.
- Lease extension (top-up).
- Delivering courtesy notices to buyer-supplied webhooks.
- Preemption between reservations inside the site authority (`pools-6-fair-scheduling-policy`).
- Choosing seller interruption strategy (`automate-seller-spot`).
- Merging the VM and bare-metal domains.

## Impact

- **Wire:** the clause inside option `params` changes option IDs, so listings re-derive them on republish; the settle route moves. There is no backwards-compatibility promise.
- **Persistence:** an evidence store per commitment reference, and lifecycle records per deal.
- **Packaging:** a new `kit/deal-lifecycle`; adapters in `kit/arkhai-payments` and `kit/alkahest`; storefronts and the buyer client bind the kit.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [x] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1 protocol boundary, D2 mechanism-defined commitment, D12 worst-case rule, D13 neutral-alternative test, D14 information placement → `docs/development/ARCHITECTURE.md` ("Authority boundaries", major flows).
- D4 adjudicator and admissibility → `openspec/specs/negotiation-protocol/spec.md`.
- D5 clause, D6 lifecycle interface, D7 authority record, D8 end service, D9 evidence store, D10 case payload → the new `deal-lifecycle` capability's `spec.md` and `architecture.md`.
- D5 option-level clause emission → `openspec/specs/settlement-configuration/spec.md` and `openspec/specs/storefront-publication/spec.md`.
- D6 role-table adapters and D11 optimistic adjudication → `openspec/specs/settlement-servicing/architecture.md` ("Capacity coupling" and "Current limits" are modified).
- D8 lease primitives → `openspec/specs/site-capacity/spec.md` and `openspec/specs/vm-storefront-fulfillment/spec.md`.
