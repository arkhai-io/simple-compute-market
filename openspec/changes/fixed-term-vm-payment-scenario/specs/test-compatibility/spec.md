## ADDED Requirements

### Requirement: Fixed-term VM payment scenario

The VM lane MUST include `e2e_vm_payment_deal` with three ordered calls: production discovery-driven buy through `arkhai.payments.v1`, settlement replay from the original profiled buyer run, and seller refund followed separately by lease-expiry/convergence mock capacity release. It MUST require receipt-gated tenant delivery and the same transaction and durable fulfillment on replay. An absent payments target remains readiness-blocked, not a private-service CI dependency.

#### Scenario: A fixed-term payment VM is delivered and refunded

- **WHEN** an owned backed VM listing advertises USD 1.00/hour and the configured payments target is ready
- **THEN** a wallet-free Ed25519 buyer discovers and buys a one-hour fixed term
- **AND** seller delivery follows actual approval, replay retains the transaction and tenant delivery, and seller refund reverses every held once part
- **AND** the mock VM lease is released through expiry and fulfillment convergence, not as an assumed effect of refund

