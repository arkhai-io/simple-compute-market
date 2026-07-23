## Context

`indexed` is parsed, serialized, and included in filter-spec identity but intentionally ignored; all configured filters currently leave it false. Listing queries load status/publisher candidates and evaluate JSONPath predicates in Python. No current benchmark or telemetry establishes an indexing need.

## Goals / Non-Goals

**Goals:** retain a precise activation gate and semantic constraints for future PostgreSQL indexing.

**Non-Goals:** select an index design before PostgreSQL schema and workload evidence exist.

## Decisions

### Keep the change deferred and taskless

Activation requires a named representative dataset/query mix whose p95 listing latency exceeds an accepted SLO. Evidence must include cardinality and filter distribution so optimization can be reproduced. Parser support alone is not activation evidence.

### Design against PostgreSQL after rollout

When activated, compare expression indexes, generated columns, normalized side tables, and GIN indexes against the finalized PostgreSQL schema and migration conventions. The old cross-dialect generated-column sketch is not binding.

### Preserve filter semantics

Indexed execution must match Python evaluation for scalar/array projection, missing values, strict mode, set/range/existence operators, updates/deletes, double-encoded legacy JSON, and filter-spec identity. Dynamic YAML declarations cannot create/drop schema at runtime; migrations own durable index artifacts.

## Risks / Trade-offs

- **[Premature indexes increase write/migration cost]** → Require measured activation.
- **[Indexed and Python semantics diverge]** → Run one conformance corpus through both paths before enabling.
- **[Filter spec changes without matching migration]** → Reject/ignore indexed activation until deployed schema advertises support.

## Activation Record Required

- PostgreSQL version/schema head.
- Dataset cardinality and payload distribution.
- Named query workload and current p50/p95/p99.
- Accepted SLO/threshold and observed breach.
- Selected index design, write amplification, migration/rollback, and semantic conformance evidence.

## Permanent Documentation Promotion

No current behavior is promoted. If activated, indexed execution and fallback semantics belong in `openspec/specs/registry-discovery/spec.md` and rationale in `architecture.md`; schema/deployment rules also belong in `deployment-state` where material.
