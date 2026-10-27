# Design

## Context

The original plan predated the repository-wide non-chain identity cutover. It
assumed an EIP-191-only `(operation, resource_id, timestamp)` signature and a
freeze window for `storefront_admin_key`. Those assumptions are no longer
valid.

`kit/identity` now owns strict `Principal` values, injected signers/verifiers,
Ed25519 and EIP-191 dispatch, canonical request and response bodies, replay
reservations, and two-proof rotation. All marketplace peers must share that
contract. A service-specific format or compatibility fallback would create a
second security boundary with weaker body and authority binding.

## Goals / Non-Goals

**Goals:** exact counterparty attribution; body-bound requests; signed
acknowledgements; wallet-free Ed25519 operation; explicit EIP-191 operation;
bounded rotation; no shared impersonation material.

**Non-Goals:** collateral, admin site management, many-to-many ownership,
chain-derived identity, or a second service signature protocol.

## Decisions

### Reuse the identity kit's version 2 contract

Service requests use `arkhai.market-request-signature.v2`. The canonical bytes
bind the signer role and principal, HTTP method, semantic operation and
resource, request ID, timestamp, and canonical body hash. Mutation responses
bind the configured authority principal, request identity, HTTP status,
timestamp, and canonical response body.

Callers never choose the identity against which they are checked. Route and
registry context select the expected role and principal. A body mutation,
cross-role replay, principal substitution, changed retry, or version 1
signature therefore fails closed.

### One protocol supports Ed25519 and EIP-191

Ed25519 is the mandatory wallet-free scheme and uses an unpadded base64url
32-byte public key. EIP-191 remains available for an explicitly configured EVM
principal whose identifier is a lowercase 20-byte address. Scheme dispatch is
local; neither mode needs RPC for message verification.

Code outside `kit/identity` handles only scheme-tagged principals and injected
signer/verifier protocols. It does not derive addresses, inspect private keys,
or branch on signature encoding.

### The registry holds principals behind an interface

A storefront resolves `(site_id, url, principal)` through a registry interface.
Its initial source may be configuration, but callers do not read configuration
directly. The many side is sites per storefront; each site identity remains
scoped to its site and cannot authenticate another.

A provisioning authority has one configured storefront counterparty. This
matches the deployed one-to-one direction without inventing per-record
ownership.

### Authentication covers requests and acknowledgements

Request verification happens before route dispatch and before a state change.
The service reserves `(principal, request_id)` with the request digest and
semantic operation. An exact retry may return the stored signed response; the
same identity with changed content or operation is a replay conflict.

Clients verify signed mutation responses before treating a remote operation as
acknowledged. A valid unsigned status code is not sufficient proof that the
configured authority accepted the operation.

### Rotation is proof-bound and time-bounded

Changing a counterparty principal requires signatures from both the active and
replacement principals over one bounded rotation statement. During the overlap,
both authenticate the same authority binding. Expiry retires the old principal;
explicit retirement may close the overlap earlier. Disablement is a distinct
operator action and never transfers authority.

### Clean cutover removes legacy authentication

The version 2 deployment is one coordinated cutover. It removes shared-key
acceptance, version 1 messages, address/private-key derivation, caller-selected
identity fields, and unsigned-response acceptance. Leaving any of those paths
would preserve the impersonation or downgrade defect the change exists to
remove.

## Risks / Trade-offs

- **Mismatched capability deployment** — clients and services advertise and
  pin version 2 capabilities; deployment and package checks reject mixed
  protocol versions.
- **Signer credentials leak into public configuration** — public principals
  belong in ConfigMaps or ordinary settings; private signer material is
  Secret-injected and never serialized into logs, manifests, or responses.
- **Replay state is lost or bypassed** — reservations are durable and written
  atomically with operation outcomes; verification before dispatch is not a
  substitute for durable replay classification.
- **A chain wallet is accidentally made mandatory** — Ed25519-only profiles
  render and run without chain, RPC, EAS, or wallet values. EIP-191 profiles
  require their explicit chain-facing settings.

## Migration Plan

1. Release and pin the shared identity kit version containing the version 2
   request, response, replay, and rotation contract.
2. Render exact public principals and Secret-backed signer credentials for both
   peers; reject mixed or legacy configuration.
3. Deploy clients and services together with body-bound request verification
   and signed-response verification enabled.
4. Exercise exact retry, changed replay, cross-role rejection, dual-scheme
   operation, and rotation overlap before accepting traffic.
5. Remove obsolete shared-key settings, code paths, comments, and deployment
   values in the same cutover.

Rollback is an artifact rollback of both peers and their configuration, not a
runtime fallback that accepts both authentication generations.

## Open Questions

None. The shared version 2 identity contract resolves the earlier
canonicalization, identity-scheme, response-authentication, and rotation
questions.
