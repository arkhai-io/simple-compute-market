## MODIFIED Requirements

### Requirement: Mechanism-neutral constrained preference

Buyer orchestration MUST normalize legacy escrow entries and settlement options into immutable preference candidates only after installed/enabled compatibility and authoritative resource constraints. Explicit repeatable settlement clauses MUST be evaluated in command order before configured-policy ranking, and every predicate in one clause MUST match the same advertised option. Policy output MUST NOT introduce an unadvertised or incompatible choice. When no explicit clause is supplied, configured mechanism priority remains the pre-acceptance policy input.

#### Scenario: Buyer requests hosted fiat

- **WHEN** a Stripe settlement clause and supported asset leave several hosted options
- **THEN** buyer policy ranks only those matching hosted options and exact deterministic fallback applies if it expresses no preference

#### Scenario: Buyer selects Alkahest

- **WHEN** an Alkahest clause or interactive choice selects an existing compatible Alkahest option
- **THEN** the existing escrow creation/submission path and run-log fields remain unchanged and no hosted API is called

#### Scenario: Several clauses match

- **WHEN** more than one explicit settlement clause has compatible candidates
- **THEN** the earliest matching clause wins before configured mechanism priority and no later clause is considered after acceptance

### Requirement: Hosted buyer action handling

After accepted terms are submitted, the buyer MAY start the accepted hosted obligation and retrieve its current action. Fresh purchase and resume MUST apply the common `--action open|print|fail` policy. The CLI MUST persist only the opaque settlement reference, public status, action type, and expiry; it MUST NOT persist or log an action URL, payment/customer/card data, provider identity, request credential, or raw service body.

#### Scenario: Hosted Checkout action is returned

- **WHEN** settlement start returns a browser redirect action and action policy is `open`
- **THEN** the CLI opens it and stores only the allowed opaque action metadata

#### Scenario: Hosted Checkout action is printed

- **WHEN** settlement start or resume returns a browser redirect action and action policy is `print`
- **THEN** the CLI displays it without opening it or writing it to the run log

#### Scenario: Buyer resumes after losing the redirect

- **WHEN** a run log contains the hosted settlement reference but no URL
- **THEN** the buyer retrieves the current action/status from the storefront and applies the current action policy rather than relying on a persisted URL or creating another settlement

## ADDED Requirements

### Requirement: Buyer normal path consumes two DSLs

Domain purchase commands MUST accept one resource-query DSL input and zero or more settlement-clause DSL inputs. Resource filtering MUST complete before settlement compatibility, clause ordering, negotiation policy, and any mechanism-specific prerequisite resolution. Removed convenience flags MUST NOT remain as hidden aliases or alternate precedence layers.

#### Scenario: Resource matches have no settlement match

- **WHEN** the resource query returns listings but the buyer has not enabled any mechanism advertised by those listings
- **THEN** the command reports a settlement incompatibility rather than claiming that the registry returned no resource listings

### Requirement: Buyer mechanism utilities are namespaced

Raw mechanism-specific setup, inspection, and mutation commands MUST live below `market settlement <mechanism>`. Normal `market buy`, `market settle`, resume, and accepted-obligation lifecycle commands MUST derive mechanism inputs from the selected option or accepted run and MUST NOT accept chain-, token-, provider-, or browser-specific flags.

#### Scenario: Accepted Alkahest run is resumed

- **WHEN** `market settle --from <run>` resumes Terms containing an Alkahest obligation
- **THEN** the command derives chain, token, decimals, and escrow identity from accepted state and typed configuration without legacy override flags
