## ADDED Requirements

### Requirement: Intended lease ends are reported separately from capacity release

Compute provisioning MUST deliver each stored `lease_ended` report to the owning storefront from a durable outbox keyed by event identity, signing the stored payload with the site's service identity. It MUST keep acknowledgements separate from the capacity-released callback and expose the same signed report through the authenticated lease read for recovery. The report MUST state intended end, not prove teardown or free capacity.

#### Scenario: The site crashes after recording an end

- **WHEN** the end transition commits and the process crashes before sending its report
- **THEN** recovery delivers the stored event with its original identity, instant and cause, rather than rebuilding them from the reservation's later state

#### Scenario: An acknowledgement is lost

- **WHEN** the storefront receives a report but its acknowledgement is lost
- **THEN** the outbox retries the same event identity and payload until acknowledged

#### Scenario: Teardown completes after the report

- **WHEN** the site reports an intended end and physical teardown completes later
- **THEN** the separate capacity-released callback retains its own acknowledgement and is still the signal of proven capacity return

#### Scenario: The storefront recovers by reading the lease

- **WHEN** a storefront misses a pushed report and reads the lease
- **THEN** the authenticated response contains the original report's payload and site proof for verbatim retention and return to the buyer

### Requirement: Site end reporting is mechanism neutral

The site MUST report lease ends only to the owning storefront and MUST NOT require a payment transaction ID, payment-mechanism dependency or payee credential to record or deliver them.

#### Scenario: A lease ends under either settlement mechanism

- **WHEN** a VM or bare-metal lease ends regardless of its deal's settlement mechanism
- **THEN** the same site event and delivery path apply without a call to any payment authority
