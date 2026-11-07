# Tasks

Blocked on `redesign-authenticated-requests`; see `proposal.md`. Its decision
1.7 determines whether these tasks proceed, narrow, or are superseded.

## 1. Decide the record before building it

- [ ] 1.1 Define what a recorded outcome is, and which routes are eligible.
      Status plus a complete JSON body is the likely answer; a streaming
      response is the case that breaks it. Declare eligibility explicitly
      rather than inferring it, the way `exact_retry_safe` is declared now.
- [ ] 1.2 Decide where the outcome is held: buffered by the middleware, which
      already reads the body to sign it, or written by the handler and
      referenced by the store. This is a question about who owns the record,
      not an implementation detail.
- [ ] 1.3 Decide retention and expiry. An expired outcome makes an exact retry
      indistinguishable from a first attempt, which is the defect being fixed,
      so "fall back to re-executing" is not an answer.

## 2. Retention

- [ ] 2.1 Extend the replay store so a reservation can be completed with its
      outcome and an exact retry resolves to it. Changed reuse stays a 409.
- [ ] 2.2 A durable provider for services that must honour this across an
          authority restart. A process-local store cannot: a restart between
          the mutation and the retry loses the record the caller needs, and
          would look conformant while not being.
- [ ] 2.3 API credits composes the durable provider.

## 3. Retire the refusal

- [ ] 3.1 Give `credits_key_adjust` an idempotency key as consume has,
      including the `credit_grants` column and its migration, so its exact
      retry resolves in the handler.
- [ ] 3.2 Remove `exact_retry_safe=False` from that route, and confirm no
      route still carries it. A route that does is one whose outcome is not
      retained.
- [ ] 3.3 Decide whether `exact_retry_safe` itself should remain. If every
      route's outcome is retained it documents nothing; if it stays, it should
      say what it means in a world where the middleware can resolve retries.

## 4. Validation

- [ ] 4.1 A middleware-level test per disposition: an exact retry resolves to
      the recorded outcome and the handler runs once; changed reuse is 409.
      Assert the handler's call count, not only the status -- a response that
      looks right while the mutation ran twice is the failure being prevented.
- [ ] 4.2 A restart test for the durable provider: an outcome recorded before
      a restart is returned after it.
- [ ] 4.3 `kit/site`, `domains/apicredits/service`, and
      `provisioning/compute/service`.
- [ ] 4.4 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 5.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
- [ ] 5.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 5.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 5.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
- [ ] 5.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 5.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 5.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change — the credits
      buy/use/top-up flow is the path that exercises an authenticated mutation surface
      end to end — or an explicit blocker naming its cause and the change that owns
      it, with the validations it gates treated as unrun.
- [ ] 5.9 **Promotion.** Write the permanent documents this change owes and complete
      the design-promotion record. The exact-retry behaviour belongs in
      `openspec/specs/marketplace-identity/spec.md`'s neighbourhood; a `spec.md` the
      deltas cover is written by the archive in 5.11, not by hand, and the record
      names it all the same.
- [ ] 5.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=retain-authenticated-request-outcomes` and resolve every match,
      then `openspec validate retain-authenticated-request-outcomes --strict`, or, while the change has no spec deltas, record that instead: the validator rejects a change with none.
- [ ] 5.11 **Archival.** Last, once every other part is checked: `openspec archive
      retain-authenticated-request-outcomes -y` merges the deltas into `openspec/specs/` and
      moves the change under `openspec/changes/archive/`; point the index row at the
      archived directory, and run `openspec validate --specs --strict`.
