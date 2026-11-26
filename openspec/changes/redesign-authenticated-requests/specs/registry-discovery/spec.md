## MODIFIED Requirements

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
