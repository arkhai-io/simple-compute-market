## ADDED Requirements

### Requirement: The filter grammar can compare exact decimal values

The filter specification MUST support a declared value type whose wire and stored
representation is a decimal-text string and whose comparison domain is exact
decimal. Range bounds declared under it MUST be parsed as exact decimals, resolved
listing values MUST be accepted when they are decimal text, and comparison MUST
NOT pass through a binary floating-point representation at any point.

The type is domain-neutral: it names no market, field, or unit, and any
specification may declare it for any decimal quantity.

The existing JSON-number value type MUST be left unchanged. Retyping its
comparison domain would alter the meaning of filters that other deployments'
specifications already declare, so exact decimal comparison MUST be a distinct
declared type that a specification opts into.

A registry MUST refuse to load a filter specification declaring a value type it
does not implement, rather than ignoring the declaration. A specification whose
comparison semantics the engine cannot honour MUST NOT be served, because a
silently-ignored type would evaluate every query under semantics the operator did
not declare.

A buyer resource-query compiler MUST render a bound of this type without loss and
MUST resolve its type from the specification like any other.

#### Scenario: A bound compares against a high-precision listing value

- **WHEN** a buyer bounds a query against a decimal-text field and a listing's
  value carries more significant digits than a binary double represents exactly
- **THEN** the comparison is exact and the listing matches or is excluded on its
  true value

#### Scenario: A decimal-text value is compared at the bound

- **WHEN** a listing's decimal-text value equals an inclusive bound exactly
- **THEN** it matches, and it does not match an exclusive bound of the same value

#### Scenario: A registry is given a specification it cannot honour

- **WHEN** a registry configured with an engine that does not implement a declared
  value type loads that filter specification
- **THEN** it refuses the specification rather than serving queries under
  substituted semantics

#### Scenario: The existing number type is unaffected

- **WHEN** a filter declared under the JSON-number value type is evaluated
- **THEN** its behaviour is unchanged by the presence of the decimal type

### Requirement: A filter may declare co-required filters

A filter declaration MAY name other declared filters that MUST be supplied
alongside it. A query supplying a filter without every filter it co-requires MUST
be refused rather than evaluated, because a constraint missing a dimension it
depends on has no interpretation.

The dependency MUST be one-directional: a co-required filter supplied on its own
remains a valid constraint in its own right.

Both the registry and the buyer resource-query compiler MUST resolve
co-requirements from the active filter specification. Neither may encode a
specific field's dependency in code, consistent with the requirement that every
field, operator, type, alias, and missing-value rule is resolved from the
specification and that no domain field is added. The registry's refusal is
authoritative: a buyer that does not understand co-requirements is still refused.

Specification validation MUST reject a co-requirement naming an undeclared filter,
naming its own declaration, or participating in a cycle. Each is a specification
defect that would otherwise surface as a query that can never be satisfied.

A filter declaring no co-requirement MUST serialize, in the served specification
and in the input to its etag, exactly as it would under an engine without this
capability. The etag signals that the semantics a buyer compiled against have
changed; an engine upgrade that changes no specification's semantics MUST NOT
rotate any specification's etag.

#### Scenario: A co-required filter is missing from a query

- **WHEN** a buyer supplies a filter whose declaration co-requires another and
  omits it
- **THEN** the query is refused rather than evaluated against an unstated dimension

#### Scenario: A co-required filter is supplied alone

- **WHEN** a buyer supplies only a filter that others co-require
- **THEN** the query is evaluated normally as a constraint on that field

#### Scenario: A client bypasses compiler validation

- **WHEN** a request reaches the registry supplying a filter without its
  co-requirements, without having been compiled by the buyer client
- **THEN** the registry refuses it

#### Scenario: A specification declares a cyclic co-requirement

- **WHEN** a filter specification declares co-requirements that form a cycle, name
  an undeclared filter, or name their own declaration
- **THEN** specification validation fails rather than the registry serving it

#### Scenario: A specification declares no co-requirement

- **WHEN** a registry whose engine supports co-requirements loads a specification
  that declares none
- **THEN** the served specification and its etag are identical to those an engine
  without the capability produces

### Requirement: The compute schema carries a listing's asking rate

The compute filter specification MUST describe an optional `asking_rate` object on
the published listing resource, carrying `amount`, `asset`, and `period`, all
required when the object is present. `amount` is exact decimal text; `asset` is an
opaque, non-empty identifier of the same kind a settlement option's published asset
carries, requiring no contract address, token decimals, or chain identity; `period`
is the time unit the amount is quoted per, `hour` in this version. The object is a
sibling of the listing's flattened dimension fields and is not nested under a
capability family.

The object is declared in the compute specification, which is data the generic
registry serves, and not in registry engine code. The registry validates it only
where it validates the listing shape today — the dry run — and does not refuse it at
the publish boundary; the storefront that builds the listing is responsible for
publishing only a complete, valid rate. No registry surface may interpret the asset
beyond comparing it for equality.

#### Scenario: A listing is dry-run with a partial asking rate

- **WHEN** a publisher dry-runs a compute listing whose `asking_rate` omits its asset
  or its period
- **THEN** the dry run reports the listing invalid, naming the asking rate

#### Scenario: A rate is quoted in an off-chain asset

- **WHEN** a listing publishes an asking rate in an asset that has no contract
  address, decimals, or chain identity
- **THEN** the registry stores and serves the asset identifier opaquely

### Requirement: Rate filters match the period and asset rather than normalizing across them

The compute filter specification MUST declare exact, fail-on-missing filters over
the asking rate's amount, asset, and period. The amount filters MUST use the exact
decimal comparison type and MUST co-require the asset and period filters, so the
refusal below is declared in the specification rather than encoded in the registry
or the buyer client.

A rate-bounded query MUST name the asset and the period it asks about, and MUST be
refused rather than evaluated when either is absent: a bare bound states neither
what is being counted nor per what.

A listing quoting a different period MUST be excluded rather than converted,
because a period signals the commitment a seller expects: a buyer shopping hourly
is not asking for supply quoted monthly.

A listing quoting a different asset MUST likewise be excluded rather than
converted. Converting between assets requires an external exchange rate that moves
continuously, which would make one query's result depend on when it ran and would
make the registry an authority on relative asset value.

A listing publishing no rate MUST be excluded from a rate-bounded query rather than
matching it, consistent with every other filter over the published listing shape. An
unstated rate has not been shown to satisfy a stated bound.

#### Scenario: A buyer bounds a query by rate

- **WHEN** a buyer queries for listings at or below a rate in a named asset and period
- **THEN** only listings quoting that asset and period and satisfying the bound are returned

#### Scenario: A rate bound names no asset or no period

- **WHEN** a buyer submits a rate bound without an asset, or without a period
- **THEN** the query is refused rather than evaluated against an unstated dimension

#### Scenario: A listing quotes a different period

- **WHEN** a listing quotes its rate in a period the query did not name
- **THEN** it is excluded rather than converted into the queried period

#### Scenario: A listing quotes a different asset

- **WHEN** a listing quotes its rate in an asset the query did not name
- **THEN** it is excluded rather than converted into the queried asset

#### Scenario: A listing publishes no rate

- **WHEN** a buyer bounds a query by rate and a listing publishes none
- **THEN** that listing is excluded from the result

#### Scenario: A rate bound compares exactly

- **WHEN** a listing's asking amount carries more significant digits than a binary
  double represents exactly and a buyer bounds a query near it
- **THEN** the listing is matched or excluded on its exact value
