## ADDED Requirements

### Requirement: API-credit publication composes settlement alternatives from quota

A quota-backed API-credit listing MUST publish `settlement_options` from every complete ready shared mechanism clause and `accepted_escrows` from valid Alkahest entries as independent alternatives. Hosted publication MUST emit one distinct option per exact ready profile and rate. Listing identity and reconciliation MUST bind service/quota resource plus the complete ordered settlement alternatives; stale unavailable quota preserves the last complete listing, zero quota closes it, and settlement readiness changes reconcile only affected alternatives without inventing capacity.

#### Scenario: Quota and three hosted profiles are ready

- **WHEN** the API-credit resource has sellable units and card, US bank transfer, and ACH clauses pass exact preflight
- **THEN** the storefront publishes three deterministic hosted alternatives alongside any configured Alkahest escrows

#### Scenario: ACH becomes unready

- **WHEN** reconciliation observes a safe ACH blocker while quota and card remain ready
- **THEN** the complete listing is updated without ACH, preserves card/Alkahest choices, and exposes no provider or payer detail

#### Scenario: Quota authority is unavailable

- **WHEN** settlement readiness is observable but authoritative quota cannot be read
- **THEN** reconciliation preserves the last complete listing rather than republishing from guessed capacity

### Requirement: API-credit publication validates domain and settlement coherence

Before publication, the storefront MUST validate that each settlement alternative's seller/claimant equals the configured canonical storefront principal, its condition can verify the signed API-credit issuance evidence contract, its currency/rate can price one credit exactly, and its expiry policy allows issuance and eligible reclaim. Hosted option account/profile/condition values MUST come from trusted config, not listing request input. Duplicate option identities, cross-service reuse, fractional/overflow rate, unsupported evidence resolver, and inconsistent parties MUST fail the affected publication.

#### Scenario: Hosted condition targets another evidence schema

- **WHEN** a configured clause cannot resolve the exact signed API-credit issuance evidence
- **THEN** that hosted alternative is blocked before registry publication

#### Scenario: Operator submits a provider account override

- **WHEN** API-credit listing creation input attempts to set a hosted account, payer, instrument, provider method, or condition payload
- **THEN** the storefront rejects the override and does not publish it

### Requirement: API-credit accepted settlement is server-authoritative

Settlement start MUST accept only the accepted negotiation/obligation identifiers and mechanism-required safe reference. The storefront MUST reload trusted listing and accepted terms, validate exact settlement selection, service, quantity, key mode/key ID, canonical buyer/claimant, price/currency, expiry, and condition, and derive issuance input server-side. Hosted start uses the safe funding-authorization reference; Alkahest continues its existing accepted-escrow proof. No caller may override key ownership, grant identity, condition, account, amount, profile, or parties.

#### Scenario: Buyer changes quantity at hosted start

- **WHEN** a start request attempts to submit another quantity, key ID, amount, profile, or claimant
- **THEN** the request is rejected before hosted materialization or credit issuance
