## ADDED Requirements


### Requirement: Whole-host fulfillment preserves selected-resource authority

Where signed accepted terms intentionally identify a Physical Resource, the fulfillment request MUST constrain scheduling to that resource at its trusted site. The site authority MUST verify current eligibility and cross-mode exclusivity, commit the Capacity Reservation before executor dispatch, and fail rather than substitute a different resource/site. Provider and executor references MUST remain independently registered and MUST NOT be inferred from buyer input.

#### Scenario: Selected host conflicts with VM allocation

- **WHEN** cross-mode accounting rejects the exclusive bare-metal reservation
- **THEN** no executor job starts and the failure identifies the accepted reservation/operation without exposing private resource inventory

#### Scenario: Placement policy prefers another site

- **WHEN** the accepted listing is mapped to one site but another site has more capacity
- **THEN** dispatch remains pinned to the accepted site and refusal does not trigger fallback

### Requirement: Bare-metal lease-ready evidence is real and portable

A successful whole-host fulfillment MUST be supported by authoritative provisioning state showing a committed allocation, live lease/fulfillment, completed access grant, and buyer-ready access method. The physical result MUST expose a credential-free public binding among the Physical Resource, allocation/Capacity Reservation and lease/fulfillment references, access method, readiness time, and expiry so the domain/storefront can bind it to the agreement, hosted obligation, buyer, and claimant in signed portable evidence. Neither result MUST include SSH private keys, bearer credentials, provider account IDs, private topology, raw executor responses, or unrestricted connection details.

#### Scenario: Executor reports success without access grant

- **WHEN** provisioning completed but buyer access is not authoritatively ready
- **THEN** fulfillment remains incomplete and no collectible satisfied evidence is published

#### Scenario: Lease becomes access-ready

- **WHEN** allocation, lease, and access authorities all confirm the same immutable binding
- **THEN** one portable signed reference is published and secret access material remains behind the authenticated domain delivery boundary

### Requirement: Bare-metal teardown is durable and capacity-safe

An authoritative lease expiry or termination MUST revoke access, tear down executor state, release the committed allocation/Capacity Reservation, and only then restore publishable capacity. Each operation MUST be durable and idempotent across restart. Unknown, retryable, or terminal teardown outcomes MUST retain resource quarantine/unavailability and normalized operator recovery evidence until reconciled; financial collection/reclaim state MUST NOT substitute for any physical step.

#### Scenario: Teardown completes

- **WHEN** access revocation and executor teardown are authoritative for the accepted lease
- **THEN** allocation release occurs once and the site may publish the Physical Resource available again

#### Scenario: Executor teardown fails

- **WHEN** access may remain or executor cleanup is terminally unresolved
- **THEN** the allocation/resource remains unavailable and operator repair can resume the same teardown identity
