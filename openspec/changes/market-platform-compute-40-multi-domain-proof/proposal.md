## Why

Extraction alone does not prove that the new boundaries are truly domain- and executor-neutral; a renamed VM service could still hide VM assumptions in dispatch, event routing, or physical accounting. A focused VM and bare-metal proof must exercise the common domain and provisioning contracts against one shared compute authority.

## What Changes

- Add end-to-end scenarios in which one extracted compute provisioner loads VM and bare-metal adapters concurrently.
- Dispatch provisioning and release by allocation-recorded executor kind rather than VM-specific routes or defaults.
- Route deal-scoped events to the owning storefront using the deal reference recorded on the allocation, not one process-global storefront setting.
- Exercise VM-shareable and bare-metal-exclusive allocations against the same physical host and verify conflict behavior before executor work starts.
- Verify generic provisioning modules and shared site modules do not import concrete VM or bare-metal request/result models.
- Parameterize the focused test/deployment topology only as required for the two compute domains.
- State: **Blocked on the common domain contract and extracted compute service.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: One authority routes allocation events and enforces cross-mode physical accounting for multiple compute storefront/domain consumers.
- `physical-provisioning`: One compute service dispatches VM and bare-metal jobs and releases through independently registered adapters.
- `market-composition`: VM and bare-metal composition roots consume the shared domain contract while retaining separate deterministic semantics.

## Non-Goals

- Do not add a storage, bandwidth, or other non-compute resource domain.
- Do not require a second physical site; multi-site deployment is separate from multi-executor and multi-domain correctness.
- Do not introduce generic packing, fractional claims, or cross-seller capacity markets.
- Do not create a third provisioning API or retain domain-specific shared clients.

## Dependencies and Related Changes

- Requires `market-platform-domain-10-contract` for the common domain composition surface.
- Requires `market-platform-compute-30-extract-service`, which in turn requires the site-lifecycle and provisioning-contract changes.
- Replaces the ambiguous second-executor/second-site scope formerly tracked by `prove-multi-domain-capacity`.

## Impact

- Affected tests and topology: VM and bare-metal storefront/provisioning integration, allocation dispatch, event routing, and physical-host conflict scenarios.
- Runtime APIs should not change; this change may expose and remove remaining VM-specific assumptions required to satisfy the existing contracts.
- Deployment templates may gain per-domain instance parameters needed by the focused proof.
