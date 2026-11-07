## ADDED Requirements

### Requirement: A lease records when it was activated

A reservation MUST carry a nullable `activated_at_utc`, written only by activation as an ISO-8601 UTC instant from the site's clock. Whether the site has recorded a lease's activation MUST be derived from it and stored nowhere else. Null MUST mean only that no activation is recorded: on a reservation that predates the column it says nothing about whether the resource was delivered, and no consumer may treat it as evidence that it was not. Every service hosting the site ledger MUST add it in its migration chain, leaving it null on every existing reservation, with no backfill.

#### Scenario: Existing reservations migrate with no activation recorded

- **WHEN** a compute provisioning or API-credits database holding leased reservations is migrated
- **THEN** every reservation has a null `activated_at_utc`, and its state, window and expiry are unchanged
- **AND** nothing records whether a lease that predates the migration was delivered

#### Scenario: The instant is read

- **WHEN** a reservation is read through the site's reservation view
- **THEN** it carries `activated_at_utc`, null until activation and the recorded instant after it

### Requirement: Activation records its instant once and changes nothing else

Activation MUST be admissible only for a lease: a `leased` reservation with a lease end. Where `activated_at_utc` is null it MUST write it in one transaction; where set, it MUST return the reservation unchanged. From any other state, and on a `leased` reservation with no lease end, it MUST be refused with nothing written. It MUST NOT change state or window, record a capacity event, or alter admission. It MUST answer 200 with the recorded reservation, 404 for an unknown one, and 409 when refused, naming the state, or for a reservation with no lease end saying that it has no lease tail.

#### Scenario: A leased reservation is activated

- **WHEN** activation is requested for a `leased` reservation with no `activated_at_utc`
- **THEN** the site records the instant from its own clock and returns the reservation with it
- **AND** the lease's state, start and end are unchanged and no capacity event is recorded

#### Scenario: Activation is retried

- **WHEN** activation is requested again for an activated lease, including after the site restarts
- **THEN** the site returns the reservation with the instant the first activation recorded

#### Scenario: A lease is truncated before activation

- **WHEN** a lease committed until T2 is truncated to T1 and then activated
- **THEN** the response carries the end T1 and the activation instant, and the lease still ends at T1

#### Scenario: A truncation falls between a lost acknowledgement and its retry

- **WHEN** activation succeeds without its answer reaching the caller, the lease is then truncated, and activation is retried
- **THEN** the retry returns the shorter end and the original activation instant, and neither call extends the lease

#### Scenario: Release already claimed the lease

- **WHEN** activation is requested for a reservation that is `releasing`, `release_failed`, `unmanaged`, `released` or `force_released`
- **THEN** the site answers 409 naming the state, writes nothing, and the release is not undone

#### Scenario: An uncommitted hold is activated

- **WHEN** activation is requested for a `reserved` reservation
- **THEN** the site answers 409 and the hold stays uncommitted and unactivated

#### Scenario: An open-ended hold is activated

- **WHEN** activation is requested for a `leased` reservation committed with no lease end
- **THEN** the site answers 409 saying it has no lease tail, and the reservation's `activated_at_utc` stays null

#### Scenario: An unknown reservation is activated

- **WHEN** activation names a reservation the site does not hold
- **THEN** the site answers 404 and writes nothing

#### Scenario: Admission around an activated lease

- **WHEN** a new reservation overlaps an activated lease's agreed window
- **THEN** admission accounts the activated lease against capacity exactly as before activation

### Requirement: Activation is addressed by reservation identity alone

An activation request MUST name only the reservation, by its `capacity_reservation_id`, and MUST carry no payment fact, billing kind, target time or instant. The instant MUST be the site's, whatever time the caller acted.

#### Scenario: A storefront activates a lease

- **WHEN** a storefront activates a lease through the site's capacity API
- **THEN** the request carries the reservation identity and nothing else, and the recorded instant is the site's clock at the transition
