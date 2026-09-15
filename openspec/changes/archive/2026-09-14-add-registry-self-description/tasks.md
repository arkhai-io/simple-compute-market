# Implementation Tasks

## 1. Shared descriptor carrier

- [x] 1.1 Add strict registry descriptor models to `market_core` with exact wire aliases and access/principal invariants.
- [x] 1.2 Add focused carrier tests for valid public and key-gated descriptors and malformed trust bundles.

## 2. Registry publication

- [x] 2.1 Add descriptor settings for the operator-authored public fields and build the complete descriptor from the active signer, filter specification, and read gate at startup.
- [x] 2.2 Serve the descriptor at the well-known route through authenticated request handling, durable replay, and signed responses without requiring a read key.
- [x] 2.3 Add typed async and sync registry-client methods and preserve method parity.
- [x] 2.4 Add focused service and client integration evidence for the body, authority pin, replay, and key-gated bootstrap path.

## 3. Deployment surfaces

- [x] 3.1 Render descriptor fields in local Compose profiles and the registry Helm chart.
- [x] 3.2 Extend Helm validation and render evidence without placing signer credentials in ordinary values.

## 4. Permanent documentation

- [x] 4.1 Promote descriptor behavior and the possession-versus-endorsement boundary to `openspec/specs/registry-discovery/{spec,architecture}.md`.
- [x] 4.2 Update `docs/development/ARCHITECTURE.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md` with the current ownership and configuration model.
- [x] 4.3 Add the active change to the roadmap and active-change index, then remove those temporary entries at closeout.

      **Done (2026-09-14).** The active-change row was removed from
      `openspec/changes/README.md`'s independent-changes table and the change
      recorded in the archived-and-superseded section instead, matching how
      the five rows removed on 2026-09-04 were handled.

      No roadmap entry existed to remove. Recording that explicitly rather
      than silently: registry self-description was never mapped to a roadmap
      goal gap, so there was nothing to reflect at completion and nothing to
      withdraw at closeout.

## 5. Validation

- [x] 5.1 Run focused core, registry-client, registry service, and Helm render tests.
- [x] 5.2 Run strict OpenSpec validation and disclose any broader suite not run.

## 6. Closeout

- [x] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and remove change-history commentary from production code.
- [x] 6.2 **Import placement.** Confirm the carrier imports only standard-library and Pydantic modules and role packages depend inward on it.
- [x] 6.3 **Documentation compliance.** Confirm every material decision is present in permanent current-state documentation.
- [x] 6.4 **Narrative compression.** Reduce completed tasks to final behavior, evidence, and promotion destinations.
- [x] 6.5 **Roadmap currency.** Remove the implemented gap from the roadmap current-state boundary.
- [x] 6.6 **Promotion.** Complete the design-promotion record and archive the change after review.

      **Done (2026-09-14).** The spec delta in
      `specs/registry-discovery/spec.md` was already promoted into
      `openspec/specs/registry-discovery/spec.md` -- the requirement
      "Registry self-description is authority-authenticated" and all four of
      its scenarios are present there -- so archival carries no unpromoted
      material. The delta is retained in the archived directory, as
      `2026-09-04-pool-declared-offering-modes` retains its own.

      Archived to `openspec/changes/archive/2026-09-14-add-registry-self-description/`.
- [x] 6.7 **Campaign index currency** (part seven, added when `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven). Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend rather than replace implementation history. Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md` to match its state at completion, or record the disposition here if its status and campaign placement are both unchanged.
      **Done (2026-09-14).** This change has no campaign, so there is no
      dependency graph to reconcile -- recorded explicitly rather than
      omitted. Its row left the independent-active-changes table and the
      archived-and-superseded section names it, so the index no longer
      offers it as work a reader may start next.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Portable descriptor and existing signed exchange | `openspec/specs/registry-discovery/{spec,architecture}.md` |
| Derived authority, schema, and access facts | `openspec/specs/registry-discovery/spec.md`; `docs/development/ARCHITECTURE.md` |
| Public configuration separated from signer credentials | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Possession is not endorsement | `openspec/specs/registry-discovery/architecture.md` |
