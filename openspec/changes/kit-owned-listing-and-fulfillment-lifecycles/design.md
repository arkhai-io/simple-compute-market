# Design

Design phase; not planned.

## Context

- `kit/capacity-publication` owns the common listing binding, event-driven
  reconciliation, registry fan-out, publication result recording, and close/reopen
  mechanics for publication-driven changes. Seller-initiated close, pause, and reopen
  are per-domain services over that binding.
- `kit/settlement-runtime` owns the per-obligation operation journal and servicing
  worker; what each domain reimplements is the step after settlement — resuming an
  accepted obligation across restarts and converging it with the executor's report.
- `site_projection_cache` (VM) and the capacity/publication kit's per-site projection
  state (bare metal) hold the same thing by two routes.

## Questions to settle before planning

- **Whether fulfillment convergence is a new kit package or part of
  `kit/settlement-runtime`.** It reads the settlement journal but drives executor
  state; a separate package keeps the settlement kit free of fulfillment vocabulary.
- **What the successor-identity rule is generically.** VM carries a seller's close or
  pause onto the listing that succeeds a pre-shape listing; bare metal's derivation
  key includes the pool. The kit needs a domain hook that says "this candidate
  succeeds that listing" without knowing why.
- **Where the divergences are.** API credits' fulfillment is issuance, not
  provisioning; the convergence mechanism must fit it without a provisioning-shaped
  no-op.

## Decisions

None yet.
