## ADDED Requirements

### Requirement: Typed compute lease activation and deadline inspection

The shared compute client and contract MUST expose offering-mode-neutral activation by reservation identity and lease inspection carrying nullable `renew_by_utc`, nullable `renewal_phase`, and the existing active instant. Activation MUST accept no payment fact or target deadline and MUST return the site's recorded lease through every client layer. It MUST use the existing authenticated service boundary and exact response verification.

#### Scenario: A caller activates through the shared client

- **WHEN** a VM or bare-metal caller activates an awaiting-activation lease
- **THEN** the client returns the site's active lease with its deadline equal to its current agreed end without importing a VM-specific model

#### Scenario: An older lease is inspected or activated

- **WHEN** a lease with null deadline and phase is read or activated through the client
- **THEN** its null fields remain visible and its lease behavior remains unchanged

#### Scenario: A response is signed by a different service

- **WHEN** a principal other than the independently configured site authority signs an activation response
- **THEN** the client refuses it instead of accepting activation
