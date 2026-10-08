## Re-scope (2026-10-08)

Hosted Stripe settlement was removed, so this design covers Alkahest and `contact-exchange.v1`; the hosted capability gate and the hosted adapter it described were removed with it. Open for the owners: whether the early-reclaim relaxation still has a user now that fiat obligations are gone (see the proposal).

## Context

See proposal.md — Why. The constraints that shape the approach:

- `SettlementObligation` (`core/src/market_core/schemas.py:274`) documents `amount`/`asset`
  as the *display/lifecycle* view of value, explicitly `None` when the mechanism's value is
  not scalar. Non-scalar value is an Alkahest-only shape, and both registered splitter arbiters —
  `erc20_splitter` and `native_token_splitter` — divide scalar value as well.
- The exclusion the change reshapes is enforced in SQL inside `BEGIN IMMEDIATE`
  (`kit/settlement-runtime/src/market_settlement_runtime/sqlite_repository.py:1052-1105`),
  not in Python. Whatever replaces it has to stay a single-statement-visible predicate over
  one row plus the operation journal.
- Alkahest's splitter arbiters are registered (`kit/alkahest/.../claims.py:143-199`) and take
  the split from an oracle's decision, not from the escrow. Any design that computes a split
  in the runtime contradicts the mechanism that already implements one.
- `contact-exchange.v1` obligations carry no amount and invoke no funding machinery at all.

## Goals / Non-Goals

**Goals:**
- One lifecycle across all mechanisms, with rail variation carried as data rather than as
  divergent lifecycles.
- A disposition that is recorded once and cannot be contradicted afterwards.
- Preserve exactly today's behavior for every obligation whose disposition is degenerate.

**Non-Goals:**
- Deriving, proposing, or adjusting a split inside the runtime. The runtime records what an
  evaluation returned and executes it.
- Splitting value the runtime cannot conserve. A non-scalar obligation gets the two
  degenerate dispositions and nothing else.

## Decisions

### The split rides on the condition outcome, not on the effect calls

`ConditionOutcome` carries the disposition; `disburse` executes what was recorded.

*Alternatives considered.* Amount parameters on `collect`/`reclaim_expired` — rejected because
two independently-parameterized calls can disagree, and nothing in the schema would catch an
obligation that collected 70% and returned 70%. A runtime-computed split from a satisfaction
percentage — rejected because it puts settlement arithmetic in the layer that is meant to be
mechanism-neutral, and contradicts the splitter arbiters, where the oracle supplies the split.

Deciding once, at evaluation, also gives the invariant a natural home: a disposition is a fact
about an obligation, recorded by one compare-and-swap winner, and effects are its execution.

### A split is over a scalar amount, in minor units

The claimant's share is an integer in the obligation's own minor units. An obligation whose
value is not scalar has only the two degenerate dispositions, and a split over one is refused.

*Alternatives considered.* Fractions or basis points — rejected because they need a rounding
rule, and a rounding rule in settlement is a rule about who eats the remainder, which is a
term, not an implementation detail. Minor units are also what every rail accepts, so no
conversion happens between the decision and the disbursement.

Carrying a second, mechanism-shaped disposition for non-scalar value — rejected, and worth
recording why, because it was the first shape of this design. It would have let the runtime
store a split it cannot conserve, on the reasoning that core does not interpret mechanism
value. But nothing needs it: the two splitter arbiters that exist divide scalar
value. There is no
mechanism today that splits a bundle, so the branch would have been an unenforceable
invariant written for a caller that does not exist. Refusing the split instead keeps
conservation total and fails closed; if a bundle-splitting arbiter ever appears, it arrives
with its own conservation rule and its own change.

### One port verb, two journal kinds

`ConditionalEscrowClient` exposes one disbursement operation. `OperationKind` keeps both
`collect` and `reclaim`, because a split genuinely produces a claimant leg and a payer leg, and
the journal records executions.

