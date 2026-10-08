## 1. The wait distinguishes what it may retry

- [x] 1.1 Parse the authority's error code, not only the HTTP status, in
      `request_eligible_pretransfer_refund`
      (`e2e-tests/tests/e2e/roles/scenarios/vms/hosted/network.py:795-809`).
- [x] 1.2 Retry `operation_conflict` only; end the wait on any other refusal and
      raise it with its code intact.
- [x] 1.3 Carry the last refusal into the timeout when the deadline is genuinely
      reached.
- [x] 1.4 Evidence: unit coverage for a retried `operation_conflict` that then
      succeeds, an immediate stop on `reversal_unsupported`, an immediate stop on
      `funding_relation_missing`, and an exhausted deadline that names its last
      refusal. Mutation-check by reverting 1.2 and confirming the stop tests fail.

## 2. The run reports the cause

- [x] 2.1 Build the diagnostic from the refusal's code rather than
      `convergence_timeout` when a lane ends on a refusal, keeping the stage as
      the stage the lane was in.
- [x] 2.2 Evidence: unit coverage that a refused lane's evidence carries the
      authority's code, and that a genuine timeout still reports a timeout.

## 3. Learn what the bank-transfer lane actually hits

- [x] 3.1 Re-run the `us_bank_transfer.v1` reclaim lane and record the refusal it
      now names. The lane currently reports `convergence_timeout` at
      `marketplace_lifecycle` with `refund: null` after a 31-minute eligibility
      wait and a 180-second retry, which says nothing about the cause.

      Run against `efd1e91f`, profile `us_bank_transfer.v1`, scenario `reclaim`,
      run ref `run_88ef942e50eebe0de6b0ecac`. Named refusal:
      `storefront: hosted settlement reclaim is temporarily unavailable`. No
      authority code reached the harness, so the diagnostic stays
      `convergence_timeout` — correct, because that sentence is classified
      retryable on purpose.

      The refusal is a literal, not an answer.
      `SettlementHostedRoutes.reclaim` ends in a bare `except Exception` that
      rewrites every remaining failure as a fixed 503 with that text
      (`hosted_routes.py:352-356`), and the module logs nothing, so the cause
      does not survive the process.

      This also rules out one hypothesis the proposal carried: a permanent
      mechanism refusal never reaches that handler.
      `SettlementRuntime.reclaim` catches `SettlementManualRequired` and returns
      a `manual_required` outcome (`runtime.py:608-609`) that the route
      projects rather than raising. Whatever this lane hit was classified
      retryable or uncertain below, or was not a mechanism refusal.

      Followed through to the cause, which is in the authority and is neither
      refusal the proposal suspected. `ReversalKind.RETURN` has no provider
      implementation: `create_reversal` branches on `CANCEL` and refunds
      everything else, so a bank-transfer return issues `refunds.create`
      against a `customer_balance` PaymentIntent. Stripe rejects it —
      `Missing email. In order to create refunds that are sent to the customer,
      the customer must have a valid email.` — confirmed directly against test
      mode on the intent this run funded. The return is email-mediated and
      wants `instructions_email`, which the authority never sends.

      That rejection is then misclassified: `create_reversal` does not wrap
      `stripe.InvalidRequestError`, so it escapes the rejection branch into
      `authority.py:4708-4714` and is reported `provider_uncertain`,
      `retryable=True`. A permanent failure is advertised as a temporary one,
      which is why nothing converged. Recorded in `docs/development/TESTING.md`.
- [x] 3.2 Record the result in `docs/development/TESTING.md`, replacing the note
      that the reclaim leg is unproven with what the authority actually answers.
      If the answer is that the profile cannot reclaim through this path, say so
      there and open the question against the authority rather than the harness.

      Implemented across the chain the code has to travel: the wait raises
      `HostedAuthorityRefusal` (`network.py`), the bridge emits
      `authority_refused` with the code, the runtime raises
      `LifecycleAuthorityRefused`, and the driver maps it to the authority's own
      code. `reversal_unsupported` and `funding_relation_missing` were added to
      the evidence allowlist, which is closed on purpose: a public code is
      enumerated before it can be published, and an unrecognised one still falls
      back to `lifecycle_contract_rejected`.

      A subtlety worth recording: the authority's own `retryable` flag is false
      for all three codes here, including `operation_conflict`. That flag means
      the identical request may be re-sent, which is not what a polling wait
      asks — a lost reservation is not re-sendable, yet the condition behind it
      can clear. The wait therefore retries `operation_conflict` and honours
      `retryable=True` for anything else, rather than keying on either alone.

      Suite: e2e unit 148 passed. Mutation-checked by restoring retry-everything:
      the two stop tests fail, and the run takes 6m39s instead of 0.4s — the
      defect made visible, since each permanent refusal is retried for its full
      180-second bound.


