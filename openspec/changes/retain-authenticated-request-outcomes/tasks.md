# Tasks

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

## 5. Closeout

- [ ] 5.1 **Comment hygiene.** `make check-comment-hygiene`.
- [ ] 5.2 **Import placement.** Module level where safe, checked against this
      change's own diff.
- [ ] 5.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement rules.
- [ ] 5.4 **Narrative compression.** Reduce completed-task notes to final
      behavior, validation evidence, and deferred work.
- [ ] 5.5 **Roadmap currency.** Update `docs/development/ROADMAP.md`, or record
      that this change has no roadmap impact.
- [ ] 5.6 **Campaign index currency.** Update this change's row and its
      campaign's dependency graph in `openspec/changes/README.md`.
- [ ] 5.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=retain-authenticated-request-outcomes`.
- [ ] 5.8 **End-to-end pipeline.** Confirm the pipeline passes and record the
      evidence. The credits buy/use/top-up flow is the path that exercises an
      authenticated mutation surface end to end.
- [ ] 5.9 **Promotion.** Complete the design-promotion record. The exact-retry
      implementation belongs in
      `openspec/specs/marketplace-identity/spec.md`'s neighbourhood.
