# Implementation Tasks

## 1. Shared descriptor carrier

- [ ] 1.1 Add strict registry descriptor models to `market_core` with exact wire aliases and access/principal invariants.
- [ ] 1.2 Add focused carrier tests for valid public and key-gated descriptors and malformed trust bundles.

## 2. Registry publication

- [ ] 2.1 Add descriptor settings for the operator-authored public fields and build the complete descriptor from the active signer, filter specification, and read gate at startup.
- [ ] 2.2 Serve the descriptor at the well-known route through authenticated request handling, durable replay, and signed responses without requiring a read key.
- [ ] 2.3 Add typed async and sync registry-client methods and preserve method parity.
- [ ] 2.4 Add focused service and client integration evidence for the body, authority pin, replay, and key-gated bootstrap path.

## 3. Deployment surfaces

- [ ] 3.1 Render descriptor fields in local Compose profiles and the registry Helm chart.
- [ ] 3.2 Extend Helm validation and render evidence without placing signer credentials in ordinary values.

## 4. Permanent documentation

- [ ] 4.1 Promote descriptor behavior and the possession-versus-endorsement boundary to `openspec/specs/registry-discovery/{spec,architecture}.md`.
- [ ] 4.2 Update `docs/development/ARCHITECTURE.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md` with the current ownership and configuration model.
- [ ] 4.3 Add the active change to the roadmap and active-change index, then remove those temporary entries at closeout.

## 5. Validation

- [ ] 5.1 Run focused core, registry-client, registry service, and Helm render tests.
- [ ] 5.2 Run strict OpenSpec validation and disclose any broader suite not run.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and remove change-history commentary from production code.
- [ ] 6.2 **Import placement.** Confirm the carrier imports only standard-library and Pydantic modules and role packages depend inward on it.
- [ ] 6.3 **Documentation compliance.** Confirm every material decision is present in permanent current-state documentation.
- [ ] 6.4 **Narrative compression.** Reduce completed tasks to final behavior, evidence, and promotion destinations.
- [ ] 6.5 **Roadmap currency.** Remove the implemented gap from the roadmap current-state boundary.
- [ ] 6.6 **Promotion.** Complete the design-promotion record and archive the change after review.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Pending implementation | Pending |