## 4. A parked obligation is not waited out

- [x] 4.1 End `_wait_public_status` on a `manual_required` projection, raising it
      as a refusal named by the projection's `funding_reason`, or
      `settlement_parked` when it carries none.
- [x] 4.2 Add `reversal_rejected` and `settlement_parked` to the evidence
      diagnostic allowlist, which stays closed: an unrecognised code still falls
      back to `lifecycle_contract_rejected`.
- [x] 4.3 Evidence: a parked projection ends the wait on its first observation
      and names its reason; a parked projection without a reason is still named;
      a terminal status still returns; a merely non-terminal status still times
      out. e2e unit 153 passed.

      Reached by fixing the authority, not the harness. `us_bank_transfer.v1`
      cannot return through the refund path at all, so with the authority
      rejecting it properly the obligation now parks with `reversal_rejected`
      instead of retrying an uncertainty forever. The harness has to stop on
      that, or the corrected authority would still read as a timeout.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`. This change's implementation predates the closeout task becoming a planning requirement, so each part is recorded with the evidence that discharges it rather than assumed.

- [x] 5.1 **Comment hygiene.** `make check-comment-hygiene` passes. Direct-read the six
      files this change touches outside `openspec/` — the four `hosted_real_stripe` modules,
      the VM hosted `network.py` scenario, and `test_reclaim_refusal.py` — for provenance
      narration: none present. `lifecycle_bridge._refusal_class`'s docstring explains why
      the refusal type is resolved dynamically rather than imported, which is a current
      invariant and the kind of local rationale comments are for.
- [x] 5.2 **Import placement.** This change added one function-local import,
      `from tests.e2e.roles.scenarios.vms.hosted import network` in
      `test_reclaim_refusal.py`, a file it shares with `carry-the-payer-return-address`.
      That module is already imported at the file's module scope, so the local import
      deferred nothing; it was moved to module level in the same closeout pass that handled
      the sibling change's copies. Every other import this change added is module level.
      **Verified against the real suite:** 237 unit tests pass under `uv run --frozen
      --project e2e-tests --find-links .dist python -m pytest e2e-tests/tests/unit`.
- [x] 5.3 **Documentation compliance.** The delta is one MODIFIED requirement,
      `test-compatibility`'s "Stripe-backed hosted settlement system evidence" — the same
      requirement `carry-the-payer-return-address` modifies. The two deltas diverged rather
      than nesting: each keeps the nine shared scenarios and adds its own, and applying them
      in sequence would have dropped whichever landed first. The permanent spec therefore
      carries the union — the nine shared scenarios plus that change's two payer-return
      scenarios plus this change's three refusal and parking scenarios, with this change's
      retry-and-parking prose. Decisions rejected here stay in `design.md`.
- [x] 5.4 **Narrative compression.** Completed-task notes carry final behavior, the observed
      authority codes, and permanent destinations, with rationale held in `design.md`'s three
      decisions. Re-read at closeout; nothing to move or delete.
- [x] 5.5 **Roadmap currency.** No goal current-state change owed. Naming the cause of a
      refusal changes what a lane reports, not which mechanisms compose or what the market
      can sell, so Goal 6's current state is unaffected and no gap row names this work.
      Disposition recorded rather than the step skipped.
- [x] 5.6 **Campaign index currency.** The index gained a row for this change on 2026-09-04
      under the "Hosted fiat settlement" campaign, which had been absent from it entirely.
      On archival that row is removed, which is the disposition a completed change owes the
      index.
- [x] 5.7 **Promotion.** Design-promotion record added to `design.md`. No production source
      references `openspec/changes/name-a-refusal-that-will-not-converge`.
