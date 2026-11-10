## ADDED Requirements

### Requirement: Production rate servicing requires a qualified hosted revision

> **Owned by `switch-on-hosted-per-period-vm`.** The VM production declaration's hosted-revision gate and the scenario "Schema is published but target is older" for VM; kept until that change's design writes its delta. Bare metal and the treatments beyond `charged` stay here.

> **Stale.** "A charged interim subset MAY activate only with explicit buyer-policy opt-in" contradicts the default buyer: the MVP's accepts a charged final period everywhere, and the full product's refuses it only on a seller's preemption and at the term end; each composition's servicing declaration instead lists its qualified treatments, and every undeclared treatment fails closed.

Production compositions MUST NOT declare rate servicing until the hosted deployment supports the vendored per-part authority/hold revision and every offered stop term. Qualification MUST verify pending notices, offered partial-period billing, afterStop holds, post-stop partial reverse and extend/lift through real responses. A charged interim subset MAY activate only with explicit buyer-policy opt-in; other terms MUST fail closed.

#### Scenario: Schema is published but target is older

- **WHEN** the schema and vectors include the required revision but the selected hosted deployment does not implement it
- **THEN** production publication, acceptance and materialization of rate deals remain disabled

#### Scenario: Hosted revision qualifies

- **WHEN** hosted behavior and consumer conformance pass for the required revision
- **THEN** VM and bare-metal production compositions may declare published-contract rate servicing and enforce the declaration at all three doors

### Requirement: Activation requalifies the owned payment and lifecycle contracts

> **Stale.** The scenario "Published schema cannot express returned" assumes `returned` is unvendored and that charged acceptance needs buyer opt-in; the vendored revision encodes it (`kit/arkhai-payments/schema/SOURCE.md`), so the intended replacement is "a treatment the composition has not declared is refused at publication and acceptance". The scenario "A seller files an exceptional end" cites "The standard seller self-penalty refunds unearned money", which no permanent specification defines.

Activation MUST requalify foundation/spot's payment and dispute contracts, not implement pricing.

#### Scenario: The full policy is enforced

- **WHEN** the owning component validates or applies this contract
- **THEN** Activation MUST requalify foundation/spot's payment and dispute contracts, not implement pricing. Observations MUST cover per-stopper/term-end treatment, fail-closed terms, activation-before-start, the setup once encoded end at Agreement start, effectively clamped to approval if later, delivery_end filing and payee-signed delivery_end rule with cause-specific remedies. delivery_end MUST use the payee-agreement mechanical guards; otherwise it MUST stay triaged; buyer half MUST own payment stops and outage retry. No storefront end-pricing correction MAY replace an unsupported term.

#### Scenario: Published schema cannot express returned

- **WHEN** a preset asks for payee last_boundary but the vendored contract cannot encode it
- **THEN** publication and acceptance refuse rather than rely on later correction; interim charged acceptance records explicit buyer-policy opt-in

#### Scenario: A seller files an exceptional end

- **WHEN** an unentitled seller end is handled through the dispute adapter
- **THEN** hosted observations satisfy deal-lifecycle's “The standard seller self-penalty refunds unearned money” and “Premature-stop penalties consume only held earnings”
- **AND** qualification records the hosted authority responses, not a second activation-owned mapping

#### Scenario: On-demand non-preemption is remedied

- **WHEN** qualification exercises seller emergency exit in on-demand or spot
- **THEN** seller entries exist only for entitlements such as spot notice; emergency uses delivery_end filing, with no seller restitution entry or several-stop-entries dependency
- **AND** on-demand always returns the partial period under its self-penalty contract; non-preemption is remedied by the premature-stop penalty and buyer case over held money, not enforced by the mandate

#### Scenario: Buyer stop is journaled while payments is down

- **WHEN** the buyer cannot reach payments and end_delivery reaches the storefront
- **THEN** hosted observations satisfy buyer-orchestration's “The buyer's end is backed by its own stop or a case”
- **AND** qualification records payment/case progress against the hosted deployment rather than defining another outage path

### Requirement: Rate activation preserves existing commitment servicing

> **Owned by `switch-on-hosted-per-period-vm`.** The VM production switch's withdrawal without reinterpreting deals, and target selector and readiness confirmation before seeding; kept until that change's design writes its delta. Bare metal and the extended VM treatments stay here.

The production switch MUST NOT reinterpret accepted terms or redirect an existing commitment to another authority. Startup coherence and continued servicing after withdrawal MUST consume convergence's market-composition contract. Deployment preparation MUST confirm target selectors and readiness before seeding and live execution, and credential values MUST remain outside public configuration and evidence.

#### Scenario: Operator withdraws the declaration

- **WHEN** new per-period deals are disabled after activation
- **THEN** accepted terms and authorities remain unchanged and convergence's continued-servicing contract is requalified

#### Scenario: Target readiness fails

- **WHEN** the intended hosted target is not ready
- **THEN** live deal scenarios do not run, the failed setup is recorded and activation remains blocked
