## ADDED Requirements

### Requirement: Bare-metal hosted servicing orders financial and physical effects

An accepted bare-metal hosted obligation MUST progress in this order: register the immutable mechanism-neutral plan; materialize exact hosted authorization; observe authoritative funding; commit an existing accepted billable hold or create/commit the accepted site's ordinary Capacity Reservation; dispatch exactly one provider-neutral whole-host fulfillment against the selected resource/allocation; verify and publish signed portable access-ready evidence; then collect. A pre-existing billable negotiation-time hold MAY remain only until its accepted deadline, but no capacity commitment, resource scheduling, allocation, executor job, lease, or access grant may begin before authoritative funded state. Idempotency MUST bind the accepted agreement, hosted operation, Capacity Reservation/allocation, fulfillment/provider operation, and evidence identifiers across retries and restart.

#### Scenario: Card authorization is pending

- **WHEN** hosted state is `requires_action` or otherwise nonfunded
- **THEN** no hold extension/replacement, capacity commitment/scheduling, or physical provisioning call is made

#### Scenario: Funding is authoritative

- **WHEN** the exact accepted operation becomes funded before all accepted deadlines
- **THEN** servicing uses the pinned selected site/resource path exactly once and never placement-falls back on refusal or failure

#### Scenario: Worker restarts after allocation commit

- **WHEN** capacity was committed but executor completion was not recorded
- **THEN** recovery resumes the same reservation/allocation/provider operation and cannot allocate or provision a second host

### Requirement: Funding expiry rechecks authority before physical release

The effective funding deadline MUST be bounded by the accepted offer expiry, billable hold, hosted profile authorization window, and fulfillment feasibility window. On expiry, servicing MUST retrieve current authoritative hosted status before deciding that the obligation is unfunded. If still unfunded, it MUST record terminal expiry, release any negotiation-time hold through its owning authority, and request hosted reclaim when eligible; it MUST NOT create a new financial operation, extend or replace the hold/offer, commit/schedule capacity, or provision a later-republished resource.

#### Scenario: Delayed webhook crosses expiry

- **WHEN** local state appears pending at expiry but authoritative retrieval reports funded within the accepted boundary
- **THEN** servicing reconciles that funded operation before any release/reclaim decision

#### Scenario: ACH remains pending after expiry

- **WHEN** authoritative retrieval remains nonfunded after the accepted boundary
- **THEN** servicing expires the obligation without reserving a host and follows exact hosted reclaim/recovery semantics

### Requirement: Pre-collection failure and reclaim remain mutually constrained

After funding, selected-site refusal, capacity loss, terminal executor failure, access-delivery failure, invalid evidence, or accepted fulfillment expiry before collection MUST prevent collection. Reclaim MAY begin only when there is no successful lease/access evidence and no collection reservation/effect, and only after authoritative hosted status confirms eligibility. Once valid fulfillment evidence is accepted or collection can no longer be excluded, recovery MUST preserve the operation and escalate ambiguous outcomes rather than releasing capacity or issuing contradictory financial actions.

#### Scenario: Selected Physical Resource is no longer reservable

- **WHEN** the pinned site refuses the exact reservation after funding
- **THEN** servicing records terminal physical failure, provisions no substitute resource, collects nothing, and requests reclaim only after the exclusion check passes

#### Scenario: Collection acknowledgement is unknown

- **WHEN** the financial authority may have accepted collection
- **THEN** servicing preserves lease/allocation and evidence, reconciles the same operation, and neither reclaims nor dispatches duplicate fulfillment

### Requirement: Financial completion does not complete physical teardown

Collection/transfer closes financial reclaim eligibility but MUST NOT mark the bare-metal lease, access grant, allocation, or Capacity Reservation released. Lease expiry or explicit authorized termination MUST drive access revocation, executor teardown, allocation release, and capacity restoration through their owning physical authorities. Failure or unknown acknowledgement at any teardown stage MUST keep the affected capacity unavailable and operator-repairable until authoritative reconciliation completes.

#### Scenario: Lease expires after successful collection

- **WHEN** the authoritative lease deadline is reached
- **THEN** the same lease/access references drive revocation and teardown exactly once without a financial reclaim

#### Scenario: Revocation outcome is unknown

- **WHEN** the access authority may have revoked access but local acknowledgement is lost
- **THEN** recovery reconciles the same revocation operation and capacity is not republished as available
