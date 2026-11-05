## ADDED Requirements

### Requirement: A lease carries an activation phase

A lease row MUST carry nullable `renewal_phase` (`awaiting_activation`, `active` or null), nullable `renew_by_utc` and nullable `activated_at_utc`. Migration MUST leave all three null on existing rows, and an existing active lease MUST NOT become awaiting activation during upgrade. `lease_end_utc` MUST keep meaning the agreed end and MUST move only through truncation. Admission MUST account the full agreed window whatever the phase.

#### Scenario: Existing leases migrate unchanged

- **WHEN** the site migrates a database with leased rows
- **THEN** every existing lease has null phase, null due instant and null activation instant, and expires only at its agreed end

### Requirement: Activation moves a lease to active and sets its due instant to the agreed end

Activation MUST move a `leased` reservation in phase `awaiting_activation` or null conditionally to phase `active`, setting its due instant to its current `lease_end_utc`. It MUST write `activated_at_utc` from the site's clock in the same transaction, once, and MUST NOT update it afterwards; the activation's reference is the reservation identity with that instant. It MUST accept no target deadline and no payment fact and MUST be addressed by reservation identity. Retried in `active` it MUST return the current lease unchanged; from `releasing`, terminal, failed-release or operator-owned states it MUST refuse without a write. Activation MUST NOT change the reservation's end.

#### Scenario: Each compute billing shape activates

- **WHEN** a reserved, on-demand, spot or Alkahest delivery activates its lease
- **THEN** the site sets the phase to active and the due instant to that lease's current agreed end, never to a payment-derived instant

#### Scenario: Activation is retried after truncation

- **WHEN** an active lease is truncated and activation is retried
- **THEN** the site returns the current lease without extending its end or moving its `activated_at_utc`

#### Scenario: A shortened lease activates and the acknowledgement is lost

- **WHEN** end service truncates a lease before activation and activation then succeeds without a persisted acknowledgement
- **THEN** the retry returns the current shorter end and the original `activated_at_utc`
- **AND** neither call extends the lease toward its original commit end

#### Scenario: Release already claimed the lease

- **WHEN** activation arrives after the reservation entered releasing
- **THEN** it is refused and the release is not undone

#### Scenario: A legacy lease is activated

- **WHEN** activation is called on a lease with null phase and null due instant
- **THEN** the phase becomes active, the due instant stays the agreed end, and nothing else about the lease changes
