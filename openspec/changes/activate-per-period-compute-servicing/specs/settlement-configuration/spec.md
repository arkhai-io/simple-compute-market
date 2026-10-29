## ADDED Requirements

### Requirement: Production rate servicing requires a qualified hosted revision

Production compositions MUST NOT declare rate servicing until the hosted deployment supports the vendored per-part authority/hold revision and every offered stop term. Qualification MUST verify pending notices, offered partial-period billing, afterStop holds, post-stop partial reverse and extend/lift through real responses. A supported charged/charged subset MAY activate before partialPeriod is vendored if dispute policy permits; other terms MUST fail closed.

#### Scenario: Schema is published but target is older

- **WHEN** the schema and vectors include the required revision but the selected hosted deployment does not implement it
- **THEN** production publication, acceptance and materialization of rate deals remain disabled

#### Scenario: Hosted revision qualifies

- **WHEN** hosted behavior and consumer conformance pass for the required revision
- **THEN** VM and bare-metal production compositions may declare published-contract rate servicing and enforce the declaration at all three doors

### Requirement: Partial-period qualification cannot use local end corrections

Activation MUST verify SCM started_period, last_boundary and stop map to authority charged, returned and prorated respectively. Unsupported terms MUST fail closed. Before the revision is vendored spot MUST offer only charged/charged, not a corrective end refund. Setup once MUST end at activation and its self-penalty MUST return all when undelivered and none after delivery.

#### Scenario: Published schema cannot express returned

- **WHEN** a preset asks for payee last_boundary but the vendored contract cannot encode it
- **THEN** publication and acceptance refuse the term rather than rely on a later storefront reversal

#### Scenario: Delivery activates successfully

- **WHEN** setup completes and the lease activates
- **THEN** rate start follows activation, setup once ends there and pays one dispute window later

### Requirement: Rate activation preserves existing commitment servicing

Enabling or withdrawing new rate-deal publication MUST NOT reinterpret accepted terms, redirect an existing commitment to another authority, or remove its lifecycle loops. Deployment preparation MUST confirm target selectors and readiness before seeding and live execution, and credential values MUST remain outside public configuration and evidence.

#### Scenario: Operator withdraws the declaration

- **WHEN** new per-period deals are disabled after activation
- **THEN** accepted commitments continue watching authority records, executing end effects and retaining evidence under their original Agreement

#### Scenario: Target readiness fails

- **WHEN** the intended hosted target is not ready
- **THEN** live deal scenarios do not run, the failed setup is recorded and activation remains blocked
