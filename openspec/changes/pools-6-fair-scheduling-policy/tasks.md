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

- [ ] 5.1 Merge implemented policy, persistence, explanation, and evidence requirements into `openspec/specs/fulfillment/spec.md`.
- [ ] 5.2 Update `docs/development/ARCHITECTURE.md` only if authority, dependency, or deployment boundaries changed.
- [ ] 5.3 Add the design-promotion record and remove temporary change provenance from production comments and docstrings.
