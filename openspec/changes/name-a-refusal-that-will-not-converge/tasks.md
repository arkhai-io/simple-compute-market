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

Per `openspec/README.md#plan-closeout-requirements`. This change's implementation predates the closeout task becoming a planning requirement. The parts are recorded here so each carries an explicit disposition rather than an assumed one; confirm and tick each rather than treating the change as closed.

- [ ] 5.1 **Comment hygiene.** Run `make check-comment-hygiene`, then direct-read the
      comments and docstrings this change touches for the fuzzier provenance-narration rule
      the target cannot catch mechanically.
- [ ] 5.2 **Import placement.** Review every import this change adds or touches and move it
      to module level where safe; retain a local import only against an observed circular
      import or a documented lazy-load reason, verified against the real suite.
- [ ] 5.3 **Documentation compliance.** Re-check this change's accepted decisions against
      `openspec/README.md`'s placement rules. It carries delta specs for
      `test-compatibility`; confirm each landed in the owning
      `openspec/specs/<capability>/spec.md`, and that durable conceptual rationale sits in
      the companion `architecture.md` rather than only in `design.md`.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and permanent-documentation
      destinations, moving durable rationale into `design.md` first.
- [ ] 5.5 **Roadmap currency.** This change belongs to no campaign, so it most likely owes
      `docs/development/ROADMAP.md` nothing. Confirm that and record the disposition
      explicitly rather than omitting the step.
- [ ] 5.6 **Campaign index currency.** This change has no row in
      `openspec/changes/README.md`; add one under the campaign that owns it with its status
      and acceptance boundary, or record here why it stands outside every campaign.
- [ ] 5.7 **Promotion.** Add a design-promotion record, mapping every accepted decision to
      its exact permanent heading, and verify no production source references
      `openspec/changes/name-a-refusal-that-will-not-converge`.
