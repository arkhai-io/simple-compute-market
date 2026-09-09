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

Where a Resource Pool declares `capacity_backing: backed`, its declared
advertisable set MUST be a subset of its declared deliverable set, enforced both
when the declaration is written and when a projection carrying it is ingested.
Where a Resource Pool declares `capacity_backing: unbacked`, its advertisable set
MUST be independent of its deliverable set, which will ordinarily be empty.

#### Scenario: An execution-less pool advertises a mode

- **GIVEN** a Resource Pool declaring `capacity_backing: unbacked` whose provider configuration proves no deliverable mode
- **WHEN** an operator declares `advertisable_modes: [vm]`
- **THEN** typed resolution returns exactly that mode
- **AND** the declaration is not narrowed by the absence of a deliverable proof

#### Scenario: A backed pool advertises beyond what it delivers

- **GIVEN** a Resource Pool declaring `capacity_backing: backed` and `deliverable_modes: [bare_metal]`
- **WHEN** an operator declares `advertisable_modes: [bare_metal, vm]`
- **THEN** the declaration is rejected and the pool's existing advertisable set is unchanged

#### Scenario: A projection carries a widened backed declaration

- **WHEN** an ingested projection carries a backed pool whose advertisable set exceeds its deliverable set
- **THEN** ingestion rejects that pool's declaration rather than accepting a set the writing side would have refused

#### Scenario: Declaration is absent

- **WHEN** a Resource Pool has no `advertisable_modes` tag
- **THEN** typed resolution returns an empty set and the pool authorizes no mode for advertisement

### Requirement: Pool-declared capacity backing

Each Resource Pool MUST be able to declare whether it can be admitted against
under the domain-neutral `capacity_backing` policy tag, whose values are `backed`
and `unbacked`. `backed` means an admission authority stands behind the pool;
`unbacked` means none does, so nothing may be reserved, committed, or released
against it.

`capacity_backing` MUST be fixed at pool creation. Replace and patch MUST reject a
request supplying a backing value differing from the pool's own, and a request
omitting it MUST preserve the stored value rather than resetting it to a replacement
default. Resetting an immutable field to a default is a change to it, so the general
policy-tag replacement semantics — under which an omitted optional tag is reset — do
not reach this tag. This exception derives from immutability, not from the separate
exception for secret provider-configuration fields, which exists because a caller
cannot restate a value a read never returns.

Authoritative document import MUST preserve a stored backing value that the document
omits, for the same reason and so that an old-format document edited and re-imported
after migration does not wipe a migrated tag. Canonical export MUST always emit the
value explicitly, so a round-tripped document carries it.

Where a create request omits `capacity_backing`, the authority MUST record `backed`
explicitly rather than storing an absent value, under a bounded compatibility rule
with a stated removal condition. Every pool therefore carries an explicit value,
which is what the preservation rule above and the projection's completeness
requirement both depend on. Moving inventory
between backed and unbacked supply is a second pool declaring the intended backing
with its capacity resources migrated across — the same shape as moving inventory to
a different executor, and for the same reason: backing is a property every listing
derived from the pool inherits, so changing it in place would silently reinterpret
listings already published.

A value outside that set MUST be rejected on write and MUST fail that pool closed
on projection ingestion. A discriminator MUST NOT resolve to a default: unlike a
cardinality hint, where a structural default is a reasonable assumption about how
many candidates to publish, a backing default would assert whether anything stands
behind a listing.

Create, replace, patch, bulk import, projection, and canonical export MUST use the
existing policy-tag channel and precedence for both this tag and
`advertisable_modes`. A producer that emits either tag MUST emit it for every
Resource Pool it projects, so that a consumer can distinguish a producer that
predates the tag from a producer that omitted it for one pool.

An existing Resource Pool's initial values MUST be derived on upgrade: its
advertisable set from its proved deliverable set, and its backing as `backed`. No
pool's advertising surface or admission behavior may change as a result of the
derivation, and each derived value MUST be reported at INFO.

#### Scenario: An existing pool is migrated

- **GIVEN** a Resource Pool whose proved deliverable set is `[vm]` and which declares neither new tag
- **WHEN** migration derives its initial values
- **THEN** its advertisable set is exactly `[vm]` and its backing is `backed`
- **AND** both conclusions are reported and its advertising surface is unchanged

#### Scenario: Replacement omits backing

- **WHEN** a replace or patch request for an existing pool omits `capacity_backing`
- **THEN** the stored backing value is preserved rather than reset to a replacement default

#### Scenario: An old-format document is re-imported after migration

- **GIVEN** a pool whose backing was recorded by migration
- **WHEN** an authoritative document omitting `capacity_backing` is imported for that pool
- **THEN** the stored backing value is preserved
- **AND** canonical export of that pool emits the value explicitly

#### Scenario: Create omits backing

- **WHEN** a pool is created with no `capacity_backing` value
- **THEN** `backed` is recorded explicitly rather than left absent

#### Scenario: Backing is changed on an existing pool

- **WHEN** a replace or patch request supplies a `capacity_backing` value differing from the pool's own
- **THEN** the request is rejected and the pool's backing is unchanged
- **AND** the supported path is a second pool declaring the intended backing with capacity resources migrated across

#### Scenario: A malformed backing value is written

- **WHEN** an operator declares a `capacity_backing` value outside `backed` and `unbacked`
- **THEN** the declaration is rejected and the pool's existing backing is unchanged

#### Scenario: A malformed backing value is ingested

- **WHEN** an ingested projection carries a pool whose `capacity_backing` value is outside `backed` and `unbacked`
- **THEN** that pool fails closed rather than resolving to either value

#### Scenario: A producer emits the tags incompletely

- **WHEN** a producer emits `capacity_backing` for some Resource Pools and omits it for another it projects
- **THEN** the projection is malformed with respect to this requirement, and the omitted pool is not treated as predating the tag
