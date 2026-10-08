## ADDED Requirements

### Requirement: Reservations carry a burn rate and a funded bound

A capacity reservation MUST carry a burn rate: a posted hold rate structure, stated by
the seller in the same form and resolved through the same tiers as the lease rate and
defaulting to the lease rate at any tier that states none, evaluated against the held
shape in exact integer arithmetic. The hold rate MUST NOT be negotiated and a negotiated
lease multiplier MUST NOT apply to it. A reservation's maximum hold duration MUST be
derived from the funds committed against it and that burn rate. Configured hold
durations and pool hold-duration policy MUST act as ceilings on the derived value rather
than as its source, so a hold never outlives its funding and never expires with
committed funds unconsumed.

#### Scenario: Hold duration is bounded by committed funds

- **WHEN** a hold is placed with funds committed against a burn rate
- **THEN** its maximum duration is the funded amount divided by that rate, and it lapses
  at that point through the ordinary expiry path

#### Scenario: Configured duration exceeds what was funded

- **WHEN** a configured hold duration or pool policy would permit longer than the funded
  amount supports
- **THEN** the funded bound governs

#### Scenario: Funded amount exceeds the configured ceiling

- **WHEN** the funded amount would support a longer hold than the configured ceiling
  permits
- **THEN** the ceiling governs, and the excess commitment is not consumed

#### Scenario: A seller states a hold rate

- **WHEN** a hold rate is stated for a capacity dimension at any resolution tier
- **THEN** the burn rate for holding that dimension uses it, and a change to the lease
  rate at that tier leaves it unchanged

#### Scenario: No hold rate is stated

- **WHEN** no tier states a hold rate for a capacity dimension
- **THEN** the burn rate uses the lease rate resolved for that dimension, and changes
  with it

#### Scenario: A negotiated multiplier does not reach the hold

- **WHEN** a negotiation concludes at a multiplier other than 1.0× and its reservation
  is held before or after agreement
- **THEN** the reservation's burn rate is unchanged by the multiplier

### Requirement: Superseding a reservation reprices it

Superseding a reservation with a changed shape MUST recompute the burn rate for the new
shape and the remaining affordable duration from the funds still uncommitted, within the
same atomic operation that supersedes the reservation. The superseding reservation MUST
NOT inherit the superseded one's burn rate.

#### Scenario: Reservation is resized into a more expensive shape

- **WHEN** a held reservation is superseded by a shape with a higher burn rate
- **THEN** the new reservation is charged at the new rate and its remaining duration is
  recomputed from the uncommitted funds

#### Scenario: Supersede fails because the new shape has no candidate

- **WHEN** the new shape cannot be admitted and the supersede rolls back
- **THEN** the original reservation retains its original burn rate and remaining
  duration unchanged

### Requirement: Non-exclusive capacity operations are not charged

An operation that reserves no capacity and excludes no other buyer MUST NOT be charged.
Only capacity held under an exclusive claim MAY be billed.

#### Scenario: Buyer verifies feasibility without holding

- **WHEN** a buyer verifies whether a shape can be served, consuming no capacity
- **THEN** no charge arises and no funds are required

#### Scenario: Buyer holds capacity

- **WHEN** a buyer holds capacity that other buyers therefore cannot reserve
- **THEN** the held time is chargeable
