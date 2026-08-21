## Why

The settlement lifecycle can only ever move an obligation's full amount in one
direction. `ConditionOutcome.decision` is a bare enum, `collect` and
`reclaim_expired` take no amount, and `reserve_settlement_operation` enforces the
two as mutually exclusive in SQL. So a deal that was two-thirds delivered has no
representation: the arbiter must round its answer to all-or-nothing before the
runtime can hear it.

Both mechanisms can already do better than the lifecycle lets them. Alkahest's
ERC20 and native-token splitter arbiters are registered today
(`kit/alkahest/src/market_alkahest/claims.py:143-199`) and exist precisely so a
contract "interprets a true decision as a set of settlement splits rather than an
all-or-nothing release" — `oracle_cli.py:10` records that splitter-backed refunds
are a separate arbiter path with no route through this CLI. On the fiat side the
hosted authority already runs `separate_charges_transfers` against a
`source_transaction`, which is the same shape: one charge, a transfer of part to
the claimant and a refund of the rest to the payer. Neither is reachable, because
the abstraction over them cannot say what they can do.

The second constraint is inherited rather than chosen. `runtime.reclaim` refuses
before `expiration_unix` and `reserve_settlement_operation` refuses a reclaim once
`condition_state == 'ready'`. Both encode an on-chain escrow's release mechanics —
a time-locked contract genuinely cannot pay the payer back early — as a universal
precondition of the runtime. A fiat obligation whose funds are still held and whose
arbiter has already answered has nothing to wait for.

## What Changes

- **A condition evaluation produces a disposition, not a boolean.**
  `ConditionOutcome` carries how much of the obligation is owed to the claimant, in
  the obligation's own minor units; the remainder is owed to the payer. `ready`
  becomes the full-to-claimant disposition and `failed` the full-to-payer one, so
  every outcome expressible today keeps its exact meaning. Placing the split on the
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
  in `kit/settlement-runtime`. Every registered mechanism — hosted, Alkahest,
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
- **A non-degenerate disposition is refused unless the bound release declares it.**
  The hosted wire carries no amount: `OperationRequest` is `protocol` and
  `request_id` only. Hosted obligations therefore accept full-to-claimant and
  full-to-payer dispositions and report a partial one as unavailable under the
  bound release, gated on a declared capability exactly as
  `payer-direct-instrument-setup.v1` is. The model ships now; the hosted rail
  reaches it when a release declares it.

## Capabilities

### New Capabilities

None. Every behavior here belongs to a capability that already exists.

### Modified Capabilities

- `settlement-servicing`: the provider-neutral escrow contract's operations are
  restated around executing a disposition rather than collecting or reclaiming;
  the durable lifecycle's collect/reclaim mutual exclusion is restated as a
  single-disposition accounting invariant; reclaim's expiry precondition is
  replaced by an unsubmitted-claimant-leg precondition; profile-specific reclaim
  remains authority-owned and additionally refuses a partial disposition the bound
  release does not declare.
- `settlement-configuration`: the capability set a hosted consumer asserts against
  its bound release admits partial disposition as a declarable capability, so a
  plan whose terms can produce a split is refused at planning time against a
  release that cannot execute one, rather than at disbursement.

## Impact

- **Code**: `kit/settlement-runtime/src/market_settlement_runtime/` — `ports.py`
  (the protocol), `models.py` (`ConditionOutcome`, `ConditionDecision`),
  `runtime.py` (`reclaim` preconditions, `_finish_*`, terminal derivation),
  `sqlite_repository.py:1040-1120` (reservation invariant),
  `servicing.py`/`jobs.py` (due-work selection over a recorded disposition).
- **Mechanisms**: `kit/hosted-settlement/src/market_hosted_settlement/adapter.py`
  (`collect`/`reclaim_expired` at 430-515), `kit/alkahest` adapter dispatch, and
  the `contact-exchange.v1` mechanism, whose obligations carry no amount and whose
  disposition is therefore degenerate by construction.
- **Persistence**: the obligation record gains the recorded disposition; a
  migration is required. `collection_state` and `reclaim_state` are retained as the
  per-leg states they already are.
- **Deferred and externally blocked.** Partial disbursement over the hosted rail
  needs an amount on the hosted operation contract, which is producer-owned and
  does not exist in the pinned client. No release declares a partial-disposition
  capability today, so on hosted this change is exercised only through the two
  degenerate dispositions, which is exactly current behavior. Early return over
  Alkahest remains mechanically impossible on-chain and is expected to be refused
  by that mechanism; this change removes the runtime's precondition, not the
  chain's.

### Non-Goals

- No dispute policy, arbiter selection, or adjudication process. What counts as
  valid delivery stays encoded in deal terms and answered by whatever arbiter those
  terms name; this change only gives the lifecycle a way to carry the answer.
- No producer-side hosted contract is authored, and no capability string is
  invented into a release manifest that does not declare it.
- No weakening of operation idempotency, work leases, uncertain-acknowledgement
  handling, compare-and-swap ordering, or fail-closed behavior.
- No new funding rail, and no change to which reversal mechanic the hosted
  authority selects — `cancel`, `return`, and `refund` remain its choice from
  funding state, never the marketplace's.
- Commitment finality — how long a committed payment stays reversible, and by
  whom — is not modeled here. It is a real gap with real consequences for
  fulfillment timing and reserves, and it is a separate change.
- No change to fulfillment, capacity, or teardown ordering; a disposition that
  returns part of an obligation does not rewrite the immutable fulfillment record.
