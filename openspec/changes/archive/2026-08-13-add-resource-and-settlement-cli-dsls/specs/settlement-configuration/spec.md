## MODIFIED Requirements

### Requirement: Mechanism-owned typed registration

Each installed mechanism MUST register its canonical ID, configuration key and schema, applicable roles, preflight, client factory, listing-option builder, buyer compatibility hook, typed public settlement-clause projections, and any mechanism-specific operator commands. Mechanism-contributed clause fields MUST live under the mechanism's configuration-key namespace and MUST declare their applicable roles, operators, and value types. The shared foundation MUST own registration, grammar integration, ordering, common status, exact option correlation, and composition; it MUST NOT interpret chain-, provider-, arbiter-, condition-, or financial-authority fields.

#### Scenario: Stripe readiness is evaluated

- **WHEN** the common status command preflights `fiat.stripe.v1`
- **THEN** the hosted adapter validates its trust/account/condition contract and returns a common sanitized result without shared code importing provider behavior

#### Scenario: Stripe clause field is evaluated

- **WHEN** a buyer clause uses an allowlisted `stripe`-qualified field
- **THEN** the hosted registration validates and projects that public value while shared selection compares the typed projection without reading opaque hosted parameters

## ADDED Requirements

### Requirement: Mechanism clause projections are public and observational

A mechanism's settlement-clause projection MUST derive only deterministic public values from the advertised option and MUST perform no preflight, client construction, RPC/provider call, account mutation, publication, or settlement transition. Credentials, provider IDs, raw URLs, webhook data, private RPC configuration, administrator state, and opaque receipts MUST NOT be declared or projected as clause fields.

#### Scenario: Clause is evaluated during discovery

- **WHEN** buyer discovery evaluates mechanism-qualified predicates across advertised options
- **THEN** evaluation is deterministic from listing data and performs no chain or provider I/O

### Requirement: Mechanism-specific utilities stay namespaced

Seller and buyer CLIs MUST expose common settlement status and normal lifecycle commands without mechanism-specific flags. Setup, diagnostics, raw inspection, and raw mutation operations that are genuinely mechanism-specific MUST live under `settlement <mechanism>` and MAY consume only that registration's typed configuration and resources. A mechanism namespace MUST NOT create a separate publication path, settlement lifecycle, priority model, or accepted-plan interpretation.

#### Scenario: Seller completes Stripe onboarding

- **WHEN** the seller invokes `market-storefront settlement stripe onboard`
- **THEN** the mechanism-owned utility uses the configured hosted client while normal `publish` remains mechanism-neutral

#### Scenario: Buyer inspects an Alkahest escrow

- **WHEN** the buyer invokes the raw escrow inspection utility
- **THEN** it resolves under `market settlement alkahest` and no raw escrow command remains at the top level
