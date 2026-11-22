## MODIFIED Requirements

### Requirement: Durable replay reservation

For its existing non-RFQ operations, the registry MUST durably reserve `(principal, request_id)` before dispatch. Reuse with different canonical request content MUST be rejected, an exact retry of a completed request MUST return the recorded status and body under a fresh signed response without repeating the operation, and a concurrent retry while the first attempt holds its lease MUST NOT dispatch a second operation. An expired unfinished lease MAY be reclaimed by one attempt.

For RFQs the registry MUST reserve the verified account subject, its authority namespace and request ID. It MUST refuse a different canonical input under that identity. A successful mutation and its contact-free receipt MUST commit once. The registry MUST freshly authorize every RFQ read, including exact retries, against current ownership, consent and time. It MUST NOT retain RFQ read bodies for replay.

#### Scenario: Completed publication is retried

- **WHEN** a publisher repeats the exact authenticated publication after losing its acknowledgement
- **THEN** the registry returns the recorded outcome without creating or mutating the listing again

#### Scenario: Request ID is reused with a changed body

- **WHEN** the same principal reuses a request ID for different canonical request content
- **THEN** the registry rejects the request as changed reuse before dispatch

#### Scenario: Retry after contact access ends

- **WHEN** a participant retries a previously successful contact read after early termination or expiry
- **THEN** the registry refuses disclosure under a fresh signed response

#### Scenario: Mutation retry after key replacement

- **WHEN** a newly authorized credential for the same account repeats a committed selection with its original request ID and logical inputs
- **THEN** the registry returns the contact-free receipt and creates no second introduction
