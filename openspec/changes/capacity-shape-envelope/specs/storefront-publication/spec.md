## ADDED Requirements

### Requirement: A storefront resolves shape bounds per field across its tiers

A storefront that publishes capability shapes SHALL resolve shape bounds for each
offering mode it publishes from three tiers, highest first: its site-scoped pool
override, the pool's `shape_bounds` hint, and its configured default. Tiers SHALL merge
per leaf of the `bounds` section: for each field's `min` and `max`, the highest tier
stating it wins, and a tier that does not state a leaf SHALL leave a lower tier's value
in place. A higher tier MAY replace a lower tier's value, including with a wider one, and
SHALL NOT remove it. A field no tier bounds SHALL NOT be constrained by admissibility.
The resolved bounds are the storefront's own policy; site admission is not changed by
them. A malformed configured default SHALL prevent the storefront from starting.

#### Scenario: An override narrows one leaf

- **WHEN** a pool hint bounds `gpu.count` from 1 to 8 and the storefront's override
  states only a maximum of 4
- **THEN** the resolved bound for `gpu.count` is 1 to 4

#### Scenario: An override widens a site bound

- **WHEN** the override states a larger maximum for a field than the pool hint
- **THEN** the override's maximum applies

#### Scenario: A configured default fills a field the pool leaves unbounded

- **WHEN** the pool hint does not bound `memory.gib` and the configured default does
- **THEN** the configured default's bound applies to `memory.gib`

#### Scenario: No tier bounds a field

- **WHEN** no tier states a bound for a field
- **THEN** admissibility does not constrain that field

### Requirement: Unusable or empty shape bounds close the pool's listings

Where the resolved bounds for a pool and mode leave a field's range empty, or where any
tier's declaration cannot be read or evaluated — malformed, naming a path the domain's
schema does not define as a quantity, or carrying a section or key the storefront's kit
does not define — the storefront SHALL close the pool's open listings for that mode,
SHALL publish nothing from the pool for that mode, and SHALL refuse any revised shape
for it, until the declaration is usable. A pool whose projection has not loaded SHALL
keep the existing hold rather than close. The storefront SHALL report the tier, the
path, and the problem, or the conflicting values of an empty range, per site in its
derivation report served by system status.

#### Scenario: The merged range is empty

- **WHEN** the pool hint states a minimum of 4 for `gpu.count` and a stored override
  states a maximum of 2
- **THEN** the pool's listings close and the report names both tiers and values

#### Scenario: The pool declares a section the storefront does not know

- **WHEN** a pool's `shape_bounds` carries a section the storefront's kit does not define
- **THEN** the pool's listings close and the report names the section

#### Scenario: The site projection has not loaded

- **WHEN** a configured site's projection has never loaded
- **THEN** its listings are held, not closed

### Requirement: Publication never advertises an inadmissible shape

A stated listing shape — from the storefront's override or the pool's `listing_shapes` —
that is inadmissible under the resolved bounds SHALL NOT be published, an open listing
for it SHALL close, and the storefront SHALL report it per site with its source tier and
problems. The VM default generator SHALL generate only shapes admissible under the
resolved bounds, choosing values from the admissibility kit's admissible values rather
than generating and filtering, and generated shapes SHALL NOT be reported. Bare-metal
publication SHALL judge each Physical Resource's derived shape against the resolved
bounds for its mode in the same way. A storefront pool override write SHALL be refused
when its own listing shapes would be inadmissible under the resolution it produces, or
when it would empty a field's range against the pool's current hint.

#### Scenario: A stated shape exceeds a bound

- **WHEN** a pool's `listing_shapes` include a shape with more GPUs than the resolved
  maximum
- **THEN** that shape is not published, an open listing for it closes, and it is
  reported with its tier and problems

#### Scenario: The default generator meets a bound

- **WHEN** a pool states no listing shapes, its members hold 8 GPUs, and the resolved
  maximum for `gpu.count` is 4
- **THEN** the default generator yields shapes of 1 to 4 GPUs and nothing is reported

#### Scenario: A bare-metal resource exceeds a bound

- **WHEN** a Physical Resource's derived shape is inadmissible under the resolved bounds
  for the bare-metal mode
- **THEN** no listing is published for it, an open one closes, and it is reported

#### Scenario: An override would empty a range

- **WHEN** a storefront administrator writes an override stating a maximum below the
  pool hint's minimum for that field
- **THEN** the write is refused and the stored override is unchanged

#### Scenario: Bounds tighten after publication

- **WHEN** a pool's bounds change so that a published listing's shape is inadmissible
- **THEN** the next reconciliation closes that listing
