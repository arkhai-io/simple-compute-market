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
