## ADDED Requirements

### Requirement: Trusted reverse-delivery ownership

Provisioning-to-storefront lifecycle/result delivery MUST resolve destination, identity, and credentials from an operator-trusted owner/site relationship. Buyer-controlled terms and opaque agreement/deal metadata MUST NOT supply authoritative callback URLs or credentials. Each caller MUST be attributable and independently revocable.

#### Scenario: Agreement metadata conflicts with trusted binding

- **WHEN** opaque agreement data contains a callback URL or credential different from the configured owner binding
- **THEN** the provisioner ignores that routing material and uses or rejects according to the trusted binding

#### Scenario: One storefront accepts several provisioners

- **WHEN** distinct authorized provisioning authorities deliver notifications to one storefront
- **THEN** the receiver authenticates and attributes each caller without relying on one process-global shared admin secret
