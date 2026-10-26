## MODIFIED Requirements

### Requirement: Settlement fields have common and mechanism-owned namespaces

The settlement DSL MUST reserve common fields for immutable option identity and mechanism-neutral values, including mechanism, option ID, and asset, and the lifecycle term codec's projections (`adjudication.dispute`, `early_termination.payer`, `early_termination.payee`, `early_termination.payee.notice_seconds`). A settlement registration MAY contribute typed public projection fields only under its configuration-key namespace, such as `arkhai_payments.deposit_agreement`, `arkhai_payments.approval_window`, or `alkahest.chain`. Unknown, role-inapplicable, secret, credential, provider-administrator, raw RPC, or non-public fields MUST be rejected. Shared parsing and selection MUST treat contributed values as typed projections and MUST NOT interpret opaque mechanism parameters.

#### Scenario: Qualified Arkhai payment field is used

- **WHEN** a clause contains `mechanism=arkhai_payments arkhai_payments.deposit_agreement=true`
- **THEN** the Arkhai payments registration validates and projects the public deposit setting while shared selection only evaluates the typed result

#### Scenario: Provider field is requested

- **WHEN** a clause names a payment provider ID, credential, webhook value, or authority-administrator field
- **THEN** validation rejects the field without contacting the payment service or exposing any provider data

#### Scenario: A buyer asks for buyer-stoppable options

- **WHEN** a clause contains `early_termination.payer=true` and a listing has one option with a payer entitlement and one without
- **THEN** only the option with the entitlement matches
