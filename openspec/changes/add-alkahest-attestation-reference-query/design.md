# Design: attestation reference lookup for fulfillment recovery

## Problem boundary

The unrecoverable local window is narrowly defined:

1. The storefront records that an on-chain submission is starting.
2. Alkahest submits an obligation that references the accepted escrow UID.
3. The transaction succeeds, but the process loses the returned attestation UID before persisting it.
4. On restart, local state cannot distinguish success from non-submission.

The storefront already has the expected escrow UID, seller identity, expected connection-details payload, and recovery context. It lacks an authoritative discovery operation over chain state.

## Required upstream contract

The upstream SDK should own provider access, deployed contract addresses, event ABI compatibility, log pagination, and network-specific behavior. The query must be bounded by a caller-supplied block or cursor and return authoritative attestation fields.

A lookup by known UID is insufficient because the missing UID is the fact being recovered. A subscription-only API is also insufficient because the matching event may have occurred before restart.

## Matching policy in Simple Compute Market

A candidate is valid only when all applicable fields match:

- `ref_uid` equals the escrow UID;
- schema equals the string-obligation schema used for fulfillment;
- attester equals the seller storefront wallet;
- recipient matches the obligation contract's expected recipient semantics;
- decoded obligation data exactly equals the expected connection details;
- the attestation is not revoked;
- the attestation is not expired when expiration applies.

Outcomes:

| Valid matches | Action |
|---|---|
| Zero | Submit once, then persist the returned UID best-effort |
| One | Adopt the UID and continue convergence |
| Multiple identical | Adopt the earliest deterministic UID, log duplicates, continue |
| Conflicting | Do not submit; leave pending for operator reconciliation |
| Query failure/uncertainty | Do not submit; retry reconciliation later |

## Integration boundary

`kit/alkahest` should wrap the upstream method behind a repository-owned protocol. VM storefront code should depend on that protocol, not probe possible SDK method names and not import raw EAS ABI details.

The VM storefront owns domain matching of connection-details data. The Alkahest kit owns translating SDK attestation records into a stable repository-neutral representation.

## Current behavior before upstream support

The production adapter supplies no discovery capability. A recorded ambiguous submission therefore remains pending and emits an operator-visible error. This is intentionally incomplete recovery but preserves duplicate safety.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Reference-based bounded lookup is required for automatic ambiguous-submission recovery | `openspec/specs/vm-storefront-fulfillment/spec.md#on-chain-fulfillment-reconciliation` |
| Blind resubmission remains prohibited | `openspec/specs/vm-storefront-fulfillment/spec.md#on-chain-fulfillment-reconciliation` |
| SDK/network mechanics belong in the Alkahest integration layer | Future `kit/alkahest` permanent documentation established during implementation |
