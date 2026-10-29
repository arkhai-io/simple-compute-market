# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
and split out of `settle-ongoing-compute-through-arkhai-payments` on the goal's fourth
review round so the double lands first. This change's own design review may reopen
any of them with a finding; its design session verifies them against the code and
adds the spec deltas.

## Context

Verified against the tree on 2026-10-28; re-verify before planning.

- `kit/arkhai-payments/fixtures/payments_client.py`: `FakePaymentsClient` uses a
  placeholder proof, emits parts `held` or `reversed`, empty events, no
  `fundedThrough` or `stop`, and has no `stop`.
- `test-vectors/payments.json` has mandates (three `once`, one `rate` that is only
  hash-checked; none mixed), a receipt, attachments, approvals; no snapshot and no
  lifecycle event.
- `e2e-tests/settings.toml`'s `[payments]` target is blank by default, and every
  payment scenario skips without one; the bare-metal and credits payment scenarios
  exist and skip.
- The lane stacks are built from images under `BUILD_AND_PACKAGING.md`'s rules;
  `TESTING.md`, "Private Service Dependencies", states what a double at a vendored
  boundary may and may not prove.

## Goals / Non-Goals

**Goals:** every payment scenario runs in the pipeline; the hostile cases are
assertable; the per-period scenarios can run before the service ships the horizon,
labelled for what they are.

**Non-Goals:** live qualification; any production code path.

## Decisions

### D1. An HTTP double, not an in-process fake

The fake becomes a service the lane stacks run, reached through the same client and
the same configuration a storefront uses for the live service, so the scenarios
exercise transport, idempotency keys, and the signed snapshot frame rather than a
Python object. It is built on the kit's models and signers; its development signing
key is a well-known fixture value, named as one in a comment, and trusted by no
production configuration.

### D2. Two contracts under one flag

The double implements the published contract as vendored, and under a flag the lane
profile sets, the proposed horizon extension: `vouchedThrough` on a rate part, a
payee-only `vouch {part, through}` that is monotonic, never past `fundedThrough`,
refused on a stopped transaction; periods beginning only inside the horizon; a
`terms` stop settled to the horizon when it lapses; and a `refund {part, amount}` of
released funds. Under the published contract a stop releases and nothing returns
released funds, so the collection scenario fails as it should; under the extension
the journal's `refund` kind drains. The flag's value is reported in every snapshot the
double serves, outside the signed frame, so a scenario can assert which contract it
ran against. The double never produces `livemode: true`.

*Rejected:* a double of the proposed contract only — it would hide that the published
contract cannot keep the guarantee. *Rejected:* two doubles — one flag, one image.

### D3. Controls are routes, not configuration

Exhaustion at an instant, stale, equal-sequence, regressed, and wrong-transaction
snapshots, delayed and dropped responses, signing-identity rotation with an overlap,
and refusal of a chosen command with a chosen `ApiErrorCode` are control routes a
scenario calls mid-run, so one deal can be driven through a sequence of conditions.
Controls are refused outside the lane profile.

### D4. Evidence class

Every scenario that runs against the extension is recorded in the lane report and in
the closeout of the change that owns it as *qualification against a proposed
contract*; a scenario against the published contract is *qualification against the
published contract*; neither is live evidence, which only the activation follow-on
produces after re-verifying the double against the service's vendored revision.

## Open questions

- Whether the double lives under `kit/arkhai-payments/fixtures`, as the fake does, or
  as a tooling project the lanes build; settled in design against
  `BUILD_AND_PACKAGING.md`'s image rules.
- The snapshot frame the double signs is reconciled against the service's published
  vector in `settle-ongoing-compute-through-arkhai-payments`' design session; if the
  service publishes none, that change names the blocker.

## Implementation cadence (recommended)

One round: the double with both contracts and its controls, the lane wiring, and the
existing bare-metal and credits payment scenarios running against it. One session.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1–D4 | `openspec/specs/test-compatibility/spec.md`; `docs/development/TESTING.md`, "Payment Receipts in Tests" and "Private Service Dependencies" |
