## 1. A disposition is a recorded fact

- [ ] 1.1 Add the disposition to `ConditionOutcome` in
      `kit/settlement-runtime/src/market_settlement_runtime/models.py` as the claimant's
      share in the obligation's own minor units. `ConditionDecision` keeps its four
      literals; `ready` and `failed` are the two degenerate dispositions.
- [ ] 1.2 Refuse a non-degenerate disposition over an obligation with no scalar amount,
      naming the value as indivisible rather than the mechanism as failed.
- [ ] 1.3 Add disposition columns to the obligation row and an additive migration in
      `sqlite_repository.py`. `collection_state` and `reclaim_state` keep their names and
      meanings as the two leg states.
- [ ] 1.4 Backfill from terminal state only — `collection_state == 'succeeded'` to
      whole-to-claimant, `reclaim_state == 'succeeded'` to whole-to-payer, otherwise no
      disposition — and make the backfill re-runnable.
- [ ] 1.5 Reject a second disposition for an obligation that already recorded one, and
      surface the disagreement instead of overwriting.
- [ ] 1.6 Evidence: unit coverage for a split that conserves the amount, a split that does
      not (refused), a split over a non-scalar obligation (refused), a degenerate
      disposition matching today's behavior exactly, and a second disposition offered
      against a recorded one.

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
- [ ] 3.2 Convert the Alkahest adapter and the `contact-exchange.v1` mechanism in the
      same commit.
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
- [ ] 4.4 Evidence: a test mechanism's obligation whose disposition owes the payer and whose
      claimant leg is unsubmitted disburses before expiry; the equivalent Alkahest obligation is
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

## 6. Prove the lifecycle end to end

- [ ] 6.1 Run the settlement-runtime, VM storefront, bare metal,
      apicredits, core buyer, core storefront, and e2e unit suites; record counts.

## 7. Record the decisions

- [ ] 7.1 Promote the disposition model and the accounting invariant into
      `openspec/specs/settlement-servicing/spec.md` via this change's delta at archive.
- [ ] 7.2 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both.

## 8. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 8.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
- [ ] 8.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 8.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe: durable conceptual rationale sits in the
      companion `architecture.md` rather than only in `design.md`, and no production
      source references `openspec/changes/disburse-a-settlement-disposition`.
- [ ] 8.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 8.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
      This change belongs to no campaign, so it most likely owes the roadmap nothing;
      confirm that and record the disposition explicitly.
- [ ] 8.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 8.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 8.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change, or an explicit blocker
      naming its cause and the change that owns it, with the validations it gates
      treated as unrun.
- [ ] 8.9 **Promotion.** Write the permanent documents this change owes — the
      `settlement-servicing` companion `architecture.md`, for any durable rationale
      that does not fit normative scenarios — and add a design-promotion record
      mapping every accepted decision to its exact permanent heading.
      `openspec/specs/settlement-servicing/spec.md`, which the delta covers, is written
      by the archive in 8.11, not by hand; the record names it all the same.
- [ ] 8.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=disburse-a-settlement-disposition` and resolve
      every match, then `openspec validate disburse-a-settlement-disposition --strict`.
- [ ] 8.11 **Archival.** Last, once every other part is checked: `openspec archive
      disburse-a-settlement-disposition -y` merges the deltas into `openspec/specs/` and
      moves the change under `openspec/changes/archive/`; point the index row at the
      archived directory, and run `openspec validate --specs --strict`.
