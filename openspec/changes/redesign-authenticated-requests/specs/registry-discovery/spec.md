## RENAMED Requirements

- FROM: `### Requirement: Body-bound version 2 registry authentication`
- TO: `### Requirement: Body-bound registry authentication`

## MODIFIED Requirements

### Requirement: Filter-spec consistency

The registry MUST identify a filter-spec version with an ETag and MUST reject a listing query whose `filter_spec_etag` query parameter is stale with HTTP 412 rather than evaluate it under different filter semantics. The ETag MUST travel as that query parameter, which the request's signature covers, and the registry MUST refuse a listing query carrying an `If-Match` header as malformed, naming the header.

#### Scenario: Cached filter spec is stale

- **WHEN** a client queries listings with a `filter_spec_etag` that does not match the active filter-spec
- **THEN** the registry returns HTTP 412

#### Scenario: A listing query sends the ETag as `If-Match`

- **WHEN** a client queries listings with the filter-spec ETag in an `If-Match` header
- **THEN** the registry refuses the query as malformed, naming `If-Match`, rather than evaluating it unchecked

### Requirement: Body-bound registry authentication

The registry client MUST receive an injected scheme-neutral signer and MUST NOT accept or derive publisher authority from a private-key string or address-only credential. Publication, update, close, publisher-identity rotation, and authenticated discovery MUST use the shared `arkhai.market-request-signature.v3` profile, whose signature binds the body bytes' digest together with the caller role, exact principal, method, query, semantic operation, resource where the operation has one, audience, request ID, origin and signing time before validation, dispatch, or persistence. Behavior-affecting query values MUST travel in the query, which the signature covers.

Every completed authenticated registry response MUST use the shared version 3 response profile to bind the registry authority, status, originating request, signing time, and response body. A client MUST verify that proof and the exact configured registry authority before accepting the result.

#### Scenario: Listing body changes after signing

- **WHEN** any listing payload field changes after the publisher creates its proof
- **THEN** the registry rejects the publication before validation or persistence

#### Scenario: Response comes from an unexpected authority

- **WHEN** a cryptographically valid response is signed by a principal outside the client's configured registry trust set
- **THEN** the client rejects the response

### Requirement: Publisher principal rotation

The registry MUST rotate a stable publisher only from a canonical intent that names the current and replacement principals, `publisher:<publisher_id>` subject, registry authority, nonce, bounded overlap, and expiry and is proven by both principals. The authenticated caller MUST be the active current primary. Applying the same nonce and intent MUST be idempotent: an exact repetition of an applied intent, from the principal it names as current, MUST be answered with the rotation's state before the intent's expiry, the caller's primary status and any active overlap are checked, since those checks govern only applying an intent. Reusing the nonce for another intent, binding an already-owned replacement, or starting a second active overlap MUST fail. The replacement becomes primary, the current principal remains active only for the requested bounded overlap, and only the active replacement primary MAY retire it early; a repeated retirement of an already retired rotation, from that replacement, MUST be answered with the retired rotation whether or not the replacement is still primary. Rotation MUST preserve the publisher and all owned listing identifiers and history.

#### Scenario: Replacement principal lacks its proof

- **WHEN** the current publisher submits a replacement identifier without a valid replacement proof
- **THEN** the registry does not bind or promote the replacement

#### Scenario: Rotation is retried

- **WHEN** the same valid rotation intent is submitted again with its publisher nonce
- **THEN** the registry returns the recorded rotation state without creating another binding

#### Scenario: A rotation is retried after its intent expired

- **WHEN** a publisher's rotation applied, its acknowledgement was lost, and its exact retry arrives after the intent's expiry and after the replacement became primary
- **THEN** the registry answers the applied rotation's state rather than refusing the retry for expiry or primary status, and binds nothing new

#### Scenario: A retirement is retried after a later rotation

- **WHEN** a replacement retired its predecessor, lost the acknowledgement, and rotated again, and the retirement's exact retry arrives
- **THEN** the registry answers the retired rotation rather than refusing the retry because the replacement is no longer primary

### Requirement: Resource query compilation preserves filter-spec authority

A buyer resource-query compiler MUST resolve every field, operator, type, alias, and missing-value rule from the active registry filter specification and MUST compile only declared filters into the registry's query. The compiled request MUST carry the matching filter-spec ETag as its `filter_spec_etag` query parameter and all behavior-affecting values in its query, which the request's signature covers. The compiler MUST NOT add domain fields, reinterpret missing values, or weaken strict filtering.

#### Scenario: Filter specification changes during query construction

- **WHEN** the buyer compiles a resource query under one filter-spec ETag and the registry activates another before execution
- **THEN** the registry rejects the request with HTTP 412 rather than evaluating it under changed semantics

#### Scenario: DSL operator is not declared for a field

- **WHEN** the user applies a range operator to a field whose filter declaration accepts only set membership
- **THEN** the buyer rejects compilation before sending the listing query

### Requirement: Registry self-description is authority-authenticated

A registry MUST publish one strict descriptor containing its public base URL,
display name, operator identity, stable authority name and active principal set,
listing schema identity and version, and access posture. It MUST return the
descriptor at `/.well-known/arkhai/registry-descriptor.json` as a public operation:
the request carries only its request identity, and the registry answers it with the
shared version 3 signed response bound over that identity.

