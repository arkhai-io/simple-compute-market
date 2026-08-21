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

- [ ] 3.1 Re-run the `us_bank_transfer.v1` reclaim lane and record the refusal it
      now names. The lane currently reports `convergence_timeout` at
      `marketplace_lifecycle` with `refund: null` after a 31-minute eligibility
      wait and a 180-second retry, which says nothing about the cause.
- [ ] 3.2 Record the result in `docs/development/TESTING.md`, replacing the note
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
