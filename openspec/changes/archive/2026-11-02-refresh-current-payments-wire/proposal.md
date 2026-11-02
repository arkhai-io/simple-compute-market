# Proposal

## Why

The generated payment consumer rejects responses allowed by the selected published contract, including effective part ends and zero gross amounts. Current producer conformance vectors are available, while the kit still documents an older publication and generator workaround.

## What Changes

- Vendor one explicitly selected schema and producer vector publication by content hash and regenerate the strict Python wire models.
- Reconcile required-nullable generation with the corrected publication, retain historical signed-byte checks, and cover current signed receipts and snapshots.
- Verify existing-server and selected-server compatibility before changing a consumer deployment; keep account, ledger, credential and provider authority outside marketplace code.
- Update affected package pins and permanent contract/generation documentation after implementation is reviewed.

No new payment mechanism, cash SDK, funding UI, refund policy, rate-part derivation, database migration or payment-service deployment is introduced.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: published payment-contract refreshes preserve strict validation, signature framing and external financial authority.

## Impact

Affected files are in `kit/arkhai-payments` and dependent package metadata/locks where version constraints change. Buyer and seller wire parsing changes to accept the selected publication; marketplace request authentication and stored transaction identities do not change. Exact live compatibility remains a deployment gate rather than a claim from local vectors.

## Permanent documentation impact

- [ ] Existing `openspec/specs/market-composition/spec.md` and companion architecture.
- [ ] Payment kit README and contract source/generation notes.
- [ ] No repository-wide package or authority-boundary change.

### Knowledge to promote

- Content-addressed publication selection, corrected nullable generation, historical/current producer evidence and compatibility limits belong in the payment kit documentation and market-composition capability.
