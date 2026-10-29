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

Activation MUST requalify foundation/spot's terms and payment-adapter contracts, not supply another pricing implementation. Observations MUST cover per-stopper and term-end treatment, fail-closed unsupported terms, activation-before-start, setup once end and exceptional-end self-correction. No storefront end-pricing correction MAY substitute for an unsupported term.

#### Scenario: Published schema cannot express returned

- **WHEN** a preset asks for payee last_boundary but the vendored contract cannot encode it
- **THEN** publication and acceptance refuse rather than rely on later correction; interim charged acceptance records explicit buyer-policy opt-in

#### Scenario: A seller corrects an exceptional end

- **WHEN** an unentitled end is corrected through the payment adapter
- **THEN** hosted records show unconditional returned stops, rate reversals since at, once unserved-share reversals and any full bond award, without an exceptional-end dispute case

#### Scenario: Counterparty-beneficial actions are available

- **WHEN** hosted qualification exercises foundation's party-action contract
- **THEN** payee stop without entitlement returns the partial period, payee may waive payer notice, payer may release held money early and payee may reverse held money, without replacing dispute-authority entries

#### Scenario: Cooperative stop is journaled while payments is down

- **WHEN** end_delivery reaches the storefront during payment outage
- **THEN** the signed receipt time governs delivery end and the retained seller command later stops billing at receipt plus payer notice with payer partialPeriod, subject to seller notice waiver

### Requirement: Rate activation preserves existing commitment servicing

The production switch MUST NOT reinterpret accepted terms or redirect an existing commitment to another authority. Startup coherence and continued servicing after withdrawal MUST consume convergence's market-composition contract. Deployment preparation MUST confirm target selectors and readiness before seeding and live execution, and credential values MUST remain outside public configuration and evidence.

#### Scenario: Operator withdraws the declaration

- **WHEN** new per-period deals are disabled after activation
- **THEN** accepted terms and authorities remain unchanged and convergence's continued-servicing contract is requalified

#### Scenario: Target readiness fails

- **WHEN** the intended hosted target is not ready
- **THEN** live deal scenarios do not run, the failed setup is recorded and activation remains blocked
