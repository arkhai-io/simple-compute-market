## ADDED Requirements

### Requirement: Buyer consumes common settlement preference

Buyer orchestration MUST filter advertised options by installed/enabled mechanisms and use the canonical configured priority as policy input before accepted Terms. It MUST resolve mechanism-specific prerequisites only after a concrete option is selected and MUST NOT treat priority as permission to switch an accepted obligation.

#### Scenario: Hosted fiat is preferred

- **WHEN** a compatible hosted and Alkahest option are both advertised and `fiat.stripe.v1` is first in buyer priority
- **THEN** the buyer policy may select hosted fiat without resolving wallet, chain, RPC, token, or gas inputs

#### Scenario: Preferred option is incompatible

- **WHEN** the first-priority mechanism has no compatible advertised option
- **THEN** policy may evaluate the next configured mechanism before negotiation acceptance, but it does not rewrite a seller option or invent fallback after acceptance

### Requirement: Buyer config template is role-appropriate

Generated buyer configuration MUST use the shared `[Settlement]` vocabulary while omitting seller-only hosted account, authority administration, onboarding, publication, and provider fields. Mechanism-specific buyer constraints MAY appear only in the owning typed subsection.

#### Scenario: Fiat-only buyer initializes configuration

- **WHEN** the user generates an Ed25519 hosted-fiat buyer config
- **THEN** the output contains identity and settlement preference inputs but no wallet/chains or seller account configuration
