## Why

Deterministic round-robin is predictable but does not account for unequal pool capacity, heterogeneous request shapes, competing consumers, utilization, topology, priority, or historical allocations. The multidimensional capacity baseline now provides accurate fit inputs, so richer placement can be designed independently without keeping completed admission work open.

## What Changes

- Define the fairness subject and scope before selecting an algorithm.
- Evaluate maintained scheduler libraries and compare candidate policies through simulation.
- Specify ordering among hard fit, fairness, utilization, spreading, cost, topology, quotas, priorities, and deterministic tie-breaking.
- Define persistence, concurrency, restart recovery, decay, starvation, indivisible-resource, exact-resource, and provider-failure semantics.
- Implement a second `SettlementSchedulingPolicy` beside deterministic round-robin only after those decisions are approved.
- Add operator-safe policy explanations, metrics, and adversarial/concurrency/restart evidence.
- Keep request, assignment, provider, and storefront contracts unchanged.

This change is design-gated and is not implementation-ready until the open policy decisions are resolved.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `fulfillment`: Add requirements for a pluggable multidimensional policy, concrete-candidate fit before fairness, deterministic tie-breaking, durable policy state, and operator-safe explanations.

## Non-Goals

- Rework authoritative multidimensional admission or the shared feasibility predicate.
- Make VM shape buyer-negotiable.
- Aggregate unrelated resource rows to manufacture a schedulable bundle.
- Move provider health, credentials, or execution checks into placement policy.
- Replace round-robin before a second policy is specified and validated.
- Adopt an external scheduler's worker, queue, control-plane, or cluster-lifecycle model merely to reuse a scoring function.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Accepted policy semantics, persistence rules, explanation contract, and evidence belong in `openspec/specs/fulfillment/spec.md`.
- Repository-wide architecture changes are required only if the selected policy changes authority, dependency, or deployment boundaries.

## Impact

- Likely code: `kit/fulfillment` policy protocol and implementations, compute lifecycle persistence, and scheduling observability.
- Tests: policy simulations, deterministic/adversarial shapes, concurrency, restart recovery, starvation, and exact-resource accounting.
- Persistence: expected transactional policy/history state; exact schema is blocked on policy selection.
- APIs and provider contracts: no intended wire break.
