## ADDED Requirements

### Requirement: Requested offering mode is explicit and bounded by the pool

Every capacity probe and reservation claim MUST carry a non-empty canonical `executor_kind` naming the requested offering mode. The site authority MUST persist that exact value on the Capacity Reservation and MUST NOT infer it from `vm_host`, `physical_host_id`, resource kind, market name, matched-resource attributes, or any default executor. A matching Resource Pool MUST currently declare the requested mode before a new hold is created.

Legacy reservations, settlement assignments, and executor jobs that predate the field MUST be backfilled only when durable request, settlement, provider-input, or executor-reference evidence proves exactly one mode. An active row with no proof or conflicting proof MUST be quarantined from execution; a completed row keeps its terminal lifecycle state while recording the quarantine. A settlement or request identity that conflicts with an already explicit reservation identity is schema drift, not a precedence choice.

#### Scenario: Claim omits the requested mode

- **WHEN** a capacity probe or reservation claim omits `executor_kind`
- **THEN** the site authority rejects it before matching resources and does not infer `vm` from a matched resource

#### Scenario: Pool does not declare the requested mode

- **WHEN** a Physical Resource matches the requested shape but its Resource Pool does not declare the claim's offering mode
- **THEN** reservation is refused with the mode and pool identified before a Capacity Reservation or debit exists

#### Scenario: Legacy identity has one durable proof

- **WHEN** a legacy reservation has no executor kind and durable provider or placement fields prove exactly one mode
- **THEN** migration records that mode on the reservation and propagates it to its settlement and executor job

#### Scenario: Legacy identity is unproved or conflicting

- **WHEN** a live legacy reservation or executor job has no single provable mode
- **THEN** migration moves it to the durable unmanaged or failed quarantine path without selecting `vm` or another fallback

### Requirement: Offering mode is enforced through fulfillment

The same pool-declaration membership predicate MUST be applied independently when the site authority admits a reservation, when fulfillment schedules a Settlement Resource, and immediately before provider dispatch. Scheduling and provisioning MUST re-read the selected Resource Pool's current declaration, including on an idempotent retry or a previously prepared provider operation. Withdrawing a mode after a hold or assignment therefore blocks new execution in that mode without mutating the historical requested mode.

Pool mode authorization and cross-mode physical accounting are independent checks. Declaring both `vm` and `bare_metal` authorizes both delivery paths but does not permit an exclusive whole-host allocation to overlap a live shareable slice; conversely, conflict-free capacity does not authorize an undeclared mode.

#### Scenario: Mode is withdrawn after reservation

- **WHEN** a Resource Pool removes the reservation's mode before scheduling
- **THEN** scheduling refuses the reservation without selecting another pool, mode, site, or executor

#### Scenario: Mode is withdrawn after provider input is prepared

- **WHEN** a Resource Pool removes the assignment's mode before a prepared create operation is dispatched
- **THEN** fulfillment refuses before provider I/O and does not treat the snapshot as permanent permission

#### Scenario: Pool declares both physical modes

- **WHEN** a Resource Pool declares `vm` and `bare_metal` but a shareable VM slice already holds the Physical Resource
- **THEN** an exclusive bare-metal request is still refused by cross-mode physical accounting
