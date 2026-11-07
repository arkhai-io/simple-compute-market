## ADDED Requirements

### Requirement: Pool-declared advertisable modes

Each Resource Pool MUST declare the set of offering modes its listings may
advertise under the domain-neutral `advertisable_modes` policy tag. The shared
resource-pool capability MUST validate this declaration as a JSON-compatible set
of unique, non-empty strings without defining which names are meaningful to a
domain. An empty declaration authorizes no mode, and neither an empty nor an
absent declaration MAY be widened by a default. Membership MUST be offered only on
declarations resolved through the shared resolver, never on raw policy tags,
because a raw read would treat an absent declaration as an empty one.

Advertisement authorization is a separate claim from delivery authorization. A
pool MUST NOT be required to prove it can deliver a mode in order to advertise
it, and `deliverable_modes` MUST retain its existing meaning, derivation, and
every execution recheck unchanged.

Where a Resource Pool declares `capacity_backing: backed`, its advertisable set
MUST be a subset of its deliverable set. A write that would violate the relation
from either side — widening the advertisable set or narrowing the deliverable set
— MUST be rejected without changing the pool, and MUST NOT be repaired by
rewriting the other declaration. Where a Resource Pool declares
`capacity_backing: unbacked`, its advertisable set is not constrained by its
deliverable set.

#### Scenario: An execution-less pool advertises a mode

- **GIVEN** a Resource Pool declaring `capacity_backing: unbacked` and an empty deliverable set
- **WHEN** an operator declares `advertisable_modes: [vm]`
- **THEN** typed resolution returns exactly that mode and the resolved declaration advertises `vm`
- **AND** the declaration is not narrowed by the absence of a deliverable proof

#### Scenario: A backed pool advertises beyond what it delivers

- **GIVEN** a Resource Pool declaring `capacity_backing: backed` and `deliverable_modes: [bare_metal]`
- **WHEN** an operator declares `advertisable_modes: [bare_metal, vm]`
- **THEN** the write is rejected and the pool is unchanged

#### Scenario: A backed pool's delivery is narrowed below its advertisement

- **GIVEN** a Resource Pool declaring `capacity_backing: backed`, `deliverable_modes: [vm]`, and `advertisable_modes: [vm]`
- **WHEN** an operator writes `deliverable_modes: []` without also narrowing `advertisable_modes`
- **THEN** the write is rejected and neither declaration is changed

#### Scenario: Advertisement declaration is empty

- **WHEN** a Resource Pool declares `advertisable_modes: []`
- **THEN** typed resolution returns an empty set and the pool authorizes no mode for advertisement

### Requirement: Pool-declared capacity backing

Each Resource Pool MUST declare whether it can be admitted against under the
domain-neutral `capacity_backing` policy tag, whose values are `backed` and
`unbacked`. `backed` means an admission authority stands behind the pool;
`unbacked` means none does, so nothing may be reserved, committed, or released
against it.

A Resource Pool declaring `capacity_backing: unbacked` MUST declare an empty
deliverable set. Every reservation, scheduling, and dispatch layer already refuses
a pool that declares no deliverable mode, so this rule is what keeps every
capacity path unreachable for an unbacked pool without any layer reading backing.
A write declaring an unbacked pool with a non-empty deliverable set MUST be
rejected without changing the pool.

A value outside `backed` and `unbacked` MUST be rejected on write. A discriminator
MUST NOT resolve to a default: unlike a cardinality hint, where a structural
default is a reasonable assumption about how many candidates to publish, a backing
default would assert whether anything stands behind a listing.

`capacity_backing` MUST be fixed at pool creation. A replace, patch, or
authoritative-document entry for an existing pool supplying a backing value that
differs from the stored one MUST be rejected and the pool left unchanged. Moving
inventory between backed and unbacked supply is a second pool declaring the
intended backing with its capacity resources migrated across, because backing is a
property every listing derived from the pool inherits, and changing it in place
would silently reinterpret listings already published.

A stored pool carrying no backing value MAY be given one; supplying a value
where none is stored is not a change to it. That state arises only from a version
predating the declaration rewriting a pool's tags, and a service refuses to start
while any stored pool lacks valid declarations, so in practice the value is
supplied by a changed definition document imported before that check.

#### Scenario: Backing is changed on an existing pool

- **WHEN** a replace, patch, or imported document entry supplies a `capacity_backing` value differing from the pool's own
- **THEN** the request is rejected and the pool is unchanged
- **AND** the supported path is a second pool declaring the intended backing with capacity resources migrated across

#### Scenario: A pool without stored backing is repaired

- **GIVEN** a stored pool whose policy tags carry no `capacity_backing`, written by a version predating the declaration
- **WHEN** a changed definition document declaring its backing is imported at startup
- **THEN** the pool records that backing and the startup declaration check passes

#### Scenario: An unbacked pool declares a deliverable mode

- **WHEN** any pool write declares `capacity_backing: unbacked` together with a non-empty `deliverable_modes`
- **THEN** the write is rejected and the pool is unchanged

#### Scenario: A malformed backing value is written

- **WHEN** any pool write declares a `capacity_backing` value outside `backed` and `unbacked`
- **THEN** the write is rejected and the pool is unchanged

### Requirement: Required advertisement and backing declarations

