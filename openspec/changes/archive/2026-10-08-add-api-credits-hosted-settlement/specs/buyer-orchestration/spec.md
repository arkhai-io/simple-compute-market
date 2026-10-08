## ADDED Requirements

### Requirement: API-credit buyer selects an exact settlement alternative

The API-credit buyer MUST use the shared settlement registry, policy, readiness, and exact `SettlementSelection` across `settlement_options` and `accepted_escrows`. Selection MUST constrain mechanism, profile, currency, interaction ability, and local payer/wallet readiness before negotiation and MUST revalidate the exact trusted option before acceptance and start. It MUST NOT translate an option into another mechanism/profile or allow legacy chain/token flags to override a hosted selection.

#### Scenario: Buyer selects hosted ACH

- **WHEN** resource/service/quantity/key intent filters and explicit settlement constraints leave one compatible advertised ACH option
- **THEN** negotiation pins its exact identity, profile, currency/rate, condition, seller, and claimant without constructing a wallet

#### Scenario: Hosted buyer is incompatible

- **WHEN** the selected local profile lacks the option's authority binding, ready ACH mandate/instrument, currency policy, or required interaction ability
- **THEN** the buyer filters or rejects it before purchase and does not silently choose card or Alkahest

### Requirement: API-credit hosted purchase uses shared authorization and transport

After accepted terms are durably recorded, the API-credit buyer MUST derive one exact hosted funding authorization from the accepted quantity-scaled obligation through the shared hosted kit, then use shared signed storefront start/status/reclaim transport. Direct hosted calls are limited to shared payer lifecycle and exact authorization; escrow lifecycle remains storefront-mediated. No API-credit code may duplicate hosted canonicalization, request/response verification, action parsing, or VM transport.

#### Scenario: Accepted hosted purchase starts

- **WHEN** the selected persistent buyer profile signs the exact authorization
- **THEN** the buyer submits only negotiation ID, obligation ID, and safe authorization reference to the API-credit storefront and polls the returned opaque settlement

#### Scenario: Funding authorization conflicts

- **WHEN** exact retry changes service, quantity, key target, amount, destination, profile, seller, condition, or expiry
- **THEN** authorization/start fails without another grant or mechanism fallback

### Requirement: API-credit hosted actions and delayed funding are resumable

The API-credit buyer MUST apply the common `--action open|print|fail` policy to payer setup, payment, confirmation, and bank-instruction actions. Run state MUST retain only accepted identities, exact profile, authorization/settlement references, public state/reason/deadline, action kind/expiry, and secret-free fulfillment reference. Resume MUST retrieve current action/status; raw actions, hosted payer/instrument/provider data, and API bearer secret MUST NOT enter the generic run log.

#### Scenario: Off-session purchase requires confirmation

- **WHEN** bounded local automation receives `requires_action`
- **THEN** the same accepted authorization/operation continues interactively without changing the API-credit obligation

#### Scenario: Bank funding survives restart

- **WHEN** a buyer restarts while push transfer or ACH is pending
- **THEN** it resumes the exact operation, displays any current transient action, and waits for authoritative issuance/collection without reauthorizing or renegotiating

### Requirement: API-credit credentials are delivered only after issuance

For a new-key purchase, the authenticated buyer result path MAY return the bearer credential only after exact-once issuance succeeds; discovery, negotiation, funding, settlement status, portable evidence, public receipt/result, and generic run logs MUST remain secret-free. Existing-key top-up MUST return public key ID and updated safe result but MUST NOT re-expose the bearer secret. The buyer MUST preserve credentials only in the existing owner-controlled API-credit credential destination, not the settlement profile store.

#### Scenario: New-key hosted purchase completes

- **WHEN** authoritative funding, issuance evidence, and collection complete
- **THEN** the canonical buyer can retrieve the new credential and use it while public settlement output contains no secret

#### Scenario: Existing key is topped up

- **WHEN** the same canonical owner completes a valid top-up
- **THEN** the buyer observes the exact credited quantity without receiving a replacement or existing secret

### Requirement: API-credit buyer verifies usable fulfillment

The full buyer flow MUST verify that a newly issued key admits the named API service, consumption decrements the balance, exhaustion returns HTTP 402 purchase guidance, and a same-owner top-up restores admitted use. These usage checks MUST be domain result checks after settlement and MUST NOT alter financial completion or expose the key in evidence/logs.

#### Scenario: Purchased credits are exhausted and replenished

- **WHEN** a new-key purchase consumes its final unit and a same-profile existing-key top-up completes
- **THEN** the next pre-top-up request receives 402 and a post-top-up request is admitted with the same key ownership
