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

## A second consumer: bare-metal Alkahest delivery (2026-10-07)

`bare-metal-mock-provisioned-deal` (Section 7) gives bare metal an Alkahest fulfillment
with the same ambiguous window, and keeps this change's rule: no blind resubmission.

- `kit/alkahest` gains `AlkahestFulfillmentPublisher`, whose outcomes are published, not
  submitted, outcome unknown, and rejected. A failure it cannot place is an unknown
  outcome.
- `kit/settlement-runtime` records a first-write-wins submission intent on the
  obligation's fulfillment operation before the submission, and the created UID beside
  it before the fulfillment is completed. An attempt that finds an intent with no UID, or
  an unknown outcome, parks the obligation for an operator (`manual_required`,
  `alkahest_submission_outcome_unknown`); a rejection is retried up to a bound, since no
  attestation exists. The administrator's status counts parked obligations.
- Bare metal's attestation data is the `sha256:` digest of its lease-ready evidence, not
  connection details, so its domain match is the digest it recorded with its intent.

What this changes here: the lookup's repository-owned protocol is injected where that
publisher's unknown outcome is decided, serving both domains, rather than into VM's
fulfillment alone; the scan cursor is written into the same first-write-wins intent; and
adopting a matching UID records it as the operation's reference and completes the parked
fulfillment. Bare metal's domain match is the evidence digest recorded in its intent
rather than connection details. The tasks carry this. If `kit-owned-listing-and-fulfillment-lifecycles` has
moved VM onto the same publisher by then, there is one injection point.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Reference-based bounded lookup is required for automatic ambiguous-submission recovery | `openspec/specs/vm-storefront-fulfillment/spec.md#on-chain-fulfillment-reconciliation` |
| Blind resubmission remains prohibited | `openspec/specs/vm-storefront-fulfillment/spec.md#on-chain-fulfillment-reconciliation` |
| SDK/network mechanics belong in the Alkahest integration layer | Future `kit/alkahest` permanent documentation established during implementation |
