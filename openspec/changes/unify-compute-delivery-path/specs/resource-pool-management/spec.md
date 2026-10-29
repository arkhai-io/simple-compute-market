## MODIFIED Requirements

### Requirement: Activation safeguards are explicitly enabled by composition

After delivery-caller qualification, the compute composition MUST expose activation_deadlines_enabled with a true repository default for new commits. Hosted operators MUST gate enablement on their own caller readiness. An explicit false override MUST supply no effective allowance without disabling provider support or pool validation. Enablement MUST affect only new commits; disabling MUST NOT clear snapshotted deadlines.

#### Scenario: Site code lands before compatible callers

- **WHEN** the site is deployed before caller qualification under the staged off setting
- **THEN** new commits retain null deadline/phase and existing leases stay unchanged
- **AND** the qualified repository default is not applied to that target before readiness

#### Scenario: Protection is enabled then disabled

- **WHEN** a qualified deployment enables protection, commits a lease, then disables it
- **THEN** that lease retains its deadline and later new commits receive null fields
- **AND** invalid pool overrides remain invalid in either setting

#### Scenario: Qualified callers use the repository default

- **WHEN** every commit/recovery caller passes owned-lane qualification and the composition default changes
- **THEN** subsequent new compute commits snapshot their allowance without backfilling legacy leases
