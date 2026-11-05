# Arkhai OpenSpec Guide

OpenSpec separates the system's durable current contract from the temporary work required to change it.

- `specs/<capability>/spec.md` describes the implemented normative contract: behavior, ownership, invariants, and lifecycle semantics.
- `specs/<capability>/architecture.md` may preserve durable current-state models, motivations, trade-offs, relationships, and limitations in freeform prose; in a capability organized by an index, that companion is `specs/<capability>/README.md`, beside an `index.md` ([Capability documentation pattern](#capability-documentation-pattern)).
- `specs/README.md` is the canonical capability documentation index.
- `changes/` describes a transition: proposal, alternatives, unresolved questions, delta requirements, migration concerns, and implementation tasks. [`changes/README.md`](changes/README.md) groups active changes into delivery campaigns without replacing each change's acceptance boundary.
- `changes/archive/` records completed transitions after their durable results have been synchronized into `specs/` and, where repository-wide, `docs/development/ARCHITECTURE.md`.
- `config.yaml` supplies repository context and artifact-quality rules.

Use `bunx @fission-ai/openspec@1.14.0 list` to inspect active changes, `show <name>` to read one, and `validate --all --strict` before review. The validator is pinned to 1.14.0: 1.14.1 adds a strict-mode failure for requirement text over 500 characters, which most permanent specs do not yet meet, and [`shorten-long-requirements`](changes/shorten-long-requirements/) restructures them and moves the pin forward.

## Documentation placement

| Knowledge | Permanent home |
|---|---|
| Repository-wide dependency layers, authority boundaries, common vocabulary, and major flows | `docs/development/ARCHITECTURE.md` |
| Testing methodology, test-level jurisdiction, and validation conventions | `docs/development/TESTING.md` |
| Configuration resolution and Kubernetes deployment conventions | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Operating a deployment: document formats, procedures, upgrade and recovery steps | `docs/operator-handbook.md` |
| Build, packaging, environment, lock, and image conventions, and the checks enforcing them | `docs/development/BUILD_AND_PACKAGING.md` |
| Directional goals, the value each delivers, current state per goal, and which change owns each open gap | `docs/development/ROADMAP.md` |
| Subsystem behavior, package ownership, lifecycle, identifiers, and errors | `openspec/specs/<subsystem>/spec.md` |
| Subsystem conceptual models, durable rationale, trade-offs, relationships, and current limits | `openspec/specs/<subsystem>/architecture.md`, or `openspec/specs/<subsystem>/README.md` where the subsystem has an `index.md` |
| The organization of an indexed subsystem's requirements, by id | `openspec/specs/<subsystem>/index.md` |
| Proposed behavior and unresolved alternatives | `openspec/changes/<change>/proposal.md` and `design.md` |
| Implementation sequence, files, validation, and manual migration work | `openspec/changes/<change>/tasks.md` |
| Change provenance and review discussion | Git history and pull requests |

`ARCHITECTURE.md` is a current-state cross-system map. It should link to detailed subsystem specifications rather than duplicate every endpoint and state transition. Permanent specs may include short rationale needed to interpret a requirement. Broader explanatory prose belongs in the capability's companion: `README.md` in a capability organized by an index, `architecture.md` in any other. Neither document preserves the chronology of how a decision was reached.

## Capability documentation pattern

A subsystem `spec.md` should contain its purpose and normative requirements for responsibilities, authority, dependencies, terminology, lifecycle, errors, retry, idempotency, versioning, and other observable behavior. Every requirement has acceptance scenarios and may point to implementation or test evidence.

A companion — `architecture.md`, or `README.md` in a capability organized by an index — may explain:

1. Conceptual models and major flows.
2. Why an authority or dependency boundary exists.
3. Ownership relationships and explicit non-responsibilities.
4. Alternatives and trade-offs that remain relevant to the current design.
5. Operational consequences and current limitations.
6. Links to adjacent capability contracts.

Both files describe the current system. Avoid wording such as "completed in POOLS-7" or "formerly lived in". Planned and partially implemented behavior remains in a change until it is true. When architecture prose states behavior implementations must satisfy, add the corresponding normative requirement to `spec.md`.

OpenSpec validates and synchronizes `spec.md` but ignores companion files and `index.md`. Every applicable change therefore names their promotion in `tasks.md` and its design-promotion record.

### A capability organized by an index

A capability's documentation follows its specification: its documents take the organization its requirements have. A component's `README.md` is its most human-readable document, the one a reader new to the component starts from; the procedural index of its requirements is a separate `index.md`. A capability may organize its documentation by an index of requirement ids. One that does keeps:

```text
openspec/specs/<capability>/
  README.md     the component's human-readable description, with its diagrams,
                its sections following index.md's parts
  index.md      the specification's organization: parts and groups as a table of
                contents, each requirement by id with its link and a summary line,
                and the retired ids
  spec.md       flat requirements, each named "### Requirement: <ID> <name>"
  diagrams/     each diagram's .drawio source and .svg export
```

Its `README.md` is its companion, and it has no `architecture.md`. The order of requirements in `spec.md` carries no meaning, since an archive appends a change's added requirements at the end; `index.md` holds the organization.

- **Ids.** An id is the capability's prefix, in upper-case letters, a hyphen, and four characters from `[a-z0-9]` chosen at random (`CW-a8tf`), so that changes on different branches are unlikely to choose the same one, and the check below catches it when they do. It encodes nothing of the organization, so a requirement keeps its id when the index moves it between groups. An id is never reused.
- **The index's shape.** `index.md` declares the prefix on a line of its own, `` Prefix: `CW` ``. Each requirement is a list item, or a table row, whose first cell is a link from its id to its heading in `spec.md` (`[CW-a8tf](spec.md#requirement-cw-a8tf-…)`), followed by its summary line, under the part and group it belongs to.
- **Retired ids.** When a change removes a requirement, its id moves to the items under `## Retired ids`, each beginning with the id and saying where its rule went.
- **Citing by id.** A requirement of an indexed capability may be cited by its id, such as `CW-a8tf`, so that the citation survives the requirement's renaming.
- **The check.** `make check-spec-index [CHANGE=<change>]` (`scripts/check_spec_index.py`), which `make check-change` runs with the change named, fails in a capability with an `index.md`, naming each, on: an `index.md` that declares no prefix, which leaves nothing else in that capability checked; a requirement whose name begins with no id; two requirements sharing an id; an id `index.md` omits or lists twice; a listed id in neither `spec.md` nor the named change's own deltas; a retired id in use; a link in `index.md` that does not resolve; and an entry whose link is not to its own id's heading in `spec.md`. With a change named, its deltas count as the archive will leave them, so closeout can write `index.md` before the archive merges a requirement into `spec.md`. A capability with no `index.md` is not checked.

A change that adds a requirement to an indexed capability gives it a new id in its delta's heading; closeout's promotion writes its index entry ([Plan closeout requirements](#plan-closeout-requirements), part 9).

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

A change to the change workflow names, in its proposal, each public interface of the workflow's engine it changes — a subcommand, a flag, an output field, a skill or its argument form, a graph node or review kind, the record set's format, or a role an adopting repository provides — and whether each change is compatible, as [`change-workflow`'s compatibility requirement](specs/change-workflow/index.md) judges it (`CW-c2tw`); review checks it. The engine carries no version of its own until it is extracted, so the proposal is where an incompatible change is declared.

## Open questions and prescribed tasks

An item may not appear under a change's `## Open questions` while a non-decision
task prescribes it. A design that calls a question open while its task list
instructs an implementer to answer it one way has not deferred the decision — it
has made it somewhere a reviewer will not look, and an implementer reading only
`tasks.md` will reasonably assume authority they were never given.

Either move the item into the design's decisions with its revisit trigger
stated, or make the task an explicit decision gate. A task that says "decide X
and record the reasoning" is a gate; a task that says "do X" is not, whether or
not it cites the open question.

## Plan closeout requirements

Every `tasks.md` for a change or a major section within one must end with a closeout task before implementation is considered planned, not invented after a review round asks for it. The closeout task has eleven parts, done in this order, and it ends by archiving the change, so the closeout review reads the change and the specifications as archived. Closeout changes documentation only: the code was last reviewed at pre-closeout, and the closeout review reads documentation, so a part that would need a code edit returns the change to implementation instead.

1. **Comment hygiene.** Confirm it; do not do it here. Comments are code, so the work belongs to implementation: the pre-closeout review reads the comments the change added, and its triage round fixes them. At closeout, run `make check-comment-hygiene`: it catches change IDs, section numbers, and task numbers mechanically, though not fuzzier violations of `AGENTS.md`'s "Python comments and docstrings" rule (references to which review or migration introduced the code). If it reports anything, or a comment the change added still needs rewriting, closeout stops and the change returns to implementation for a fix round; closeout never edits code, so its review, which reads only documentation, covers everything closeout changed.
2. **Import placement.** Confirm it; do not do it here, for the same reason as comment hygiene. During implementation, before the pre-closeout review, migrate local (function-level) imports to module level wherever safe. Not a blanket move: check each import actually added or touched by the section for a real reason to stay local first — a genuine circular import (verify by attempting the move and reading the actual failure, not by assuming) or a documented, deliberate lazy-load reason (e.g. avoiding import cost for a rarely-exercised code path) — before relocating it. Cross-reference against the section's own diff rather than auditing every pre-existing local import in a touched file; this step is about what the section added, not a general-purpose repo cleanup. Verify each candidate move against the real test suite, not just a syntax check, since a passing import at definition time does not guarantee no circular dependency exists at call time. At closeout, check the imports the change added; one that should move returns the change to implementation.
3. **Documentation compliance.** Re-check the change's own accepted decisions against this document's placement rules directly — do not defer this to an external reviewer noticing it first.
4. **Narrative compression.** Shorten completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations. Move detailed alternatives, debugging narratives, and review rationale into `design.md` first if they are not already there — this step deletes duplication, not information.
5. **Roadmap currency.** Update the affected goal's current-state description and gap-to-change mapping in [`docs/development/ROADMAP.md`](../docs/development/ROADMAP.md), and name that update in the design-promotion record. Most changes owe nothing here; a change with no roadmap impact records that disposition explicitly rather than omitting the step, so an absent roadmap edit is a deliberate finding rather than an unanswered question at review.
6. **Campaign index currency.** Update the change's row, and its campaign's dependency graph, in [`changes/README.md`](changes/README.md) so the recorded status matches what is now true, and name that update in the design-promotion record. The index answers what a reader may start next, and a stale row misdirects that decision. A change whose status and campaign placement are both unchanged records that disposition explicitly rather than omitting the step. A change that creates, renames, supersedes, or removes a change directory reconciles the index's links in the same step: a link to a directory that does not exist is a blocking defect under `AGENTS.md`'s cross-reference rule, not a stale link to fix later. `make check-change-index` checks each row's cell count, its link to its change's directory (an `archived` row links its archive, and a row linking an archive is `archived` or `in closeout`), its status against the legend, its dependencies, and that every active change directory has exactly one row; an archived change needs no row, since archived rows may be pruned from the index over time. Closeout leaves other rows' `Depends on` as they are: a dependency lands when it is `archived`, which is written only once the closeout review's triage records that the change advances and the archive is cleaned up. Archive cleanup then removes the change from every other row's `Depends on`, and returns each dependent whose status is `ready for planning`, `in planning`, or `ready for implementation` to `ready for design`: the dependent's design rests on a codebase this change has just altered, so it is reverified before it is planned or implemented. A dependent `in implementation` keeps its status, because its implementation has begun. A dependent that is `blocked in` a phase keeps its status, because that blocker is independent of this change; archive cleanup records in its `Notes` that design reverification is owed once the blocker clears.
7. **Packaging.** Run `make check-packaging` and resolve every failure it reports, then run `make check-architecture-change CHANGE=<change-name>`: a change may not be archived while it owns an architecture exception or override row, so each is deleted with its edge or reassigned to the open change that now owns the divergence. Run `make check-agent-skills` too when the change touched `.agents/`, `.claude/`, or `.codex/`. It builds the wheelhouse, then checks that every environment and image install derives its internal packages from its lock, that every lock is current with its project, the wheels the tree builds, and the repository, that every Python version selection reads the root declaration, and that every package keeps the layer, scope, and kind rules (`make check-architecture`). Passing test suites do not prove this: a suite can pass against an environment a missing or hand-maintained refresh left stale, and the next environment to rebuild then fails instead. [`docs/development/BUILD_AND_PACKAGING.md`](../docs/development/BUILD_AND_PACKAGING.md) says what each check enforces.
8. **End-to-end pipeline.** Confirm the end-to-end pipeline passes, and record the evidence — the run, its result, and the scenarios that exercise this change's behaviour. A change is not complete because its own suites are green: this is the tier that catches a wire contract whose two sides disagree, a service that starts cleanly and cannot settle, and a configuration gap no unit test can see, none of which any in-process test will report. If the pipeline cannot run for a reason unrelated to the change, record that as an explicit blocker naming the cause and the change that owns it, and treat the validations it gates as unrun rather than as passed.
9. **Promotion.** Write the permanent documents the closeout task names — architecture companions, `ARCHITECTURE.md`, other documents under `docs/`, `openspec/specs/README.md` — and complete the design-promotion record (see below). A `spec.md` the change's deltas cover is written by the archive in part 11, not by hand; the record names it all the same. In a capability organized by an index, promotion also writes its `index.md`: an entry, with its link and summary line under its part and group, for each id the change's deltas add; for each requirement they rename, its entry's link moved to the new heading; for each they modify, its summary line revised where it no longer holds; and, for each requirement they remove, its id moved to the retired ids with where its rule went. The index check accepts the new ids from the change's deltas, so the entries are written before the archive merges them.
10. **Documentation citations.** Run `make check-doc-citations CHANGE=<change-name>` after promotion, so the documents it wrote are there to resolve, and resolve every match; then validate the change with `openspec validate <change-name> --strict`, the last check before the archive. A change with no spec deltas records that instead, since the validator rejects a change with none, and archives with `--skip-specs`. `AGENTS.md` treats a citation whose target does not resolve as a blocking defect rather than a stale link, and this target additionally rejects a citation pointing at a *tombstone*: a tombstoned file still exists on disk while its content is gone, so the plain existence test that preceded this could never fail on a rename-to-tombstone — the likeliest broken citation in a renaming change. Scoped to the change on purpose. A change owes the citations it wrote, and gating archival on the whole repository's documentation debt would let one team's stale runbook block everyone else's, which turns a check into something people route around. Run the target unscoped to see the repository-wide picture.
11. **Archival.** Archive the change as the last step, once every other part is done: `openspec archive <change-name> -y` merges its spec deltas into `openspec/specs/` and moves it to `changes/archive/<date>-<change-name>/`; the change's row in [`changes/README.md`](changes/README.md) then links to that directory. A change whose `spec.md` promotion was made by hand before this rule archives with `--skip-specs`, so the merge is not applied twice. The closeout review and its triage then read the archived change and the permanent documents as archived, and find the change by name under the archive (`scripts/change-workflow find <change-name>`).

If a plan's closeout task grows unusually large on its own, decide deliberately whether the growth belongs to the change — a found defect fixed in place, or unification the architecture favours — or is separate work better split, rather than noticing only once the section is hard to review ([Defects found during a change](#defects-found-during-a-change)).

During implementation, maintain a promotion record in the active change:

```markdown
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Fulfillment owns provider-neutral execution contracts | `openspec/specs/fulfillment/spec.md#ownership` |
| Kit dependency layers | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` |
```

The record is change history and remains in the change directory. The destination documents describe only the resulting current state.

## Defects found during a change

A defect found while working a change is fixed in that change when its fix is understood and small beside the change, even where it lies outside the change's stated scope: a change of its own costs a design, reviews, validation and a closeout, which a small fix does not repay. A defect that is large, or not understood well enough to fix without a design of its own, gets its own change, or an unowned gap where no change owns its area (`AGENTS.md`, "Deferred work"). This is a judgement of proportion, not a rule that changes stay narrow, and growth that unifies behaviour the architecture wants shared ([`ARCHITECTURE.md`, "Composition from above and below"](../docs/development/ARCHITECTURE.md#composition-from-above-and-below)) is not scope creep. A defect fixed outside the stated scope is recorded where the change's reviewers will see it: in the task notes, or in the triage record.

## Implementation completion checklist

Before marking implementation complete:

- [ ] Code and tests satisfy the change specification.
- [ ] Existing completed tasks remain preserved; corrections are appended or amended.
- [ ] Every accepted material decision has been classified as permanent, temporary, superseded, or rejected.
- [ ] Subsystem-specific durable knowledge is present in `openspec/specs`.
- [ ] Repository-wide durable knowledge is present in `ARCHITECTURE.md`.
- [ ] Permanent documents describe current state rather than completion history.
- [ ] Production code contains no references to `openspec/changes`, task IDs, previous file locations, or migration provenance — `make check-comment-hygiene` passes.
- [ ] Non-obvious comments communicate local rationale and invariants.
- [ ] The change contains a design-promotion record.
- [ ] Validation evidence and any unrun suites are disclosed.

## Current capability documentation

See the canonical [capability documentation index](specs/README.md) for every normative contract and architecture companion.

## Contributor workflow

1. Read `AGENTS.md`, `docs/development/ARCHITECTURE.md`, the owning permanent specs, and the active change.
2. Audit the proposed delta against current code and focused evidence.
3. Resolve design questions in the active change and identify permanent documentation impact.
4. Preserve completed tasks and create or amend an implementation plan only after the design is ready.
5. Implement code and tests, recording in the design-promotion record each decision's permanent destination; the documents themselves are written at closeout.
6. Run focused behavioral, package, typing, and integration checks appropriate to the boundary.
7. Close out: promote the accepted current-state documentation, confirm no production code references temporary change documents, complete the promotion record, and archive the change, which synchronizes its verified delta into `specs/`; the closeout review then reads the archived change.
