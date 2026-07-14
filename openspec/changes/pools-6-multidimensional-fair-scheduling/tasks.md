# POOLS-6 tasks

## Design resolution

- [ ] Confirm domain boundaries and whether VM and pod compute share a provisioning domain.
- [ ] Choose the fairness subject and fairness scope.
- [ ] Define multidimensional units, normalization, and concrete resource-bundle semantics.
- [ ] Choose pool weighting and the precedence of fit, fairness, utilization, spreading, cost, and topology.
- [ ] Specify indivisible resources, quotas, priorities, preemption, and starvation behavior.
- [ ] Specify historical accounting, persistence, decay, restart recovery, and exact-resource accounting.
- [ ] Specify provider-failure and explicit reassignment behavior.

## Evaluation

- [ ] Evaluate maintained external scheduler libraries against the policy protocol and operational constraints.
- [ ] Compare lowest projected dominant utilization, capacity-weighted pool fairness, and consumer-aware DRF through simulations.
- [ ] Define policy explanation, metrics, and debugging surfaces.

## Implementation after design approval

- [ ] Add multidimensional requirement and candidate contracts.
- [ ] Implement a second policy beside round-robin to prove interface generality.
- [ ] Persist fairness state transactionally with capacity claims and assignments.
- [ ] Add simulation, concurrency, restart, starvation, and adversarial-shape tests.
- [ ] Promote approved requirements into baseline OpenSpec and update architecture pointers only after behavior becomes current state.
