## 1. Resolve Policy Design

- [ ] 1.1 Confirm the fairness subject and fairness scope with stakeholders and update `proposal.md`, `design.md`, and `specs/fulfillment/spec.md`.
- [ ] 1.2 Specify pool weighting and precedence among fit, fairness, utilization, spreading, cost, and topology.
- [ ] 1.3 Specify indivisible resources, quotas, priorities, preemption, fallback, and starvation behavior.
- [ ] 1.4 Specify historical accounting, persistence, decay, restart recovery, and exact-resource accounting.
- [ ] 1.5 Specify provider-failure and explicit-reassignment behavior.
- [ ] 1.6 Identify exact implementation paths and schema changes after the policy is selected; do not begin implementation before tasks 1.1–1.5 are approved.

## 2. Evaluate Candidate Policies

- [ ] 2.1 Build deterministic workload traces covering unequal pools, heterogeneous and adversarial shapes, indivisible resources, exact-resource requests, and topology constraints.
- [ ] 2.2 Evaluate maintained external scheduler libraries against `market_fulfillment.SettlementSchedulingPolicy` and reject dependencies requiring unrelated runtime machinery.
- [ ] 2.3 Compare lowest projected dominant utilization, capacity-weighted pool fairness, and consumer-aware DRF using the same traces.
- [ ] 2.4 Record the selected policy, rejected alternatives, metrics, and explanation schema in `design.md` and the fulfillment delta.

## 3. Implement the Approved Policy

- [ ] 3.1 Add the second policy under `kit/fulfillment/src/market_fulfillment/` without changing request, assignment, or provider contracts.
- [ ] 3.2 Add additive persistence for policy/history state and commit it transactionally with capacity claims and assignments in the owning compute lifecycle.
- [ ] 3.3 Add explicit composition/configuration that preserves deterministic round-robin as rollback.
- [ ] 3.4 Add durable operator-safe decision explanations and metrics.

## 4. Verify Behavior

- [ ] 4.1 Add focused policy unit tests for complete fit, stable tie-breaking, unequal pools, exact-resource accounting, and explanation redaction.
- [ ] 4.2 Add simulation evidence for convergence, starvation boundaries, quotas/priorities, and adversarial request shapes.
- [ ] 4.3 Add concurrency and restart integration tests proving accepted assignments and fairness history are not recomputed or double-counted.
- [ ] 4.4 Run fulfillment, site-capacity, compute-service integration, typing, wheel, and strict OpenSpec validation.

## 5. Promote Accepted Design

- [x] 5.1 **Withdrawn** 2026-10-14: closeout does this — the archive in 6.11 writes the `fulfillment` spec its delta covers, and 6.9 writes the architecture companion. As first planned: Merge implemented policy, persistence, explanation, and evidence requirements into `openspec/specs/fulfillment/spec.md`.
- [ ] 5.2 Update `docs/development/ARCHITECTURE.md` only if authority, dependency, or deployment boundaries changed.
- [ ] 5.3 Add the design-promotion record and remove temporary change provenance from production comments and docstrings.
- [ ] 5.4 **Comment hygiene and import placement, before the pre-closeout review.** Run `make check-comment-hygiene` and read the comments this change added for any that narrate the review or migration that introduced them; move each import the change added to module level unless a verified circular import or a recorded lazy-load reason keeps it local. Closeout only confirms both.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read the comments this change added for any that narrate the review or migration that introduced them. Do not edit code here: anything to rewrite returns the change to implementation.
- [ ] 6.2 **Import placement — confirm.** Check the imports this change added for any still local without a recorded reason. One that should move returns the change to implementation.
- [ ] 6.3 **Documentation compliance.** Re-check this change's accepted decisions against `openspec/README.md`'s placement rules, and the permanent documents against the code they describe. Durable conceptual rationale for the `fulfillment` policy sits in its companion `architecture.md` rather than only in `design.md`.
- [ ] 6.4 **Narrative compression.** Compress completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations, moving durable rationale into `design.md` first.
- [ ] 6.5 **Roadmap currency.** Update the affected goal's current state and gap mapping in `docs/development/ROADMAP.md`, or record that no goal is affected. This change sits under the lesser goal “POOLS capacity and fulfillment foundation”, which has no roadmap goal behind it, so it most likely owes the roadmap nothing; confirm that and record the no-impact disposition explicitly.
- [ ] 6.6 **Campaign index currency.** Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md`, or record that both are unchanged. Other rows' `Depends on` are left alone: archive cleanup releases dependents after the closeout gate.
- [ ] 6.7 **Packaging.** Run `make check-packaging` and resolve every failure it reports (a failure needing a code or lock change returns the change to implementation).
- [ ] 6.8 **End-to-end pipeline.** Record the passing run the latest validation names, its result, and the scenarios that exercise this change, or an explicit blocker naming its cause and the change that owns it, with the validations it gates treated as unrun.
- [ ] 6.9 **Promotion.** Write the permanent documents this change owes — `openspec/specs/fulfillment/architecture.md` (the selected policy's rationale and rejected alternatives) and `docs/development/ARCHITECTURE.md` only if authority, dependency, or deployment boundaries changed — and complete the design-promotion record, mapping every accepted decision to its exact permanent heading; verify no production source references this change's directory. A `spec.md` the deltas cover (`openspec/specs/fulfillment/spec.md`) is written by the archive in 6.11, not by hand; the record names it all the same.
- [ ] 6.10 **Documentation citations.** After promotion, run `make check-doc-citations CHANGE=pools-6-fair-scheduling-policy` and resolve every match, then `openspec validate pools-6-fair-scheduling-policy --strict`.
- [ ] 6.11 **Archival.** Last, once every other part is checked: `openspec archive pools-6-fair-scheduling-policy -y` merges the deltas into `openspec/specs/` and moves the change under `openspec/changes/archive/`; point the index row at the archived directory, and run `openspec validate --specs --strict`.
