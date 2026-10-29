## Why

Every payment scenario in the end-to-end lanes skips: `e2e-tests/settings.toml`'s
`[payments]` target is blank by default, and the only stand-in for the service is
`kit/arkhai-payments`' `FakePaymentsClient`, an in-process fake with a placeholder
proof that emits parts `held` or `reversed`, no `fundedThrough`, no stop, no event
sequence, and no `stop` call. Nothing in the pipeline can drive a transaction to
exhaustion, serve a stale or wrong-transaction snapshot, regress an event sequence, or
rotate the signing identity — the cases that decide whether a storefront's handling of
the contract is safe — and the live service cannot be driven to any of them on demand.

This is the first change of the roadmap goal that sells compute by the period until
either party stops ([`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops))
on the kit side: it lands before the mechanism it tests, so that every later change
is proven against it from its first round rather than against a double built last.

## What Changes

- The fake grows into an **in-lane HTTP double** of the payments service the lane
  stacks can run, built on the kit's models and signers, with a development signing
  key that is a well-known fixture value and says so, trusted by no production
  configuration. It serves approve, `GET /transactions/{id}` with a verifiable proof
  over the snapshot frame, `fundedThrough`, `stop`, and the event sequence; `start`,
  `stop`, partial and whole `reverse`; attachments; and the period clock from `start`.
- It implements **two contracts under one flag**: the published contract as vendored,
  and the proposed horizon extension
  ([`settle-ongoing-compute-through-arkhai-payments`](../settle-ongoing-compute-through-arkhai-payments/)
  D5) — a payee-only `vouch {part, through}` on a rate part, periods beginning only
  inside `vouchedThrough`, and a `terms` stop when it lapses — so the per-period
  scenarios can run before the service ships it. Under the published contract the
  double releases on stop and never returns released funds, so the collection case
  fails as it should; under the proposed extension it also accepts a `refund` of
  released funds, so the `refund` journal kind has something to drain into in the
  lane.
- **Test controls**: exhaust a payer's funds at a chosen instant; serve a stale,
  equal-sequence, regressed, or wrong-transaction snapshot; delay or drop a response;
  rotate the signing identity with an overlap; and refuse chosen commands with chosen
  error codes, so the refusal table is exercised.
- `e2e-tests`' `[payments]` target points at the double under the lane profiles, so
  the existing bare-metal and credits payment scenarios run in the pipeline and stop
  skipping. A `livemode: true` snapshot is never produced by the double.

The double proves the marketplace's use of the contract; live qualification stays the
payments service's. Evidence produced against the proposed extension is recorded as
*qualification against a proposed contract*, never as live evidence.

## Capabilities

### Modified Capabilities

Expected: `test-compatibility` (the double, its controls, and the evidence class).
`.openspec.yaml` sets `skip_specs` until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- Any change to the kit's production code paths: derivation, verification, and the
  lifecycle operations are `settle-ongoing-compute-through-arkhai-payments`'.
- A stand-in for live qualification; the double never substitutes for the service's
  own tests, and the activation follow-on verifies it against the service's published
  vectors before any live evidence is claimed.

## Dependencies and Related Changes

- Depends on nothing. The vendored contract is what it implements.
- `settle-ongoing-compute-through-arkhai-payments` depends on it and reconciles the
  double's snapshot frame against the service's published vector in its design
  session; `activate-per-period-compute-servicing` re-verifies the double against the
  vendored revision before servicing is declared live.

## Impact

`kit/arkhai-payments/fixtures` or a tooling project the lanes build (settled in
design against `BUILD_AND_PACKAGING.md`'s image rules), the e2e lane stacks that gain
the double, and `e2e-tests`' payment settings.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The in-lane payments double, its two contracts, what it proves and what it does
  not — `test-compatibility` spec and `docs/development/TESTING.md`, "Payment
  Receipts in Tests".
