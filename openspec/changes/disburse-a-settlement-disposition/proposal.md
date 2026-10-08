## Re-scope (2026-10-08)

Hosted Stripe settlement was removed (`fiat.stripe.v1`, `kit/hosted-settlement`, the hosted client, and the real-Stripe lanes), so this change covers Alkahest and `contact-exchange.v1`; Arkhai payments does not use the settlement runtime. The hosted adapter conversion, hosted capability gating, the hosted release-pin delta, and the real-Stripe lanes were removed with it.

Open for the owners: the early-reclaim relaxation was motivated by fiat obligations whose funds are held. Decide whether it still has a user; if it stays, its requirement needs a home in the `settlement-servicing` delta.

## Why

The settlement lifecycle can only ever move an obligation's full amount in one
direction. `ConditionOutcome.decision` is a bare enum, `collect` and
`reclaim_expired` take no amount, and `reserve_settlement_operation` enforces the
two as mutually exclusive in SQL. So a deal that was two-thirds delivered has no
representation: the arbiter must round its answer to all-or-nothing before the
runtime can hear it.

Alkahest can already do better than the lifecycle lets it. Alkahest's
ERC20 and native-token splitter arbiters are registered today
(`kit/alkahest/src/market_alkahest/claims.py:143-199`) and exist precisely so a
contract "interprets a true decision as a set of settlement splits rather than an
all-or-nothing release" — `oracle_cli.py:10` records that splitter-backed refunds
are a separate arbiter path with no route through this CLI. That path is not
reachable, because the abstraction over it cannot say what it can do.

The second constraint is inherited rather than chosen. `runtime.reclaim` refuses
before `expiration_unix` and `reserve_settlement_operation` refuses a reclaim once
`condition_state == 'ready'`. Both encode an on-chain escrow's release mechanics —
a time-locked contract genuinely cannot pay the payer back early — as a universal
precondition of the runtime. A mechanism whose funds are not time-locked, and whose
arbiter has already answered, has nothing to wait for.

## What Changes

- **A condition evaluation produces a disposition, not a boolean.**
  `ConditionOutcome` carries how much of the obligation is owed to the claimant, in
  the obligation's own minor units; the remainder is owed to the payer. `ready`
  becomes the full-to-claimant disposition and `failed` the full-to-payer one, so
  every outcome expressible today keeps its exact meaning. A split requires a scalar
  amount, which both registered splitter arbiters divide; an obligation whose
  value is a bundle keeps only the two degenerate dispositions. Placing the split on the
  evaluation rather than on the effects means collection and return cannot disagree
  about it, and matches how the splitter arbiters already work: the oracle supplies
  the split.
- **One disbursement verb replaces the collect/reclaim pair on the mechanism port.**
  `ConditionalEscrowClient.collect` and `reclaim_expired` become a single operation
  that executes a recorded disposition. The runtime's `OperationKind` keeps both
  `collect` and `reclaim` as journal entries, because a split genuinely does produce
  a claimant leg and a payer leg; only the port collapses, so no journal migration
  is required and existing operation history stays readable.
- **BREAKING (mechanism port).** `ConditionalEscrowClient` is an exported protocol
  in `kit/settlement-runtime`. Every registered mechanism — Alkahest and
  contact-exchange — implements the new operation. There is no compatibility
  shim: a mechanism that has not been converted fails the protocol check at
  registration rather than silently servicing obligations through a verb the
  runtime no longer calls.
- **The collect-versus-reclaim exclusion becomes an accounting invariant.** Today
  `sqlite_repository.py:1072-1105` refuses `fulfill`/`check`/`collect` once a
  reclaim is in flight and refuses `reclaim` once collection is in flight, once a
  fulfillment reference exists, or once the condition is `ready`. That either/or is
  replaced by: exactly one disposition is recorded per obligation, its legs sum to
  the obligation amount, and each leg is executed at most once. Concurrency safety
  is unchanged — it is still one compare-and-swap winner before mechanism I/O — but
  the winner is the disposition, not the direction.
- **Reclaim stops being gated on expiry.** The precondition becomes what actually
  matters and is already tracked: no claimant leg has been submitted. A mechanism
  that cannot return funds early still refuses, and that refusal is now the
  mechanism's answer under its own rules rather than a precondition the runtime
  imposes on every mechanism on one mechanism's behalf.

## Capabilities

### New Capabilities

None. Every behavior here belongs to a capability that already exists.

### Modified Capabilities

- `settlement-servicing`: the provider-neutral escrow contract's operations are
  restated around executing a disposition rather than collecting or reclaiming;
  the durable lifecycle's collect/reclaim mutual exclusion is restated as a
  single-disposition accounting invariant; reclaim's expiry precondition is
  replaced by an unsubmitted-claimant-leg precondition.

## Impact

- **Code**: `kit/settlement-runtime/src/market_settlement_runtime/` — `ports.py`
  (the protocol), `models.py` (`ConditionOutcome`, `ConditionDecision`),
  `runtime.py` (`reclaim` preconditions, `_finish_*`, terminal derivation),
  `sqlite_repository.py:1040-1120` (reservation invariant),
  `servicing.py`/`jobs.py` (due-work selection over a recorded disposition).
- **Mechanisms**: the `kit/alkahest` adapter dispatch and the `contact-exchange.v1`
  mechanism, whose obligations carry no amount and whose
  disposition is therefore degenerate by construction.
- **Persistence**: the obligation record gains the recorded disposition; a
  migration is required. `collection_state` and `reclaim_state` are retained as the
  per-leg states they already are.
- **Deferred.** Early return over Alkahest remains mechanically impossible
  on-chain and is expected to be refused by that mechanism; this change removes the
  runtime's precondition, not the chain's.

### Non-Goals

- No dispute policy, arbiter selection, or adjudication process. What counts as
  valid delivery stays encoded in deal terms and answered by whatever arbiter those
  terms name; this change only gives the lifecycle a way to carry the answer.
- No weakening of operation idempotency, work leases, uncertain-acknowledgement
  handling, compare-and-swap ordering, or fail-closed behavior.
- No new funding rail.
- Commitment finality — how long a committed payment stays reversible, and by
  whom — is not modeled here. It is a real gap with real consequences for
  fulfillment timing and reserves, and it is a separate change.
- No change to fulfillment, capacity, or teardown ordering; a disposition that
  returns part of an obligation does not rewrite the immutable fulfillment record.
