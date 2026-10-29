## ADDED Requirements

### Requirement: Commit snapshots an activation deadline when the pool resolves an allowance

On first commit, an effective pool-resolved allowance MUST set renew_by_utc to max(commit_time, lease_start_utc) plus that allowance and renewal_phase to awaiting_activation. Such a commit MUST require a finite end. Recommit MUST preserve both fields. No effective allowance and migrated existing leases MUST retain null fields and end-only expiry.

#### Scenario: A compute reservation is committed

- **WHEN** a reservation in a pool resolving a provisioning allowance is first committed with a finite agreed end
- **THEN** the site records the provisional deadline from max(commit time, lease start) and the awaiting-activation phase without receiving payment terms

#### Scenario: A commit is retried after the pool policy changes

- **WHEN** a committed reservation is committed again after its pool allowance changes
- **THEN** its original deadline, phase and agreed window remain unchanged

#### Scenario: An existing lease or quota hold has no allowance

- **WHEN** the site migrates an existing lease or commits a quota hold whose pool resolves no allowance
- **THEN** its deadline and phase are null and its previous expiry semantics remain unchanged

#### Scenario: A protected pool receives an unbounded commit

- **WHEN** a pool resolving an allowance is asked to commit with no finite end
- **THEN** the site refuses without committing the lease

#### Scenario: A future lease starts after commit

- **WHEN** a lease starting at 12:00 commits at 10:00 with a 30-minute allowance
- **THEN** its provisional deadline is 12:30, not 10:30
- **AND** its agreed window and admission accounting are unchanged

### Requirement: Activation replaces the provisional deadline with the agreed end

Activation MUST move a leased awaiting_activation reservation conditionally to active with deadline equal to its current lease_end_utc. It MUST accept no target deadline or payment fact. Leased active/null-phase retries MUST return unchanged; other states MUST refuse mutation. An elapsed unclaimed deadline MUST NOT itself prevent activation.

#### Scenario: Each compute billing shape activates

- **WHEN** a reserved, on-demand, spot or Alkahest delivery activates its awaiting-activation lease
- **THEN** the site sets the deadline to that lease's current agreed end, never to a payment-derived deadline

#### Scenario: Activation is retried after truncation

- **WHEN** an active lease is truncated and activation is retried
- **THEN** the site returns the current lease without extending its end or resetting its deadline

#### Scenario: A shortened awaiting lease activates and acknowledgement is lost

- **WHEN** end service truncates a lease before activation and activation then succeeds without a persisted acknowledgement
- **THEN** retry returns the current shorter end and original active instant
- **AND** neither call extends the lease to the original commit end

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
