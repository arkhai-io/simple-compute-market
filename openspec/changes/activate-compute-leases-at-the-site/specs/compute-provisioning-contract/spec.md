## ADDED Requirements

### Requirement: Typed compute lease activation and lease inspection

The shared compute client and contract MUST expose offering-mode-neutral activation by reservation identity and lease inspection carrying nullable `renew_by_utc`, nullable `renewal_phase`, and nullable `activated_at_utc`, the instant the site's activation transition wrote once. Activation MUST accept no payment fact or target deadline and MUST return the site's recorded lease through every client layer. It MUST use the existing authenticated service boundary and exact response verification.

#### Scenario: A caller activates through the shared client

- **WHEN** a VM or bare-metal caller activates an awaiting-activation lease
- **THEN** the client returns the site's active lease, its due instant equal to its current agreed end, without importing a VM-specific model

#### Scenario: An older lease is inspected or activated

- **WHEN** a lease with null deadline and phase is read through the client
- **THEN** its null fields are visible as null, not defaulted

#### Scenario: A null-phase lease is activated on a site with the operation

- **WHEN** a lease with null deadline and phase is activated through the client on a site that exposes activation
- **THEN** the client returns the lease as active, its due instant the agreed end, and a repeat returns the same lease

#### Scenario: The site has no activation operation

- **WHEN** the site exposes no activation route and the caller holds a verified legacy lease view
- **THEN** the caller treats the lease as already active without a site write, and any other phase or an unverified view is repair-required

#### Scenario: A response is signed by a different service

- **WHEN** a principal other than the independently configured site authority signs an activation response
- **THEN** the client refuses it instead of accepting activation
