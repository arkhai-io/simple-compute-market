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
- [ ] 4.3 Add the active change to the roadmap and active-change index, then remove those temporary entries at closeout.

## 5. Validation

- [x] 5.1 Run focused core, registry-client, registry service, and Helm render tests.
- [x] 5.2 Run strict OpenSpec validation and disclose any broader suite not run.

## 6. Closeout

- [x] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and remove change-history commentary from production code.
- [x] 6.2 **Import placement.** Confirm the carrier imports only standard-library and Pydantic modules and role packages depend inward on it.
- [x] 6.3 **Documentation compliance.** Confirm every material decision is present in permanent current-state documentation.
- [x] 6.4 **Narrative compression.** Reduce completed tasks to final behavior, evidence, and promotion destinations.
- [x] 6.5 **Roadmap currency.** Remove the implemented gap from the roadmap current-state boundary.
- [ ] 6.6 **Promotion.** Complete the design-promotion record and archive the change after review.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Portable descriptor and existing signed exchange | `openspec/specs/registry-discovery/{spec,architecture}.md` |
| Derived authority, schema, and access facts | `openspec/specs/registry-discovery/spec.md`; `docs/development/ARCHITECTURE.md` |
| Public configuration separated from signer credentials | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Possession is not endorsement | `openspec/specs/registry-discovery/architecture.md` |
