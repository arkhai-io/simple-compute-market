## ADDED Requirements

### Requirement: Publication derives all ready settlement options

A storefront MUST preflight every enabled installed settlement registration and derive deterministic listing options from every ready mechanism in configured priority order. One unready mechanism MUST be suppressed with an operator-visible sanitized blocker while ready peers remain publishable. If none are ready, publication MUST fail without mutating accepted negotiations or active settlement state.

#### Scenario: Stripe is unready and Alkahest is ready

- **WHEN** both are enabled but hosted account readiness is false
- **THEN** the storefront publishes the Alkahest option, omits the Stripe option, and reports the hosted blocker without provider detail

#### Scenario: Readiness returns after publication

- **WHEN** a previously suppressed mechanism becomes ready
- **THEN** reconciliation may add its deterministic option without changing listing identity or any already accepted Terms

### Requirement: Storefront owns seller settlement UX

Seller configuration, readiness, mechanism administration, and publication MUST be exposed through the storefront CLI and generated role config surface. A hosted client MAY supply workflow primitives, but a separate provider-specific seller executable MUST NOT be the normal marketplace entry point.

#### Scenario: Seller inspects all settlement mechanisms

- **WHEN** `market-storefront settlement status --json` runs
- **THEN** it returns the common status schema for every installed mechanism in configured order without a listing or financial side effect
