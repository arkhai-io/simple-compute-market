# Add attestation reference lookup for fulfillment recovery

## Why

The VM storefront can recover physical fulfillment and all local post-provisioning work after restart, but one chain boundary remains intentionally incomplete. If `string_obligation.do_obligation(...)` succeeds on-chain and the process loses the response before persisting the returned fulfillment UID, the storefront cannot determine whether the obligation was already submitted.

Blindly submitting again can create duplicate attestations for the same accepted escrow. The current implementation therefore preserves safety by leaving the escrow pending and requiring operator reconciliation. That avoids duplicate settlement but does not provide automatic eventual convergence.

The installed `alkahest-py` interface supports lookup by a known attestation UID and provides internal log-watching behavior, but it does not expose a bounded query for attestations that reference an escrow UID. The storefront must not guess nonexistent methods or duplicate Alkahest's chain-specific ABI, deployment-address, event-decoding, and RPC behavior.

## What Changes

### Upstream Alkahest capability

Add a supported, bounded attestation query that can find obligation attestations by reference UID. The API must:

- query from a caller-provided block or equivalent bounded cursor;
- return complete attestation records or stable UIDs that can be resolved through the existing lookup API;
- filter by, or expose enough fields to validate, schema, reference UID, attester, recipient, encoded data, expiration, and revocation;
- work across every network supported by the existing Alkahest configuration;
- define duplicate and pagination behavior;
- avoid treating indexer absence or lag as proof that no attestation exists.

A representative Python surface is:

```python
async def find_attestations(
    *,
    ref_uid: str,
    from_block: int,
    schema_uid: str | None = None,
    attester: str | None = None,
) -> list[Attestation]:
    ...
```

The exact name and location are owned by Alkahest. The required contract is reference-based, bounded, and returns enough authoritative chain data for exact matching.

### Simple Compute Market changes

After the supported query exists:

- add a narrow adapter in `kit/alkahest` that exposes the upstream query without leaking SDK-specific objects into domain code;
- inject that adapter into VM storefront fulfillment reconciliation;
- persist the chain scan starting block before the first submission attempt;
- query before any retry after an ambiguous submission outcome;
- match the escrow UID, schema, seller/attester, recipient semantics, exact connection-details obligation data, and revocation/expiration state;
- adopt one matching fulfillment UID without resubmission;
- handle identical duplicates deterministically and log them prominently;
- leave conflicting attestations pending for operator review;
- add integration coverage against the real Alkahest test environment.

## What This Enables

- Automatic recovery when the chain transaction succeeded but the response or local checkpoint was lost.
- Eventual convergence of accepted VM deals without risking duplicate on-chain fulfillment.
- Safe restart recovery through the complete storefront lifecycle, including chain settlement.
- Removal of the current operator-only reconciliation path for this failure window.
- A reusable attestation-discovery primitive for other domains that submit obligations by reference UID.

## Current limitation

Until the upstream capability exists, the VM storefront must not blindly resubmit after an ambiguous chain outcome. It leaves the escrow pending, logs the condition, and requires operator reconciliation. This is a deliberate safety limitation, not evidence that no fulfillment occurred.

## Capabilities

### Modified Capabilities

- `vm-storefront-fulfillment`: ambiguous on-chain submissions become automatically reconcilable when a supported reference-query capability is available.
- `alkahest-integration`: gains a bounded, authoritative attestation lookup by reference UID.

## Non-Goals

- Do not implement raw EAS event scanning directly in the VM storefront.
- Do not make a hosted indexer the sole correctness boundary.
- Do not change the accepted rule that commercial delivery takes priority over local bookkeeping durability.
- Do not permit blind resubmission when chain outcome is unknown.

## Dependencies

- Requires an upstream Alkahest release that exposes the supported query contract.
- Depends on the existing Section 9 versioned recovery envelope and ambiguous-submission checkpoint.

## Permanent documentation impact

- [ ] Existing subsystem specification: `openspec/specs/vm-storefront-fulfillment/spec.md`
- [ ] Existing subsystem architecture or integration documentation for `kit/alkahest`, if one is established during implementation
- [ ] No repository-wide `ARCHITECTURE.md` change anticipated

### Knowledge to promote

- The authoritative matching fields and duplicate/conflict policy.
- The bounded scan/cursor contract.
- The distinction between safe pending behavior without the query and automatic convergence with it.
