## ADDED Requirements

### Requirement: Pluggable multidimensional policy
The `SettlementSchedulingPolicy` boundary SHALL support a multidimensional scheduling policy without changing capacity-settlement assignment identity, physical-settlement requests, or provider-facing contracts. Deterministic round-robin SHALL remain available as a compatibility and rollback policy.

#### Scenario: Second policy proves interface generality
- **WHEN** deterministic round-robin or the configured multidimensional policy is injected into the scheduler
- **THEN** reservation validation, idempotency, eligibility, assignment persistence, and provider execution use the same orchestration contracts

### Requirement: Concrete candidate fit precedes fairness
A multidimensional policy MUST receive only concrete resources or explicitly modeled resource bundles that satisfy every required dimension. Aggregate capacity across unrelated resources MUST NOT establish eligibility.

#### Scenario: Pool aggregates fit but no resource fits
- **WHEN** aggregate pool capacity is sufficient across unrelated resources but no concrete candidate satisfies the complete reservation shape
- **THEN** the pool is not eligible solely because its aggregate totals fit

### Requirement: Deterministic durable policy selection
A policy MUST define stable tie-breaking. Historical accounting or score inputs that affect selection MUST be persisted transactionally with the capacity claim and assignment so retries and restart recovery do not recompute an accepted decision from different state.

#### Scenario: Candidates have identical policy scores
- **WHEN** two or more candidates have identical scores
- **THEN** stable tie-breakers produce the same selected candidate for the same durable input state

#### Scenario: Accepted assignment is retried after restart
- **WHEN** scheduling retries an unchanged reservation after process restart
- **THEN** the existing assignment is returned without advancing fairness history or selecting another candidate

### Requirement: Explainable policy decisions
A fair or utilization-aware policy MUST produce an operator-safe explanation containing policy identity and version, candidate eligibility counts, hard rejection reasons, fairness subject and scope, normalized score inputs, applied weights or constraints, deterministic tie-breaker, and the selected candidate or no-candidate reason. Explanations MUST NOT expose provider secrets.

#### Scenario: Operator inspects a successful selection
- **WHEN** an operator reads the recorded decision explanation
- **THEN** it identifies the eligible set, score inputs, fairness scope, tie-breaker, and selected pool and resource

#### Scenario: Operator inspects a failed selection
- **WHEN** no candidate can be selected
- **THEN** the explanation identifies the applicable hard rejections and policy constraints without exposing provider secrets
