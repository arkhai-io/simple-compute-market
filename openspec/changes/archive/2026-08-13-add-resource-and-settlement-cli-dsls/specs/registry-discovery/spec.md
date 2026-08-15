## ADDED Requirements

### Requirement: Resource query compilation preserves filter-spec authority

A buyer resource-query compiler MUST resolve every field, operator, type, alias, and missing-value rule from the active registry filter specification and MUST compile only declared filters into the registry's canonical query input. The compiled request MUST carry the matching filter-spec ETag and all behavior-affecting values in the authenticated semantic body. The compiler MUST NOT add domain fields, reinterpret missing values, or weaken strict filtering.

#### Scenario: Filter specification changes during query construction

- **WHEN** the buyer compiles a resource query under one filter-spec ETag and the registry activates another before execution
- **THEN** the registry rejects the request with HTTP 412 rather than evaluating it under changed semantics

#### Scenario: DSL operator is not declared for a field

- **WHEN** the user applies a range operator to a field whose filter declaration accepts only set membership
- **THEN** the buyer rejects compilation before sending the listing query

### Requirement: Pushdown remains semantic rather than physical

Resource-query explanation MUST identify which canonical predicates are evaluated by the registry and which settlement constraints remain buyer-local. Declaring or compiling a predicate MUST NOT activate database indexing, change the registry HTTP route, or promise a physical execution plan. Any future indexed execution MUST remain semantically equivalent under the separate measured activation contract.

#### Scenario: Query uses an unindexed filter

- **WHEN** a valid DSL comparison compiles to a declared filter whose `indexed` marker is absent or behaviorally inert
- **THEN** the registry evaluates it with current filter semantics and explanation makes no indexing claim
