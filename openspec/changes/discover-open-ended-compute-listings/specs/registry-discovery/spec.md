## ADDED Requirements

### Requirement: Compute capacity bounds are queryable listing fields

The compute registry schema MUST carry listing-level `available_until_utc` and
`max_duration_seconds` using the published-payload carrier policy. Its filter
specification MUST expose typed lower-bound resource filters on both, with existing
ETag authority checks. UTC availability MUST be compared as an instant rather than
by lexical timestamp spelling. Indexing these fields MUST NOT require a stored
class or lifecycle policy summary.

#### Scenario: Capacity available through a required date

- **WHEN** a buyer asks for capacity available until at least a UTC instant
- **THEN** listings with earlier or unknown availability do not satisfy the filter
- **AND** equivalent timezone-normalized instants compare equally

#### Scenario: Relative maximum is explicitly unlimited

- **WHEN** a listing explicitly states a null or nonpositive unlimited relative maximum and a buyer requires a finite minimum maximum duration
- **THEN** the known unlimited relative bound satisfies that minimum
- **AND** an absent legacy bound remains unknown rather than implicitly unlimited

### Requirement: Option filtering preserves a realizable selection

A discovery clause MUST match every predicate on one eligible option. A listing
MUST survive only if such an option exists, and surviving option identities MUST
reach selection. Registry pushdown and local evaluation MUST use the same common
codec and mechanism projections; a coarse pushdown MUST NOT discard a locally
matching option.

#### Scenario: Attractive facts belong to different options

- **WHEN** only one option has the requested period and only another has the requested payee notice
- **THEN** their listing fails the conjunction

#### Scenario: Predicate cannot be pushed

- **WHEN** the registry supports a capacity filter but not an option predicate
- **THEN** discovery applies the capacity filter remotely and the complete option clause locally
- **AND** explanation reports the distinction without changing survivors
