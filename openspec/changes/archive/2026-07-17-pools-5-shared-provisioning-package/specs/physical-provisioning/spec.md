> **Provenance note (2026-07-17):** This delta was never implemented and
> never merged into `openspec/specs/physical-provisioning/spec.md`. It is
> preserved verbatim here for historical record only. Do not treat it as
> normative. See `../../proposal.md`'s "Disposition" for closure rationale.

## MODIFIED Requirements

### Requirement: Compute-owned caller contract

Shared storefront/provisioner DTOs, executor-neutral resource-pool models,
generic client behavior, and — once implemented — the physical-settlement
scheduler, fulfillment-provider, and provider-registry contracts MUST be
owned by compute provisioning rather than the VM domain, while direct VM
operator APIs MAY retain VM-owned host, VM action, Ansible job, credential,
and lease models.

#### Scenario: Bare-metal storefront installs the shared client

- **WHEN** a bare-metal caller installs the compute-provisioning client without VM execution extras
- **THEN** it can submit and observe bare-metal lifecycle operations without importing VM request models

#### Scenario: Provisioning service exposes resource-pool administration

- **WHEN** the VM operator client or provisioning service creates, validates, imports, or returns a resource-pool model
- **THEN** that executor-neutral model resolves from `compute_provisioning` and no removed generic provisioning-client package is required

#### Scenario: A second domain needs fulfillment execution

- **WHEN** a domain besides VM needs `FulfillmentProvider`/`ProviderRegistry` behavior
- **THEN** those contracts resolve from `compute_provisioning` rather than being duplicated or imported from the VM-owned service
