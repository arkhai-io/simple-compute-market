## ADDED Requirements

### Requirement: Production rate servicing requires a qualified hosted revision

Production compositions MUST NOT declare rate servicing until the hosted deployment supports the vendored per-part authority/hold revision and every offered stop term. Qualification MUST verify pending notices, offered partial-period billing, afterStop holds, post-stop partial reverse and extend/lift through real responses. A charged interim subset MAY activate only with explicit buyer-policy opt-in; other terms MUST fail closed.

#### Scenario: Schema is published but target is older

- **WHEN** the schema and vectors include the required revision but the selected hosted deployment does not implement it
- **THEN** production publication, acceptance and materialization of rate deals remain disabled

#### Scenario: Hosted revision qualifies

- **WHEN** hosted behavior and consumer conformance pass for the required revision
- **THEN** VM and bare-metal production compositions may declare published-contract rate servicing and enforce the declaration at all three doors

### Requirement: Activation requalifies the owned payment and lifecycle contracts

Activation MUST requalify foundation/spot's payment and dispute contracts, not implement pricing. Observations MUST cover per-stopper/term-end treatment, fail-closed terms, activation-before-start, setup once end, exceptional_end filing and sole mechanical payee self-penalty. Buyer_end MUST remain human-triaged; buyer half MUST own payment stops and outage retry. No storefront end-pricing correction MAY replace an unsupported term.

#### Scenario: Published schema cannot express returned

- **WHEN** a preset asks for payee last_boundary but the vendored contract cannot encode it
- **THEN** publication and acceptance refuse rather than rely on later correction; interim charged acceptance records explicit buyer-policy opt-in

#### Scenario: A seller files an exceptional end

- **WHEN** an unentitled seller end is handled through the dispute adapter
- **THEN** hosted observations satisfy deal-lifecycle's “The standard seller self-penalty refunds unearned money” and “Premature-stop penalties consume only held earnings”
- **AND** qualification records the hosted authority responses, not a second activation-owned mapping

#### Scenario: On-demand non-preemption is remedied

- **WHEN** qualification exercises seller emergency exit in on-demand or spot
- **THEN** seller entries exist only for entitlements such as spot notice; emergency uses exceptional_end filing, with no seller restitution entry or several-stop-entries dependency
- **AND** on-demand always returns the partial period under its self-penalty contract; non-preemption is remedied by the premature-stop penalty and buyer case over held money, not enforced by the mandate

#### Scenario: Buyer stop is journaled while payments is down

- **WHEN** the buyer cannot reach payments and end_delivery reaches the storefront
- **THEN** hosted observations satisfy buyer-orchestration's “The buyer's end is backed by its own stop or a case”
- **AND** qualification records payment/case progress against the hosted deployment rather than defining another outage path

### Requirement: Rate activation preserves existing commitment servicing

The production switch MUST NOT reinterpret accepted terms or redirect an existing commitment to another authority. Startup coherence and continued servicing after withdrawal MUST consume convergence's market-composition contract. Deployment preparation MUST confirm target selectors and readiness before seeding and live execution, and credential values MUST remain outside public configuration and evidence.

#### Scenario: Operator withdraws the declaration

- **WHEN** new per-period deals are disabled after activation
- **THEN** accepted terms and authorities remain unchanged and convergence's continued-servicing contract is requalified

#### Scenario: Target readiness fails

- **WHEN** the intended hosted target is not ready
- **THEN** live deal scenarios do not run, the failed setup is recorded and activation remains blocked
