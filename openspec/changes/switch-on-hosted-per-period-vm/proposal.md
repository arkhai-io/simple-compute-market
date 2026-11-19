## Why

`serve-running-rate-deals` services on-demand and spot deals in both compute lanes
against the lane doubles, but no shipped configuration offers them, nothing tells a
seller how to or a buyer what they get, and nothing has compared the hosted payment and
dispute authorities with the doubles the lanes rely on. The payments service documents
rate execution as implemented, and its hosted mediation rules a payee's delivery-end
filing mechanically; SCM's lanes cannot yet produce a dispute authority's stop on a rate
deal, because the mediation double executes only reversals.

This change is the last of Goal 8's MVP changes, after
`drive-the-storefront-clock-in-lanes` and `serve-running-rate-deals`. It takes the VM
switch-on from
[`activate-per-period-compute-servicing`](../activate-per-period-compute-servicing/).
Turning the MVP on does not complete Goal 8.

## What Changes

- **A documented, supported switch-on.** The seller quickstart explains offering
  on-demand and spot VM: the recurring clause, the declaration `[charged, returned]`
  with no setup charge, the clause's delivery deadline and dispute window, withdrawal and
  payout timing. The VM storefront chart ships a production example doing the same. The
  buyer quickstart explains the options, the default refusals, funding and the dispute
  remedy. No code gate is added; withdrawal is the seller removing the declaration.
- **A delivery deadline from the seller's payments clause, as a stopgap**, enforced by
  the storefront and retired by `renewable-compute-lease-deadlines`.
- **Ruling side effects on the doubles.** The mediation double executes a ruling's
  `stop` and `penalty`, and the VM lane runs a seller's filing and a buyer's contested
  case on rate deals, each ruled with an authority stop, proving what the storefront does
  after a ruling.
- **Live verification as boundary comparisons.** Six VM live scenarios — the buyer's
  stop, funds running out, a spot preemption, the term end, a seller's filing and a
  buyer's contested case ruled by a topology's policy — give the hosted authorities the
  inputs their lane twins gave the doubles and compare the outputs through shared
  assertions, on wall time with mock provisioning. Each states its topology requirements
  in prose; the deployment prepares a topology meeting them, runs them and records the
  sanitized evidence in the change.
- **Storefront operator runbooks**: an abandoned lease, committed reservations past
  their deadline, draining before a receipt key change, and what each dispute outcome
  shows a seller operator.

## Capabilities

### Modified Capabilities

- `test-compatibility`: the live verification form, topology requirements in prose, the
  six live scenarios, the two lane rows and the mediation double's `stop` and `penalty`.
- `deployment-state`: the VM storefront chart's production example.

### New Capabilities

None.

## Non-Goals

- Bare metal, setup charges, `prorated`, and Goal 8's completion bar, which stay with `activate-per-period-compute-servicing`.
- Any release, or declaring anything in production: creating a release is independent of any change, and production is the latest release.
- Naming or preparing a hosted target; the deployment prepares topologies from the stated requirements.
- Any SCM dependency on the dispute authority's operator API, or tests of the interaction between mediation and payments, which the payments service's own live verification covers.
- Hosting the dispute authority's policy or operator procedures, which stay with the authority.
- A pre-written fallback for a failed live comparison.
- A site-enforced delivery deadline (`renewable-compute-lease-deadlines`).
- Re-anchoring running deals across a receipt key change; the runbook drains instead.
- The payments service's production readiness.

## Impact

- Documentation: the seller and buyer quickstarts, the operator handbook's storefront runbooks, the VM chart's production example, and the corrected caveats in `settlement-configuration`'s companion and `deal-lifecycle`'s architecture.
- Test tooling: the mediation double (`stop`, `penalty`), two VM lane rows, `LaneTime`'s wall-time case, and six live scenarios with their requirements in `e2e-tests/README.md`.
- No wire, database or service configuration change; no compatibility is owed, since no release carries rate servicing.

