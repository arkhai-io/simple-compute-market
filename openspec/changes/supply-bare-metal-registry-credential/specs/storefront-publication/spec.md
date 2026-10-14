## MODIFIED Requirements

### Requirement: Registry publication ownership
A storefront MUST publish, update, close, and reconcile its listings against one or more configured registries using its publisher identity.

The bare-metal storefront MUST accept an optional registry bearer from `BARE_METAL_STOREFRONT_REGISTRY_API_KEY` and supply it only to its configured registry, including the signed reachability read. An unset or empty value MUST send no bearer. The credential MUST NOT appear in logs, status, or configuration representations and MUST NOT replace marketplace signature or authority verification.

#### Scenario: Derived capacity disappears
- **WHEN** authoritative capacity no longer supports a derived listing
- **THEN** reconciliation closes that listing in configured registries without treating stale local state as authority

#### Scenario: Bare-metal registry requires a write credential
- **WHEN** the bare-metal storefront is configured with a registry bearer
- **THEN** its publication clients and signed reachability read send that bearer while retaining the seller signer and registry authority pin

#### Scenario: Bare-metal registry needs no bearer
- **WHEN** the registry bearer is unset or empty
- **THEN** publication clients and signed reachability reads omit the Authorization header
