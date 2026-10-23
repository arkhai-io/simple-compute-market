## MODIFIED Requirements

### Requirement: The payments mandate is derived exactly from the Agreement

The mandate's `deal` MUST be `sha256(JCS(agreement))` and its transaction ID `sha256(JCS(mandate))`. It MUST name `settlement_params.payer_account` as `from`, the selected option's payee account as `to`, and one `once` part for the agreed amount and asset, plus one seller-funded `bond` part when the option carries `bond`. It MUST use the service's published fee policy and the fixed nonce `arkhai.payments.v1`. It MUST authorize `start` for the seller alone, `stop` only on stoppable parts and only for the initiators the option's `early_termination` entitles, and `reverse` for the seller and Arkhai dispute authority.

#### Scenario: Hold and approval expiry follow the accepted timing

- **WHEN** a seller derives a mandate from an Agreement accepted at `accepted_at`
- **THEN** the hold is `ceil(start_utc - accepted_at) + duration_seconds + window` whole seconds, approval expires at `floor(accepted_at) + window`, and fractional timestamps stay unchanged in the Agreement and its deal hash

#### Scenario: A once mandate is derived

- **WHEN** a mandate is derived from an option with one `once` part and no `early_termination`
- **THEN** the seller is its only `start` authority and it has no `stop` authority

#### Scenario: A bonded mandate is derived

- **WHEN** a mandate is derived from an option carrying `bond`
- **THEN** it has a `bond` part funded by the seller for that amount, and it is committed only once both parties have approved it
