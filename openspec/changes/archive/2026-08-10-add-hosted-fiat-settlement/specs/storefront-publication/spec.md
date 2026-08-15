## ADDED Requirements

### Requirement: Preflighted VM fiat option publication

A VM storefront with hosted settlement enabled MUST preflight the configured account readiness, client/manifest contract version, resolver, and condition capability before publishing a fiat option. A published option MUST contain only account reference, `funds_flow="separate_charges_transfers"`, `payment_method_types=("card",)`, lowercase currency/rate, and one typed condition descriptor. It MUST NOT expose provider IDs, URLs, credentials, RPC configuration, webhook data, or administrator state.

#### Scenario: Hosted authority preflight succeeds
- **WHEN** the account and selected condition profile are ready under the configured contract version
- **THEN** the listing publishes one deterministic hosted option beside its unchanged Alkahest entries

#### Scenario: Enabled hosted preflight fails
- **WHEN** readiness or capability preflight fails
- **THEN** the storefront suppresses hosted options, emits a sanitized diagnostic, and continues serving valid Alkahest listings

### Requirement: Server-authoritative settlement start

`POST /api/v1/settlements` MUST accept only negotiation and obligation identifiers, reload the accepted plan, and resolve payer, account, money, expiry, and condition server-side. `GET /api/v1/settlements/{settlement_ref}` MUST return public status and an optional transient buyer action. Buyer-authorized `POST .../{settlement_ref}/reclaim` MUST enter the shared reclaim lifecycle; internal collection MUST run through the shared claims engine. These routes MUST NOT alias or change `/api/v1/settle/{escrow_uid}`.

#### Scenario: Start request supplies provider or money fields
- **WHEN** a caller attempts to override account, amount, currency, condition, or Checkout parameters
- **THEN** the storefront rejects the request and creates no hosted settlement

#### Scenario: Existing Alkahest settle route is called
- **WHEN** a legacy buyer calls `/api/v1/settle/{escrow_uid}`
- **THEN** response shape, authorization, persistence, and side effects remain unchanged

### Requirement: Fulfillment precedes hosted financial collection

After authoritative funding, the shared obligation lifecycle MUST reserve `funded → fulfilling`, commit immutable VM fulfillment through the existing domain boundary, and only then submit condition evidence for check/collection. A fulfillment failure MUST leave capacity cleanup ordered after the hosted refund reaches a terminal successful reclaim outcome.

#### Scenario: Provisioning fails after payment
- **WHEN** hosted funding is authoritative but VM fulfillment fails
- **THEN** no transfer occurs, one reclaim/refund is driven to terminal success, and capacity is released only under the existing failure dispatcher ordering
