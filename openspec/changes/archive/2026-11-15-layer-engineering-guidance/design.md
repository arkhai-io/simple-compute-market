# Design: layer engineering guidance

Status: design settled and reviewed; design review 19's findings are settled in D5,
D21, and D22. Round 1's triage amended D8 and D10 and settled the decisions under
"Settled at round 1's triage". Round 2's triage amended D3 and settled the decisions
under "Settled at round 2's triage"; later triages settled theirs under their own
"Settled at" headings, rounds 4 and 5 sharpening D3 for `AGENTS.md`. The return to
design before the pre-closeout review settled D24 to D35: the tags stay minimal,
committing to no selection formula, and the repository's cross-system documents
divide into description, rules, and procedures, the rules moving into
`docs/guidance/repository/`, in one more round before closeout.

The documents the change removed are named by their former paths without the leading
`docs/`: `agents/change-workflow.md` (moved to `docs/change-workflow-handbook.md`),
`agents/domain.md`, `development/BUILD_AND_PACKAGING.md`, and
`development/RELEASING.md`.

## Context

- **The documents and their size.** About 8,900 lines:

  | Document | Lines | Read by every step (`load.common`) |
  |---|---|---|
  | `AGENTS.md` | 242 | yes, and always in context through `CLAUDE.md` |
  | `docs/development/ARCHITECTURE.md` | 1,315 | yes |
  | `docs/development/TESTING.md` | 1,793 | yes |
  | `docs/development/DEPLOYMENT_AND_CONFIG.md` | 2,148 | yes |
  | `openspec/README.md` | 171 | yes |
  | `development/BUILD_AND_PACKAGING.md` | 216 | no |
  | `docs/development/VALIDATION_RUNBOOK.md` | 1,557 | no |
  | `development/RELEASING.md` | 281 | no |
  | `docs/agents/` (`change-workflow.md`, `domain.md`) | 1,024 | no |
  | `docs/prompts/` (five files) | 172 | no |

  Every step reads 5,669 lines through `load.common`; design adds `ROADMAP.md`.
  Most of `TESTING.md` and `DEPLOYMENT_AND_CONFIG.md` is market material most steps
  never use.
