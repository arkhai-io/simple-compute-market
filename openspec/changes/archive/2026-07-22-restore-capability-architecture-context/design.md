## Context

Before OpenSpec adoption, `docs/development/ARCHITECTURE.md` combined repository maps, subsystem rationale, requirements, endpoint inventories, operations, and planned work in one 3,874-line file. The migration ledger at `openspec/changes/archive/2026-07-13-migrate-planning-to-openspec/migration-ledger.json` classified all headings, but the resulting requirements-oriented specifications retained only a small portion of the explanatory prose.

OpenSpec currently parses only each capability's `spec.md`. It permits companion Markdown files but does not validate, display, or synchronize them. Custom workflow schemas can control change artifacts, but the installed OpenSpec parser and synchronizer still hardcode `spec.md`, `## Requirements`, requirement blocks, and scenarios.

## Goals / Non-Goals

**Goals:**

- Restore concise current-state rationale that explains why capability boundaries exist.
- Keep normative behavior machine-readable in `spec.md` while allowing freeform permanent architecture prose.
- Preserve one proposal → design → tasks → promotion → sync/archive lifecycle for both forms of knowledge.
- Establish one discoverable capability index.
- Recover an evidence-backed baseline for the implemented API-credits domain.

**Non-Goals:**

- Reproduce the old architecture document verbatim.
- Restore endpoint catalogs, file trees, ports, package inventories, historical plans, or change provenance.
- Change OpenSpec's parser or introduce a custom workflow schema.
- Resolve unrelated packaging, publication, configuration, FRP, typed-client, e2e extraction, or settlement-generalization work.
- Change runtime code, APIs, persistence, or deployment behavior.

## Decisions

### Companion architecture documents are permanent but non-normative

Each capability may contain:

```text
openspec/specs/<capability>/
├── spec.md
└── architecture.md
```

`spec.md` remains the normative machine-parsed contract. `architecture.md` explains the conceptual model, ownership rationale, trade-offs, current limits, and relationships to adjacent capabilities. Architecture prose describes only the current system and may not substitute for a requirement when observable behavior must be enforced.

Keeping prose in a companion file avoids contorting architectural explanation into synthetic WHEN/THEN scenarios. Embedding prose after `## Requirements` in `spec.md` was considered, but companion files provide clearer ownership and prevent parser-sensitive heading mistakes.

### The capability index is canonical

`openspec/specs/README.md` is the canonical table of contents for normative and architecture documents. `openspec/README.md` owns workflow guidance, while `docs/development/ARCHITECTURE.md` owns the cross-system map; both link to the capability index rather than maintaining competing detailed inventories.

### Promotion remains explicit

OpenSpec does not synchronize companion files. Every applicable change must therefore include an exact task and design-promotion record for accepted rationale. Archive review verifies the permanent architecture destination manually, just as it already verifies repository-wide architecture promotion.

A custom schema was considered but rejected because current OpenSpec schema customization changes artifact ordering/templates, not the hardcoded permanent-spec parser or delta synchronizer.

### Restoration is claim-based, not heading-based

The pre-migration document is evidence for what may have been lost, not authority for the current system. Restored prose is filtered against current specs, implementation, tests, and configuration. Current limitations are stated where they prevent old aspirational descriptions from becoming false baseline architecture.

### API credits receives an owning capability

The API-credits domain is implemented and tested but absent from permanent capability specifications. Its normative authority, quota, issuance, and consumption behavior is added as a new capability. Its architecture companion explains why market authorization, bearer usage identity, and quota authority remain separate.

## Risks / Trade-offs

- **Companion files are invisible to OpenSpec validation and sync** → Make their promotion and index coverage explicit repository governance requirements and archive checks.
- **Normative behavior could drift into prose** → Require observable invariants to remain in `spec.md`; architecture documents link to the normative contract and label current limits.
- **Duplicated cross-system content may drift** → Keep `docs/development/ARCHITECTURE.md` concise and make the capability index canonical.
- **Old prose may encode stale behavior** → Restore only claims verified against current evidence and record unresolved topics below.
- **A broad documentation change is harder to review** → Group documents by composition, lifecycle, and operations and commit each coherent group separately.

## Deferred and unresolved topics

The following are not current baseline architecture and require separate changes:

- Artifact Registry versus PyPI publication authority and package inventory.
- Local sibling `tool.uv.sources` usage versus wheel-only dependency policy.
- A universal mounted-profile versus environment-variable configuration rule.
- FRP production ownership, credential, and teardown guarantees.
- Repository-wide typed-client authority, versioning, and sync/async parity.
- Full black-box extraction and removal of sleeps/private calls from e2e tests.
- Generic settlement-plan materialization, reclaim, and durable receipt servicing.
- Restart-safe or distributed fulfillment assignment and fairness policy.
- Generic multi-storefront deal-event routing.

## Migration Plan

1. Add the capability index and planning-governance delta.
2. Add architecture companions in composition, lifecycle, and operations groups.
3. Add and validate the API-credits normative spec and architecture companion.
4. Update workflow guidance and the repository-wide architecture map.
5. Record promotion destinations, run strict OpenSpec and link checks, synchronize deltas, and archive the change.

Rollback is documentation-only: revert the affected documents and restore the previous index links. No runtime rollback is required.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Capability contracts and rationale use separate permanent files | `openspec/specs/planning-governance/spec.md` and `openspec/README.md` |
| Capability documents have one canonical table of contents | `openspec/specs/README.md` |
| Cross-system architecture links to detailed capability rationale | `docs/development/ARCHITECTURE.md` |
| Verified subsystem rationale belongs to owning companions | `openspec/specs/*/architecture.md` |
| API-credits has a dedicated permanent capability | `openspec/specs/api-credits/spec.md` and `architecture.md` |
