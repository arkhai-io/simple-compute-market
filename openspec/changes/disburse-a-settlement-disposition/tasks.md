## 1. A disposition is a recorded fact

- [ ] 1.1 Add the disposition to `ConditionOutcome` in
      `kit/settlement-runtime/src/market_settlement_runtime/models.py`: the claimant's
      share as a minor-unit integer where the obligation states a scalar amount, and a
      mechanism-shaped opaque value where it does not. `ConditionDecision` keeps its four
      literals; `ready` and `failed` are the two degenerate dispositions.
- [ ] 1.2 Add disposition columns to the obligation row and an additive migration in
      `sqlite_repository.py`. `collection_state` and `reclaim_state` keep their names and
      meanings as the two leg states.
- [ ] 1.3 Backfill from terminal state only — `collection_state == 'succeeded'` to
      whole-to-claimant, `reclaim_state == 'succeeded'` to whole-to-payer, otherwise no
      disposition — and make the backfill re-runnable.
- [ ] 1.4 Reject a second disposition for an obligation that already recorded one, and
      surface the disagreement instead of overwriting.
- [ ] 1.5 Evidence: unit coverage for a scalar split that conserves the amount, a scalar
      split that does not (refused), a non-scalar disposition the runtime stores without
      arithmetic, a degenerate disposition matching today's behavior exactly, and a second
      disposition offered against a recorded one.

## 2. The reservation invariant

- [ ] 2.1 Replace the directional predicate in `sqlite_repository.py:1052-1105` with the
      accounting one from design.md — one disposition winner, a leg reserves only if the
      recorded disposition owes it something and it has not already reserved or succeeded,
      `fulfill`/`check` still refuse against a disposition owing the claimant nothing. Keep
      it inside the existing `BEGIN IMMEDIATE` and to one row plus one journal query.
- [ ] 2.2 Remove `condition_state == 'ready'` as a reason to refuse a payer leg.
- [ ] 2.3 Evidence: the existing collect-races-reclaim concurrency tests still pass
      unchanged for degenerate dispositions; new coverage for both legs of one split
      reserving independently, a leg reserving twice, and a leg reserving against a
      disposition that owes it nothing. Mutation-check by reverting 2.1 and confirming the
      new tests fail.

## 3. One disbursement verb

- [ ] 3.1 Collapse `collect` and `reclaim_expired` in `ports.py` into one operation that
      executes a recorded disposition. No compatibility shim — an unconverted mechanism
      fails the `runtime_checkable` protocol at registration.
- [ ] 3.2 Convert the hosted adapter
      (`kit/hosted-settlement/src/market_hosted_settlement/adapter.py:430-515`), the
      Alkahest adapter, and the `contact-exchange.v1` mechanism in the same commit.
- [ ] 3.3 Keep `collect` and `reclaim` as `OperationKind` journal entries; a split records
      both legs under one disposition. No journal migration.
- [ ] 3.4 Evidence: each mechanism disburses both degenerate dispositions with unchanged
      receipts and unchanged operation identities; a mechanism missing the operation is
      refused at registration.

## 4. Expiry becomes a mechanism's answer

- [ ] 4.1 Remove the `self._clock() < expiration_unix` precondition from `runtime.reclaim`
      in `runtime.py:576`.
- [ ] 4.2 Have the Alkahest mechanism refuse a pre-expiry payer leg as its own answer,
      carrying a normalized reason and a retry deadline at expiry.
- [ ] 4.3 Have the scheduler honor that deadline so a refused disbursement backs off to
      expiry rather than re-attempting on every due-work tick.
- [ ] 4.4 Evidence: a fiat obligation whose disposition owes the payer and whose claimant
      leg is unsubmitted disburses before expiry; the equivalent Alkahest obligation is
      refused by the mechanism and rescheduled at expiry, not retried on the default
      interval. Assert the next-attempt time, not just the refusal.

## 5. Projections and operator surfaces

- [ ] 5.1 Derive obligation and plan status from the recorded disposition and its two leg
      states rather than from collection-or-reclaim.
- [ ] 5.2 Disambiguate `SettlementPlanStatus`'s existing `partial` literal, which means
      "some obligations of this plan are done", from an obligation disbursed under a
      partial disposition. Do not reuse the word for both.
- [ ] 5.3 Evidence: unit coverage for a plan containing one fully-collected obligation, one
      split obligation, and one returned obligation, asserting each projection reads
      unambiguously.

## 6. Capability gating on the hosted rail

- [ ] 6.1 Refuse a non-degenerate disposition for a hosted obligation unless the bound
      release declares the partial-disposition capability, reading the capability name the
      producer defines and treating absence as "cannot split".
- [ ] 6.2 Report that refusal as unavailable under the bound release, naming the release —
      not as a mechanism failure — and never approximate a split with a whole disbursement
      plus a marketplace-selected refund.
- [ ] 6.3 Refuse terms at acceptance when their condition evaluator can produce a partial
      disposition and the bound release declares no such capability.
- [ ] 6.4 Evidence: a split refused against today's bound release names the release; the two
      degenerate dispositions are unaffected; terms admitting a split are refused before an
      obligation is materialized.

## 7. Prove the lifecycle end to end

- [ ] 7.1 Run the settlement-runtime, hosted-settlement, VM storefront, bare metal,
      apicredits, core buyer, core storefront, and e2e unit suites; record counts.
- [ ] 7.2 Run one hosted development lane against real Stripe test mode on a funding profile
      that currently passes end to end, confirming a degenerate disposition settles exactly
      as it does today. Record the result and the lane used.
- [ ] 7.3 Re-run the `us_bank_transfer.v1` reclaim lane that a tool timeout cut off, so the
      payer-leg path has been exercised on all three profiles at least once.
- [ ] 7.4 Confirm no partial disposition was exercised against hosted, since no release
      declares the capability, and state that plainly in the evidence.

## 8. Record the decisions

- [ ] 8.1 Promote the disposition model and the accounting invariant into
      `openspec/specs/settlement-servicing/spec.md` and the capability pin into
      `openspec/specs/settlement-configuration/spec.md` via this change's deltas at archive.
- [ ] 8.2 Record in `docs/development/TESTING.md` that partial dispositions are unreachable
      on the hosted rail until a release declares the capability, and that rollback is safe
      only while every disposition is degenerate.
