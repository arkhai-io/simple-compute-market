# Physical provisioning future delta

## PROPOSED Requirements — not yet approved or implemented

### Requirement: Pluggable multidimensional policy

A future physical-provisioning scheduler MAY support multidimensional scheduling policies behind the existing `SettlementSchedulingPolicy` boundary without changing Capacity Settlement Assignment identity or provider-facing settlement contracts.

#### Scenario: Second policy proves interface generality

- **GIVEN** deterministic round-robin and a future multidimensional policy
- **WHEN** either policy is injected into the scheduler
- **THEN** reservation validation, idempotency, eligibility, assignment persistence, and physical settlement use the same orchestration contracts.

### Requirement: Concrete candidate fit precedes fairness

A future multidimensional policy SHALL select only a concrete resource or explicitly modeled resource bundle that satisfies every required dimension.

#### Scenario: Pool aggregates fit but no resource fits

- **GIVEN** aggregate pool capacity sufficient across multiple unrelated resources
- **AND** no one concrete candidate satisfies the reservation shape
- **WHEN** scheduling is evaluated
- **THEN** the pool is not treated as an eligible placement solely because its aggregate totals fit.

### Requirement: Deterministic and explainable selection

A future fair policy SHALL define deterministic tie-breaking and produce an operator-safe explanation of eligibility, score inputs, fairness scope, and the selected candidate.

> These requirements remain proposed. POOLS-6 must resolve the documented Non-Work decisions before approval or implementation.
