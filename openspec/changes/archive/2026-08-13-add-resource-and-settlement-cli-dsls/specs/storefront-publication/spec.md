## MODIFIED Requirements

### Requirement: Publication derives all ready settlement options

A storefront MUST preflight every enabled installed settlement registration and derive deterministic listing options from every ready mechanism in configured priority order and the seller's validated settlement publication clauses. A clause MUST NOT make a disabled or unready mechanism publishable. One unready mechanism MUST be suppressed with an operator-visible sanitized blocker while ready peers remain publishable. If no enabled ready mechanism has a valid publication clause, publication MUST fail without mutating accepted negotiations or active settlement state.

#### Scenario: Stripe is unready and Alkahest is ready

- **WHEN** both have publication clauses but hosted account readiness is false
- **THEN** the storefront publishes the Alkahest option, omits the Stripe option, and reports the hosted blocker without provider detail

#### Scenario: Readiness returns after publication

- **WHEN** a previously suppressed mechanism becomes ready and its publication clause remains valid
- **THEN** reconciliation may add its deterministic option without changing listing identity or any already accepted Terms

#### Scenario: Clause names a disabled mechanism

- **WHEN** seller publication input names a mechanism whose typed configuration is disabled
- **THEN** publication rejects that clause without using it as an implicit enablement override

### Requirement: Storefront owns seller settlement UX

Seller configuration, readiness, mechanism administration, and publication MUST be exposed through the storefront CLI and generated role config surface. Normal publication MUST accept mechanism-neutral settlement clauses and MUST NOT expose provider-, chain-, or escrow-specific flags. Mechanism administration MUST remain under `settlement <mechanism>`. A hosted client MAY supply workflow primitives, but a separate provider-specific seller executable or top-level mechanism-specific publication flow MUST NOT be the normal marketplace entry point.

#### Scenario: Seller inspects all settlement mechanisms

- **WHEN** `market-storefront settlement status --json` runs
- **THEN** it returns the common status schema for every installed mechanism in configured order without a listing or financial side effect

#### Scenario: Seller publishes two mechanisms

- **WHEN** normal publication receives valid Stripe and Alkahest settlement clauses
- **THEN** the storefront derives both through their ready registrations without invoking a mechanism-specific publication command

## ADDED Requirements

### Requirement: Publication pricing is explicit per settlement clause

Every priced settlement publication clause MUST contain one asset-scoped decimal rate and unit. The owning mechanism MUST normalize it to canonical integer minor or base units using authoritative asset scale, reject non-exact conversion, and include the normalized rate in deterministic option identity. A resource-level `min_price` or other untyped scalar MUST NOT be reused as the price of more than one mechanism.

#### Scenario: Dual listing uses equal human prices

- **WHEN** a seller explicitly publishes USD 2/hour and six-decimal-token 2/hour clauses for one resource
- **THEN** the resulting options carry 200 and 2000000 canonical units respectively and both display as 2 asset units/hour

#### Scenario: Dual listing omits one mechanism rate

- **WHEN** a resource has one valid mechanism clause and another enabled mechanism has no explicit rate-bearing clause
- **THEN** publication does not infer the missing mechanism's price from the first clause

### Requirement: Per-resource settlement input uses the common clause contract

Command defaults, imported resource records, and reconciliation inputs that describe settlement options MUST parse to the same typed settlement-clause model before option derivation. Unknown fields, conflicting duplicate values, role-inapplicable fields, and malformed rates MUST fail the affected candidate without creating a partially interpreted option.

#### Scenario: Imported resource overrides settlement defaults

- **WHEN** one resource record supplies its own complete settlement clauses
- **THEN** those clauses replace the command-level defaults for that resource and are validated through the same grammar and registrations
