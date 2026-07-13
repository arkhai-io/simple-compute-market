## Why

The storefront-to-provisioner client and much of the provisioning HTTP vocabulary remain VM-owned even though the service already executes VM and bare-metal lifecycles. A versioned compute-provisioning contract is required before the service can move out of the VM domain without either leaking VM models into shared code or reducing the boundary to unvalidated JSON.

## What Changes

- Introduce a versioned compute-provisioning contract for executor action submission, durable job observation and control, credentials/results, lease registration and termination, release recovery, and deal-scoped events.
- Define shared correlation and idempotency fields: allocation ID, deal reference, executor kind, action kind, job ID, and contract version.
- Define typed executor-owned parameter and result envelopes validated by the selected VM or bare-metal adapter.
- Cover both storefront-to-provisioner commands and provisioner-to-storefront lifecycle events in the same compatibility contract.
- Replace the VM-owned shared provisioning client with a compute-owned contract/client package and migrate VM and bare-metal callers.
- **BREAKING**: remove shared use of VM-specific request models after all in-repository consumers migrate.
- State: **Blocked on `market-platform-compute-10-site-lifecycle`.**

## Capabilities

### New Capabilities

- `compute-provisioning-contract`: Versioned command, job, lease, result, credential, and lifecycle-event semantics shared by compute storefronts and the compute provisioner.

### Modified Capabilities

- `physical-provisioning`: VM and bare-metal execution use the common compute contract while their adapters retain concrete validation and execution semantics.

## Non-Goals

- Do not place compute provisioning contracts in `core_storefront`; domains that do not provision compute remain independent.
- Do not standardize VM and bare-metal action payloads beyond their shared envelope and lifecycle invariants.
- Do not move the deployable service or change its image in this change.
- Do not preserve a second VM-specific shared client after the coordinated in-repository cutover.
- Do not add host-ranking policy; `add-host-capacity-filters` remains conditional and may extend placement later.

## Dependencies and Related Changes

- Requires `market-platform-compute-10-site-lifecycle` to establish allocation and event ownership.
- `market-platform-compute-30-extract-service` moves the service only after this contract is adopted in its current location.
- The reverse callback concern from `extract-storefront-callback-client` is absorbed here as lifecycle-event transport and dependency direction.
- `add-host-capacity-filters` may add optional placement constraints without changing this lifecycle contract.

## Impact

- Affected packages: `domains/vms/provisioning/client`, VM and bare-metal storefront/provisioning adapters, and the current VM-hosted provisioning service.
- Wire compatibility: coordinated versioned API cutover; every in-repository producer and consumer migrates together.
- Packaging: a compute-owned contracts/client distribution replaces the VM-owned shared client.
- Persistence and deployment location remain unchanged.