The authority principal MUST come from the active registry signer, the schema
identity MUST come from the active filter specification, and the access posture
MUST come from the active read gate. Operator-authored public fields MUST remain
ordinary configuration. Signer credentials and read keys MUST NOT enter the
descriptor. A bootstrap client, which needs no key of its own, MUST verify the signed
response, bound to its fresh request ID, against the principal set carried in the
validated descriptor before returning it; a client configured with the registry's
principals MUST verify it against them. A bootstrap client MUST refuse a URL whose
scheme is not `https`, with certificate verification, unless its caller explicitly
opts into plain HTTP for local or test use, and MUST refuse a descriptor whose base
URL is not the URL it bootstrapped from.

#### Scenario: Client inspects a public registry

- **WHEN** any client requests the well-known descriptor with a fresh request identity
- **THEN** the registry returns the complete descriptor under a response proof from the principal named in that descriptor, bound to that request identity

#### Scenario: Registry reads require a key

- **WHEN** the registry requires a read key
- **THEN** the descriptor remains readable without that key and declares `key-gated` posture with an acquisition pointer

#### Scenario: Descriptor configuration contradicts access policy

- **WHEN** a key-gated registry has no acquisition pointer or a public registry configures one
- **THEN** startup fails before the registry serves a contradictory descriptor

#### Scenario: Descriptor is used as a trust bootstrap

- **WHEN** a client verifies the signed response against the principal carried in the descriptor
- **THEN** the proof establishes credential possession but does not by itself establish third-party endorsement of the operator or URL

#### Scenario: A replayed descriptor is offered to a bootstrap

- **WHEN** a bootstrap client receives a descriptor whose signed response binds a request ID other than the one it sent
- **THEN** the client rejects the descriptor

#### Scenario: A bootstrap is given a plain-HTTP URL

- **WHEN** a client bootstraps a registry from an `http` URL without opting into plain HTTP
- **THEN** the client refuses before sending any request, naming the scheme

#### Scenario: A descriptor claims another base URL

- **WHEN** a bootstrap client reads a correctly signed descriptor whose base URL differs from the URL it bootstrapped from
- **THEN** the client rejects the descriptor rather than pinning its principal under the claimed URL

### Requirement: Durable replay reservation

The registry MUST durably reserve `(principal, request_id)` before dispatch. Reuse with different canonical request content MUST be rejected, an exact retry MUST be resolved as its route's declared exact-retry resolution says, and a concurrent retry while the first attempt holds its lease MUST NOT dispatch a second operation. On a `RERUN` route an expired unfinished lease MAY be reclaimed by one attempt. Listing publication, update and deletion MUST be declared `RECORDED`: each is an absolute setter or a delete that a later write may supersede, so an exact retry MUST be answered with the recorded outcome and MUST NOT run again.

#### Scenario: Completed publication is retried

- **WHEN** a publisher repeats the exact authenticated publication after losing its acknowledgement, within the retention
- **THEN** the registry answers the publication's recorded outcome under a fresh signed response without running the publication again

#### Scenario: A deletion is retried after the listing was republished

- **WHEN** a publisher deletes a listing and loses the acknowledgement, the listing is published again, and the deletion's exact retry arrives within the retention
- **THEN** the registry answers the deletion's recorded outcome under a fresh signed response, and the republished listing remains

#### Scenario: Request ID is reused with a changed body

- **WHEN** the same principal reuses a request ID for different canonical request content
- **THEN** the registry rejects the request as changed reuse before dispatch

### Requirement: Seller publication evidence is independently verifiable

The registry MUST retain and return, as a listing's `publication`, the exact publication HTTP body bytes as base64 and the record of the seller's signed request, carrying every value its signature covers, its seller proof included. Its ordinary response signature MUST cover that evidence. Mutable lifecycle/oracle updates MUST retain distinct seller evidence, returned as `updates`, mapping each changed field to its update's body and request record, and MUST NOT rewrite the publication proof. The evidence MUST let a consumer verify the seller's body, context and identity rather than treating the registry's signature as the seller's commitment: the registry attests what it served and which keys belong to the publisher; the seller's proof attests the terms. Evidence the registry retained under version 2 MUST be returned as it was retained, its record the version 2 request envelope, and MUST remain verifiable. Because the read lays this evidence over the seller's published document, the registry MUST refuse by name, as reserved registry metadata, a publication carrying `publication`, `updates`, `publisher_publication` or `publisher_updates`.

#### Scenario: A consumer verifies a listing's commercial term

- **WHEN** a consumer decodes `publication.body_base64` and verifies its request record with the listing's publisher principals
- **THEN** the body digest and seller signature bind the listing's published terms
- **AND** historical verification is distinct from live request freshness and publisher trust

#### Scenario: A seller publishes a term named like the evidence

- **WHEN** a seller's publication carries a field named `updates` or `publication`
- **THEN** the registry refuses it as reserved registry metadata, naming the field, rather than accepting it and overwriting it with evidence on read

#### Scenario: A listing published before the cutover is read

- **WHEN** a consumer reads a listing whose publication the registry retained under version 2
- **THEN** its `publication` record is the version 2 request envelope, which the consumer verifies by its protocol

#### Scenario: A seller changes status or oracle after publication

- **WHEN** an authorized seller updates a supported lifecycle/oracle field
- **THEN** reads retain the original publication proof and, under `updates`, the latest signed update for each changed field
- **AND** unsupported update keys are refused by name rather than discarded
