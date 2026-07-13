## Context

The repository already has an empty `openspec/specs/` tree and `spec-driven` configuration, but its effective planning system remains document-based:

- `ARCHITECTURE.md` mixes durable principles, current runtime facts, package inventories, known debt, and references to pending work.
- `TODO.md` mixes planned changes, in-progress programs, implemented history, deferred/conditional ideas, operational gotchas, and documentation gaps. One heading is missing from its index and several large items contain both landed and pending work.
- `design-remaining-work.md` and `provisioning-migration-plan.md` duplicate parts of the TODO while carrying decisions and sequencing that do not fit a flat backlog.
- Inline TODO/FIXME notes may represent real work, stale commentary, or local implementation detail.

A mechanical Markdown move would preserve these ambiguities. The migration therefore needs an inventory, classification, normalization, and coverage pass before legacy planning text can be retired.

## Goals / Non-Goals

**Goals:**

- Give each kind of information one canonical home: specs for current normative behavior, active changes for proposed deltas, archived changes for completed decisions, and ordinary docs for operational guidance and non-normative orientation.
- Preserve the architectural principles and vocabulary that constrain future changes without copying the full architecture reference into every artifact.
- Split the monolithic backlog into independently actionable changes with explicit requirements, scenarios, design decisions, dependencies, and implementation tasks.
- Produce a machine-checkable migration ledger proving disposition of every legacy planning section and actionable inline marker.
- Make future drift harder through OpenSpec configuration rules, validation, and repository-facing contributor guidance.

**Non-Goals:**

- Implement any pending architecture or TODO item during this migration.
- Treat prose as correct merely because it exists; current-state claims must be checked against code or marked unresolved.
- Convert operational runbooks, release procedures, issue-discovery procedures, or explanatory diagrams into requirements when they are better retained as documentation.
- Create one giant permanent `architecture` capability or one giant backlog change.
- Preserve obsolete compatibility plans or completed task history in active changes.

## Decisions

### 1. Separate normative state from proposed deltas

Stable behavior becomes main specs under `openspec/specs/<capability>/spec.md`. Pending work becomes one or more changes under `openspec/changes/<change>/`. Completed design history is represented by archived changes when it remains useful; otherwise provenance in the migration ledger is sufficient.

Alternative: import `ARCHITECTURE.md` as a single spec and `TODO.md` as one change. Rejected because it reproduces the current coupling, prevents independent validation/archive, and makes scenarios too broad to be useful.

### 2. Organize baseline specs by durable capability

The initial capability map should follow system responsibilities, not package names:

- market composition and package boundaries;
- listing registry and discovery;
- negotiation protocol;
- settlement plans and servicing;
- storefront and publication;
- site capacity and reservations;
- physical provisioning and lease lifecycle;
- buyer orchestration and plugins;
- deployment and schema migration;
- testing and compatibility contracts.

The exact map may be adjusted during inventory when two areas cannot be specified independently. Package paths remain implementation evidence, not capability identities.

Alternative: one spec per wheel/service. Rejected because package ownership is itself changing, while capability contracts should survive moves such as `domains/vms/provisioning` to `provisioning/compute`.

### 3. Use a migration ledger as the loss-prevention mechanism

Create a temporary, version-controlled ledger within this change. Each source unit receives a stable source reference, classification, destination, disposition, and verification state. Source units include every heading in the four named planning documents and every repository-owned actionable TODO/FIXME marker found by the agreed scan.

Allowed classifications:

| Classification | Destination |
|---|---|
| current normative behavior | baseline capability spec |
| proposed behavior | active OpenSpec change |
| implemented historical change | archived change or ledger-only history |
| operational warning/runbook material | retained ordinary documentation |
| deferred/conditional idea | active change explicitly marked deferred/conditional, or documented rejection |
| duplicate | canonical destination plus duplicate link |
| stale/incorrect | removal with evidence |
| ambiguous/external | unresolved ledger entry naming the blocker/owner |

Legacy files are not pruned while any ledger row lacks a disposition and destination.

Alternative: rely on reviewer memory and a final diff. Rejected because the source corpus is large, cross-linked, and internally inconsistent.

### 4. Split changes at independent acceptance boundaries

A TODO heading is a candidate, not automatically a change. Split compound programs when parts can be implemented and archived independently; merge duplicate headings when they describe the same observable outcome. Dependencies are stated in proposal/design text rather than encoded by keeping unrelated tasks in one change.

Examples from the current corpus:

- Registry Postgres migration and init-container/schema-guard work remain separate but linked changes.
- “Market Core Extraction follow-ons” splits into settlement-plan shapes, capacity multi-domain proof, storefront-client wire genericization, buyer CLI residue, and publishing setup.
- POOLS items already landed are baseline/archive evidence; only genuinely remaining POOLS work stays active.
- Documentation gaps become doc changes only if a concrete missing audience contract and acceptance criterion exist.

### 5. Treat inline notes conservatively

The scan covers tracked, repository-owned source and documentation files while excluding generated output, vendored code, lockfiles, archived OpenSpec artifacts, and migration histories. Each marker is inspected in context. A marker becomes a change only when it names unresolved observable work; local reminders that belong to an existing change become tasks; stale markers are removed only with code evidence.

Alternative: automatically create a change per marker. Rejected because marker volume and quality do not imply backlog intent.

### 6. Keep concise human orientation docs

After cutover, retain a short architecture overview and links to capability specs, active changes, and operational docs. Remove normative duplication and the flat TODO backlog. Redirect old stable entry points where practical so external links fail clearly rather than silently serving stale plans.

### 7. Configure future artifact quality

`openspec/config.yaml` will carry concise project context: architecture vocabulary, core/kit/domain dependency direction, role/plugin boundaries, Python tooling, focused verification, and clean-cutover rules. Artifact rules require:

- proposals to name non-goals and impacted capabilities;
- specs to describe observable contracts with scenarios and avoid source-path-only requirements;
- designs to record wire/data compatibility and migration decisions;
- tasks to include focused behavioral verification and documentation cleanup after behavior works.

The configuration must stay concise; detailed current behavior belongs in specs, not global prompt context.

### 8. Perform a staged cutover

1. Inventory and classify all source material.
2. Establish and validate baseline specs from current, code-verified behavior.
3. Create normalized active/archived changes for pending and completed work.
4. Cross-check all destinations against the ledger and OpenSpec validation.
5. Update contributor entry points and prune/redirect legacy planning content.
6. Archive this migration change only after the post-cutover scan finds no orphan planning source.

This order keeps the old documents available until their replacements are proven complete.

## Risks / Trade-offs

- **Specs can fossilize incorrect prose.** Mitigation: require code/test evidence for current-state claims; unresolved contradictions remain ledger entries rather than requirements.
- **Too many tiny capabilities or changes reduce navigability.** Mitigation: split at independent observable contracts and archive boundaries, not headings or files.
- **Too few artifacts recreate the monolith.** Mitigation: reject changes that contain unrelated acceptance boundaries or multiple independently deployable programs.
- **Cross-links may break when legacy files shrink.** Mitigation: inventory incoming repository links, retain redirects/indexes where useful, and verify links before deletion.
- **OpenSpec has no native backlog status taxonomy for every legacy label.** Mitigation: encode “deferred,” “conditional,” and external blockers explicitly in proposal/design text; do not pretend they are implementation-ready.
- **The migration can churn while architecture work continues.** Mitigation: record the source revision in the ledger and run a final delta scan before cutover.
- **A concise overview loses narrative depth.** Trade-off accepted: narrative explanation remains in ordinary docs where helpful, while normative statements live once in specs.
