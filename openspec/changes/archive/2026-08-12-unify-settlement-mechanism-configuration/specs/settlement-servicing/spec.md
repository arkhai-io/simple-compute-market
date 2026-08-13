## ADDED Requirements

### Requirement: Configuration composes one settlement runtime

Each composition root MUST build installed mechanism clients from the typed settlement registrations and inject them into the single mechanism-neutral settlement runtime. Enablement, priority, or mechanism-specific commands MUST NOT create a parallel lifecycle, operation journal, claim engine, retry loop, or status authority.

#### Scenario: Both mechanisms are enabled

- **WHEN** Alkahest and hosted Stripe registrations are ready
- **THEN** both dispatch through the same obligation identity, operation journal, leases, retry rules, and aggregate status contract

### Requirement: Mechanism configuration cannot reinterpret durable plans

Mechanism configuration and readiness MAY govern new option publication and admission, but a persisted accepted plan MUST retain its canonical mechanism, exact parameters, payer/claimant direction, and stable operation identities. Recovery MUST use authoritative stored state even when that mechanism is no longer preferred or enabled for new deals.

#### Scenario: Hosted mechanism is disabled after funding

- **WHEN** reconciliation resumes an existing funded hosted obligation after operators disable new hosted publication
- **THEN** the runtime continues authoritative status/collection/reclaim recovery for that obligation rather than switching or abandoning it
