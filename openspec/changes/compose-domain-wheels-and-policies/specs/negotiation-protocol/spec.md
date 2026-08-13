## ADDED Requirements

### Requirement: Composed negotiation policy catalogue
Policy names in operator configuration MUST resolve against a catalogue
composed once per role from an explicit set of sources and immutable
thereafter. Resolution MUST NOT mutate the catalogue, and a role MUST NOT
resolve a policy name against process-global state populated by import side
effects.

Composition MUST fail, before the role serves requests, when a source cannot
be loaded, when a source offers a value that is not a middleware, or when two
sources offer the same name. A conflict MUST name both offering sources. There
MUST be no mechanism by which one source silently shadows another.

#### Scenario: A configured chain is resolved
- **WHEN** a role resolves its configured policy names against a composed
  catalogue
- **THEN** the chain is returned in the configured order and the catalogue is
  unchanged

#### Scenario: Two sources offer the same policy name
- **WHEN** a catalogue is composed from sources that both offer one name
- **THEN** composition fails naming that policy and both offering sources

#### Scenario: A policy source cannot be loaded
- **WHEN** a declared source raises while loading
- **THEN** composition fails naming that source, and the role does not start
  with a partial catalogue

#### Scenario: A configured name is unavailable
- **WHEN** configuration names a policy no source offers
- **THEN** resolution fails listing the available policy names and instructing
  the reader to import no package

#### Scenario: Two roles are composed in one process
- **WHEN** a buyer catalogue and a storefront catalogue are composed in the
  same process
- **THEN** each is an independent value, and a name offered to one role is not
  resolvable by the other

### Requirement: Domain-chosen policy discovery
A domain MUST declare which discovery mechanisms may supply its negotiation
policies, and the composing role MUST use only the mechanisms that domain
declares. Operator configuration MAY parameterise a declared mechanism but
MUST NOT introduce one the domain did not declare. The generic policy layer
MUST define the discovery protocol and its implementations without referencing
any domain, domain contract, or capability type.

#### Scenario: A domain declares only build-time policies
- **WHEN** a domain supplies its policies from an inline source and declares no
  filesystem or remote source
- **THEN** the composed catalogue contains only that domain's declared
  policies, and no operator setting causes another mechanism to be consulted

#### Scenario: A new discovery mechanism is introduced
- **WHEN** a mechanism satisfying the discovery protocol is added
- **THEN** it is usable by a domain that declares it, the protocol is
  unchanged, and no other domain's composed catalogue changes

#### Scenario: The generic policy layer is checked for domain references
- **WHEN** the generic negotiation policy layer's imports and diagnostics are
  reviewed
- **THEN** it references no domain package, and no error message instructs the
  reader to import one