Every pool write MUST carry both `advertisable_modes` and `capacity_backing`
explicitly: create, replace, patch whenever it supplies policy tags, and every
entry of an authoritative definition document, validated or imported. The create
and replace models MUST declare policy tags as a required field rather than
defaulting it to an empty map that validation then refuses, so the published
schema states that it cannot be omitted. A write
omitting either MUST be rejected with a validation problem naming the missing tag.
The service MUST NOT default, preserve, or merge either tag from any other source;
the policy tags a write supplies are the policy tags stored. The replacement rule
that resets omitted optional policy tags does not reach these two tags, because
they are not optional.

The shape of `deliverable_modes`, the presence and shape of both new
declarations, the backed subset rule, and the unbacked empty-deliverable rule
MUST be applied by one shared validation, identically for the typed
administration models, the service, and authoritative document validation and
import, so a typed client cannot construct a write the service would refuse for
its declarations. Backing immutability is evaluated against stored state and MUST be reported
as a structured problem on the validate-only path as well as refusing an import.

A service that seeds Resource Pools at startup, whether from a definition document
or from its own bootstrap, MUST refuse to start when a seeded pool does not carry
valid declarations, naming the pool and the problem. A service MUST likewise refuse
to start when a stored Resource Pool does not carry valid declarations.

Canonical export MUST emit both tags for every pool, so an exported document is a
valid import.

#### Scenario: A write omits a declaration

- **WHEN** a create, replace, patch supplying policy tags, or imported document entry omits `advertisable_modes` or `capacity_backing`
- **THEN** the write is rejected with a problem naming the missing tag and no pool is changed

#### Scenario: A document predating the declarations is imported

- **WHEN** an authoritative document whose pool entries carry neither tag is validated or imported
- **THEN** validation reports each missing tag per entry and the import changes nothing

#### Scenario: A seeded pool lacks declarations

- **WHEN** a service starts with a changed pool definition document, or a bootstrap seed, producing a pool without valid declarations
- **THEN** the service refuses to start and names the pool and the problem

#### Scenario: A stored pool lacks declarations

- **WHEN** a service starts against a database holding a Resource Pool without valid declarations
- **THEN** the service refuses to start and names the pool and the problem

#### Scenario: An export carrying declarations is round-tripped

- **WHEN** an operator exports the current pool state and imports it unedited
- **THEN** every pool entry carries both declarations and the import reports every pool unchanged

### Requirement: Shared resolution of advertisement and backing declarations

The shared resource-pool capability MUST expose one domain-neutral resolver that
turns a pool's policy tags into typed advertisable modes and backing, sharing its
implementation with write-side validation. It MUST fail rather than resolve to a
default for a malformed value of either tag, a backed pool whose advertisable set
exceeds its deliverable set, and an unbacked pool with a non-empty deliverable set.
It MUST report an absent tag distinctly from a malformed one, so a consumer can
apply a producer-version rule to a producer that emits a tag for no pool while
failing a single omitting pool closed.

Any reader of projected pool declarations MUST resolve them through this resolver,
so the site that writes a declaration and every consumer that reads it agree on
what a valid declaration is.

#### Scenario: A projected backed pool advertises beyond what it delivers

- **WHEN** the resolver receives policy tags declaring `capacity_backing: backed` with an advertisable set exceeding the deliverable set
- **THEN** it fails for that pool rather than returning either set

#### Scenario: A projected backing value is malformed

- **WHEN** the resolver receives a `capacity_backing` value outside `backed` and `unbacked`
- **THEN** it fails for that pool rather than resolving to either value

#### Scenario: A projected pool omits a declaration

- **WHEN** the resolver receives policy tags carrying neither `advertisable_modes` nor `capacity_backing`
- **THEN** it reports each tag as absent, distinctly from malformed, and returns no default

### Requirement: Complete emission and upgrade derivation

Create, replace, patch, bulk import, projection, and canonical export MUST carry
both tags on the existing policy-tag channel. A producer that emits either tag MUST
emit it for every Resource Pool it projects, so that a consumer can distinguish a
producer that predates the tag from a producer that omitted it for one pool.

On upgrade, every existing Resource Pool — including the system-owned `default`
pool and pools held by any service that stores its own Resource Pools — MUST have
both tags written by migration: `advertisable_modes` equal to its proved
deliverable set, and `capacity_backing: backed`. Migration MUST overwrite any value
previously stored under either key, MUST report each derived value at INFO, and MUST
NOT change any pool's advertising surface or admission behavior.

#### Scenario: An existing pool is migrated

- **GIVEN** a Resource Pool whose proved deliverable set is `[vm]`
- **WHEN** migration runs
- **THEN** its advertisable set is exactly `[vm]` and its backing is `backed`
- **AND** both values are reported at INFO and its admission behavior is unchanged

#### Scenario: An existing pool held an opaque value under a new key

- **GIVEN** a Resource Pool whose policy tags already carry `capacity_backing` or `advertisable_modes` as unrecognized opaque metadata
- **WHEN** migration runs
- **THEN** both keys are overwritten with the derived values

#### Scenario: A migrated site is projected

- **WHEN** a migrated producer projects its Resource Pools
- **THEN** every projected pool carries both tags

#### Scenario: A producer emits the tags incompletely

- **WHEN** a producer emits `capacity_backing` for some Resource Pools and omits it for another it projects
- **THEN** the projection is malformed with respect to this requirement, and the omitted pool is not treated as predating the tag
