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

### Requirement: Seller publication evidence is independently verifiable

The registry MUST retain and return the exact publication HTTP body bytes as base64
and the authenticated v2 request envelope including its seller proof. Its ordinary
response signature MUST cover that evidence. Mutable lifecycle/oracle updates MUST
retain distinct seller evidence and MUST NOT rewrite the publication proof. Buyers
MUST verify the seller body, context and identity rather than treating a registry
signature as a seller commitment.

#### Scenario: A buyer verifies a listing's commercial term

- **WHEN** a buyer decodes publisher_publication.body_base64 and verifies its request envelope
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
