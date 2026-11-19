## ADDED Requirements

### Requirement: Accepted listing content is retained

The registry MUST store and serve the complete schema-admitted publication document,
including unknown admitted properties and explicit nulls. Republication MUST replace
commercial content whole under the same listing and publisher identities. Omitted
terms MUST disappear. Registry-owned metadata names MUST be refused at publication
with an error naming each collision, never silently overwritten.

#### Scenario: A publisher sends an admitted top-level term

- **WHEN** a publisher publishes a schema-valid listing with an additional top-level term
- **THEN** detail and search reads return that term unchanged and filters evaluate it

#### Scenario: A seller withdraws a term by republication

- **WHEN** the owner republishes a complete listing omitting a previous commercial term
- **THEN** reads no longer contain that term and no per-field merge restores it
- **AND** listing identity, publisher identity and creation time remain unchanged

#### Scenario: A seller submits registry-owned metadata

- **WHEN** a publication carries publisher_id, publisher_principals, created_at,
  updated_at, publisher_publication or publisher_updates
- **THEN** publication is refused naming the reserved fields

### Requirement: Legacy listing reads do not invent seller evidence

A row without a publication document MUST remain readable by synthesizing its
existing carriers. Its publication evidence MUST be null until a successful
republication stores the complete document and seller proof atomically. Lost
fields and signatures MUST NOT be fabricated or attributed to the seller.

#### Scenario: A listing predates retained documents

- **WHEN** a buyer reads or filters a legacy listing
- **THEN** the registry serves its existing carriers and explicitly absent publication proof
- **AND** a subsequent valid republication establishes the document and proof together

#### Scenario: A legacy listing is bounded by asking rate

- **WHEN** a buyer bounds a compute query by asking rate and a legacy listing's carriers
  held a rate inside its capacity description
- **THEN** the rebuilt listing carries no `pricing` and is excluded from the bound
- **AND** it matches again once its seller republishes the rate in `pricing`

### Requirement: Seller publication evidence is independently verifiable

The registry MUST retain and return the exact publication HTTP body bytes as base64
and the authenticated v2 request envelope including its seller proof. Its ordinary
response signature MUST cover that evidence. Mutable lifecycle/oracle updates MUST
retain distinct seller evidence and MUST NOT rewrite the publication proof. The
evidence MUST let a consumer verify the seller's body, context and identity rather
than treating the registry's signature as the seller's commitment: the registry
attests what it served and which keys belong to the publisher; the seller's proof
attests the terms.

#### Scenario: A consumer verifies a listing's commercial term

- **WHEN** a consumer decodes publisher_publication.body_base64 and verifies its request envelope
- **THEN** the canonical body hash and seller signature bind the listing's published terms
- **AND** historical verification is distinct from live request freshness and publisher trust

#### Scenario: A seller changes status or oracle after publication

- **WHEN** an authorized seller updates a supported lifecycle/oracle field
- **THEN** reads retain the original publication proof and the latest signed update for each changed field
- **AND** unsupported update keys are refused by name rather than discarded

## MODIFIED Requirements

### Requirement: Schema-driven listing validation

A registry MUST validate publication and dry-run candidates against its configured
filter-spec listing shape and compile discovery filters from that specification,
without hardcoding a concrete market schema into route signatures. Authentication
MUST precede publication validation. A schema-invalid publication MUST be refused
before changing listing content or publisher state.

#### Scenario: Publisher submits a listing

- **WHEN** a signed listing candidate is published
- **THEN** the registry validates the complete body against the filter-spec listing shape before storing it

#### Scenario: A schema-invalid publication is submitted

- **WHEN** an authenticated publication violates the configured listing shape
- **THEN** it fails with field-path errors and leaves prior listing content unchanged

### Requirement: The filter grammar can compare exact decimal values

The filter specification MUST support a declared value type whose wire and stored
representation is a decimal-text string and whose comparison domain is finite
exact decimal. Range bounds declared under it MUST be parsed as exact decimals,
resolved listing values MUST be accepted when they are decimal text, and comparison
MUST NOT pass through a binary floating-point representation at any point.

Only finite values are decimal values of this type. A query bound that parses as a
non-number or an infinity MUST be refused as an invalid parameter, never evaluated.
A listing value that does MUST be treated as no value, so `on_missing` decides it:
a listing rebuilt from its legacy carriers was never validated against the full
listing shape, and a malformed stored listing must not be able to fail a query.

The type is domain-neutral: it names no market, field, or unit, and any
specification may declare it for any decimal quantity.

