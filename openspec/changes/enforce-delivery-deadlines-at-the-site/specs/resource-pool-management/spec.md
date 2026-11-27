## ADDED Requirements

### Requirement: A pool states its delivery deadline, nothing, or none

A Resource Pool's policy metadata MUST support a `delivery_deadline_seconds` tag with three states: a positive whole number of seconds; absent; or a statement of none. The pool MUST resolve one value from it, which is what the site contributes: the delivery deadline publication reads for the pool, the ceiling on a commit's accepted deadline, and the deadline of a commit that carries none. A pool stating a number MUST resolve that number. A pool stating nothing MUST resolve its provider's declared default, and none where its provider declares none. A pool stating none MUST resolve none, contributing none of the three, and MUST NOT stop the site enforcing a deadline a commit carries. No service-level or site-wide setting MAY turn a pool's resolved deadline on or off. Every surface that persists a pool's policy tags MUST validate the tag through one shared check and refuse any other value without changing the pool.

#### Scenario: A pool states a number

- **WHEN** an operator writes a pool whose tag states 900 seconds
- **THEN** the pool resolves 900 seconds, whatever its provider's default

#### Scenario: A pool states nothing

- **WHEN** a pool of a provider declaring a default states no delivery deadline
- **THEN** the pool resolves its provider's default

#### Scenario: A pool states none

- **WHEN** an operator writes a pool of a provider declaring a default, stating none
- **THEN** the pool resolves no delivery deadline, whatever its provider's default

#### Scenario: Two pools of one site differ

- **WHEN** one site's VM pool states nothing and its bare-metal pool states none
- **THEN** the VM pool resolves its provider's default and the bare-metal pool resolves none

#### Scenario: A malformed value is written

- **WHEN** an operator submits a negative or fractional delivery deadline through the pool API or a pool document
- **THEN** the write is refused and the stored pool is unchanged

### Requirement: Providers declare a default delivery deadline

Each provider MAY declare a default delivery deadline, a positive whole number of seconds, and the service's composition MUST supply the providers' declarations as data. The VM and bare-metal providers MUST declare one. A provider that declares none MUST leave a pool stating nothing with no resolved deadline.

#### Scenario: A quota provider declares none

- **WHEN** the API-credits service composes its ledger with no provider declaring a default
- **THEN** its pool resolves no delivery deadline

#### Scenario: A provider's default changes

- **WHEN** a provider's declared default changes between two releases
- **THEN** a pool stating nothing resolves the new default, and a pool stating a number still resolves that number

## MODIFIED Requirements

### Requirement: The pool authority answers the site's pool facts

Resource-pool management SHALL supply a reader satisfying the site authority's pool-facts
port without importing the site authority. Given the caller's session and a pool
identifier, it SHALL report whether the pool exists, whether it is enabled, its declared
deliverable offering modes or that they are unreadable, and whether declarations in the
pool need a host, resolved from the pool's provider and the host requirement its
composition supplies. With no host requirement supplied, no pool SHALL need a host; with
one supplied, a provider it does not name SHALL need one. It SHALL also report the
delivery deadline the pool resolves, or that it resolves none, from the pool's tag and
the provider defaults its composition supplies, and the site SHALL learn nothing of the
tag or a default but that resolved value.

#### Scenario: A pool whose provider needs a host

- **GIVEN** a composition supplying a host requirement in which the pool's provider
  needs a host
- **WHEN** the site reads the pool's facts
- **THEN** the pool is reported existing, with its enablement and deliverable modes, and
  as needing a host

#### Scenario: A composition supplying no host requirement

- **WHEN** a composition supplying no host requirement reads a pool's facts
- **THEN** the pool is reported as needing no host

#### Scenario: A pool identifier with no stored pool

- **WHEN** the site reads the facts of a pool identifier no stored pool has
- **THEN** the pool is reported as not existing, not enabled, with unreadable deliverable
  modes, and as needing a host exactly when a host requirement is supplied

#### Scenario: A pool stating no delivery deadline, under a provider default

- **GIVEN** a composition supplying a default delivery deadline for the pool's provider
- **WHEN** the site reads the facts of a pool that states no delivery deadline
- **THEN** the pool is reported as resolving that default

#### Scenario: A composition supplying no provider default

- **WHEN** a composition supplying no provider default reads the facts of a pool that
  states no delivery deadline
- **THEN** the pool is reported as resolving none
