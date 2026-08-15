## ADDED Requirements

### Requirement: Provider-neutral conditional escrow client

The kit-owned settlement runtime MUST drive every settlement mechanism through one asynchronous conditional-escrow contract whose operations materialize an obligation, retrieve authoritative status, evaluate an immutable fulfillment reference, collect an authorized obligation, and reclaim an expired obligation. Results MUST expose only an opaque mechanism reference, public lifecycle status, optional buyer action, optional condition anchor, and opaque durable receipt.

#### Scenario: Hosted materialization requires buyer action
- **WHEN** `fiat.stripe.v1` materialization creates a hosted Checkout action
- **THEN** the runtime persists the opaque hosted reference and public action metadata while the action URL remains transient and service-owned

#### Scenario: Alkahest remains selected
- **WHEN** an `alkahest.v1` obligation is serviced
- **THEN** the existing Alkahest adapter, fields, SDK operations, and outcomes remain unchanged and no hosted-service call occurs

### Requirement: Versioned hosted condition input

A hosted obligation MUST carry exactly one immutable condition descriptor with a unique condition ID, a versioned evaluator kind, a configuration-owned resolver ID where applicable, and canonical demand encoded as either `evm-abi` or `application/jcs+json`. Negotiated condition parameters MUST contain immutable policy inputs only and MUST NOT contain credentials, URLs, RPC endpoints, headers, or signing keys.

#### Scenario: Hosted option contains an unconfigured resolver URL
- **WHEN** the adapter validates a condition whose negotiated parameters contain a caller-supplied resolver URL
- **THEN** materialization fails before buyer payment action is created

### Requirement: Hosted adapter validation and state projection

The `fiat.stripe.v1` adapter MUST accept only buyer-funded, seller-claimed obligations with a positive integer minor-unit amount, lowercase ISO 4217 currency, immutable account reference, expiry, and supported typed condition. Provider `false` MUST remain pending, retryable transport or provider uncertainty MUST enter shared retry handling, and hosted `operator_review` MUST project as `manual_required` without inventing a successful outcome.

#### Scenario: Condition is not currently satisfied
- **WHEN** the hosted authority returns an authoritative false evaluation before expiry
- **THEN** the shared worker retains a pending condition and may check again without collecting or marking terminal failure

#### Scenario: Hosted authority requires operator review
- **WHEN** status reports `operator_review`
- **THEN** marketplace state reports manual intervention and does not collect, reclaim, or guess provider outcome

### Requirement: Fulfillment and reclaim exclusion

Hosted servicing MUST use the shared obligation identity, operation journal, work leases, and compare-and-set transitions. At stored expiry, reclaim MAY reserve only when no fulfillment lease or success, submitted collect/provider transfer, or reserved satisfied evaluation exists. Fulfillment success MUST permanently remove reclaim authority and MUST resume check and collect after restart even when expiry subsequently passes.

#### Scenario: Fulfillment succeeds immediately before expiry
- **WHEN** immutable VM fulfillment commits before the reclaim compare-and-set
- **THEN** reclaim is rejected and restart resumes hosted condition check and collection

#### Scenario: Pending condition reaches expiry without fulfillment success
- **WHEN** no fulfillment lease/success, collect reservation, or satisfied evaluation exists at expiry
- **THEN** reclaim may reserve and the shared lifecycle prevents a later collect reservation

### Requirement: Secret-free fulfillment projection

The VM domain MUST encode only the versioned evidence allowed by the accepted condition. EAS mode MUST send a configured resolver ID and fulfillment UID; portable mode MUST send only the allowlisted proof projection. Generic fulfillment results, tenant credentials, SSH material, connection details, arbitrary provider fields, URLs, and headers MUST NOT enter fulfillment references, hosted requests, settlement rows, logs, or generated fixtures.

#### Scenario: VM fulfillment contains connection credentials
- **WHEN** a condition evidence projection is generated from a successful fulfillment result
- **THEN** credentials and connection fields are absent and a canary test rejects any projection that would include them