The existing JSON-number value type MUST be left unchanged. Retyping its
comparison domain would alter the meaning of filters that other deployments'
specifications already declare, so exact decimal comparison MUST be a distinct
declared type that a specification opts into.

A registry MUST refuse to load a filter specification declaring a value type it
does not implement, rather than ignoring the declaration. A specification whose
comparison semantics the engine cannot honour MUST NOT be served, because a
silently-ignored type would evaluate every query under semantics the operator did
not declare.

A buyer resource-query compiler MUST render a bound of this type without loss and
MUST resolve its type from the specification like any other.

#### Scenario: A bound compares against a high-precision listing value

- **WHEN** a buyer bounds a query against a decimal-text field and a listing's
  value carries more significant digits than a binary double represents exactly
- **THEN** the comparison is exact and the listing matches or is excluded on its
  true value

#### Scenario: A decimal-text value is compared at the bound

- **WHEN** a listing's decimal-text value equals an inclusive bound exactly
- **THEN** it matches, and it does not match an exclusive bound of the same value

#### Scenario: A query bound is not finite

- **WHEN** a request bounds a decimal-text filter by a non-number or an infinity
- **THEN** the registry refuses the parameter rather than evaluating the query

#### Scenario: A stored listing value is not finite

- **WHEN** a listing's decimal-text value is a non-number or an infinity and a query
  bounds that field
- **THEN** the listing is treated as publishing no value, and the query completes

#### Scenario: A registry is given a specification it cannot honour

- **WHEN** a registry configured with an engine that does not implement a declared
  value type loads that filter specification
- **THEN** it refuses the specification rather than serving queries under
  substituted semantics

#### Scenario: The existing number type is unaffected

- **WHEN** a filter declared under the JSON-number value type is evaluated
- **THEN** its behaviour is unchanged by the presence of the decimal type

### Requirement: The compute schema carries a listing's asking rate

The compute filter specification MUST describe an optional top-level `pricing` object
holding a listing's listing-level prices: an optional `asking_rate` and an optional
`rate_structure`. `pricing` MUST admit no other property. A settlement option's price
stays with the option it prices, and the capacity description carries no price.

`asking_rate` carries `amount`, `asset`, and `period`, all required when the object is
present. `amount` is exact decimal text; `asset` is an opaque, non-empty identifier of the
same kind a settlement option's published asset carries, requiring no contract address,
token decimals, or chain identity; `period` is the time unit the amount is quoted per,
`hour` in this version. `rate_structure` maps a family name to a list of entries, each
carrying exactly `asset`, a decimal-text `rate`, and `per`; the specification names no
family.

The object is declared in the compute specification, which is data the generic registry
serves, and not in registry engine code. The registry validates it wherever it validates
the listing shape: at publication and in the dry run. No registry surface may interpret an
asset beyond comparing it for equality, or interpret a rate structure at all.

A price at its earlier location — `asking_rate` in the capacity description, or a
top-level `rate_structure` — MUST be refused at publication, naming the field and its
place in `pricing`, as the specification refuses its other retired names: stored, it
would match no rate bound and its seller would get no signal.

#### Scenario: A listing is dry-run with a partial asking rate

- **WHEN** a publisher dry-runs a compute listing whose `pricing.asking_rate` omits its
  asset or its period
- **THEN** the dry run reports the listing invalid, naming the asking rate

#### Scenario: A listing misspells a pricing term

- **WHEN** a publisher publishes a compute listing whose `pricing` carries a property the
  specification does not name
- **THEN** publication is refused naming `pricing`, and no listing content changes

#### Scenario: A shape-priced listing publishes its rate structure

- **WHEN** a listing publishes `pricing.rate_structure` beside its asking rate
- **THEN** the registry stores and serves both unchanged and rate filters read only the
  asking rate

#### Scenario: A rate is quoted in an off-chain asset

- **WHEN** a listing publishes an asking rate in an asset that has no contract
  address, decimals, or chain identity
- **THEN** the registry stores and serves the asset identifier opaquely

#### Scenario: A rate is published inside the capacity description

- **WHEN** a publisher publishes a compute listing carrying an asking rate in its
  capacity description
- **THEN** publication is refused naming `listing_resource.asking_rate` and
  `pricing.asking_rate`, and no listing content changes

#### Scenario: A rate structure is published at the top level

- **WHEN** a publisher publishes a compute listing carrying `rate_structure` beside
  `pricing` rather than inside it
- **THEN** publication is refused naming `rate_structure` and
  `pricing.rate_structure`, and no listing content changes
