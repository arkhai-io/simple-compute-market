## Why

**Supersedes `add-storefront-principal-authentication`** (2026-08-06). That
change proposed multi-principal shared-secret authentication for a topology that
is no longer pursued. The defect it found remains: `storefront_admin_key`
authenticates inbound authority requests and signs outbound authority callbacks,
so either party can impersonate the other and rotation requires a coordinated
flip.

The repository now has one canonical solution. `kit/identity` owns strict
scheme-tagged principals, injected signers/verifiers, the body-bound
`arkhai.market-request-signature.v2` contract, signed responses, replay
classification, and two-proof rotation. Service peers must consume that
contract rather than retain the earlier EIP-191-only request format.

## What Changes

- Provisioning authorities and storefronts authenticate each request with an
  injected marketplace signer and verify it against an exact registered
  counterparty principal before route dispatch.
- Version 2 authentication binds role, principal, method, semantic operation
  and resource, request ID, timestamp, and canonical body hash. Exact retries
  may reuse a reserved request identity; changed reuse and legacy formats fail
  closed.
- Mutation responses are signed over the response status, request identity,
  authority principal, timestamp, and canonical response body. Callers verify
  the configured authority principal before accepting an acknowledgement.
- A storefront reaches site records through a registry interface and keeps a
  separate principal per authority. An authority keeps the one storefront
  principal it serves.
- Ed25519 and EIP-191 use the same protocol. Ed25519 is the wallet-free default;
  EIP-191 remains available only when explicitly selected. Verification is
  local and requires no RPC or chain configuration.
- Rotation requires old and replacement proofs, uses a bounded overlap, and
  records retirement. Disablement removes authority without assigning it to a
  replacement principal.
- The shared key, address derivation fallback, caller-selected identity fields,
  and version 1 signatures are removed as authentication paths in the cutover.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: an authority verifies body-bound version 2 requests
  against the registered storefront principal and signs its own responses with
  material the storefront never holds.
- `storefront-publication`: a storefront keeps exact site principals, verifies
  authority requests and responses against them, and coordinates bounded
  principal rotation.

## Non-Goals

- Do not add multi-principal shared-secret configuration or per-record
  `owner_principal` ownership for the abandoned many-to-many topology.
- Do not implement collateral, staking, or an on-chain registration
  prerequisite.
- Do not make a chain wallet mandatory for service authentication.
- Do not build storefront-admin site management; configuration remains the
  initial registry source behind an interface.
- Do not invent a service-specific signature or replay format beside the
  identity kit contract.

## Impact

- Affected code: `provisioning/compute/service`, `core/storefront`, domain
  composition roots, site/storefront clients, and their focused tests.
- Affected configuration: public scheme-tagged principals in ordinary
  configuration and signer credentials only through Secret-backed inputs.
- Affected deployment: render checks must prove public/private separation,
  optional chain configuration, exact principal matching, and rejection of
  legacy protocols.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — service identity authority and
      package boundaries.
- [x] `openspec/specs/physical-provisioning/{spec,architecture}.md` — request,
      response, replay, and rotation behavior.
- [x] `openspec/specs/storefront-publication/{spec,architecture}.md` — site
      registry and authority trust behavior.
- [x] `openspec/specs/marketplace-identity/{spec,architecture}.md` — shared
      principal and signature contract.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — public principal and Secret
      credential placement.

## Dependencies and Related Changes

- `add-nonchain-marketplace-identities` owns the shared version 2 identity
  contract and reconciles this service boundary with buyer, registry,
  storefront, settlement, and deployment identity behavior.
- Supersedes `add-storefront-principal-authentication`; Git history preserves
  its abandoned shared-secret mechanism.
- Unblocks `replace-polling-with-authenticated-push` by providing a trusted
  reverse channel.
