## MODIFIED Requirements

### Requirement: The payments mandate is derived exactly from the Agreement

The mandate's `deal` MUST be `sha256(JCS(agreement))` and its transaction ID `sha256(JCS(mandate))`. It MUST name `settlement_params.payer_account` as `from`, the selected option's payee account as `to`, and one `once` part for the agreed amount and asset. It MUST use the service's published fee policy and the fixed nonce `arkhai.payments.v1`. The part MUST carry its own lifecycle authorities: `stop` for buyer and seller, each with no notice and the partial period charged; `reverse` for the seller and the Arkhai dispute authority; and an empty `extend`, with a zero maximum hold extension. The mandate MUST NOT carry mandate-level authorities, and a stored mandate that does is refused, never rewritten.

#### Scenario: Hold and approval expiry follow the accepted timing

- **WHEN** a seller derives a mandate from an Agreement accepted at `accepted_at`
- **THEN** the hold is `ceil(start_utc - accepted_at) + duration_seconds + window` whole seconds, approval expires at `floor(accepted_at) + window`, and fractional timestamps stay unchanged in the Agreement and its deal hash

#### Scenario: The part's own authorities grant nothing beyond immediate stop and reversal

- **WHEN** a seller derives a mandate and the buyer checks it
- **THEN** both derive the identical mandate, whose one `once` part lets buyer and seller stop it with `P0D` notice and the partial period charged, lets the seller and the dispute authority reverse it, lets nobody extend its hold, and states `maxHoldExtension` `P0D`, and the mandate has no mandate-level `authorities`

#### Scenario: A mandate in the previous wire is refused

- **WHEN** stored settlement data or a counterparty's mandate carries mandate-level `authorities`, or a part without its own authorities or maximum hold extension
- **THEN** it is refused before any approval or verification, and the stored Agreement bytes and mandate are left as they are
