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
- [ ] 2.3 Persist the chain scan starting block before first submission when it is not already recoverable from accepted-deal state; for a fulfillment through `kit/alkahest`'s `AlkahestFulfillmentPublisher`, inside the first-write-wins submission intent `kit/settlement-runtime` records.
- [ ] 2.4 Replace the absent production query capability with the supported adapter where the publisher's unknown outcome is decided: in VM storefront composition, and in the bare-metal storefront's Alkahest step, so a parked bare-metal submission adopts a matching UID as its recorded reference and completes.
- [ ] 2.5 Implement exact candidate matching and canonical duplicate selection: VM matches its connection-details data; bare metal matches the evidence digest recorded in its intent.
- [ ] 2.6 Preserve safe pending behavior for query errors and conflicting matches.
- [ ] 2.7 Add unit tests for zero, one, duplicate-identical, conflicting, revoked, expired, and query-failure outcomes.
- [ ] 2.8 Add a real Alkahest integration test for a successful-chain/lost-local-UID recovery, for VM and for bare metal.

## 3. Documentation and validation

- [x] 3.1 **Withdrawn** 2026-10-14: closeout does this — 4.9 writes the `settlement-servicing` contract no delta covers, and the archive in 4.11 writes the `vm-storefront-fulfillment` spec its delta covers. As first planned: Promote the implemented reconciliation contract into `openspec/specs/vm-storefront-fulfillment/spec.md` and, for the shared publisher's unknown outcome, `openspec/specs/settlement-servicing/spec.md` ("A fulfillment submission with an unknown outcome is never repeated").
- [ ] 3.2 Establish or update permanent `kit/alkahest` documentation for the query abstraction.
- [ ] 3.3 Run focused VM storefront, bare-metal storefront, settlement-runtime kit, Alkahest kit, and root repository tests.
- [ ] 3.4 Run strict OpenSpec validation where the CLI is available.
- [ ] 3.5 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both.

## 4. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 4.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
- [ ] 4.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 4.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe. It carries a delta spec for
      `vm-storefront-fulfillment`; confirm durable conceptual rationale sits in the
      companion `architecture.md` rather than only in `design.md`.
- [ ] 4.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 4.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
      This change sits under the lesser goal "Settlement and deal servicing depth",
      which has no roadmap goal behind it, so it most likely owes the roadmap nothing;
      confirm that and record the no-impact disposition explicitly.
- [ ] 4.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 4.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 4.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change, or an explicit blocker
      naming its cause and the change that owns it, with the validations it gates
      treated as unrun.
- [ ] 4.9 **Promotion.** Write the permanent documents this change owes — the
      `settlement-servicing` reconciliation contract for the shared publisher's unknown
      outcome ("A fulfillment submission with an unknown outcome is never repeated",
      3.1), which no delta covers; the permanent `kit/alkahest` documentation for the
      query abstraction (3.2); and any durable rationale for the
      `vm-storefront-fulfillment` companion `architecture.md` — and complete the
      design-promotion record, mapping every accepted decision to its exact permanent
      heading, and verify no production source references
      `openspec/changes/add-alkahest-attestation-reference-query`. A `spec.md` the
      deltas cover (`vm-storefront-fulfillment`) is written by the archive in 4.11, not
      by hand; the record names it all the same.
- [ ] 4.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=add-alkahest-attestation-reference-query` and
      resolve every match, then
      `openspec validate add-alkahest-attestation-reference-query --strict`.
- [ ] 4.11 **Archival.** Last, once every other part is checked: `openspec archive
      add-alkahest-attestation-reference-query -y` merges the deltas into
      `openspec/specs/` and moves the change under `openspec/changes/archive/`; point the
      index row at the archived directory, and run `openspec validate --specs --strict`.
