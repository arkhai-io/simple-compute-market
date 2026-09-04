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

## 4. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 4.1 **Comment hygiene.** Run `make check-comment-hygiene`, then direct-read the comments and docstrings this change touches for the fuzzier provenance-narration rule the target cannot catch mechanically.
- [ ] 4.2 **Import placement.** Review every import this change adds or touches and move it to module level where safe; retain a local import only against an observed circular import or a documented lazy-load reason, verified against the real suite.
- [ ] 4.3 **Documentation compliance.** Re-check this change's accepted decisions against `openspec/README.md`'s placement rules. It carries delta specs for `vm-storefront-fulfillment`; confirm each landed in the owning `openspec/specs/<capability>/spec.md`, and that durable conceptual rationale sits in the companion `architecture.md` rather than only in `design.md`.
- [ ] 4.4 **Narrative compression.** Compress completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations, moving durable rationale into `design.md` first.
- [ ] 4.5 **Roadmap currency.** This change sits under the lesser goal “Settlement and deal servicing depth”, which has no roadmap goal behind it, so it most likely owes `docs/development/ROADMAP.md` nothing. Confirm that and record the no-impact disposition explicitly rather than omitting the step.
- [ ] 4.6 **Campaign index currency.** Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md` to match its state at completion, or record the disposition here if its status and campaign placement are both unchanged.
- [ ] 4.7 **Promotion.** Complete the design-promotion record, mapping every accepted decision to its exact permanent heading, and verify no production source references `openspec/changes/add-alkahest-attestation-reference-query`.
