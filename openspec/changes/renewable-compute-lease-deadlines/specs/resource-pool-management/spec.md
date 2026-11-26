## ADDED Requirements

### Requirement: A pool states its delivery deadline, nothing, or none

A Resource Pool's policy metadata MUST support a `delivery_deadline_seconds` tag with three states: a positive whole number of seconds; absent; or a statement that the pool enforces none. A pool stating a number MUST resolve that number. A pool stating nothing MUST resolve its provider's declared default, and none where its provider declares none. A pool stating none MUST resolve none. No service-level or site-wide setting MAY turn a pool's resolved deadline on or off. Every surface that persists a pool's policy tags MUST validate the tag through one shared check and refuse any other value without changing the pool.

#### Scenario: A pool states a number

- **WHEN** an operator writes a pool whose tag states 900 seconds
- **THEN** the pool resolves 900 seconds, whatever its provider's default

#### Scenario: A pool states nothing

- **WHEN** a pool of a provider declaring a default states no delivery deadline
- **THEN** the pool resolves its provider's default

#### Scenario: A pool states none

- **WHEN** an operator writes a pool of a provider declaring a default, stating that it enforces none
- **THEN** the pool resolves no delivery deadline

#### Scenario: Two pools of one site differ

- **WHEN** one site's VM pool states nothing and its bare-metal pool states none
- **THEN** the VM pool resolves its provider's default and the bare-metal pool resolves none

#### Scenario: A malformed value is written

- **WHEN** an operator submits a negative or fractional delivery deadline through the pool API or a pool document
- **THEN** the write is refused and the stored pool is unchanged

### Requirement: Providers declare a default delivery deadline

Each provider MAY declare a default delivery deadline, a positive whole number of seconds, and the service's composition MUST supply the providers' declarations as data. The VM and bare-metal providers MUST declare one. A provider that declares none MUST leave a pool stating nothing with no resolved deadline. The pool authority MUST supply a pool's resolved delivery deadline among the pool facts the site ledger reads in its own transaction, and the site MUST learn nothing of the tag or the default but that resolved value.

#### Scenario: A quota provider declares none

- **WHEN** the API-credits service composes its ledger with no provider declaring a default
- **THEN** its pool resolves no delivery deadline

#### Scenario: A provider's default changes

- **WHEN** a provider's declared default changes between two releases
- **THEN** a pool stating nothing resolves the new default, and a pool stating a number still resolves that number
