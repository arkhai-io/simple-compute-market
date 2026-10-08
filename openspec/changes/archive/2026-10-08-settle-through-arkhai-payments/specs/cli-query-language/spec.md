## MODIFIED Requirements

### Requirement: Publication rates are asset-scoped human quantities

A settlement publication clause that sets a rate MUST name its asset and unit and MUST express the rate as a decimal human quantity. The selected mechanism MUST normalize that quantity exactly once to its canonical integer base or minor units without rounding. A missing asset/unit, excessive precision, zero or negative value where unsupported, or one untyped price reused across mechanisms MUST fail before publication. Each mechanism alternative MUST receive its own explicit rate even when their displayed human values are equal.

#### Scenario: Equal displayed rates use different scales

- **WHEN** a seller publishes `2/hour` for USD/2 and separately `2/hour` for a six-decimal token
- **THEN** the Arkhai payment option records 200 minor units and the token option records 2000000 base units without sharing an intermediate `min_price`

#### Scenario: Decimal cannot be represented exactly

- **WHEN** the named asset scale cannot represent the supplied decimal rate without rounding
- **THEN** publication rejects that clause and publishes no option derived from it

### Requirement: Settlement clauses are correlated ordered alternatives

Each `--settlement` occurrence MUST form one typed conjunction over one `SettlementOption`. Repeated clauses MUST be evaluated in command order as pre-acceptance alternatives. Every comparison in a clause MUST match the same option; comparisons MUST NOT be satisfied by different options from one listing. Explicit clauses MUST only narrow installed, enabled, mechanism-compatible advertised options and MUST NOT enable a mechanism, invent an option, or authorize post-acceptance failover.

#### Scenario: Two settlement alternatives are supplied

- **WHEN** the buyer supplies a Arkhai payment clause followed by an Alkahest clause and both have compatible advertised matches
- **THEN** selection considers the Arkhai payment clause first and retains the Alkahest clause only as a pre-acceptance alternative

#### Scenario: Predicates occur on different options

- **WHEN** one listing has a Arkhai payment USD/2 option and a separate Alkahest option whose fields collectively but not individually satisfy one clause
- **THEN** the clause does not match that listing

#### Scenario: Accepted mechanism later becomes unavailable

- **WHEN** accepted Terms pin an option selected through a settlement clause and its mechanism later becomes disabled or unready
- **THEN** recovery resumes the pinned obligation without evaluating another clause

### Requirement: Settlement fields have common and mechanism-owned namespaces

The settlement DSL MUST reserve common fields for immutable option identity and mechanism-neutral values, including mechanism, option ID, and asset. A settlement registration MAY contribute typed public projection fields only under its configuration-key namespace, such as `arkhai_payments.deposit_agreement` or `alkahest.chain`. Unknown, role-inapplicable, secret, credential, provider-administrator, raw RPC, or non-public fields MUST be rejected. Shared parsing and selection MUST treat contributed values as typed projections and MUST NOT interpret opaque mechanism parameters.

#### Scenario: Qualified Arkhai payment field is used

- **WHEN** a clause contains `mechanism=arkhai_payments arkhai_payments.deposit_agreement=true`
- **THEN** the Arkhai payments registration validates and projects the public deposit setting while shared selection only evaluates the typed result

#### Scenario: Provider field is requested

- **WHEN** a clause names a payment provider ID, credential, webhook value, or authority-administrator field
- **THEN** validation rejects the field without contacting the payment service or exposing any provider data
