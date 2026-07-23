## ADDED Requirements

### Requirement: Versioned domain provision envelope

Shared buyer and storefront clients MUST carry provision intent in a versioned domain envelope containing domain kind and domain-defined payload, without compute-specific parameters in the shared wire.

#### Scenario: VM buyer opens negotiation

- **WHEN** a VM buyer constructs initial provision intent
- **THEN** the shared client transmits the VM domain kind and VM-owned payload through the generic envelope

#### Scenario: API-credit buyer opens negotiation

- **WHEN** an API-credit buyer constructs initial provision intent
- **THEN** the same shared client transmits the API-credit domain kind and API-credit-owned payload without VM fields

#### Scenario: Envelope kind does not match storefront domain

- **WHEN** a storefront receives provision terms for a different domain kind or unsupported payload version
- **THEN** it rejects the round before policy or settlement processing with an actionable compatibility error

### Requirement: Legacy provision wire removal

After every in-repository producer and consumer migrates, the shared client and storefront MUST reject the obsolete flat compute-shaped provision-terms form rather than silently coercing it.

#### Scenario: Legacy client calls updated storefront

- **WHEN** a client submits flat legacy provision fields without a supported domain envelope
- **THEN** the storefront returns a version/shape error and does not begin or continue negotiation
