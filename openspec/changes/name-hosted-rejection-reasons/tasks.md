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

- [ ] 2.1 The manual-required finish path records the reason so it survives to
      the projection rather than only to `last_error`.
- [ ] 2.2 The hosted status projection reports a stable reason for a
      `manual_required` obligation, built once in the shared surface rather than
      in each domain's copy.
- [ ] 2.3 The VM, API-credit, and bare-metal storefronts project it identically,
      by construction rather than by three matching edits.
- [ ] 2.4 Evidence: an obligation parked by a refused operation projects its
      reason in every domain; a projection of a parked obligation with no reason
      is impossible; no provider detail appears in any projected field.

## 3. Diagnose what it names

- [ ] 3.1 The hosted materialization assertion in the e2e fixture reports the
      result it rejected — status, action kind, funding reason, populated fields
      — without emitting an action URL.
- [ ] 3.2 Run one interactive `card.v1` lane locally against the real Stripe test
      account and record the rejection code the authority returns.
- [ ] 3.3 Correct it here if it is a marketplace defect; record it for
      `add-bare-metal-hosted-settlement` if it is an authority-side or
      configuration matter. A development run qualifies no lane either way.

## 4. Closeout

- [ ] 4.1 Hygiene clean, strict validation, suites for every touched package, and
      the ROADMAP updated if the hosted-settlement status changes shape.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A non-retryable authority rejection retains the authority's stable code and drops its message | `openspec/specs/settlement-servicing/spec.md` (promote at synchronization) |
| An obligation parked as `manual_required` projects a stable reason, identically in every adopting domain | `openspec/specs/settlement-servicing/spec.md` (promote at synchronization) |
