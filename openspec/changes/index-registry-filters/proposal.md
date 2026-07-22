## Why

Registry filtering currently narrows status/publisher in SQL and evaluates configured JSONPath filters in Python. The filter spec already accepts `indexed: true`, but no filter uses it and there is no cardinality, workload, p95 latency, or SLO evidence justifying schema-maintained indexes.

## What Changes

- Preserve `indexed` as a forward-compatible declaration while it remains behaviorally inert.
- Define activation only after a named PostgreSQL workload exceeds an accepted listing-query latency threshold at representative cardinality.
- Once activated, design PostgreSQL-native scalar/array indexing and migration/maintenance semantics that preserve every current filter behavior.
- State: **Deferred/conditional; blocked on PostgreSQL rollout and measured threshold evidence. No implementation tasks.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `registry-discovery`: Permit measured PostgreSQL query evidence to activate indexed filter execution without changing filter semantics.

## Dependencies and Related Changes

- Depends on completed `migrate-registry-to-postgres`; SQLite/generated-column sketches are not the target design.
- Requires a benchmark/telemetry change or evidence naming listing cardinality, query mix, p95 latency, and target SLO before activation.

## Non-Goals

- Do not implement indexes because the parser accepts `indexed`.
- Do not change `on_missing`, strict filtering, arrays, range/set/existence operators, or legacy JSON compatibility.
- Do not let runtime filter-spec replacement mutate production schema outside migration governance.

## Impact

No current runtime impact. After activation, work would touch PostgreSQL migrations/index maintenance, filter query planning, metrics/benchmarks, and semantic parity tests.