- **The repository documents after the capability moves.** Once round 6 moved each
  capability's sections beside it, the five cross-system documents hold about 3,700
  lines: `ARCHITECTURE.md` 1,231, `TESTING.md` 1,178, `DEPLOYMENT_AND_CONFIG.md` 839,
  `RELEASING.md` 262, `BUILD_AND_PACKAGING.md` 212. Each mixes three kinds of
  material: a description of the system (`ARCHITECTURE.md`'s overview, authority,
  vocabulary, and flows; `TESTING.md`'s lanes), rules a change must satisfy here
  (package layers, where tests go, mounting, locks, the published set), and
  procedures the owner or an operator runs (`RELEASING.md`'s setup, release, and
  troubleshooting; how an operator supplies settings).
- **Loading by path already exists.** `[load]` in `.agents/workflow.toml`, printed
  by `config load <step>` (CW-l7hn), lists the documents each step reads. The
  post-compaction hook (`scripts/change_workflow/hook.py`) tells a Claude Code
  session to re-read `load.common`, its skill, and its change; it names documents
  rather than injecting them, which exceed the hook's limit, and cannot tell the
  session's step. Codex, which runs the reviews, has no such hook. `[load]` takes
  literal paths. The archived capability contract left loading by tag to this
  change's vocabulary.
- **Mixing.** `AGENTS.md`'s comment rule mixes a rule for any repository, a rule of
  the workflow (never name a change), and a fulfillment example. `TESTING.md`
  states general test levels, then Python conventions with this repository's CLIs
  inside them, then capability sections such as "Pool Offering-Mode Enforcement".
  `ARCHITECTURE.md` carries engineering rules ("Implementation rules", the
  database-concurrency tests, the test-double rule). `openspec/README.md` holds the
  OpenSpec documentation model and the closeout parts beside this repository's
  placement table and validator pin.
- **Citations.** About 286 files cite the main guidance documents; about 74 cite
  `openspec/README.md`, "Plan closeout requirements", many by part number.
  `scripts/check_doc_citations.py` checks that a cited path exists, not its anchor.
- **Checks that enforce guidance.** Comment hygiene, history wording, local
  imports, decision destinations, version bumps, the capability and specification
  indexes, citations, public content and secrets, the pre-push check, the
  architecture and packaging checks, and the workflow's default checks.
- **Restatement.** Skills restate guidance where a step applies it, never stricter
  than its source (`agents/change-workflow.md`, "Skills"); the skills cite the
  main guidance documents about 40 times.
- **`docs/prompts/`** holds chat-session prompts that the change skills superseded;
  nothing cites them.
- **Work in flight.** About a dozen changes are in implementation or closeout, and
  most promote into `TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`, or `ARCHITECTURE.md`.

## Decisions

### D1 — Three layers, assigned by a dependency test, with a citation direction

Every piece of guidance belongs to one layer:

- **Engineering:** holds in a repository that uses neither the change workflow nor
  OpenSpec.
- **Workflow:** holds in any repository that adopts the workflow, OpenSpec
  included, and names nothing of one repository.
- **Repository:** names this repository's packages, services, tools, deployment,
  documents, or make targets.

A lower layer never cites a higher one: engineering cites only engineering,
workflow cites workflow or engineering, repository cites any. This is the package
direction rule applied to documents, and it keeps a later lift-out of a layer a
move rather than a rewrite. OpenSpec's documentation model — `spec.md`, its
companion, changes, promotion — is workflow material, since the workflow requires
OpenSpec and an adopter takes both. Each layer divides further: engineering by
language or tool (Python, Helm, uv), repository by the capability it pertains to.
A subdivision is a partition within its layer with no precedence of its own. The
test also gives closeout a basis to evaluate promoted guidance (D16).

Rejected: three layers classified case by case, which leaves borderline sections to
fresh judgement and nothing to place a new section; a separate pack layer with its
own precedence, which duplicates the tag axis; a shared/repository split only,
which fails `extract-change-workflow-repository`'s need for the workflow line.

### D2 — Design settles the rules; implementation produces the inventory

Design settles the test, the placement, and the tags, and records the hard-case
sample below. The first implementation round applies the test to every section and
writes the full inventory as a table in the change: one row per section or part of
one, with its layer, tags, destination, and reason, and an `Ambiguous` column for
each row the test did not decide. The owner corrects the rows in that round's
triage, before any text moves; a row showing a rule is wrong returns the change to
design. The inventory is change history: the placement and tags are its permanent
record.

Rejected: the full inventory in design, which would make a 300–400-row design stale
against documents edited weekly before implementation read it and spend the design
review on rows rather than the rules producing them; a hybrid for the loaded
documents only, most of the same size; no inventory, leaving a 9,000-line move as
the only thing to review.

#### Hard-case sample

Destinations are provisional file names; round 1 confirms them.

| Section today | Layer and tags | Destination | Why |
|---|---|---|---|
| `AGENTS.md` "Working model" (Discuss, Plan, Implement) | workflow: design, planning | `docs/guidance/workflow/working-model.md` | presupposes changes and phases |
| `AGENTS.md` "Asking the owner" | workflow: design | `working-model.md` | the owner's role is the workflow's |
| `AGENTS.md` "Amend a rule or comply" | split: engineering, documentation (amend rather than except); repository (the testing-levels example) | `docs/guidance/engineering/rules.md`; `AGENTS.md` | Ambiguous: its relation to D9's exceptions is for the owner to confirm |
| `AGENTS.md` "Documentation ownership" | split: engineering, documentation (current state; provenance in version control); workflow, documentation (spec, companion, changes); repository (`ARCHITECTURE.md`, `DEPLOYMENT_AND_CONFIG.md`, handbook ownership) | `engineering/documentation.md`; `workflow/openspec-documentation.md`; `AGENTS.md` | three layers in one section |
| `AGENTS.md` "Python comments and docstrings" | split: engineering, comments (comments describe the current system; what they are for); engineering, comments, python (docstrings); workflow, comments (never name a change, task, or `tasks.md`); repository (the fulfillment example; the hygiene check's file types) | `engineering/comments.md`; `workflow/change-references.md`; `AGENTS.md` | the rule's example names a capability |
| `AGENTS.md` "Diagrams" | engineering, documentation, diagrams; the graph-table example to the workflow's README | `engineering/diagrams.md` | the principle holds anywhere; the example is the workflow's |
| `AGENTS.md` "Package and dependency discipline" | split: engineering, dependencies, python (any import is a dependency; declare what you import); repository (layers, `ARCHITECTURE.toml` rows, `make check-architecture`) | `engineering/dependencies.md`; the cross-system architecture document | the rule is general, its enforcement this repository's |
| `AGENTS.md` "Tests and diagnostics" | split: engineering, testing; repository (`make check-packaging`) | `engineering/testing.md`; `AGENTS.md` | |
| `AGENTS.md` "Public repository discipline" and its three first subsections | engineering, repository-content (D6), with this repository's choice of the public case at the root (D9) | `engineering/repository-content.md`; `AGENTS.md` | the workflow runs in private repositories too |
| `AGENTS.md` "Cross-references must resolve" | split: engineering, documentation (citations resolve); workflow, closeout (the promotion story; check before promoting) | `engineering/documentation.md`; `workflow/closeout.md` | |
| `AGENTS.md` "Deferred work" | split: workflow, planning (owning change, unowned gap in the index, the roadmap's role, 31 O1f); repository (the `ROADMAP.md` path, no GitHub Issues, the discovery harness) | `working-model.md`; `AGENTS.md` | |
| `AGENTS.md` "Domain docs", `agents/domain.md` | split: workflow (the workflow's terms in its specification); repository (the market's homes) | `workflow/terms.md`; `AGENTS.md` | Ambiguous: whether "one home per term" is engineering |
| `openspec/README.md` introduction and validator pin | split: workflow, documentation (the OpenSpec layout); repository (the pin and its command) | `openspec-documentation.md`; `openspec/README.md` | |
| `openspec/README.md` "Documentation placement" | split: workflow (spec, companion, change rows); repository (rows naming `docs/development/`) | both | |
| `openspec/README.md` "Capability documentation pattern", "A capability organized by an index" | workflow, documentation; repository (`make check-spec-index`) | `openspec-documentation.md` | |
| `openspec/README.md` "Change documentation requirements", "Open questions and prescribed tasks" | workflow, planning | `workflow/changes.md` | |
| `openspec/README.md` "Plan closeout requirements" | D8 | `workflow/closeout.md`; `openspec/README.md` for this repository's parts | |
| `openspec/README.md` "Defects found during a change" | workflow, planning; its link to `ARCHITECTURE.md` neutralized | `workflow/changes.md` | the direction rule |
| `openspec/README.md` "Implementation completion checklist", "Contributor workflow" | workflow | `working-model.md` | Ambiguous: both duplicate "Working model" |
| `ARCHITECTURE.md` "Implementation rules" | engineering, implementation; its frp and gitleaks examples stay as repository illustration | `engineering/implementation.md` | |
| `ARCHITECTURE.md` "Testing strategy", the test-double paragraph | engineering, testing; the payments and mediation doubles as repository examples | `engineering/test-doubles.md` | |
| `ARCHITECTURE.md` "Deterministic database-concurrency tests" | engineering, testing | `engineering/concurrency-tests.md` | |
| …its misfiled subsections | "Durable fulfillment acceptance" beside `fulfillment`; "Public repository content checks" beside `market-change-workflow` | `openspec/specs/fulfillment/`; `openspec/specs/market-change-workflow/README.md` | Ambiguous: "Atomic workload-lifecycle cutovers" is general in form, market in terms |
| `ARCHITECTURE.md` "Package and dependency layers" | repository | stays | cross-system |
| `TESTING.md` "Four-Level Hierarchy", "Unit Tests" core definitions | engineering, testing | `engineering/test-levels.md` | |
| `TESTING.md` mocking and command-module conventions | engineering, testing, python; the bare-metal CLI as repository example | `engineering/test-seams.md` | its remaining-CLIs gap is an exception (D9) |
| `TESTING.md` negotiation-runtime convention | repository, testing | `openspec/specs/negotiation-protocol/testing.md` | one capability |
| `TESTING.md` "Coverage Contract Between Levels" | engineering, testing | `test-levels.md` | |
| `TESTING.md` "The canonical compute deal", the lanes | repository, testing | stays | cross-system |
| `TESTING.md` "Pool Offering-Mode Enforcement" | repository, testing | `openspec/specs/resource-pool-management/testing.md` | one capability |
| `TESTING.md` "Payment Receipts in Tests" | repository, testing | beside its capability | Ambiguous: which capability owns the receipt fixture |
| `TESTING.md` "Chart Render Tests" | split: engineering, testing, helm (a render test asserts on manifests or refusal); repository (the charts, the pinned Helm) | `engineering/helm-render-tests.md`; stays | |
| `DEPLOYMENT_AND_CONFIG.md` "Profile-based configuration" | split: engineering, configuration; repository (the profiles) | `engineering/configuration.md`; stays | |
| `DEPLOYMENT_AND_CONFIG.md` "The method a document kind follows" and its siblings | engineering, configuration | `engineering/definition-documents.md` | |
| `DEPLOYMENT_AND_CONFIG.md` "Marketplace identity configuration" | repository, configuration | `openspec/specs/marketplace-identity/configuration.md` | Ambiguous: overlap with the operator handbook |
| `DEPLOYMENT_AND_CONFIG.md` "Kubernetes: ConfigMap and Secret mounting" | repository, deployment | stays | cross-system |
| `agents/change-workflow.md` | workflow; its step table's validation parts and links to `market-change-workflow` split out | `agents/change-workflow.md`; `openspec/specs/market-change-workflow/README.md` | the direction rule |
| `RELEASING.md` | repository: rules and procedures | its versioning policy to engineering (D10 as amended at round 1); its rules to `docs/guidance/repository/` and its procedures to the owner's handbook (D10 as amended at the return to design) | a procedure beside rules |
| `VALIDATION_RUNBOOK.md` | outside the guidance set: no frontmatter, no layer-table row | stays whole (D10, 48 F1) | a procedure, not guidance |
| `openspec/config.yaml` | outside the guidance set; its restatements as rows | stays (D23) | |
| `docs/prompts/` | outside the guidance set | untouched (D12) | |

### D3 — Shared layers in `docs/guidance/`; capability guidance beside its capability

The initial migration organizes shared guidance as `docs/guidance/engineering/` and
`docs/guidance/workflow/`, each with a `README.md` holding its tag table (D18). The
organization is for people navigating the tree, and may change: the tag defines a
file's layer, the workflow attaches no meaning to directories, and a lift-out
selects files by layer tag, which the direction rule keeps cheap.
The workflow's guide, `agents/change-workflow.md`, is not guidance: it becomes
the change workflow's operator handbook, holding only what the owner needs to know,
beside the other handbooks in `docs/`, with no frontmatter; what agents need of it
moves out by the rule under "Settled at round 2's triage" (amended at round 2's
triage, 58 O7).

Repository guidance sits beside the system it pertains to: a section of
`TESTING.md` or `DEPLOYMENT_AND_CONFIG.md` that pertains to one capability moves to
a guidance file in `openspec/specs/<capability>/`, such as
`openspec/specs/resource-pool-management/testing.md`, whose place gives its
capability. Repository rules spanning several systems sit in small files under
`docs/guidance/repository/`, and the description of the system in the cross-system
documents under `docs/development/` (D25, D27, amended at the return to design).
`AGENTS.md` remains the entry: the layers, where each lives, this repository's own
rules, and its exceptions (D9).

Rejected: keeping every document's name and splitting each into layer parts, which
blocks file-level division for later changes; one file per layer, which defeats
careful context management; one flat `docs/guidance/` for every shared file, which
the owner declined in favour of layer directories as navigation; capability
material left in the large documents under capability headings (D20), which would
move the same sections twice.

### D4 — Tags are frontmatter drawn from a controlled vocabulary

Each guidance file carries its tags in frontmatter (D17), drawn from its layer's
vocabulary table or a lower layer's (D18). Tags need more flexibility than a
directory structure allows: a file can carry a topic, a tool, and its layer at once.
Nothing resolves a tag in this change; `[load]` keeps paths (D5), and the guidance
check is the tags' only reader (D21).

Rejected: the path as the tag, with tool directories and capability headings,
which forces every section into one place; a marker beside each heading, which
runs against file-level division and needs a section extractor in any loader; no
tags until the loader, which would retag what this change moves.

### D5 — `[load]` is re-pointed and may name a directory

`load.common` names `docs/guidance/` as one entry, beside `AGENTS.md`, the
repository's cross-system documents, and `openspec/README.md`; `config load`
expands a directory entry into the Markdown files beneath it, in sorted order, and
the hook and every skill see the expanded list. Every guidance file under
`docs/guidance/` is read by every step, the repository's rules under
`docs/guidance/repository/` included, those `BUILD_AND_PACKAGING.md` and
`RELEASING.md` held among them, which no step loaded before (D27); the description
documents stay listed by path; capability guidance is read with its capability (D22).
Files a reorganization adds or moves within `docs/guidance/` are picked up without
editing the configuration. The expansion selects nothing, so it decides nothing
about the loader. It is a compatible change to a public interface (CW-c2tw).

A directory entry fails closed (design review 19 F3). An entry ending in `/` is a
directory entry, so the name tells a missing directory from a missing file;
`config load` refuses one that is missing, unreadable, or holds no Markdown file,
naming the entry, and the post-compaction hook, which already turns a configuration
error into telling the session its documents are unknown, says so rather than
naming nothing. Literal entries are unchanged, and an absent or empty `load` list
still means no documents, so every existing configuration resolves as before.
Nothing needs a deliberately empty directory: until the last round `load.common`
lists the new files by path.

Rejected: listing every file, which a forgotten entry silently leaves unread;
moving repository documents into per-step lists now, which answers the loader's
question without its design and leaves them out of the hook's re-read; loading by
tag, which is the loader; for a directory entry, allowing an empty directory with a
marker for a deliberate one, which nothing here needs; refusing any entry naming
nothing on disk, literal files included, which changes what a literal entry means
for an adopting repository's existing configuration.

### D6 — Engineering guidance describes private and public repositories

The workflow runs in private repositories as well as public ones, so engineering
guidance describes what may enter a repository of either kind: what holds in every
repository (no credential of any kind; deterministic development fixtures with a
comment; requirements described by the repository's own behaviour), what a public
repository additionally refuses, and what a private one may hold. This repository's
root guidance applies the public case (D9). The private-repository section is the
one piece of new guidance this change writes, limited to what a private repository
may hold that a public one may not. "Cross-references must resolve" splits into an
engineering documentation rule and the workflow's closeout story.

Rejected: a public-only engineering file under a context tag a repository selects,
which treats the private case as absence rather than describing it; assuming a
public repository; keeping everything but credentials in the repository layer.

### D7 — Language and tool rules carry a tool tag

Python, uv, and Helm rules are engineering guidance tagged with a `tool`-kind tag.
Where a rule has a language-neutral principle and a language form, the inventory
splits them into two files, so a repository in another language does not load the
Python form.

Rejected: keeping the Python form inside the neutral file.

### D8 — The workflow's closeout parts in `docs/guidance/workflow/closeout.md`

Every closeout part is workflow material: closeout exists only in the workflow, and
engineering guidance may not cite it. What a part confirms may be a rule of any
layer, and the command it runs is the repository's. The workflow's parts — comment
hygiene, import placement, documentation compliance, narrative compression,
roadmap currency, campaign index currency, promotion, guidance placement (D16),
documentation citations, archival — move to `docs/guidance/workflow/closeout.md`,
each under its own heading, in order, archival last, with the position at which the
repository's own parts run. Roadmap currency is the workflow's because every
adopting repository keeps a roadmap as this one does; the part says "the
repository's roadmap", and this repository's guidance names its path (amended at
round 1's triage, 31 O1f). This repository's parts — packaging and end-to-end
pipeline evidence — move to `openspec/README.md`'s "This repository's closeout
parts", which `AGENTS.md`'s layer table names, so closeout, planning, and review
find them through the root guidance without the workflow naming a repository path.
Citations name parts by heading, never by number, so reordering or a repository's
own parts never break them. `add-skill-extension-points` builds its closeout slot
on this list, and depends on this change for its design.

`closeout.md` names no make target: a part that runs a check says "the repository's
comment checks" or "the repository's guidance check", and this repository's
guidance names each command. The round that moves the list leaves this repository's
parts in `openspec/README.md` under their final heading and adds `AGENTS.md`'s row
naming them at once, so closeout can find them before the root guidance is
rewritten in a later round.

Rejected: the list whole in `openspec/README.md`, tagged, which leaves workflow and
repository material interleaved; dissolving the list beside the rules it confirms,
which breaks the direction rule; leaving the list to `add-skill-extension-points`,
which this change's emptying of `openspec/README.md` rules out.

### D9 — Exceptions sit beside the component they apply to

A repository's exception to shared guidance — selecting a case it leaves open, or
overriding one of its rules — is a row in a table headed "Exceptions to shared
guidance", with the columns `Shared rule | Kind | Here | Reason`, where `Kind` is
`selects` or `overrides`. Work not yet meeting a shared rule is deferred work, not
an exception (amended at round 5's triage, S6 CLI exception). The table sits beside the component it applies to; an
exception spanning several systems, such as this repository's choice of the public
case or the signing credential's environment variable, sits in `AGENTS.md`, which both harnesses keep
in context. Narrowing a shared rule is an ordinary repository rule. The guidance
check validates every table and lists them all (D21). Once engineering guidance
lives outside this repository, an exception has nothing of its own to sit beside,
so it lives in the repository's guidance.

Rejected: an inline note beside each affected rule, which cannot survive the
lift-out and cannot be audited; the workflow configuration, which holds what the
engine runs; a single root table for every exception, which loads every
capability's exceptions into every step; a separate `EXCEPTIONS.md`, which a Codex
session loses at compaction.

### D10 — Large repository documents are treated section by section

D1's test and adjacency apply to every section. `DEPLOYMENT_AND_CONFIG.md`'s
general method moves to engineering with neutral examples, its capability sections
beside their capabilities; overlap with the operator handbook is flagged in the
inventory rather than settled by the agent. A section of a procedure that states
policy rather than a step is classified by D1 like any other, so `RELEASING.md`'s
versioning policy moves to engineering, its repository reasons staying and citing it
(amended at round 1's triage, 31 O1e). The validation runbook is a procedure outside
the guidance set: it carries no frontmatter and no row in `AGENTS.md`'s layer table,
and moves nothing (48 F1). Any uv convention of `BUILD_AND_PACKAGING.md` that holds
anywhere moves out tagged `tool`.

What remains of the five cross-system documents divides by D25's kinds (amended at
the return to design): their description stays in `docs/development/`, their rules
move to `docs/guidance/repository/` (D27), and their procedures move whole to
handbooks. `RELEASING.md` and `BUILD_AND_PACKAGING.md`, which hold no description of
their own once their rules and procedures leave, dissolve.

Rejected: cutting a procedure into pieces filed beside the rules each step touches,
which scatters runbooks nobody follows in pieces; a procedure moves whole to its
handbook, and the validation runbook stays as it is.

### D11 — Skills keep their restatements; the inventory lists them

The skills' citations are re-pointed to the moved guidance and their restatements
stay. Round 1's inventory lists every restatement as a row, as the worklist of the
loader change, which can teach the hook a session's step, name its tagged files,
and answer for harnesses without a hook. Removing restatements changes what agents
are told and needs that reload first.

Rejected: replacing restatements with citations now, wholly or for workflow rules
only, which leaves Codex sessions without the rule after compaction and makes any
compliance regression unattributable inside this move.

### D12 — `docs/prompts/` is left as it is

The prompts are deprecated and inert. They stay untouched and outside the guidance
set: no tags, no row in `AGENTS.md`'s table. Their citations of moved sections go
stale; the citation check checks paths, which remain.

Rejected: removing them, which the owner does not want now; inventorying and
layering them, which would carry superseded text into the new structure.

### D13 — Every check enforcing guidance is classified in `market-change-workflow`'s README

Each check enforcing guidance — comment hygiene, history wording, local imports,
decision destinations, version bumps, the capability and specification indexes,
citations, public content and secrets, the pre-push check, the architecture and
packaging checks, the workflow's default checks, and the guidance check — is a row
in a table in `openspec/specs/market-change-workflow/README.md`'s "This
repository's checks": the rule it enforces, linked to its guidance; that rule's
layer; and where the check runs. The table is repository material citing lower
layers, beside the system that runs the checks. The guidance check enforces
workflow rules and is this repository's script for now; whether it becomes a
workflow default is `extract-change-workflow-repository`'s question. Nothing moves.

Rejected: the classification only in the inventory, lost at archive; in the
guidance files, which the direction rule forbids.

### D14 — Capability deltas

`change-workflow` adds the layer tag (CW-g7lt), the link direction (CW-d2rw),
placement beside the system (CW-p9sa), exceptions (CW-x4ex), directories carrying
no meaning (CW-n6dm), and capability guidance read with its capability (CW-r8cg),
and modifies CW-l7hn for directory entries; its README takes the rationale.
`market-change-workflow` modifies MCW-c4ek to add the guidance check to the closing
checks. `planning-governance` changes no requirement; its Evidence section's
closeout part numbers are re-pointed by hand to part names, outside the archive's
merge, in the round that moves the closeout list, since the citation breaks then. The placement
principles are the workflow's because they govern how the workflow places and reads
guidance.

### D15 — Merges reconcile in-flight work; an anchor check catches what moved

This change resolves what `dev` gains through its merge step, and each change in
flight meets the restructure at its own merge. The guidance check fails on a
citation of a guidance file whose anchor names no heading in it, across the
repository but for the archived changes and `docs/prompts/` (D21), so a
section that moved fails loudly at a change's next pre-commit rather than leaving a
stale citation that resolves only to its file. The moving rounds follow one another
directly, the capability moves last; this change does not wait on the changes in
closeout.

Rejected: relying on merges alone, which leaves stale anchors passing every check;
an anchor check scoped to each change, which leaves existing staleness; a freeze;
scripted moves, which cannot reproduce hand-written splits.

### D16 — A closeout part checks guidance placement

Closeout's "Guidance placement" part, after promotion and before documentation
citations, reads each guidance section the change added, moved, or rewrote since it
branched against the layer test, adjacency, and exception placement; moves what is
misplaced and re-points its citations; and runs the guidance check. A misplacement
needing a decision is reported for the closeout review. A change that touched no
guidance records that. The guidance check also fails on a link from a guidance file
to one tagged with a higher layer, on every commit.

Rejected: the mechanical rule alone, which misses a general rule written with a
market example; leaving placement to the closeout review, which finds without
fixing; an implementation-time check alone, which precedes promotion.

### D17 — The frontmatter is YAML holding `tags`, a layer tag among them

```markdown
---
tags: [engineering, testing, python]
---
```

Every guidance file carries exactly one layer tag. The tag, not the directory,
states the layer, so repository guidance outside any layer directory states its
layer too. YAML follows the skills' `SKILL.md` frontmatter.

Rejected: a separate `layer:` key; TOML frontmatter.

### D18 — Each layer's vocabulary is a Markdown table

```markdown
## Tags

| Tag | Kind | Description |
|---|---|---|
| `engineering` | layer | Holds in a repository that uses neither the change workflow nor OpenSpec |
| `testing` | topic | Test levels, the coverage between them, doubles, and determinism |
| `python` | tool | Python language and library conventions |
```

The engineering and workflow tables sit in their layers' `README.md`; the layer
tags are defined with the layer model. Each layer's table lists its own layer tag as
its first row, as the example shows, so `engineering` is a row of the engineering
table, `workflow` of the workflow table, and `repository` of the repository table in
`docs/guidance/repository/README.md`. The
layer model itself — the test and the link direction — is workflow material, stated
for readers in `docs/guidance/workflow/README.md` and normatively by CW-g7lt and
CW-d2rw; a row naming another layer's word is not a link, so the engineering table's
description of its layer may say what it holds without the workflow. This
repository's table sits in `docs/guidance/repository/README.md`, which `AGENTS.md`
links (D32, amended at the return to design), and lists only tags neither shared
layer has; capability tags are not
listed, since a capability's guidance is located by its directory. A file uses tags
from its layer's table or a lower one. A table reads well to a person and lets a tag
carry further columns later. Round 1's inventory fixes the initial tags; no tag is
created that no file uses.

Rejected: TOML vocabulary files; one shared vocabulary, which splits at lift-out
and lets engineering use a repository tag.

### D19 — Shared files start flat

Each shared layer's files start flat, named by subject. Directories may nest when a
fileset grows too large to navigate, named for their organization rather than after
the tags of the files within.

### D20 — Capability headings in repository documents: superseded

Tagging capability sections by capability-named headings inside the large
repository documents was settled and then superseded by D3: capability guidance
moves beside its capability, so nothing capability-specific remains under such
headings.

### D21 — `make check-guidance`

The guidance set is every Markdown file under `docs/guidance/`; every Markdown file
in a capability's directory under `openspec/specs/` other than its `spec.md`, its
companion (`architecture.md`, or `README.md` in a capability organized by an
index), and its `index.md`, whatever its name and whether or not it is tagged;
every other Markdown file outside `openspec/changes/` carrying `tags` frontmatter;
and the documents `AGENTS.md`'s layer table names, which act as the manual
override. A capability's guidance is found by that rule before its frontmatter is
read, so an untagged capability guide fails the check rather than escaping it
(design review 19 F1). `make
check-guidance` (`scripts/check_guidance.py`), which `make check-repository` calls,
fails on a guidance file with no `tags`; on zero or several layer tags; on a tag in
neither its layer's table nor a lower one; on a table row no file uses; on a
malformed table; on an exception row citing no guidance file or naming an unknown
kind; on a link to a guidance file tagged with a higher layer (D16); and, in any
tracked Markdown file outside the archived changes and `docs/prompts/`, on a
citation of a guidance file — a Markdown link or a quoted path — whose anchor names
no heading in it (D15). Archived changes keep the citations they were written with,
and the deprecated prompts are left as they are (D12). It does not compare a
layer tag with a directory, since directories carry no meaning.
`scripts/check_guidance.py --list [--tag <tag>]` prints each guidance file with its
tags, and `--list-exceptions` every exception row, so a lift-out, the closeout part,
and a later loader read the set without re-implementing it.

Rejected: warning on an unused tag, which lets the vocabulary accrete; no check;
finding capability guidance by its tags alone, which leaves an untagged guide
invisible to the check that should catch it; a fixed list of eligible guidance file
names per capability, which a guide of another name escapes; a manifest of each
capability's guidance files, which is metadata to keep in step with the files.

### D22 — A step reads the guidance beside a capability

Wherever a step reads a capability's specification and companion — design,
planning, implementation, review, triage, merge, closeout — it also reads every
guidance file in the capability's directory, as D21 finds them. Triage reads the
specifications its findings cite before deciding a fix, and merge reconciles them
and the code against both sides (design review 19 F2). Guidance moved beside its capability would
otherwise be read by no step, and exceptions beside a component would never reach
the agent.

Rejected: naming capability files in `[load]`, which needs globs and reloads every
capability's guidance into every step; folding capability guidance into companions.

### D23 — `openspec/config.yaml` stays outside the guidance set

It is configuration the OpenSpec tool reads as one context block. Round 1's
inventory lists its restatements as rows; round 2 onward re-points only what would
go stale.

### D24 — The workflow keeps its tags, minimal and committing to no selection formula

Tags are an expected part of the workflow: CW-g7lt and CW-n6dm stand as written,
every guidance file carrying one layer tag and tags from the vocabulary tables. Which
tags exist, what combination of tags a session about to load guidance can express,
and whether the loader is the workflow's or the repository's, are undecided, and
belong to the loader change. Until it lands every guidance file the repository can
identify is loaded (D5, D22), which nothing in the workflow enforces. The tagging
this change builds is the minimum that keeps the files describable without
constraining that design (D28).

Rejected: the workflow requiring only that each piece of guidance has one layer and
can be reached from what a step loads, the tags becoming this repository's
convention, which makes tags optional for the workflow when they are expected of it;
removing the layers from the workflow as well; deferring every tag question to the
loader, which is this decision's own position on selection, not on the tags
themselves.

### D25 — Repository documents divide into description, rules, and procedures

A document holds one kind of material, placed by the test 58 O5 applies to the
workflow layer:

- **A description of the system** — what it is and why: its shape, authorities,
  vocabulary, flows, and topology. Both the owner and agents read it, so it is
  written once and stays narrative.
- **Rules for work** — what a change here must produce or satisfy; wrong if a
  change's work product were otherwise. They are agent guidance.
- **Procedures** — what the owner or an operator does or types. They live in
  handbooks in `docs/`, without frontmatter and outside the guidance set, beside the
  operator handbook and the change workflow's handbook; an operator's procedure goes
  to the operator handbook (141 F1), the owner's to the owner's handbook,
  `docs/release-handbook.md`, which holds the procedures that publish this
  repository's packages and artifacts. A developer's procedure — running the
  lanes, rendering the charts, qualifying a purchase — goes to the validation
  runbook, `docs/development/VALIDATION_RUNBOOK.md`, already a procedure kept whole
  outside the guidance set (48 F1), or, for running a project's own tests, to that
  project's `README.md`; `openspec/README.md`'s placement table names both
  (amended at 184 F1, which found three such procedures left in a description and
  a rules file for want of a home).

The principle holds in any repository, so it is engineering guidance, in
`docs/guidance/engineering/documentation.md` (D33).

Rejected: leaving the documents as the repository layer, procedures included, which
keeps the owner reading documents shaped for agents and agents loading the owner's
procedures; moving only the procedures out, which leaves rules and description
interleaved and gives D27 no seam; a strict two-way split by reader, which agents
would have to load whole anyway, since they need the description, and which invites
a second copy of it.

### D26 — The split joins this change

D25's split is made by this change, before closeout, rather than by a change of its
own. The anchor check (D15) and the directory entry (D5) it relies on are in place,
the citations are re-pointed once, and the repository layer is finished in the same
change that made the shared ones.

Rejected: a change of its own, opened from an unowned gap row citing D24 and D25,
which would let this change close out and release `add-skill-extension-points` and
`extract-change-workflow-repository` sooner, neither needing the split; moving only
the procedures here, which cuts one decision across two changes; deferring with
nothing recorded but this design.

### D27 — Repository rules are small tagged files under `docs/guidance/repository/`

The repository's cross-system rules become small files, one subject each, under
`docs/guidance/repository/`, carrying `tags` frontmatter with the `repository` layer
tag and tags naming what each covers, as the shared layers' files do; a `README.md`
there describes the layer, how its files are organized, and its tag table (D32). The
description stays in `docs/development/`, one document per topic: `ARCHITECTURE.md`,
`TESTING.md` (the lanes, the canonical deal, the doubles), and
`DEPLOYMENT_AND_CONFIG.md` (the stacks, release topology, persistence), each keeping
its tags and its row in `AGENTS.md`'s layer table so the guidance check and a later
loader find it. `BUILD_AND_PACKAGING.md` and `RELEASING.md` dissolve into rule files
and the owner's handbook (D10 as amended).

```text
docs/guidance/repository/
  README.md                  the layer, its organization, its tag table
  package-layers.md          [repository, architecture, dependencies]
  chart-render-tests.md      [repository, testing, helm]
  migrations-at-startup.md   [repository, persistence, deployment]
  published-packages.md      [repository, packaging, versioning]
  …                          file names and tags provisional; the round's inventory fixes them
docs/development/
  ARCHITECTURE.md            description: overview, authority, vocabulary, flows, topology
  TESTING.md                 description: the lanes, the canonical deal, the doubles
  DEPLOYMENT_AND_CONFIG.md   description: stacks, release topology, persistence
```

Small single-subject files suit whatever selection a loader adopts (D24), and the
description stays a narrative its readers can follow. Directories carry no meaning
(CW-n6dm): the directory is navigation, and `load.common`'s one `docs/guidance/`
entry loads the files without a configuration edit. Every citation of a moved rule
is re-pointed, skills included, the anchor check failing any missed; changes in
flight meet the new layout at their merges (D15).

Rejected: keeping the five documents, each divided into a description part and a
rules part, which leaves whole-document tags no loader can select within; the rule
files under `docs/development/`, which `load.common` could reach only by a directory
entry that also loads the roadmap, the runbook, and the issue-discovery guide, or by
listing each file, which D5 rejected; the description in small files too, which
cuts up a narrative read top to bottom and loaded whole.

### D28 — Tags name what a file covers

A guidance file's tags name what it substantially covers, and content on another
subject goes in another file. No selection formula is assumed: 31 O1c's assumption
that a loader reads a file when a session carries every tag the file carries is
withdrawn (amended at the return to design), and the workflow README's statement of
it is reworded to the descriptive rule. No file is split, widened, or narrowed to
suit a formula; the round's inventory sets each file's tags by this rule, the
capability configuration files holding startup refusals and the contract's
versioning among the rows it decides, and D27 absorbs the split of
`DEPLOYMENT_AND_CONFIG.md` by tag.

Rejected: keeping the conjunctive assumption, which commits the loader's formula
(D24); withdrawing it but freezing today's tags, which leaves tags misdescribing
their files.

### D29 — The draw.io rule is repository guidance in `docs/guidance/repository/diagrams.md`

Diagramming with draw.io is a repository concern: the rule that this repository's
diagrams are drawn in draw.io, the `.drawio` source beside its `.svg` export, moves
from `openspec/README.md`, where 127 O1 placed it for want of a home, to
`docs/guidance/repository/diagrams.md`, tagged `[repository, diagrams]` and linking
the engineering `diagrams.md`. `openspec/specs/change-workflow/diagrams.md` and its
`overrides` row stay beside their capability. Guidance on using draw.io well, such
as keeping its exports small, would be engineering guidance tagged with the tool,
promoted if it is ever written; the repository still states that it draws in
draw.io.

Rejected: leaving it in the OpenSpec guide, which has nothing to do with diagrams.

### D30 — The split is one implementation round before closeout

The change re-enters planning after its design review: new sections before the
closeout section, implemented as one round whose inventory (D34) and moves are
written together and reviewed together. The pre-closeout review and its validation,
owed when the change returned to design, follow that round.

Rejected: an inventory round corrected before any text moves, then the moves, as
rounds 1 and 3 did, which adds a review and validation cycle while two changes wait
to spare what one round costs instead: a row the owner corrects is a fix to a
document move, made in the same triage with the inventory as its map; the session
stopping for the owner on the `Ambiguous` rows before moving them, which pauses the
round for the same correction its triage makes (170 F1, reaffirmed); three rounds,
which add a review cycle while two changes wait.

### D31 — `openspec/README.md` stays beside `openspec/`

This repository's OpenSpec guide stays where it is: a guide to the directory it sits
in, named by `AGENTS.md`'s roles table and the closeout parts' citations. It loses
the draw.io paragraph (D29), and its placement table names each kind's home (D33).

Rejected: moving it into `docs/guidance/repository/` for uniformity alone.

### D32 — `AGENTS.md` names the repository layer's directory and links its tags

`AGENTS.md`'s layer table names `docs/guidance/repository/` and the description
documents, in place of the documents whose rules move; "What every session reads"
gains a repository row beside the engineering and workflow rows (138 O1's pattern);
its "Tags" section moves into `docs/guidance/repository/README.md`, which `AGENTS.md`
links, as each shared layer's README holds its own table (amends 127 O1 and D18).
`load.common` needs no new entry: its `docs/guidance/` entry covers the new files,
and it keeps the description documents by path.

Rejected: keeping the repository's tag table in `AGENTS.md`, which leaves the
repository layer unlike the two shared ones.

### D33 — D25's principle is engineering guidance

`docs/guidance/engineering/documentation.md` states the three kinds of D25. The
workflow README's division between the workflow's specification, guidance, and
handbook (58 O5) links it as its instance, a workflow file linking an engineering
one. `openspec/README.md`'s placement table names the description documents,
`docs/guidance/repository/`, and the handbooks. This is new guidance, reviewed in the
round's triage (31 O1b).

Rejected: stating the principle only in the workflow README, which D1's test places
in engineering, since it holds without the workflow.

### D34 — The round inventories what it moves

The round's inventory gives every section of the five cross-system documents its
kind (D25), destination, and tags (D28), with an `Ambiguous` column for each row the
test did not decide — `ARCHITECTURE.md`'s package layers, which mix description and
rules sentence by sentence, the known case. It is written before the text moves and
reviewed with the moves in the round's triage (D30); a row the owner corrects there
becomes a fix to the move. Operator procedures go to the operator handbook (141 F1),
and a non-guidance document contradicting moved guidance is brought in line (31 O1b).

Rejected: moving without an inventory, which leaves the move as the only thing to
review (D2).

### D35 — No requirement or code changes

CW-g7lt, CW-d2rw, CW-p9sa, CW-n6dm, and MCW-c4ek already cover files under
`docs/guidance/repository/`. The guidance check finds them by place under
`docs/guidance/` and reads a vocabulary from the table under a "Tags" heading in any
guidance file (`scripts/check_guidance.py`, `read_guidance`), so moving the
repository's table (D32) needs no code change. The round's only code edits follow
the documents that dissolve (D10 as amended): `scripts/tests/test_publish_matrix.py`
reads the published-package table from its file under `docs/guidance/repository/`,
and the packaging checks' docstrings and messages, which name
`BUILD_AND_PACKAGING.md`, name the files that hold their conventions.

### Settled at round 1's triage

The owner settled these while correcting the inventory; the inventory's "Rules from
round 1's triage" applies them row by row.

- **31 O1a — General rules stated in this repository's terms.** Guidance compatible
  with other systems of its kind is engineering, moved with a neutral example, even
  where many repositories have no clients or no end-to-end tests; the repository's
  statement stays as its instance and cites it. A description of this system — its
  architecture, one capability's mechanism, a workaround tied to its environment —
  stays repository material, or goes to the capability's companion. A form that
  differs by language is a matter of tagging, not layering.
- **31 O1b — Deduplication, reviewed.** The change deduplicates the guidance. Copies
  that agree merge into one home. Where copies differ, or a merge would change what
  the guidance says, the section moving them proposes one text and lists the pair,
  and that round's triage reviews both forms with the owner; no change to what
  guidance says is assumed. The operator handbook, the runbook, and other
  non-guidance documents do not move, but are brought in line where the decided
  guidance contradicts them. No change-index row records the pairs.
- **31 O1c — Tags are atoms.** There are no compound tags. A file's tags name what it
  covers, and content on another subject goes in another file; the assumption that a
  later loader reads a file when a session carries every tag the file carries is
  withdrawn, no selection formula being assumed (D28, amended at the return to
  design). A tool a developer, build, or
  deployment runs has a tool tag; a library code imports carries its language's tag.
  "This repository uses X" is repository material; how to use X well is engineering
  tagged X, for any X. The loader change decides how tags select.
- **31 O1d — Multi-capability sections.** A section goes beside the capability whose
  specification owns what it governs, not the service that reads or enforces it;
  parts with different owners split where they separate cleanly, and otherwise stay
  cross-system; a capability-named example of a shared rule stays with the rule.
- **31 O1e — Exceptions and the diagram case.** "Amend a rule or comply" is reworded
  as a framework for when an exception is expected: once guidance is shared and
  other repositories change it, "never" is too strong, while the rule's purpose —
  stopping an owner from declaring everything an exception — stays. Section 4 drafts
  the wording and its triage reviews it. The change workflow's hand-laid graph is a
  temporary `overrides` row against the diagrams rule, until the "Current limits"
  bullet on generating it closes; the row sits beside the capability it applies to,
  in a new guidance file `openspec/specs/change-workflow/diagrams.md`, as CW-x4ex
  requires (48 F2).
  `agents/domain.md` is removed once its rows move.
- **31 O1f — The roadmap and the capability index.** Every adopting repository keeps
  the roadmap and the OpenSpec change organization this repository uses, so the
  roadmap's role, the capability index's role, and what goes to each are workflow
  material; their paths and contents are this repository's (D8 amended). Scripts and
  checks stay where they are: moving them is `extract-change-workflow-repository`'s.
- **31 O1g — Within a layer.** Each row keeps the file its layer gives it, with two
  rows the rules above decide: the principle that work is not complete because its
  own suites pass is engineering testing guidance (31 O1a), and the operator-control
  rule splits into a production half in `implementation.md` and a test half in
  `test-seams.md` (31 O1c).
- **29 F1 — The project layout.** `BUILD_AND_PACKAGING.md`'s "Project layout" splits
  into its Python rules, its uv rules, its Hatchling form (each engineering, tagged
  with its tool), and this repository's selection of Hatchling, which stays.

### Settled at round 2's triage

The owner settled these at the triage of round 2, the workflow layer; the owner
reviews the layering by hand before round 3.

- **58 O5 — The workflow's specification, its guidance, and its handbook.** Within
  the workflow layer, a statement is placed by what it constrains. The
  specification states what the workflow does — its steps, exits, records, and the
  engine's commands and interfaces — as requirements the engine and the skills are
  held to, and its companion explains how and why. The guidance states what whoever
  works a change must produce or satisfy — what a design, a plan, a task note, a
  comment, or a closeout must contain — rules applied by judgement and read by every
  step. The handbook tells the owner how to operate the workflow. The test: wrong if
  the engine or a skill behaved otherwise, the specification's; wrong if a change's
  work product were otherwise, guidance; telling the owner what to do or type, the
  handbook's. `docs/guidance/workflow/README.md` states the rule. Rejected: the
  workflow's guidance beside its capability, which CW-r8cg would have read only with
  that capability while every step needs it; the guidance as normative
  requirements, in a document no step loads.
- **58 O7 — The operator handbook.** The workflow's guide is the change workflow's
  operator handbook (D3 as amended): not guidance, so no frontmatter and no place in
  the guidance set; it holds what the owner needs to know and nothing workflow agents
  need; it sits beside the other handbooks in `docs/`. What agents need of it moves
  by O5's rule — what the workflow does to the specification or its companion, what
  a change's work must produce to `docs/guidance/workflow/` — and its citations are
  re-pointed to where each statement lands. Diagrams serve a human reader more than
  an agent, so the handbook embeds the workflow's diagrams; they may stay in
  `openspec/specs/change-workflow/diagrams/`, linked from the handbook. Rejected:
  keeping the guide whole and tagged `workflow` as a procedure (D10's reasoning),
  which leaves agent-facing rules in an owner's document; splitting only its rule
  sections into guidance.
- **58 O6 — Closeout's parts name the rules they confirm by layer.** Every part stays
  the workflow's (D8). Each part names and links the rules it confirms, each to its
  own layer's file — engineering to `docs/guidance/engineering/`, the workflow's own
  to `docs/guidance/workflow/`, the repository's by role — and "Documentation
  compliance" confirms the permanent documents a change wrote against the
  engineering rule that documentation describes the current system, besides
  placement. Rejected: a separate "Documentation currency" part, which lengthens the
  list every plan and the closeout skill carry; leaving the current-state rule
  confirmed by no part.
- **58 O3 — Guidance reads as timeless.** Permanent documentation and guidance
  describe the system they apply to declaratively, with no wording relative to a
  migration or a planned change, even while they change constantly;
  `engineering/documentation.md` states it.

### Settled at round 2's repeat triage

The owner settled these at the triage of review 72, their notes 71, and the
orchestrating session's observations 73, on the workflow layer's fixes and re-plan.

- **72 F1 — Section 3's differing pairs.** The owner reviewed the pairs section 3
  listed under 31 O1b and accepted each as written: the permanent documents are
  written at closeout, after the code's last review, and "implemented" no longer
  includes them; Implement's and the checklist's completion lists are one list; the
  citation check runs after promotion; and the move's smaller neutralizations stand.
- **72 F2 — A proposed home for an agent rule with none.** A statement of the guide
  that tells an agent what to do, that no requirement states and that is no
  explanation, is given a proposed home — a requirement in this change's
  `change-workflow` delta, or the workflow's guidance, by 58 O5's test — which the
  round's triage reviews with the owner, as 31 O1b's differing pairs; the handbook
  cites it. The skills' restatement rule (the guide's "Skills") is the known case.
  Rejected: stopping section 3 until each such rule is settled, which an unattended
  session cannot ask and which splits the handbook over another return; retiring
  such rules, which shrinks the contract the skills rely on.
- **71 O1 — Closeout changes only inert paths, and inert paths have a default.**
  CW-pkug states closeout's rule in the repository's inert paths rather than
  "documentation", which the workflow never defined: closeout changes only inert
  paths and changes' records, and a part needing any other change returns the change
  to implementation. The rule then matches what archive cleanup already exempts from
  validation (CW-trdu), which reads only what changed after the closeout review's
  commit, so closeout's own commit is never validated. CW-n7ra gains a default for a
  repository that declares none, `openspec/` and every Markdown file (`**/*.md`); a
  declaration, an empty one included, replaces it. This repository keeps its
  declaration and adds `AGENTS.md`, root guidance that closeout's guidance
  placement may edit and that no validation proves anything about. A consequence:
  closeout no longer re-points a citation inside a skill or a docstring; that
  returns the change to implementation. Rejected: keeping "documentation only",
  which leaves the term undefined and a non-inert closeout edit unvalidated;
  deferring it to a later workflow change while this one rewrites `closeout.md`.
- **73 R1 — Routing observations.** That an owner's notes on a returned triage's
  fixes and re-plan have no triage short of another review, and that an
  owner-directed review's exit to triage is passed over while the agreed round's
  sections are open, are workflow maintenance the owner revisits after this change
  merges; neither is this change's.

### Settled at round 3's triage

The owner settled these at the triage of review 86, validation 87, and their notes
88, on section 3's re-run, the operator handbook.

- **72 F2 — The proposed homes kept.** Every home section 3 proposed stands: CW-s7rq,
  CW-b5cf, CW-e3gt, CW-o9hd, CW-t2lw, and CW-w6vy in the `change-workflow` delta;
  `changes.md`'s "One change per branch" and `working-model.md`'s `Owed by
  validation:` line in the guidance. The guide's engine details stay the companion's,
  not requirements, since they describe how the engine works rather than a rule a
  step follows; the refusals of `round-view`, `round-done`, and `change-clone-remove`
  stay in the handbook as what the owner meets running the commands.
- **71 O1 — The archive's own writes are exempt.** Under an empty `inert-paths`
  declaration no path is inert, so CW-pkug as first amended would have returned every
  archive to implementation, which cannot archive: a loop with no exit. CW-pkug
  exempts the archive's own writes — the change's own documents and their move into
  the archive, its row of the change index, and its deltas merged into the
  specifications — as it exempts changes' records, and CW-n7ra's empty declaration
  names both exemptions; the merge transcribes delta text already validated and
  reviewed with the change's commits. The change's documents and its index row are
  included because closeout writes its task notes and the row as it archives, and
  the engine's changes' records are only the ledger and `reviews/`.
  Promotion elsewhere follows the declaration, and under an empty one returns to
  implementation, where it is validated. Rejected: accepting that an empty
  declaration makes closeout impossible; making `openspec/` inert whatever the
  declaration, which contradicts "an empty one included" and changes every commit's
  hook tier; validating closeout's commit at archive cleanup, which reverses 71 O1's
  reasoning and changes the engine, a workflow change of its own.
- **88 O2 — The handbook cites no requirement id** (revises 72 F2 for the handbook).
  The handbook's reader is the owner, to whom a bare id says nothing; the handbook
  describes the system well enough that the owner need not open the specification,
  and its introduction links the specification, its index, and the companion once as
  the authority. The traceability 72 F2 wanted is the inventory's, whose rows map
  each statement of the guide to its home. Rejected: ids turned into links, which
  still interrupt the prose.
- **88 O1, O3, O4 — The handbook in the order the owner needs it.** An introduction
  saying what the workflow is and why; a table of contents; orchestrating a change —
  starting it, the normal course of a change and what it asks of the owner, reading a
  round, triage, then the interventions, common before rare; parallel changes and
  where they contend, with the state diagram; the steps — the graph, the step table
  with how to run each alone, and a paragraph per step on its responsibility, entry,
  and exits; the state written to disk, for intervening by hand; the engine, with
  its parts diagram; and customization. Fixed in the triage session, on the owner's
  word, rather than by re-running section 3.
- **100 F1 (round 3's repeat pass) — The handbook's opening states where the workflow
  stops.** By the owner's choice it describes the whole lifecycle through the merge:
  archive cleanup ends the workflow, drafting the merge commit message and pull
  request description and then copying the history; the orchestrating session opens
  the pull request; its review and merge are the owner's; validation runs wherever a
  later step relies on the change's commits. Replaced: an opening saying validation
  runs before every review and that the workflow reaches a merged pull request,
  neither true.
- **98 R1 — Validation starting waived parts before finding the waiver.** Deferred by
  the owner, with 73 R1, to workflow maintenance after this change merges; validation
  158 met the same case (the seq 113 waiver held, the parts ran needlessly).

### Settled at round 4's triage

The owner settled these at the triage of review 109, validation 110, and their notes
111, on sections 4 and 5, the engineering layer.

- **111 O4 — `AGENTS.md` restates no shared rule** (sharpens D3). The entry holds the
  layer table, each shared layer's README linked for its files, this repository's
  guidance documents, its tags, its exceptions, and its own rules; each repository
  rule states only what is particular here and links the shared rule it applies by
  name, never paraphrasing it. Rejected: a one-line-per-file index of all guidance,
  which would survive a Codex review's compaction but grows with every file,
  duplicates the layer READMEs, and repeats what `load.common` already loads;
  keeping summaries of a few rules, which leaves arbitrary which rules survive
  compaction.
- **111 O2 — The cross-system documents are the repository layer, stated so.** Each
  document's opening states what it holds as the repository layer, and each instance
  links its shared rule without paraphrasing it (O4's rule). The owner's revisit
  before the pre-closeout review divided them by D25's kinds, the rules moving to
  `docs/guidance/repository/` in this change (D25 to D27).
- **111 O1 and O3 — No list of guidance files kept by hand.** The assumptions test
  reads a directory the guidance documents' provision names, ending in `/`, as
  providing every Markdown file beneath it, as D5 reads a directory entry, so
  `market-change-workflow`'s provisions row names `docs/guidance/` rather than each
  file; a directory any other provision names provides only itself, so the test
  still checks every other path a skill names; `load.common` collapses to the same entry
  at task 9.3, as D5 planned.
- **Sections 4 and 5's differing pairs (31 O1b, 31 O1e).** Accepted as section 4's
  and section 5's notes write them: integration's three forms in `test-levels.md`,
  the merged test-double and dependency statements, the End-to-end pipeline part's
  one sentence, `rules.md`'s exceptions framework, and the wording each section
  listed. `system-tests.md` adds that an observation is never inferred from another;
  the runbook's other two qualification rules stay its own.
- **109 F1 — The packaging rule is against aggregate lists.** A project's manifest
  declares what it imports; nothing else lists internal packages. Rejected: an
  exemption appended to the absolute form.
- **109 F2 — A contract fixture waits for its producer's test.** The dormant
  validator is dropped, with its Python form, no tracked code using one. Rejected: keeping it as a stated
  temporary exception.
- **Inventory row 384 — No `implementation-python.md`.** The route pattern's package
  split has no reason particular to Python, so the pattern is `implementation.md`'s
  alone (D7).

### Settled at round 5's triage

The owner settled these at the triage of review 126, validation 126, and their notes
127, on section 6, the repository layer at the root and across systems.

- **127 O1 — `AGENTS.md` holds what can be nowhere else** (sharpens D3 and 111 O4).
  That the repository works its changes through the change workflow, and where its
  specification, handbook, skills, and configuration are; what every session reads,
  workflow session or not, `docs/guidance/` named as one directory; where each
  layer's guidance lives, each shared layer's README saying how its files are
  organized and which tags it defines; the repository's tags and its exceptions
  spanning systems; and its rules for any agent's actions here whatever the task —
  what enters the repository and how it is pushed, where deferred work and terms go.
  A topic's repository instance is in the repository's guidance for its topic, and a
  check's scope beside the check: the `deploy-local` rule, the packaging checks, and
  draw.io in their files under `docs/guidance/repository/` (D27, D29, amended at the
  return to design), the comment and citation checks' scopes in
  `market-change-workflow`'s README. The draw.io rule will be declared again by the extracted
  engine's own repository guidance; it is read once in each repository. Rejected:
  removing only the pure pointers, which leaves the line to judgement.
- **126 F1 — A chosen list is not a copy.** `packaging.md` forbids what builds,
  locks, or installs from copying the manifests and locks; a list choosing packages
  for a purpose of its own, such as the published set, is kept where the choice is
  made, and a document repeating the manifests for its reader is checked against
  them. Rejected: generating the release guide's dependency column and the
  publication set, which changes the release process.
- **S6 CLI exception — Tech debt is no exception.** Work not yet meeting a shared
  rule is deferred work, an OpenSpec change or a roadmap gap, never an exceptions
  row: the CLIs' test seams leave `AGENTS.md`'s table, `TESTING.md` naming the gap.
  A reviewer's list of known divergences would come better from metadata on the
  change or gap than from a second hand-kept list. Rejected: a temporary-exception
  sentence in `rules.md`, which would record tech debt in two places.
- **Section 6's differing pairs (31 O1b).** Accepted as section 6's notes write them
  (rows 148, 167, 497, 575, `clobber-wheels`, and the paraphrase sweep); the runbook's
  section 25 brought in line with `TESTING.md` on adoption (row 484), which the
  adoption helper confirms; the roles table kept apart from the layer table, since
  the roadmap is no guidance; no `checks` tag, which no file carries.
- **S6 tag reach.** `RELEASING.md`'s artifact destination is packaging; the revisit
  settled tag reach as D28, D27 absorbing the split of `DEPLOYMENT_AND_CONFIG.md`.

### Settled at round 6's triage

The owner settled these at the triage of review 141, validation 142, and their notes
138 and 143, on section 7, the repository layer beside each capability.

- **141 F1 — An operator's procedure goes to the handbook, and another capability's
  rule beside that capability** (applies CW-p9sa and `openspec/README.md`'s
  placement table; corrects inventory row 578). The settlement configuration's
  production cutover sequence is the operator handbook's, under "Upgrading a
  deployment", linked from the two capability guides whose migrations it runs; the
  publication migration is `storefront-publication`'s; the VM storefront's retired
  inventory keys sit with its retired-settings list in `DEPLOYMENT_AND_CONFIG.md`.
  Rejected: the whole migration narrative in the handbook, which would put the
  capabilities' refusal rules in an operator document; and leaving row 578's
  placement, which hides the sequence from the operators who run it.
- **138 O1 — "What every session reads" names each shared layer** (amends 127 O1's
  "`docs/guidance/` named as one directory"). The table has an engineering row and a
  workflow row, each linking its layer's README; `load.common` keeps D5's one
  `docs/guidance/` entry, and task 9.3 checks that the two name the same files.
  Rejected: `load.common` naming the two directories, which would make a new
  directory under `docs/guidance/` need a configuration edit, against D5's reason.
- **Section 7's differing pairs (31 O1b).** Rows 550 and 565, 570, 571 kept; the
  handbook's payments step table gains the two conditions it lacked. The API-credit
  services' own state stays in `DEPLOYMENT_AND_CONFIG.md`'s "Stateful service
  persistence". `AGENTS.md`'s sentence on capability guidance, for sessions outside
  the workflow, stays (127 O1). Wider tags on the configuration files are set by
  D28's rule in the round D30 adds; `guidance-review` reads no capability guidance,
  being outside D22's seven skills.

### Settled in implementation

The owner settled these at the triages of round 7 (review 157, validation 158, notes
159, on sections 8 and 9) and round 8 (review 176, validation 177, notes 178, on
sections 10 to 13), or let them stand when presented.

- **157 F1 — The guidance check excludes only the capability's companion.** The
  companion is `README.md` beside an `index.md` and `architecture.md` otherwise, as
  CW-r8cg and D21 say, so an indexed capability's `architecture.md` is guidance and is
  checked. Rejected: a shared capability-document helper, since no other code
  classifies the companion.
- **The guidance check's and the loader's limits, presented at round 7 and kept.** The
  check reads no setext headings, block quotes, or HTML comments, which no guidance
  file uses; an exception row may cite any guidance file, as MCW-c4ek words it,
  CW-x4ex's "shared guidance" left to the owner; and a `[load]` directory entry
  resolving outside the repository has no guard, since none is named and CW-l7hn asks
  nothing of it. The owner raised none.
- **Section 11's differing pair — a locally verifiable scenario.**
  `docs/guidance/repository/deal-scenarios.md` takes `ARCHITECTURE.md`'s form over
  `TESTING.md`'s: the payments service and the dispute authority are both replaced by
  the in-lane doubles, and an external-topology scenario making a deal extends a
  locally verifiable one, since every lane runs the mediation double. No finding at
  round 8 raised it.
- **176 F1 — The hook-merging criterion is a repository rule.** `ARCHITECTURE.md`'s
  criterion for when domain hooks may be merged states a rule for a future design
  choice, so it moved to `production-code.md`, "Domain hooks", linking
  `market-composition`'s "Typed phase boundaries" for the reasoning. Rejected:
  generalizing it into `implementation.md`, new shared guidance needing its own
  review. `TESTING.md`'s gate passages and `DEPLOYMENT_AND_CONFIG.md`'s
  release-topology sentences stay as description, each describing behaviour a check
  or the chart holds; closeout's documentation compliance re-checks them.
- **178 O1 — `dev`'s packaging and release changes mapped, not moved.** The inventory's
  "Dev's packaging and release changes, for the merge" classifies what `dev`'s
  `publish-wheels-through-a-gate` wrote in the documents this change splits, by kind
  and destination here, what it overturns here, and the portable rules it suggests;
  the merge places `dev`'s text from it. Rejected: leaving the whole placement to the
  merge; writing the portable rules into the engineering layer now, which would
  contradict this branch's CI publishing until the merge.
- **178 O2 — The published-packages table's future is outside this change.** No process
  reads it: two tests hold it equal to the workflow's table and the manifests.
  Dropping it and its tests is code beyond D35, so it is an unowned row under the
  package and release readiness campaign in `openspec/changes/README.md`.

### Settled at the closeout review's triage

The owner settled these at the triage of closeout review 196, on placements closeout's
14.10 reported.

- **196 F1 — Operator steps leave the capability guidance and the description.** The
  payments-mode cutover's steps and the rollback past pool constraints went to the
  operator handbook ("Changing the payments service mode", "Rolling back past pool
  constraints"), the capability guides keeping the behaviour they rest on;
  `DEPLOYMENT_AND_CONFIG.md`'s migration-check table lost its "Remedy" column, which
  restated "Upgrading a deployment". `introduction-delivery`'s re-delivery commands,
  `settlement-configuration`'s legacy-override rule, and the `pool-override` flags
  stay, as description and a rule.
- **196 F2 — The registry's profile and chart material sits beside
  `deployment-state`.** Its requirement "The registry reads profile-shaped env files"
  governs it, so the paragraphs moved to `deployment-state/configuration.md`, the
  descriptor settings and the umbrella alias staying in `registry-discovery`.
  Rejected: moving the requirement to `registry-discovery`, a change to a
  specification beyond D35; placing the rest of 14.10's list here, each needing a
  reading of its own, so it is an unowned row in `openspec/changes/README.md`.

### Implementation cadence

A review round per layer, so each layer is reviewed by itself, and the code last,
since a check written before the guidance complies with it cannot be validated
against it:

1. **The inventory.** The full inventory, with its `Ambiguous` column, its
   restatement rows (D11, D23), and the check classification draft (D13). No text
   moves. Its triage corrects the rows. One round, two sessions: the root and
   workflow documents (`AGENTS.md`, `openspec/README.md`, `docs/agents/`,
   `ARCHITECTURE.md`), then the large repository documents, `openspec/config.yaml`,
   and the skills' restatements.
2. **The workflow layer.** `docs/guidance/workflow/` with its table, `closeout.md`
   with the guidance placement part, workflow material out of `AGENTS.md`,
   `openspec/README.md`, and `agents/change-workflow.md`, and every citation
   of what moved, skills included. One session.
3. **The engineering layer.** `docs/guidance/engineering/` with its table and
   neutral examples, engineering material out of `AGENTS.md`, `ARCHITECTURE.md`,
   `TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`, `BUILD_AND_PACKAGING.md`, and
   `RELEASING.md`'s versioning policy (D10 as amended), and its citations. One
   session, over two sections the plan cuts — the testing files and the rest — since
   round 1's inventory gives the layer forty files.
4. **The repository layer at the root and across systems.** `AGENTS.md` rewritten
   (its layer table, repository tags, exceptions, closeout-parts row),
   `openspec/README.md` as this repository's guide with its closeout parts, the
   cross-system documents' frontmatter, and D13's table. One session.
5. **The repository layer beside each capability.** Capability sections moved
   beside their capabilities, the skills' reading lists (D22), and their citations.
   One session.
6. **The code.** `make check-guidance` with its rules and listings, wired into
   `make check-repository`; `[load]` directory entries; `load.common` collapsed to
   `docs/guidance/`; and fixes to whatever the check finds in the guidance. One
   session.

7. **The repository documents by kind** (D25 to D34, added at the return to
   design). One round, after the code and before closeout: the inventory of the five
   cross-system documents by kind, then the moves it gives — the rule files under
   `docs/guidance/repository/` with their README and the repository's tag table, the
   description documents reduced, `BUILD_AND_PACKAGING.md` and `RELEASING.md`
   dissolved, the owner's handbook and the operator handbook's procedures, the
   draw.io rule, `documentation.md`'s three kinds and the workflow README's tag
   wording, `AGENTS.md`, `openspec/README.md`'s placement table, and every citation of
   what moved, skills included. The inventory and the moves are reviewed together
   (D30). The pre-closeout review follows.

Until round 6, each round adds the guidance files it creates to `load.common` by
path, so later sessions on the branch read them. Rounds 2 to 5 follow one another
directly (D15).

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1, the layers, their test, and the link direction | `openspec/specs/change-workflow/spec.md`, CW-g7lt and CW-d2rw; `openspec/specs/change-workflow/README.md#the-repositorys-guidance-is-layered`; `docs/guidance/workflow/README.md#the-layers-of-guidance` |
| D2, the inventory | none: change history (`inventory.md`) |
| D3, shared guidance under `docs/guidance/`, repository guidance beside its system, the workflow's guide as its handbook | `openspec/specs/change-workflow/spec.md`, CW-p9sa; `openspec/specs/change-workflow/README.md#the-repositorys-guidance-is-layered`; `openspec/README.md#documentation-placement`; `AGENTS.md#where-the-guidance-lives`; `docs/guidance/workflow/README.md#what-the-workflows-guidance-holds`; `docs/change-workflow-handbook.md` |
| D4, frontmatter tags | `openspec/specs/change-workflow/spec.md`, CW-g7lt; `openspec/specs/change-workflow/README.md#the-repositorys-guidance-is-layered` |
| D5, `[load]` directory entries | `openspec/specs/change-workflow/spec.md`, CW-l7hn; `openspec/specs/change-workflow/README.md#inert-paths-and-the-documents-a-step-loads` and its "Current limits" bullet on `[load]`; `.agents/workflow.toml` |
| D6, private and public repositories | `docs/guidance/engineering/repository-content.md`; `AGENTS.md#exceptions-to-shared-guidance`; `openspec/specs/change-workflow/README.md#the-repositorys-guidance-is-layered` |
| D7, tool tags | `docs/guidance/engineering/README.md#tags` |
| D8, the closeout parts by layer | `docs/guidance/workflow/closeout.md`; `openspec/README.md#this-repositorys-closeout-parts`; `AGENTS.md#where-the-guidance-lives`; `openspec/specs/planning-governance/spec.md#evidence`; `openspec/specs/change-workflow/README.md#closeout-and-archival`; `.agents/skills/change-closeout/SKILL.md` |
| D9, exceptions | `openspec/specs/change-workflow/spec.md`, CW-x4ex; `openspec/specs/change-workflow/README.md#the-repositorys-guidance-is-layered`; `AGENTS.md#exceptions-to-shared-guidance`; `docs/guidance/engineering/rules.md#when-an-exception-is-expected` |
| D10, the documents section by section | none: the documents themselves |
| D11, the skills' restatements | none: the inventory's restatements table, for the loader change; CW-s7rq holds the restatement rule |
| D12, `docs/prompts/` | none: left as it is |
| D13, the checks' classification | `openspec/specs/market-change-workflow/README.md#what-each-check-enforces` |
| D14, the capability deltas | `openspec/specs/change-workflow/spec.md` and `index.md`, "The repository's guidance" under "5. The public surface", CW-l7hn's and CW-n7ra's summary lines; `openspec/specs/market-change-workflow/spec.md` and `index.md`, MCW-c4ek's summary line |
| D15, the anchor check | `openspec/specs/market-change-workflow/spec.md`, MCW-c4ek; `openspec/specs/market-change-workflow/README.md#the-closing-checks` |
| D16, the guidance placement part | `docs/guidance/workflow/closeout.md#guidance-placement`; `.agents/skills/change-closeout/SKILL.md`; `openspec/specs/change-workflow/README.md#closeout-and-archival`; MCW-c4ek for its mechanical rule |
| D17, the frontmatter | `openspec/specs/change-workflow/spec.md`, CW-g7lt; `docs/guidance/engineering/README.md` |
| D18, the vocabulary tables | `docs/guidance/engineering/README.md#tags`; `docs/guidance/workflow/README.md#tags`; `docs/guidance/repository/README.md#tags` |
| D19, flat files | `openspec/specs/change-workflow/spec.md`, CW-n6dm; `openspec/specs/change-workflow/README.md#the-repositorys-guidance-is-layered`; `docs/guidance/workflow/README.md#how-the-files-are-organized` |
| D20 | none: superseded by D3 |
| D21, `make check-guidance` | `openspec/specs/market-change-workflow/spec.md`, MCW-c4ek; `openspec/specs/market-change-workflow/README.md#the-closing-checks` and `#what-each-check-enforces`; `openspec/README.md#the-checks-the-workflows-parts-run-here` |
| D22, capability guidance read with its capability | `openspec/specs/change-workflow/spec.md`, CW-r8cg; `openspec/specs/change-workflow/README.md#the-repositorys-guidance-is-layered`; the seven skills that read a capability's specification |
| D23, `openspec/config.yaml` | none: unchanged in kind |
| D24, tags committing to no selection formula | none: CW-g7lt stands; the open loader question is `openspec/specs/change-workflow/README.md#current-limits` and the lesser goal's gap row in `openspec/changes/README.md` |
| D25, description, rules, and procedures | `docs/guidance/engineering/documentation.md#a-document-holds-one-kind-of-material`; `docs/guidance/workflow/README.md#what-the-workflows-guidance-holds`; `openspec/README.md#documentation-placement`, its developer's-procedures row (184 F1) |
| D26, the split in this change | none: scope |
| D27, the repository's rules under `docs/guidance/repository/` | `docs/guidance/repository/README.md`; `AGENTS.md#where-the-guidance-lives`; `openspec/README.md#documentation-placement`; the openings of `docs/development/ARCHITECTURE.md`, `TESTING.md`, and `DEPLOYMENT_AND_CONFIG.md` |
| D28, tags name what a file covers | `docs/guidance/workflow/README.md#the-layers-of-guidance`; `docs/guidance/engineering/README.md#tags`; `openspec/specs/change-workflow/README.md#the-repositorys-guidance-is-layered` |
| D29, the draw.io rule | `docs/guidance/repository/diagrams.md` |
| D30 | none: the round's place in the change |
| D31 | none: `openspec/README.md` stays where it is |
| D32, `AGENTS.md` and the repository's tags | `AGENTS.md#what-every-session-reads` and `#where-the-guidance-lives`; `docs/guidance/repository/README.md#tags` |
| D33, D25's principle as engineering guidance | `docs/guidance/engineering/documentation.md#a-document-holds-one-kind-of-material`; `openspec/README.md#documentation-placement` |
| D34 | none: the round's inventory is change history |
| D35 | none: no requirement or code changes |
| 72 F2, the guide's agent rules given homes | `openspec/specs/change-workflow/spec.md`, CW-s7rq, CW-b5cf, CW-e3gt, CW-o9hd, CW-t2lw, CW-w6vy, and their `index.md` entries; `docs/guidance/workflow/changes.md#one-change-per-branch`; `docs/guidance/workflow/working-model.md#plan` |
| 71 O1, closeout in inert paths and the default inert paths | `openspec/specs/change-workflow/spec.md`, CW-pkug and CW-n7ra, and their `index.md` lines; `openspec/specs/change-workflow/README.md#closeout-and-archival` and `#inert-paths-and-the-documents-a-step-loads`; `docs/guidance/workflow/closeout.md`; `.agents/workflow.toml` |
| 184 F1, a developer's procedures in the runbook or a project's README | `openspec/README.md#documentation-placement`; the moved steps in `e2e-tests/README.md`, `docs/development/VALIDATION_RUNBOOK.md`, and `docs/operator-handbook.md#storefront-configuration-under-helm` |
| Roadmap currency | none owed: `docs/development/ROADMAP.md` names no goal or gap this change touches; the lesser goal lives in the change index |
| Campaign index currency | `openspec/changes/README.md`: this change's row; the lesser goal's current-state paragraph rewritten for the layered guidance, and its gap row narrowed to loading by tag, the skills' restatements, moving a layer out, and citing guidance held elsewhere, each unowned |

## Open Questions

None. Loading by tag — which tags a session carries, how they select files, and
whether the loader is the workflow's or the repository's (D24) — removing the
skills' restatements, moving a layer out of the repository, and citing guidance held
outside it are later changes, recorded as the lesser goal's unowned gaps.
