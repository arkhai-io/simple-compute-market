## RENAMED Requirements

- FROM: `### Requirement: Only the seller reverses a held payment`
- TO: `### Requirement: Only the seller refunds a held payment`

## MODIFIED Requirements

### Requirement: The payments mandate is derived exactly from the Agreement

The mandate's `deal` MUST be `sha256(JCS(agreement))` and its transaction ID `sha256(JCS(mandate))`. It MUST name `settlement_params.payer_account` as `from`, the selected option's payee account as `to`, and, on once-only options, one `once` part for the agreed amount and asset, with per-part authorities. Every `once` hold MUST last no less than its own part end plus the option's `adjudication.dispute_window_seconds` (prepaid service ends at Agreement term end; setup ends at the later of the Agreement start and approval), and approval MUST expire after the option's `approval_window`. A hosted option MUST NOT carry `bond` until the payments service can hold a seller-funded part. It MUST use the service's published fee policy and the fixed nonce `arkhai.payments.v1`. A `once`-only mandate MUST authorize no `start` and no `stop`, and MUST authorize `reverse` for the seller and the agreement's dispute authority, the account its `adjudication.dispute` names, and MUST list only that authority under the one `extend` authorities key, which also authorizes `lift`. The dispute authority's account MUST come from the option, not from `[Settlement.arkhai_payments]`. Each part MUST carry `maxHoldExtension` from `adjudication.case_hold_max_seconds`, `null` when unbounded. A `reverse` MAY name a part and an amount up to what that part still holds.

#### Scenario: Hold and approval expiry follow the accepted timing

- **WHEN** a seller derives a mandate from an Agreement accepted at `accepted_at`
- **THEN** each prepaid once part has absolute end start_utc + duration_seconds and hold {afterStop: dispute_window}; approval expires at floor(accepted_at) + approval_window, and fractional Agreement timestamps stay unchanged in its deal hash
- **AND** delayed approval does not shift the part end or replace the stop-relative hold with a duration from acceptance

#### Scenario: A once mandate is derived

- **WHEN** a mandate is derived from an option with one `once` part and no `early_termination`
- **THEN** it has no `start` or `stop` authority, only the dispute authority may `extend` or `lift`, and its hold ends no earlier than the dispute window after the term end

#### Scenario: A hosted option names a bond

- **WHEN** a seller configures a hosted option with `bond`
- **THEN** the builder refuses to emit it, naming the unsupported term

### Requirement: Only the seller refunds a held payment

A refund MUST be seller-initiated through `reverse`. `reverse` is authorized for the seller and the agreement's dispute authority, which uses it only to apply outcomes, and never for the buyer. A full refund MUST keep its ordering against delivery start; a partial `reverse` that leaves money held, such as a discount on a running deal, MUST record no refund intent and change no deal status. The payments service releases an un-reversed hold without a settlement-service call.

#### Scenario: Seller operator refunds a held payment

- **WHEN** a seller-authenticated refund request names an accepted payment deal
  with a verified receipt and still-held funds
- **THEN** the storefront records refund intent, requests `reverse` for that
  transaction, and records the deal refunded; repeats return the same result
  without a second reversal

#### Scenario: Refund and delivery start race

- **WHEN** a refund request and the start of delivery for the same deal overlap
- **THEN** exactly one transition wins: if refund intent was recorded first,
  delivery does not start; if delivery started first, the refund proceeds and
  the deal records both the delivery and the refund

#### Scenario: A seller discounts a running deal

- **WHEN** a seller submits a `reverse` of a quarter of a delivered deal's held payment
- **THEN** the payments service records one partial reverse, and the storefront records no refund intent and leaves the deal's status and lease unchanged

#### Scenario: Only the seller initiates a refund

- **WHEN** delivery fails or the seller voluntarily corrects an unentitled end
- **THEN** the seller files exceptional_end with the agreement's dispute authority and sends no stop or reverse for it; mediation's standard ruling returns unearned money then applies the capped premature-stop penalty, and a buyer disputing the account files a case

## ADDED Requirements

### Requirement: Snapshot verification accepts bounded identity history

Hosted snapshot verification MUST accept configured current/retiring identities with validity windows, embedded-receipt attestation and a caller-supplied minimum sequence. It MUST refuse unverified, cross-deal, mode-changed or regressing state. A fresh current-key snapshot MAY attest an embedded old receipt while retaining original bytes; consumers MUST NOT implement a parallel verifier.

#### Scenario: Rotation re-anchors an old receipt

- **WHEN** a current-key snapshot attests an old receipt during the configured identity overlap
- **THEN** verification checks identity windows, commitment and mode binding and minimum sequence before supplying re-anchoring evidence
