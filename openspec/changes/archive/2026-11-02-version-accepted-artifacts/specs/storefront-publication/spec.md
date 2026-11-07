## ADDED Requirements

### Requirement: Bare-metal evidence retains its proof representation

The bare-metal domain MUST provide an immutable evidence document containing
original canonical UTF-8 bytes, their verified digest, and a separate validated
view. It MUST verify the outer digest against the expected digest and the nested
result digest from original result JSON before view conversion. Strict v1 schema
validation MUST remain; a current-model dump MUST NOT replace proof input.

#### Scenario: The application view changes

- **WHEN** stored v1 evidence decodes into a view with a new default
- **THEN** its retained bytes and outer and nested digests remain unchanged

#### Scenario: The nested result is changed

- **WHEN** original result JSON does not match its evidence's result digest
- **THEN** validation fails before yielding a usable view or publication

### Requirement: Evidence persistence verifies and preserves the first document

Persistence MUST hash retrieved canonical TEXT against the expected digest before
returning a document. Save MUST preserve first-write-wins and return the verified
document actually stored. Corruption MUST fail explicitly without normalization,
replacement, or a new digest. Alkahest recovery MUST journal and publish the
retained verified digest under existing submission rules.

#### Scenario: Save is retried with another candidate

- **WHEN** a negotiation already has a valid stored evidence document
- **THEN** save returns the original document without changing its bytes or digest

#### Scenario: Stored outer content is corrupted

- **WHEN** evidence TEXT does not hash to the requested digest even though its
  nested result remains valid
- **THEN** load refuses it and the worker neither republishes it nor replaces its digest

#### Scenario: The worker restarts before publication

- **WHEN** the worker resumes a deal with previously stored valid evidence
- **THEN** its submission intent and publication use the retained verified digest
  rather than a digest of its current application view

### Requirement: Resolution preserves the existing signed evidence wire contract

The route MUST authorize through validated party facts and existing roles, sign
retained canonical evidence bytes, and emit the original evidence object inside
the existing signed envelope. Both typed clients MUST compare the received
evidence's canonical digest with the requested digest before returning its
validated document. Existing kinds, fields, routes, proof protocol, and
authorization MUST remain unchanged.

#### Scenario: A party resolves historical evidence

- **WHEN** an authorized buyer, claimant, or administrator resolves valid stored v1 evidence
- **THEN** the proof covers retained bytes and the evidence object gains no fields
  from current-view defaults

#### Scenario: A client receives another valid document

- **WHEN** an async or sync client requests one digest and receives otherwise
  valid evidence with another digest
- **THEN** the client refuses the mismatch before returning its view

#### Scenario: An unrelated principal requests evidence

- **WHEN** a principal without existing evidence-reader authorization requests a document
- **THEN** the route refuses it without expanding access privileges

### Requirement: Evidence clients retain field-style Python usability

Both clients MUST retain their method signatures and named signed-response
carrier. Its evidence document MUST expose read-only properties for existing
evidence and nested result fields, with digest and canonical JSON operations from
retained content. The nominal type change MUST take a minor domain-distribution
release under the pre-1.0 policy; consumers requiring the document API MUST
declare its new minimum version.

#### Scenario: An existing caller reads evidence attributes

- **WHEN** a caller reads `signed.evidence.condition_anchor`,
  `signed.evidence.result.access_ready_at`, or `signed.evidence.evidence_digest`
- **THEN** those reads remain usable and the digest names the retained document

#### Scenario: A document is serialized for the route

- **WHEN** the named signed-response carrier is emitted as JSON
- **THEN** fields remain `protocol`, `seller_principal`, `evidence`, and `proof`,
  with no new bytes field or wire wrapper
