## ADDED Requirements

### Requirement: Bare-metal delivery enters through the core fulfillment hook

Bare-metal payment settlement and the Alkahest ready continuation MUST start delivery by calling core's `fulfill_domain` with a `StorefrontFulfillmentContext`, never by calling the bare-metal fulfillment service directly. The registered bare-metal hook MUST build its service and the compute delivery path from the clients in the context's `ports` and the storefront's lifecycle in its `domain_input`, so every bare-metal delivery passes end-service admission and core's check that the result keeps the deal's negotiation, settlement reference and site.

#### Scenario: A bare-metal payment deal settles

- **WHEN** a bare-metal buyer's payment receipt verifies
- **THEN** settlement calls `fulfill_domain`, the hook runs the delivery path with admission, and core validates the returned identities

#### Scenario: The hook is called without the storefront's lifecycle

- **WHEN** the bare-metal hook is invoked with no lifecycle in `domain_input`
- **THEN** it refuses before any capacity or fulfillment call
