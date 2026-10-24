## ADDED Requirements

### Requirement: Capacity-backed VM listings are finite standing offers

Following committed capacity changes, a storefront SHALL use publication's domain-owned fit decision to keep fungible and specific-resource VM offers published only while their bound source fits another advertised instance. It SHALL close offers that no longer fit and reopen the same automatically capacity-closed listing when fit returns. Publication is not a reservation guarantee or public purchase quantity.

#### Scenario: Seven of eight identical offers have settled

- **GIVEN** one resource can fit eight instances of a published shape and pre-settlement hold TTL is zero
- **WHEN** settlement reservations consume seven instances
- **THEN** the same listing remains open in registry discovery because one more instance fits

#### Scenario: Settlement consumes the final fitting instance

- **WHEN** a committed reservation leaves no fitting instance of the listing's advertised shape
- **THEN** the storefront closes that listing at its configured registries through the existing capacity-event lifecycle without requiring a seller publication command
- **AND** under healthy services the close is attempted within one configured capacity polling interval plus projection-refresh and registry-write time

#### Scenario: Positive residual capacity is insufficient

- **GIVEN** a listing requires a shape larger than the remaining capacity of every eligible member
- **WHEN** the capacity change is reconciled
- **THEN** the listing closes even though some capacity remains
- **AND** fragmented capacity across fungible members is not summed to manufacture a fitting member

#### Scenario: Specific-resource capacity returns

- **GIVEN** a specific-resource listing was automatically closed for insufficient capacity
- **WHEN** release or hold expiry commits enough capacity for that bound resource to fit the shape again
- **THEN** the storefront reopens the same listing ID at the registries with the same binding and commercial terms
- **AND** capacity on another resource or site does not reopen the pinned listing

#### Scenario: Fungible capacity returns

- **GIVEN** a fungible listing was automatically closed because no eligible member in its bound pool could fit its shape
- **WHEN** a committed release makes an eligible member fit again
- **THEN** the storefront reopens the same pool-derived listing ID without pinning a new physical resource

#### Scenario: A refund does not release capacity

- **WHEN** a financial refund or lease expiry is observed but the site has not committed an authoritative capacity release
- **THEN** that financial or clock signal alone does not cause the listing to reopen

### Requirement: Capacity reconciliation refreshes the projections it evaluates

A capacity-triggered listing pass SHALL refresh the affected site's existing resource-pool and capacity-bucket projection inputs before evaluating the shared domain fit decision. Concurrent capacity-effect passes SHALL be serialized so opposite status changes cannot overwrite newer intent out of order. Unknown or failed refreshes SHALL NOT be treated as empty capacity or as proof of restored capacity. Work SHALL remain eligible for bounded retry independently of feed cursor progress.

#### Scenario: The capacity feed is ahead of the projection cache

- **GIVEN** cached projections still show capacity before the final reservation
- **WHEN** the reservation's capacity event arrives
- **THEN** reconciliation refreshes its projection inputs before deciding whether the offer fits
- **AND** the event cannot be permanently discharged merely by evaluating the old cached generation

#### Scenario: One site cannot refresh

- **WHEN** a site's projection refresh fails
- **THEN** existing last-good projection reporting is retained and the failure is not interpreted as zero or newly restored capacity
- **AND** that site's work is retried without requiring another capacity event
- **AND** healthy-site reconciliation remains eligible without modifying unrelated bindings

#### Scenario: A successful projection is empty

- **WHEN** the affected site successfully reports an empty projection
- **THEN** reconciliation treats it as known empty rather than falling back to stale inventory

#### Scenario: Startup misses a capacity change

- **WHEN** the storefront starts after a reservation or release, or its initial reconciliation fails
- **THEN** a bounded recovery cycle refreshes and reconciles current capacity without requiring replay of the original event or a new event

### Requirement: Registry availability converges independently of settlement

Registry effects SHALL remain outside settlement's success boundary. The storefront SHALL retain or reconstruct per-registry delivery work from durable current listing intent and publication results until every configured target converges. Bounded retry SHALL survive errors, partial success, quiet feeds and restart, and SHALL apply current intent rather than superseded events.

#### Scenario: Registry is unavailable during exhaustion

- **WHEN** a settlement reservation succeeds and the registry close fails
- **THEN** settlement remains successful and the reservation remains authoritative
- **AND** a subsequent bounded cycle retries the current desired listing status even with no further capacity change

#### Scenario: Only one registry accepted a change

- **WHEN** one registry accepts close or reopen and another configured registry fails
- **THEN** the failed target remains eligible for repair rather than being marked complete by aggregate first-success

#### Scenario: Reopen publication reaches a closed registry row

- **WHEN** capacity recovery republishes an existing closed listing
- **THEN** the same ID is explicitly restored to open status rather than assuming payload upsert reopens it

#### Scenario: Release supersedes a failed close

- **GIVEN** registry delivery of an exhaustion close failed
- **WHEN** capacity becomes available before the next successful registry attempt
- **THEN** the subsequent pass converges the listing to the currently fitting open intent
- **AND** an older queued close cannot leave the registry closed afterward

#### Scenario: Storefront restarts with outstanding delivery

- **WHEN** a storefront restarts after local status changed but before all registry writes succeeded or their results were recorded
- **THEN** reconciliation reconstructs outstanding work from durable local intent, configured targets and publication records and retries it
- **AND** neither retry nor restart creates a replacement listing or reserves capacity again

### Requirement: Automatic capacity recovery preserves seller closure intent

Automatic capacity recovery SHALL reopen only listings closed by capacity reconciliation. Explicit seller closure and pause SHALL remain effective until the seller changes them. A closed legacy row with unknown closure origin SHALL NOT be guessed to be capacity-closed.

#### Scenario: Seller closes an offer before capacity returns

- **WHEN** the seller explicitly closes an offer and its capacity later becomes sufficient
- **THEN** automatic reconciliation does not reopen that offer

#### Scenario: Capacity recovers for a paused offer

- **WHEN** capacity recovery reopens an automatically capacity-closed listing that is also seller-paused
- **THEN** its seller pause remains effective and capacity reconciliation does not resume buyer acceptance
