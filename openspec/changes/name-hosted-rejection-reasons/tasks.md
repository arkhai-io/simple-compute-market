## 1. Keep the half of the error that is safe to keep

- [x] 1.1 `_released_call` carries the authority's stable `code` into both the
      temporary and the manual-required failure it raises, and continues to drop
      the released client's message and sever its cause.
- [x] 1.2 Evidence: a non-retryable rejection produces a failure naming the
      operation and the code; a retryable one still produces a temporary failure;
      neither carries the client's message, and the cause stays severed. A code
      that is not the authority's stable enumeration is treated as no code at
      all, so free text cannot be laundered through the field. One correction
      folded in: the suite could not run on a machine with a proxy configured,
      because constructing the released client builds its transport from the
      ambient environment before any request -- the same failure this branch
      already found in the hosted e2e. Suite: hosted-settlement 156.

## 2. A parked obligation says why

- [x] 2.1 The manual-required finish path records the reason so it survives to
      the projection rather than only to `last_error`.
- [x] 2.2 The hosted status projection reports a stable reason for a
      `manual_required` obligation, built once in the shared surface rather than
      in each domain's copy.
- [x] 2.3 The VM, API-credit, and bare-metal storefronts project it identically,
      by construction rather than by three matching edits.
- [x] 2.4 Evidence: an obligation parked by a refused operation projects its
      reason in every domain; no provider detail reaches the mechanism state a
      projection reads; and a repository-level surface test rejects a domain
      that reassembles the reason itself. One refinement recorded in design.md:
      the reason travels in the mechanism state the record already carries,
      under one key, so no schema migration and no new consumer field were
      needed. Suites: settlement-runtime 78, hosted-settlement 158, VM
      storefront 941, API-credit storefront 76, bare-metal storefront 122,
      scripts 84.

## 3. Diagnose what it names

- [x] 3.1 The hosted materialization assertion in the e2e fixture reports the
      result it rejected — status, action kind, funding reason, populated fields
      — without emitting an action URL.
- [x] 3.2 Run one interactive `card.v1` lane locally against the real Stripe test
      account and record the rejection code the authority returns.

      It returned none. `POST /api/v1/escrows` answered `403` with no code the
      marketplace could use, which is why the first run after section 2 still
      projected no reason — and why section 1 was not yet enough. The
      marketplace now names a refusal the authority does not, so a parked
      obligation cannot be reasonless whoever is at fault.
- [x] 3.3 Correct it here if it is a marketplace defect; record it for
      `add-bare-metal-hosted-settlement` if it is an authority-side or
      configuration matter. A development run qualifies no lane either way.

      Neither, as it turned out: a harness gap. The released authority refuses
      every escrow a storefront opens while `HOSTED_SETTLEMENT_STOREFRONT_CALLERS`
      is unset, and nothing ever set it — not the harness, not the documented
      broker payload. The harness builds that storefront, so it states which
      principal exists, on the same terms as the environment and database path
      it already states. With that, the lane materializes a real escrow against
      the real test account and advances past funding authorization.

      What it reaches next is a separate subject and is recorded for
      `add-bare-metal-hosted-settlement`: buyer status polling refuses the
      storefront's response as malformed or legacy response authentication.
      This development run still qualifies no lane.

## 4. Closeout

- [ ] 4.1 Hygiene clean, strict validation, suites for every touched package, and
      the ROADMAP updated if the hosted-settlement status changes shape.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A non-retryable authority rejection retains the authority's stable code and drops its message | `openspec/specs/settlement-servicing/spec.md` (promote at synchronization) |
| An obligation parked as `manual_required` projects a stable reason, identically in every adopting domain | `openspec/specs/settlement-servicing/spec.md` (promote at synchronization) |
