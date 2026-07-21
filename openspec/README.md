# Arkhai OpenSpec Guide

OpenSpec separates the system's durable current contract from the temporary work required to change it.

- `specs/` describes the implemented system: behavior, ownership, invariants, lifecycle semantics, and durable design rationale.
- `changes/` describes a transition: proposal, alternatives, unresolved questions, delta requirements, migration concerns, and implementation tasks.
- `changes/archive/` records completed transitions after their durable results have been synchronized into `specs/` and, where repository-wide, `docs/development/ARCHITECTURE.md`.
- `config.yaml` supplies repository context and artifact-quality rules.

Use `bunx @fission-ai/openspec@latest list` to inspect active changes, `show <name>` to read one, and `validate --all --strict` before review.

## Documentation placement

| Knowledge | Permanent home |
|---|---|
| Repository-wide dependency layers, authority boundaries, common vocabulary, and major flows | `docs/development/ARCHITECTURE.md` |
| Subsystem behavior, package ownership, lifecycle, identifiers, errors, and durable rationale | `openspec/specs/<subsystem>/spec.md` |
| Proposed behavior and unresolved alternatives | `openspec/changes/<change>/proposal.md` and `design.md` |
| Implementation sequence, files, validation, and manual migration work | `openspec/changes/<change>/tasks.md` |
| Change provenance and review discussion | Git history and pull requests |

`ARCHITECTURE.md` is a current-state cross-system map. It should link to detailed subsystem specifications rather than duplicate every endpoint and state transition. Permanent specs may include rationale when it is needed to prevent a future implementation from violating an important boundary; they should not preserve the chronology of how the decision was reached.

## Capability specification pattern

A subsystem specification should normally contain:

1. Purpose and responsibilities.
2. Non-responsibilities and authority boundaries.
3. Package or service ownership.
4. Dependency constraints.
5. Official terminology and identifiers.
6. Lifecycle and state semantics.
7. Behavioral requirements and acceptance scenarios.
8. Error, retry, idempotency, and versioning rules where applicable.
9. Durable rationale for non-obvious architectural choices.
10. Evidence pointing to the tests or implementation surfaces that prove the current contract.

Specifications describe the current system. Avoid wording such as "completed in POOLS-7" or "formerly lived in". Planned and partially implemented behavior remains in a change until it is true.

## Change documentation requirements

Every non-trivial `proposal.md` should identify permanent documentation impact:

```markdown
## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- <material accepted decision and intended permanent destination>
```

Every implementation-ready `tasks.md` should name the exact promotion work rather than using a generic "update docs" task.

During implementation, maintain a promotion record in the active change:

```markdown
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Fulfillment owns provider-neutral execution contracts | `openspec/specs/fulfillment/spec.md#ownership` |
| Kit dependency layers | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` |
```

The record is change history and remains in the change directory. The destination documents describe only the resulting current state.

## Implementation completion checklist

Before marking implementation complete:

- [ ] Code and tests satisfy the change specification.
- [ ] Existing completed tasks remain preserved; corrections are appended or amended.
- [ ] Every accepted material decision has been classified as permanent, temporary, superseded, or rejected.
- [ ] Subsystem-specific durable knowledge is present in `openspec/specs`.
- [ ] Repository-wide durable knowledge is present in `ARCHITECTURE.md`.
- [ ] Permanent documents describe current state rather than completion history.
- [ ] Production code contains no references to `openspec/changes`, task IDs, previous file locations, or migration provenance.
- [ ] Non-obvious comments communicate local rationale and invariants.
- [ ] The active change contains a design-promotion record.
- [ ] Manual deletions are represented by review tombstones and listed in the delivery summary.
- [ ] Validation evidence and any unrun suites are disclosed.

## Current capability specifications

| Capability | Contract |
|---|---|
| [Market composition](specs/market-composition/spec.md) | Core/kit/domain dependency direction, role ownership, and plugins |
| [Registry discovery](specs/registry-discovery/spec.md) | Publication, filter-spec validation, identity, and compatibility |
| [Negotiation protocol](specs/negotiation-protocol/spec.md) | Signed synchronous rounds, policy hooks, and deterministic Terms |
| [Settlement servicing](specs/settlement-servicing/spec.md) | Plans, claims, mechanism codecs, and heartbeats |
| [Storefront publication](specs/storefront-publication/spec.md) | Seller surfaces, listing reconciliation, and domain runtimes |
| [Site capacity](specs/site-capacity/spec.md) | Capacity authority, reservations, aggregation, and events |
| [Resource-pool management](specs/resource-pool-management/spec.md) | Pool administration, provider configuration, and host membership |
| [Fulfillment](specs/fulfillment/spec.md) | Settlement-resource scheduling, provider execution contracts, identities, and versioned envelopes |
| [Physical provisioning](specs/physical-provisioning/spec.md) | Executor dispatch, asynchronous jobs, and lease release |
| [Buyer orchestration](specs/buyer-orchestration/spec.md) | Plugins, policy selection, aggregation, and recovery |
| [Deployment and state](specs/deployment-state/spec.md) | Topology, persistence, migrations, packaging, and internal wheels |
| [Testing and compatibility](specs/test-compatibility/spec.md) | Test levels, fixtures, e2e staging, and rollout contracts |
| [Planning governance](specs/planning-governance/spec.md) | Specification ownership, evidence, and change readiness |

## Contributor workflow

1. Read `AGENTS.md`, `docs/development/ARCHITECTURE.md`, the owning permanent specs, and the active change.
2. Audit the proposed delta against current code and focused evidence.
3. Resolve design questions in the active change and identify permanent documentation impact.
4. Preserve completed tasks and create or amend an implementation plan only after the design is ready.
5. Implement code, tests, permanent documentation, and the change's design-promotion record together.
6. Run focused behavioral, package, typing, and integration checks appropriate to the boundary.
7. Synchronize the verified delta, confirm no production code references temporary change documents, and archive the completed change.
