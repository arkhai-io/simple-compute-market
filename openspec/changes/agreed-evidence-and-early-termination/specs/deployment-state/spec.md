## MODIFIED Requirements

### Requirement: Domain payment persistence is role-owned

Storefront databases MUST persist exact Agreement bytes and opaque settlement data in `negotiation_threads`; domain receipt and fulfillment or grant progress MUST stay under that storefront's ordered migrations. The payments service owns transaction, ledger, hold-release, hold-extension, and fee state; the agreement's dispute authority owns case and outcome state. VM and bare metal MUST keep selected-site authority bindings independent of payment trust. API credits MUST keep its registry, credits authority, gated application, storefront, and buyer roles separate.

#### Scenario: Seller restarts after payment approval

- **WHEN** the storefront reloads an accepted payment negotiation
- **THEN** it retrieves the same mandate and transaction ID from its negotiation state and resumes domain progress without migrating a Stripe profile, credential, or operation ID

### Requirement: Marketplace deployment config contains consumer data only

Arkhai payment consumers MUST use `[Settlement.arkhai_payments]` for trusted service origin, Ed25519 receipt identity, fee policy, and an environment-variable name for the owner's API key, and `[[Dispute]]` entries for the dispute authorities they offer or accept. The API key MUST reach only its owning buyer or seller process. Outside loopback the service origin MUST use HTTPS. Public renderings MUST omit resolved credentials and contain no payment authority, provider, database, or worker deployment.

#### Scenario: Payments consumer is rendered

- **WHEN** an operator enables Arkhai payments
- **THEN** only consumer policy and credential references enter marketplace configuration, while the independently operated payments service owns its ledger and provider roles
