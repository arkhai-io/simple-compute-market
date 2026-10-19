## Why

`ResourcePoolService` permits an existing pool's provider to change through
replace, patch, and authoritative document import. These paths delete the old
handler's configuration and assign the new provider inside one transaction.
Existing inventory is thereby routed through another provider without the
resource reassignment checks that protect live obligations.

The provider is part of a pool's stable routing context, just as its immutable
capacity backing is part of the admission context. The provider needs the same
refusal on every administration path, including document validation.

Pool models currently validate mode and backing declarations, while the service
validates five additional domain-neutral policy hints. Moving those request-only
checks into the models lets typed callers and the server reject the same
malformed request before database work.

## What Changes

- Fix the provider at creation. Replace, patch, and authoritative import refuse
  a differing provider before mutation, preserving metadata and configuration.
  Validate-only reports the same violation without a reconciliation diff.
- Retain `PoolUpdate.provider`; an equal value has no effect and does not itself
  rewrite configuration. Configuration stays editable within the pool's provider.
- Share provider and backing comparisons across individual and document writes,
  preserving backing's repair allowance when no backing value is stored.
- Remove the unused `PoolConfigHandler.delete_config` operation, both concrete
  implementations, and obsolete test methods and fakes.
- Validate hold, SLA, listing-shape, asking-rate, and pricing rate-list hints in
  `PoolCreate`, `PoolReplace`, and a `PoolUpdate` supplying policy tags. Raw
  document entries reuse the contracts-owned checks with their structured errors.
- Move asking-rate structural validation to contracts and declare its direct
  capability-shape dependency. Resolution stays in the authority, and
  provider-specific validation stays with registered handlers.
- Migrate inventory through a second pool and existing member APIs. Capacity
  declarations retain the site's live-obligation guard; host moves retain their
  relay-protection hooks. These guards have different scopes.
- On an empty provisioning database with a mounted pool document, let startup
  create the default from that document before inventory import. Existing
  databases retain their default and host backfill; no document retains the VM
  bootstrap. Canonicalize the VM provider identity to `vm.ansible`, preserving
  existing VM pool configuration and fulfillment state through a migration.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `resource-pool-management`: provider immutability on every write path, shared
  stored-state checks, and model-level policy-hint validation.

## Non-Goals

- No member-migration command or new member-move guard.
- No change to provider configuration schemas or provider-owned validation and
  persistence responsibilities. VM registration uses `vm.ansible`.
- No storefront behavior change or domain-specific hint validation.
- No general validation-guidance edit before the owner's closeout consideration
  of its wording and home.

## Impact

- Contracts models, hint validators, structural asking-rate helpers and tests in
  `kit/resource-pools-contracts`; service, handler protocol, resolver imports and
  tests in `kit/resource-pools`.
- VM and bare-metal handler implementations, fulfillment/provisioning test fakes,
  and provisioning handler and administrative API tests. Compute adapter
  composition drops its deletion-hook requirement, with focused tests accepting
  deletion-free handlers while preserving the remaining required-hook checks.
- Contracts declares `arkhai-kit-capability-shape` directly and adds it to its
  package allowlist. Admissibility already installs that distribution transitively;
  no persistence, web framework, or new installed distribution is introduced.
- Request and response fields stay unchanged. Provider changes formerly accepted
  receive HTTP 400. Malformed hints in individual API bodies move from HTTP 400
  to HTTP 422; typed construction fails locally. Document validation retains
  structured problems, and import retains HTTP 400 with path-named detail text.
  Service-owned provider/configuration refusals retain HTTP 400.
- A changed mounted document changing an existing provider fails startup, applies
  nothing and records no new digest. An unchanged document is still skipped.
- The initial audit missed the bare-metal development default's bootstrap swap,
  exposed by validation 19/20. Fresh databases now create that default from the
  mounted document. Existing VM data is preserved; disposable bare-metal and test
  state needs no compatibility path. VM documents/callers use `vm.ansible`; the
  old `ansible` name has no runtime alias. The kit's swap test becomes refusal
  evidence; the direct handler-deletion test leaves.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `openspec/specs/resource-pool-management/spec.md`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Provider immutability, statuses/problems, patch semantics, model hint validation
  and the handler interface — `openspec/specs/resource-pool-management/spec.md`,
  via the deltas. Its Evidence section needs an explicit closeout edit to replace
  provider-replacement evidence and update model/hint paths; requirement merging
  does not rewrite that section.
- Stable routing context, separate capacity/host migration guards, and the
  model/service validation boundary —
  `openspec/specs/resource-pool-management/architecture.md`.
- Provider and backing immutability in Resource pools, plus the direct shape
  dependency in the thin-distributions description —
  `docs/development/ARCHITECTURE.md`.
- Refusal of changed-provider documents, atomic application and unchanged digest —
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, Definition documents.
- Contracts tests own model and structural checks; library integration tests own
  transactions and document behavior; service integration tests own HTTP behavior —
  `docs/development/TESTING.md`, Pool Offering-Mode Enforcement.
- Remove Goal 1's provider-swap gap and update its current state —
  `docs/development/ROADMAP.md`. Keep campaign acceptance and status current in
  `openspec/changes/README.md`.
- General request-first validation guidance remains for the owner's closeout
  consideration. Its promotion and permanent home are deliberately undecided;
  implementation does not require a repository-wide guidance edit.

## Dependencies and Related Changes

No active prerequisite. The site's live-obligation rule is authoritative in
`openspec/specs/site-capacity/spec.md`, under “A capacity resource does not move
pools under live obligations.” The change follows backing immutability's refusal
and document-reconciliation behavior.
