## ADDED Requirements

### Requirement: Asking-rate hint validation

Resource Pool policy metadata MUST support a domain-neutral `asking_rates` key
carrying, per offering mode, the rates a site asks for the shapes its listings are
sold in. It is a key of its own rather than a value inside `pricing`, because every
compute-family domain reads it through one shared reader and one structural check,
as `listing_shapes` is read.

A Resource Pool management surface that accepts `asking_rates` MUST require a mapping
from offering mode to a list of entries. Each entry MUST carry a `shape` that is a
structurally well-formed family-grouped capability shape, checked by the shared
structural check the capability shape utility provides; an `amount` that is positive
decimal text without an exponent; an `asset` that is a trimmed, non-empty string; and
a `period` that is a canonical lowercase unit token. An empty list MUST be accepted.

The check MUST NOT depend on any domain's family or field names, and MUST NOT restrict
which periods are accepted: which families and fields are meaningful, and which
periods a published rate may use, MUST be validated by the domain that reads the hint.
Every surface capable of persisting a Resource Pool's `policy_tags` MUST apply the
same check: the bulk pool-document import path and the individual pool admin API
(`create`/`replace`/`update`). The value MUST be projected verbatim.

#### Scenario: Operator supplies a malformed asking rate

- **WHEN** an operator submits an `asking_rates` entry whose amount is a JSON number,
  whose asset is blank, or whose shape holds a family that is not a mapping, through
  any pool-write surface
- **THEN** Resource Pool validation rejects the update without changing the stored
  policy metadata

#### Scenario: Operator quotes a period no domain accepts

- **WHEN** an operator submits a structurally well-formed entry quoted per `month`
- **THEN** Resource Pool validation accepts it, and a storefront that accepts only
  `hour` holds the pool's listings and reports the declaration unreadable
