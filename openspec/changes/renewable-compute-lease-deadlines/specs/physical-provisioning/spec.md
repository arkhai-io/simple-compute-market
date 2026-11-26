## ADDED Requirements

### Requirement: The lease watchdog releases a lease the site reports due

The lease watchdog MUST act on the site's due read and MUST claim each due lease through the site's conditional transition before any provider effect. A lease whose claim the site refuses MUST be left untouched for a later cycle. A lease claimed at its activation deadline MUST follow the same release lifecycle and release guard as a lease claimed at its end, with provider calls outside the ledger's transactions. An activation deadline MUST NOT end a lease whose activation is recorded.

#### Scenario: A storefront stops before delivery

- **WHEN** an unactivated lease passes its activation deadline and the watchdog's claim succeeds
- **THEN** the watchdog releases it through the ordinary guarded path, needing neither a storefront nor a payment service to do so

#### Scenario: A storefront stops after activation

- **WHEN** an activated lease passes its activation deadline with its lease end still ahead
- **THEN** the watchdog does not release it

#### Scenario: A create is in flight at the deadline

- **WHEN** a lease is claimed at its activation deadline while its create operation is still in flight
- **THEN** the lifecycle adopts the create's result and completes teardown, and capacity is not freed ahead of proven release

### Requirement: An activation lapse is reported as an intended lease end

The `lease_ended` report for a lease claimed at its activation deadline MUST state a cause for the lapse, that deadline as its claimed deadline, and a phase naming the activation deadline. It MUST state an intended end, as every `lease_ended` report does, and MUST NOT authorize a payment effect or be a prerequisite of the seller's `delivery_end` filing.

#### Scenario: The watchdog claims an activation lapse

- **WHEN** the watchdog's claim of an unactivated lease at its activation deadline succeeds
- **THEN** the site records one `lease_ended` report carrying the lapse's cause, the deadline and its phase
- **AND** capacity return is still reported separately, once release is proven

#### Scenario: No report has reached the storefront

- **WHEN** a deal misses its delivery deadline and no `lease_ended` report has reached its storefront
- **THEN** nothing the site provides makes the seller's `delivery_end` filing wait for one