## Dependencies and Related Changes

- Depends on `serve-running-rate-deals` (archived).
- Takes the mediation double's `stop` execution from `converge-ongoing-compute-leases`; its index row and Goal 8 gap are edited in implementation.
- Live verification waits for the deployment to prepare a topology meeting the stated requirements and record the evidence; the buyer's contested case needs a topology applying a ruling policy and may close out unproven.
- Production is gated externally on the payments service going live.
- Parts taken from `activate-per-period-compute-servicing` (task numbers in its `tasks.md`): 1.1, 1.2, 1.3a's policy in the form D11 leaves it, 2.3–2.4 as topology requirements, 3.1, 3.1a and 3.2 (live scenarios, VM only), 3.3 (the VM production example), 3.4 (withdrawal, already a requirement).

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `test-compatibility`, `deployment-state`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `docs/seller-quickstart.md` and the VM chart's production example — the supported switch-on and its withdrawal; `settlement-configuration`'s companion and `deal-lifecycle/architecture.md` — the corrected hosted-qualification caveat.
- D2: `docs/guidance/workflow/changes.md`, a new section "A change cuts no release" — creating a release is independent of any change, and no change declares anything in production.
- D3: `docs/guidance/engineering/system-tests.md`, "Locally verifiable and external-topology scenarios" — the repository declares a live scenario's topology requirements without naming infrastructure, and the deployment prepares topologies from them; `docs/development/TESTING.md`, a new "Live verification" under "4. System Integration Tests (End-to-End)" — this repository's form.
- D4: `docs/guidance/engineering/system-tests.md` — a live test's provisioning mode follows what it proves; `test-compatibility`'s companion — `LaneTime.reach`'s wall-time case.
- D5: `docs/guidance/engineering/test-doubles.md`, "A double mirrors its producer", and `docs/development/ARCHITECTURE.md`, "Authority boundaries" — no dependency on an endpoint the producer's public client lacks; past it, the producer's own live tests qualify; `docs/guidance/engineering/system-tests.md` — a person's decision comes from a topology policy or the test.
- D6: `docs/guidance/engineering/system-tests.md`, "Locally verifiable and external-topology scenarios" and "A scenario is a sequence of state changes" — the live verification form, its shared assertion, failure on difference, the caller's balance reset and cleanup, and bounded polling of a live producer; `docs/guidance/engineering/test-doubles.md`, "A double mirrors its producer" — asynchronous producer decisions by polling and by inbound call (that logic downstream of an uncreatable side effect is proven on amendable doubles is already covered there, so it is not promoted again); `test-compatibility`'s spec and companion ("The in-lane mediation double", "Payment evidence ownership") and `docs/development/TESTING.md` — the double's `stop` and `penalty` and the lane rows.
- D7: `openspec/specs/settlement-configuration/configuration.md`, "Settlement consumer configuration and cutover", and `docs/seller-quickstart.md` — the clause deadline as the storefront-enforced stopgap `renewable-compute-lease-deadlines` retires.
- D8: `test-compatibility` and `deployment-state` specifications, by archive.
- D9: `docs/attachments/switch-on-hosted-per-period-vm/` — the live evidence summary; `docs/development/ROADMAP.md` Goal 8 cites it.
- D10: `docs/seller-quickstart.md` and `docs/buyer-quickstart.md`.
- D11: `docs/operator-handbook.md` — the storefront runbooks; `deal-lifecycle/architecture.md` — the key-stability assumption.
- D12: no permanent destination — the implementation cadence governs this change's rounds only.
- D13: `docs/guidance/engineering/system-tests.md`, "Locally verifiable and external-topology scenarios" — a mode earns its own scenario only where it makes the external party run different code, with an example; `docs/development/TESTING.md`, "Live verification" — where this repository's requirements live. That requirements start as prose read with judgement is not promoted, on the owner's word.
- D14: no permanent destination — a decision about this change's handling of a failed live comparison.