*Alternatives considered.* Renaming the journal kinds to match the port — rejected: it forces a
migration over persisted operation history for no behavioral gain, and operator status text that
says "collect" is still accurate. Keeping two port verbs — rejected: that is precisely where the
disagreement risk lives.

`collection_state` and `reclaim_state` on the obligation record are retained unchanged; they were
always per-leg states and now say so.

### The exclusion invariant becomes an accounting predicate

Today's predicate is directional: refuse `fulfill`/`check`/`collect` while a reclaim is live;
refuse `reclaim` while collection is live, a fulfillment reference exists, or the condition is
`ready`. It replaces with:

- a disposition may be recorded only if none is recorded (one compare-and-swap winner);
- a leg may reserve only if the recorded disposition owes it something and it has not already
  reserved or succeeded;
- `fulfill`/`check` still refuse against a recorded disposition that owes the claimant nothing,
  which is the old fulfill-versus-reclaim guard restated.

`condition_state == 'ready'` stops being a reason to refuse a payer leg, because under a partial
disposition "ready" and "owes the payer something" are simultaneously true. That clause was the
same one blocking early return, which is why both land together.

This is still one row plus one journal query inside `BEGIN IMMEDIATE`, and it is a shorter
predicate than the one it replaces.

### Expiry becomes a mechanism's answer, not the runtime's precondition

`runtime.reclaim`'s `self._clock() < expiration_unix` check is removed. A time-locked mechanism
refuses the disbursement itself.

*Alternative considered.* A per-mechanism `supports_early_return` flag consulted by the runtime —
rejected because it restates a mechanism's own rules in a second place that can drift out of
agreement with them, and the port already has the vocabulary for a refusal with a normalized
reason and a deadline.

That vocabulary matters here: the refusal must carry the retry deadline so the scheduler backs
off to expiry instead of re-asking on every due-work tick. Without that, removing the local gate
converts one skipped obligation into a polling loop against a chain.

## Risks / Trade-offs

- **A mechanism refusal becomes a retry storm** → the refusal carries a normalized deadline and
  the scheduler honors it; covered by a task and a test that asserts the next attempt is
  scheduled at expiry rather than at the default retry interval.
- **Backfilled rows disagree with live ones** → backfill is derived from terminal state only
  (`collection_state == 'succeeded'` → whole-to-claimant, `reclaim_state == 'succeeded'` →
  whole-to-payer, otherwise no disposition), so no in-flight obligation is given a disposition it
  did not earn. An obligation mid-flight records its disposition at its next evaluation.
- **The port break lands on three mechanisms at once** → intentional: no compatibility shim, so
  an unconverted mechanism fails the `runtime_checkable` protocol at registration rather than
  being quietly skipped. The blast radius is bounded because all three mechanisms live in this
  repo.
- **A bundle-valued obligation can never be split** → accepted, and currently costless: no
  splitter arbiter divides non-scalar value, so nothing loses a capability it has. The cost
  arrives only if such an arbiter is built, and it arrives as a refused split with a clear
  reason rather than as a silently unconserved one.
- **A partial disposition makes "settled" ambiguous in operator surfaces** → aggregate plan
  status already has a `partial` literal for multi-obligation plans, so the word is now
  overloaded. Task 5 disambiguates the projections rather than reusing it.

## Migration Plan

1. Additive schema migration: disposition columns on the obligation row. No column is dropped or
   retyped; `collection_state` and `reclaim_state` keep their names and meanings.
2. Backfill from terminal state as described above. Deterministic, and re-runnable.
3. Convert the two mechanisms and flip the port in one commit, since there is no shim.
4. Ship with behavior unchanged for every existing obligation: a partial disposition arises only
   from an arbiter that returns one.

**Rollback.** Additive columns mean an older binary ignores them and reads the same lifecycle
states it always did — but only while every disposition is degenerate. Rollback
therefore stays safe exactly until the first split is disbursed, and that boundary should be
stated before an arbiter that returns a split is enabled rather than discovered later.
