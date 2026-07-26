# Tasks

## 1. Upstream Alkahest capability

- [ ] 1.1 Define and publish a bounded query API for attestations by `ref_uid`.
- [ ] 1.2 Return or expose schema, UID, reference UID, attester, recipient, encoded data, expiration, and revocation state.
- [ ] 1.3 Define pagination, duplicate ordering, supported-network behavior, and query-failure semantics.
- [ ] 1.4 Add upstream tests for matches before process start, zero matches, multiple matches, revoked attestations, and bounded scans.
- [ ] 1.5 Release an `alkahest-py` version containing the capability.

## 2. Simple Compute Market integration

- [ ] 2.1 Upgrade the pinned Alkahest dependency after the upstream release is available.
- [ ] 2.2 Add a repository-owned query protocol and neutral attestation result model in `kit/alkahest`.
- [ ] 2.3 Persist the chain scan starting block before first submission when it is not already recoverable from accepted-deal state.
- [ ] 2.4 Replace the absent production query capability in VM storefront composition with the supported adapter.
- [ ] 2.5 Implement exact candidate matching and canonical duplicate selection.
- [ ] 2.6 Preserve safe pending behavior for query errors and conflicting matches.
- [ ] 2.7 Add unit tests for zero, one, duplicate-identical, conflicting, revoked, expired, and query-failure outcomes.
- [ ] 2.8 Add a real Alkahest integration test for a successful-chain/lost-local-UID recovery.

## 3. Documentation and validation

- [ ] 3.1 Promote the implemented reconciliation contract into `openspec/specs/vm-storefront-fulfillment/spec.md`.
- [ ] 3.2 Establish or update permanent `kit/alkahest` documentation for the query abstraction.
- [ ] 3.3 Run focused VM storefront, Alkahest kit, and root repository tests.
- [ ] 3.4 Run strict OpenSpec validation where the CLI is available.
