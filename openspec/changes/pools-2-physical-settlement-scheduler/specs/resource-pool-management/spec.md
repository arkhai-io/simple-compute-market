## MODIFIED Requirements

### Requirement: Non-destructive pool lifecycle

Pool removal MUST disable the pool rather than delete it. The system-owned
`default` pool MUST always remain present under its configured ID and MUST
remain the fallback for hosts and create requests that omit a pool ID
regardless of its own enabled state; disabling it is otherwise ordinary and
only excludes it from new scheduler selection. The service MUST reject
disabling any pool — including `default` — that has at least one active
settlement-resource binding.

#### Scenario: Operator deletes a non-default pool

- **WHEN** an operator sends DELETE for an existing non-default pool
- **THEN** the service sets `enabled=false` and the pool remains retrievable by ID

#### Scenario: Operator disables the default pool

- **WHEN** an operator sends DELETE, PUT, or PATCH that disables `default` and it has no active settlement-resource binding
- **THEN** the service sets `enabled=false`, `default` remains retrievable by ID, and hosts or create requests that omit a pool ID still resolve to it

#### Scenario: Operator disables a pool with an active settlement-resource binding

- **WHEN** an operator sends DELETE, PUT, or PATCH that would disable a pool — including `default` — with at least one active settlement-resource binding
- **THEN** the service rejects the operation and the pool remains enabled
