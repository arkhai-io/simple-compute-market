## MODIFIED Requirements

### Requirement: The payments mandate is derived exactly from the Agreement

The mandate's `deal` MUST be `sha256(JCS(agreement))` and its transaction ID `sha256(JCS(mandate))`. It MUST name `settlement_params.payer_account` as `from`, the selected option's payee account as `to`, and one `once` part for the agreed amount and asset, with mandate-level authorities. Every hold MUST last until the lease end plus the option's `adjudication.dispute_window_seconds`, and approval MUST expire after the option's `approval_window`. A hosted option MUST NOT carry `bond` until the payments service can hold a seller-funded part. It MUST use the service's published fee policy and the fixed nonce `arkhai.payments.v1`. A `once`-only mandate MUST authorize no `start` and no `stop`, and MUST authorize `reverse` for the seller and Arkhai dispute authority. A `reverse` MAY name a part and an amount up to what that part still holds.

#### Scenario: Hold and approval expiry follow the accepted timing

- **WHEN** a seller derives a mandate from an Agreement accepted at `accepted_at`
- **THEN** the hold is `ceil(start_utc - accepted_at) + duration_seconds + dispute_window_seconds` whole seconds, approval expires at `floor(accepted_at) + approval_window`, and fractional timestamps stay unchanged in the Agreement and its deal hash

#### Scenario: A once mandate is derived

- **WHEN** a mandate is derived from an option with one `once` part and no `early_termination`
- **THEN** it has no `start` or `stop` authority, and its hold ends the dispute window after the lease end

#### Scenario: A hosted option names a bond

- **WHEN** a seller configures a hosted option with `bond`
- **THEN** the builder refuses to emit it, naming the unsupported term
