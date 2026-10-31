## ADDED Requirements

### Requirement: Rate-part servicing is storefront-side and mechanism-neutral

The shared storefront servicing loop MUST live in kit/deal-servicing, receive payment/dispute adapters through lifecycle protocols, and receive physical effects through injected domain ports. It MUST NOT import mechanism kits, dispute kits or domain implementations. VM and bare-metal compositions MUST wire the same servicing behavior into the storefront loop controller, retaining domain-owned physical semantics.

#### Scenario: Both domains compose rate servicing

- **WHEN** VM and bare-metal storefronts enable servicing
- **THEN** both use the shared end service and their own injected lease/activation/teardown ports without a copied convergence state machine

### Requirement: Accepted rate commitments retain their servicing composition

A storefront with accepted rate-part commitments MUST refuse startup if its servicing loop is absent. Withdrawal of new publication MUST NOT remove servicing from existing commitments. An authority outage alone MUST NOT cause this local-coherence refusal. Proposed-contract declarations MUST remain lane-only until production activation qualifies the hosted contract deployment.

#### Scenario: Servicing is removed with active commitments

- **WHEN** a storefront starts with persisted accepted rate-part commitments and no end-service loop
- **THEN** startup refuses its incoherent local composition before serving new work

#### Scenario: New publication is withdrawn during an outage

- **WHEN** publication is disabled and the payment authority is unavailable
- **THEN** the correctly composed storefront starts, preserves its pending work and continues physical servicing of existing commitments
