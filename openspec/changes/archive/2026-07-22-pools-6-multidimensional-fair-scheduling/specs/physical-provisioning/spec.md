# Physical provisioning future delta

## ADDED Requirements

> These requirements are provisional — see proposal.md's "Status of the
> requirement delta" note. POOLS-6 must resolve the documented Non-Work
> decisions in a dedicated design session before implementation or
> archival.

### Requirement: Pluggable multidimensional policy

The `SettlementSchedulingPolicy` boundary SHALL remain capable of supporting a multidimensional scheduling policy without changing Capacity Settlement Assignment identity or provider-facing settlement contracts.

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

#### Scenario: Tie-break is deterministic

- **GIVEN** two or more candidates with identical fairness scores
- **WHEN** the policy selects among them
- **THEN** the same input state always yields the same selected candidate.

#### Scenario: Selection is explainable

- **GIVEN** a completed policy selection or a policy failure to find a candidate
- **WHEN** an operator inspects the decision
- **THEN** the recorded explanation identifies which candidates were eligible, the score inputs considered, the fairness scope applied, and the resulting choice or reason for no choice.
