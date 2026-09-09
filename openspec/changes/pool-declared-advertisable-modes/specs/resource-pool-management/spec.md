## ADDED Requirements

### Requirement: Pool-declared advertisable modes

Each Resource Pool MAY declare the set of offering modes its listings may
advertise under the domain-neutral `advertisable_modes` policy tag. The shared
resource-pool capability MUST validate this declaration as a JSON-compatible set
of unique, non-empty strings and expose typed resolution and membership behavior
without defining which names are meaningful to a domain. An absent or empty
declaration authorizes no mode and MUST NOT be widened by a default.

Advertisement authorization is a separate claim from delivery authorization. A
pool MUST NOT be required to prove it can deliver a mode in order to advertise
it, and `deliverable_modes` MUST retain its existing meaning, derivation, and
every execution recheck unchanged.

Where a Resource Pool is capacity-backed, its declared advertisable set MUST be a
subset of its declared deliverable set, enforced both when the declaration is
written and when a projection carrying it is ingested. Where a Resource Pool is
unbacked, its advertisable set MUST be independent of its deliverable set, which
will ordinarily be empty.

Create, replace, patch, bulk import, projection, and canonical export MUST use the
existing policy-tag channel and precedence. An existing pool's initial
advertisable set MUST be derived from its proved deliverable set, so that no
pool's advertising surface changes on upgrade, and each derived set MUST be
reported at INFO.

#### Scenario: An execution-less pool advertises a mode

- **GIVEN** an unbacked Resource Pool whose provider configuration proves no deliverable mode
- **WHEN** an operator declares `advertisable_modes: [vm]`
- **THEN** typed resolution returns exactly that mode
- **AND** the declaration is not narrowed by the absence of a deliverable proof

#### Scenario: A backed pool advertises beyond what it delivers

- **GIVEN** a capacity-backed Resource Pool declaring `deliverable_modes: [bare_metal]`
- **WHEN** an operator declares `advertisable_modes: [bare_metal, vm]`
- **THEN** the declaration is rejected
- **AND** the pool's existing advertisable set is unchanged

#### Scenario: A projection carries a widened backed declaration

- **WHEN** an ingested projection carries a capacity-backed pool whose advertisable set exceeds its deliverable set
- **THEN** ingestion rejects that pool's declaration rather than accepting a set the writing side would have refused

#### Scenario: Declaration is absent

- **WHEN** a Resource Pool has no `advertisable_modes` tag
- **THEN** typed resolution returns an empty set and the pool authorizes no mode for advertisement

#### Scenario: An existing pool is migrated

- **GIVEN** a Resource Pool whose proved deliverable set is `[vm]` and which has no advertisable declaration
- **WHEN** migration derives its initial advertisable set
- **THEN** the derived set is exactly `[vm]`, that conclusion is reported, and the pool's advertising surface is unchanged
