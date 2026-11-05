# Spec Delta

## ADDED Requirements

### Requirement: Compute readiness progresses without buyer polling

For a committed VM or bare-metal deal, seller servicing MUST adopt the existing
fulfillment's validated active delivery and durably record availability without
a buyer calling a fulfillment status or access route. Adoption MUST preserve
selected-site and resource identity, source-evidence validation, deadlines and
end-service admission. It MUST NOT dispatch another fulfillment.

#### Scenario: The buyer disconnects after commit

- **WHEN** the selected site's existing fulfillment becomes active before the delivery deadline after an accepted commitment
- **THEN** seller servicing records availability and the buyer's signed lifecycle read reports delivery progress without a legacy fulfillment read
- **AND** repeated servicing preserves one fulfillment and the recorded availability instant

#### Scenario: Readiness observation fails

- **WHEN** the site cannot return or validate its active result during servicing
- **THEN** availability remains unproved and later servicing retries the same fulfillment
- **AND** recovery of site end reports and physical teardown remains independently runnable

#### Scenario: A final end precedes adoption

- **WHEN** an end or delivery deadline already refuses disclosure when the active result is observed
- **THEN** servicing does not mark the resource available or disclose access
- **AND** the existing fulfillment follows the ordinary physical end path
