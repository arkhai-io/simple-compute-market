## ADDED Requirements

### Requirement: Capacity shape admissibility

A site authority MUST expose, for a given resource pool, whether a complete proposed
capacity shape is admissible, and what range remains admissible for a single dimension
given the remainder of a proposed shape. Both answers MUST accept the whole proposed
shape as input so an implementation MAY let one dimension's admissible range depend on
the others. The authority MUST NOT expose per-dimension bounds as a value callers read
and compare themselves. Admissibility MUST be answered from declared pool policy and
MUST be independent of current availability. A pool that declares no bounds MUST admit
any shape.

#### Scenario: Whole shape is evaluated

- **WHEN** a complete proposed capacity shape is evaluated for a pool
- **THEN** a single admissibility decision is returned for the shape as a whole

#### Scenario: Admissible range is requested for one dimension

- **WHEN** the admissible range for one dimension is requested together with the rest of
  a proposed shape
- **THEN** the range returned is valid for that remainder, and the caller does not
  reconstruct it from separately readable bounds

#### Scenario: Shape is admissible but nothing is free

- **WHEN** a shape is within a pool's declared bounds while the pool currently has no
  capacity available for it
- **THEN** it is reported admissible, and unavailability is reported separately rather
  than as inadmissibility

#### Scenario: Pool declares no bounds

- **WHEN** admissibility is evaluated for a pool with no declared bounds
- **THEN** every shape is admissible

#### Scenario: Bounds are declared for a domain-specific dimension

- **WHEN** a domain declares bounds for a dimension in its own vocabulary
- **THEN** the authority validates only that the bound is well formed, without knowledge
  of that dimension's meaning
