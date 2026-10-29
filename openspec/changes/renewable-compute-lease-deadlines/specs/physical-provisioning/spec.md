## ADDED Requirements

### Requirement: The compute watchdog enforces unactivated lease deadlines

The lease watchdog MUST consider the earlier of the agreed lease end and a non-null lease deadline, using the site's conditional expiry claim before provider effects. An activation-lapsed lease MUST follow the existing release lifecycle and capacity guard. An activated lease MUST have no renewable liveness deadline earlier than its agreed end. Provider calls MUST remain outside ledger transactions.

#### Scenario: A storefront disappears before activation

- **WHEN** an unactivated compute lease becomes due and expiry claims its observed tuple
- **THEN** the watchdog releases through the ordinary guarded path without contacting a storefront or payment service

#### Scenario: The storefront disappears after activation

- **WHEN** an activated lease passes its former provisional deadline while its agreed end remains in the future
- **THEN** the watchdog does not reclaim it for absent storefront renewal

#### Scenario: Creation is already dispatched

- **WHEN** activation lapse is claimed for a lease whose create operation is still in flight
- **THEN** the lifecycle adopts its result and completes the ordinary teardown path rather than freeing capacity ahead of proven release

### Requirement: Activation lapse is signed physical-end evidence

The signed `lease_ended` record MUST support `activation_deadline_lapsed` with the claimed deadline and phase alongside the base record's identity, correlation and actual end time. Deadline expiry MUST NOT fabricate an earlier physical end. The durable outbox MUST preserve record identity and signed content across retries. This evidence MUST NOT itself authorize a payment stop, reversal or refund.

#### Scenario: The watchdog releases for activation lapse

- **WHEN** the deadline wins the due comparison and its claim leads to a physical end
- **THEN** the event records the activation-lapse cause, claimed deadline and phase, and the actual end instant under the base event contract

#### Scenario: Event acknowledgement is lost

- **WHEN** delivery of the signed lease-ended record is retried
- **THEN** the original identity and signed evidence are preserved

#### Scenario: Delivery fails without a site event

- **WHEN** no signed lease-ended record has arrived at the storefront
- **THEN** the site contract supplies no payment operation and imposes no event prerequisite on the seller's exceptional-end filing
