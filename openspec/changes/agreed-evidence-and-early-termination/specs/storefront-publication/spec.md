## MODIFIED Requirements

### Requirement: Payment publication discloses mandate policy

VM, bare-metal, and API-credit storefronts supporting `arkhai.payments.v1` MUST publish ready payment clauses as independent `settlement_options` beside supported Alkahest alternatives. Every option MUST bind asset, rates, payee account, approval window, `adjudication` with its dispute window, and agreement-deposit setting. No Stripe funding profile or provider object MAY enter an option.

#### Scenario: A payment clause is ready

- **WHEN** a resource has a complete ready Arkhai payment clause and supported Alkahest terms
- **THEN** publication exposes distinct choices with independent rates and deterministic option IDs

#### Scenario: Payment policy is incomplete

- **WHEN** a clause lacks required payee, asset, approval window, dispute window, or deposit policy
- **THEN** publication rejects it without inferring values from an Alkahest price or mutating accepted deals

## ADDED Requirements

### Requirement: Lifecycle terms are published per option

A listing MUST publish lifecycle terms, including the dispute window, only inside its settlement options. The VM admin interrupt route MUST identify an Alkahest interruptible deal by its accepted option's release condition, not by a listing field.

#### Scenario: An administrator interrupts an Alkahest deal

- **WHEN** an administrator interrupts a deal whose accepted Alkahest option uses the splitter release condition
- **THEN** the route accepts it, without reading a listing-level marker
