## ADDED Requirements

### Requirement: Idempotent physical settlement resource selection

The provisioning service MUST expose a `PhysicalSettlementScheduler` that
binds a `PhysicalSettlementRequest` to exactly one `SettlementResource`,
keyed durably by `allocation_id`, and MUST return the existing binding
rather than selecting a different resource on repeated calls for the same
`allocation_id`.

#### Scenario: Selection is retried for the same allocation

- **WHEN** `select_resource` is called twice with the same `allocation_id`
- **THEN** the second call returns the same `settlement_resource_id` as the first without creating a second binding

#### Scenario: Concurrent selection races for the same allocation

- **WHEN** two concurrent `select_resource` calls race for the same `allocation_id`
- **THEN** exactly one settlement resource binding is created and both callers observe it

### Requirement: Bottleneck-normalized pool selection

When a `PhysicalSettlementRequest` carries fungible pool/capacity
attributes rather than an explicit `resource_id`, the scheduler MUST select
among enabled, eligible pools by the lowest bottleneck resource-dimension
utilization — the maximum of per-dimension utilization ratios across
CPU/RAM/GPU/disk — rather than a static priority ordering.

#### Scenario: One eligible pool is GPU-saturated

- **WHEN** an eligible pool is at high GPU utilization but low utilization on every other dimension
- **THEN** the scheduler prefers another eligible pool whose bottleneck dimension is lower, even if its average utilization is higher

#### Scenario: No eligible pool exists

- **WHEN** every pool matching the request is disabled or exhausted
- **THEN** selection fails with an actionable pool-unavailable error instead of binding a disabled or exhausted pool

### Requirement: Specific-resource request path

A `PhysicalSettlementRequest` MAY carry an explicit `resource_id` instead
of pool/capacity attributes. When it does, the scheduler MUST bind exactly
that resource and MUST NOT substitute a different one. Operator-facing
configuration for opting a listing into this path is not defined by this
requirement.

#### Scenario: Explicit resource_id is honored

- **WHEN** a request supplies `resource_id` instead of pool/capacity attributes
- **THEN** the scheduler binds that `resource_id` or fails outright, without silently substituting a different resource
