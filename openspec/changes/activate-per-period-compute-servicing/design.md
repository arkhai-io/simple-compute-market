# Design

Recorded at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
on the goal's fourth review round, so the external blocker has a row. The change is
blocked in design until the payments service publishes the billing horizon; its
design session begins by reading the revision as vendored and may reopen anything
below with a finding.

## Context

To be verified when the block lifts.

- The requirement: `settle-ongoing-compute-through-arkhai-payments` D5 and its
  "Requests to the payments service" §1.
- The double's proposed extension: `add-arkhai-payments-lane-double` D2.
- The dark posture and its three doors: `converge-ongoing-compute-leases` D1 and D9;
  `negotiate-open-ended-compute-terms` D9; `settle-ongoing-compute-through-arkhai-payments`
  D10.
- The evidence classes: qualification against a proposed contract, qualification
  against the published contract, live evidence (`add-arkhai-payments-lane-double`
  D4).

## Goals / Non-Goals

**Goals:** the per-period products are on, with live evidence, and the goal is
complete.

**Non-Goals:** any product change.

## Decisions

### D1. Verify the double before trusting anything built against it

The first task is to re-run the vendored vectors against the double and list every
divergence between the proposed extension and the published revision; every
divergence is a finding against the change that relied on it before servicing is
declared. This is why qualification against a proposed contract was kept as a named
evidence class apart from live evidence.

### D2. The declaration flips once, in production profiles

Per-period servicing is declared against the `published` contract in both compute
compositions' production profiles; the lane-only `proposed` declaration is retired
when the revision makes the double's extension flag redundant, else kept for
scenarios the revision does not yet cover. Nothing else in the product changes.

### D3. Completion is this change's closeout

The goal's completion criterion is this change's closeout: every per-period scenario
recorded as live evidence, the roadmap updated, the scenario diagrams promoted.

## Open questions

- Whether the revision carries a post-stop correction, which decides what the
  `refund` journal kind drains into; read from the vendored schema.
- Whether the lane's `proposed` declaration survives; decided in D2 against the
  revision.

## Implementation cadence (recommended)

One round: vendoring and verification, the kit adjustments, the declaration, the
live runs, the documentation. One session.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1 | `openspec/specs/test-compatibility/spec.md` |
| D2 | `settlement-configuration` spec; `DEPLOYMENT_AND_CONFIG.md` |
| D3 | `ROADMAP.md`, Goal 8 |
