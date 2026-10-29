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
- **THEN** hosted records show stop per part under buyer-checked seller PT0S/returned entries and reverse per part/amount under existing authority for rate earnings since at, once unserved shares and any full bond award, with no exceptional-end payments kind/field or dispute case

#### Scenario: Restitution requires mandate authorization

- **WHEN** hosted qualification exercises on-demand seller restitution
- **THEN** every part has the explicit seller PT0S/returned stop entry visible to buyer checking, with no implicit role-based permission, payee waiver of payer notice or payer early release
- **AND** the seller holds only that stop entry; non-preemption is remedied by buyer case over held money and the bond, not enforced by the mandate

#### Scenario: Spot multi-entry support is unavailable

- **WHEN** payments cannot represent several stop entries per account per part
- **THEN** spot's immediate seller stop remains an unscheduled gated dependency and emergency exit waits out seller notice; activation must not claim immediate restitution

#### Scenario: Cooperative stop is journaled while payments is down

- **WHEN** end_delivery reaches the storefront during payment outage
- **THEN** signed receipt time governs delivery end and, only where an entry authorizes the storefront's dispute-free action, it journals a cooperative stop with buyer receipt-plus-notice treatment and payer partialPeriod, without notice waiver
- **AND** absent that authorization, stopping payments remains the buyer half's job

### Requirement: Rate activation preserves existing commitment servicing

The production switch MUST NOT reinterpret accepted terms or redirect an existing commitment to another authority. Startup coherence and continued servicing after withdrawal MUST consume convergence's market-composition contract. Deployment preparation MUST confirm target selectors and readiness before seeding and live execution, and credential values MUST remain outside public configuration and evidence.

#### Scenario: Operator withdraws the declaration

- **WHEN** new per-period deals are disabled after activation
- **THEN** accepted terms and authorities remain unchanged and convergence's continued-servicing contract is requalified

#### Scenario: Target readiness fails

- **WHEN** the intended hosted target is not ready
- **THEN** live deal scenarios do not run, the failed setup is recorded and activation remains blocked
