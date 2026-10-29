## ADDED Requirements

### Requirement: Commit snapshots an activation deadline when the pool resolves a delivery deadline

On first commit, the site MUST set renew_by_utc to max(committed_at_utc, lease_start_utc) plus the deal's accepted delivery_deadline_seconds supplied with the commit, and renewal_phase to awaiting_activation; committed_at_utc is the deal's commitment instant supplied with the commit and MUST NOT be later than the site's commit time. The site MUST refuse a commit whose accepted deadline exceeds the pool's current effective delivery deadline or carries one where the pool resolves none. A commit supplying no accepted deadline MUST take the pool's current effective deadline when one resolves. Such a commit MUST require a finite end. Recommit MUST preserve both fields. No effective delivery deadline MUST leave the phase and due instant as the activation change's migration left them: null, with end-only expiry.

#### Scenario: A compute reservation is committed

- **WHEN** a reservation in a pool resolving a delivery deadline is first committed with a finite agreed end
- **THEN** the site records the provisional deadline from max(commitment instant, lease start) and the awaiting-activation phase without receiving payment terms

#### Scenario: A storefront supplies a future commitment instant

- **WHEN** a commit carries a commitment instant later than the site's clock
- **THEN** the site refuses the commit

#### Scenario: The pool was lengthened after acceptance

- **WHEN** a deal accepted with a 1800-second deadline is committed after the pool's deadline was raised to 3600
- **THEN** the site enforces 1800 seconds from the anchor

#### Scenario: The pool was shortened below the accepted deadline

- **WHEN** a deal accepted with an 1800-second deadline is committed after the pool's deadline was lowered to 900, or after the pool stopped enforcing one
- **THEN** the site refuses the commit, the storefront classifies the refusal as seller failure before dispatch with no provisioning issued, and the reservation it already holds is released through the storefront's no-dispatch release path rather than left to its expiry

#### Scenario: A commit is retried after the pool policy changes

- **WHEN** a committed reservation is committed again after its pool delivery deadline changes
- **THEN** its original deadline, phase and agreed window remain unchanged

#### Scenario: An existing lease or quota hold has no delivery deadline

- **WHEN** the site migrates an existing lease or commits a quota hold whose pool resolves no delivery deadline
- **THEN** its deadline and phase are null and its previous expiry semantics remain unchanged

#### Scenario: A protected pool receives an unbounded commit

- **WHEN** a pool resolving a delivery deadline is asked to commit with no finite end
- **THEN** the site refuses without committing the lease

#### Scenario: A future lease starts after commit

- **WHEN** a lease starting at 12:00 is committed at 10:00, commitment instant 10:00, with a 30-minute delivery deadline
- **THEN** its provisional deadline is 12:30, not 10:30
- **AND** its agreed window and admission accounting are unchanged

### Requirement: Activation replaces the provisional deadline with the agreed end

Activation, as `activate-compute-leases-at-the-site` defines it, MUST replace an awaiting_activation lease's provisional deadline with its current lease_end_utc. An elapsed unclaimed deadline MUST NOT itself prevent activation.

#### Scenario: Activation arrives after the deadline but before expiry claims it

- **WHEN** the deadline has elapsed and the reservation remains leased and awaiting activation
- **THEN** activation may claim the transition and replace the deadline with the agreed end

#### Scenario: Expiry already claimed the lease

- **WHEN** activation arrives after the reservation entered releasing
- **THEN** it is refused and neither release nor its deadline is undone

### Requirement: Deadline expiry claims the exact observed lease tuple

A due query MUST return the observed end, deadline and phase. Expiry MUST claim `leased` state and equality of that tuple atomically before any release effect. A mismatch MUST cause no mutation, event, outbox item or provider call. The due instant MUST be the earlier non-null deadline or agreed end; ordinary term end MUST win ties. Successful claims MUST use the existing guarded release path without holding a transaction over provider I/O.

#### Scenario: Activation wins against a stale expiry read

- **WHEN** expiry reads an awaiting-activation deadline and activation changes the phase before expiry claims it
- **THEN** the stale claim fails with no release effect and a later cycle reevaluates the lease

#### Scenario: Expiry wins against activation

- **WHEN** expiry claims the unchanged due tuple before activation
- **THEN** the reservation enters releasing once and activation cannot resurrect it

#### Scenario: Truncation changes the tuple after a due read

- **WHEN** the agreed end changes between expiry's due read and claim
- **THEN** the stale claim fails without effects and a new due read determines the correct cause

#### Scenario: Deadline and agreed end coincide

- **WHEN** a lease becomes due at both its deadline and agreed end
- **THEN** expiry records ordinary term end rather than activation lapse

### Requirement: Activation deadlines do not shorten admission windows

Capacity admission MUST account the full agreed lease window, not the activation deadline. Truncation MUST remain earlier-only and MUST cap any non-null deadline to the new end. Capacity MUST remain unavailable until the ordinary guarded release succeeds, regardless of an elapsed activation deadline.

#### Scenario: A forward reservation overlaps the agreed term

- **WHEN** a new reservation overlaps a leased reservation's agreed window but starts after its provisional activation deadline
- **THEN** admission still accounts the existing lease against capacity

#### Scenario: An activation deadline is earlier or later than a truncated end

- **WHEN** a leased reservation is truncated to an earlier end
- **THEN** its deadline is no later than the new end and truncation never extends the agreed window

#### Scenario: A create remains in flight at expiry

- **WHEN** an activation deadline is claimed while fulfillment creation is in flight
- **THEN** the existing release guard prevents capacity returning until delivery is resolved and safe release is proven
