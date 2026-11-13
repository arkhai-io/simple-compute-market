# Design: layer engineering guidance

Status: design settled and reviewed; design review 19's findings are settled in D5,
D21, and D22. Round 1's triage amended D8 and D10 and settled the decisions under
"Settled at round 1's triage". Round 2's triage amended D3 and settled the decisions
under "Settled at round 2's triage".

## Context

- **The documents and their size.** About 8,900 lines:

  | Document | Lines | Read by every step (`load.common`) |
  |---|---|---|
  | `AGENTS.md` | 242 | yes, and always in context through `CLAUDE.md` |
  | `docs/development/ARCHITECTURE.md` | 1,315 | yes |
  | `docs/development/TESTING.md` | 1,793 | yes |
  | `docs/development/DEPLOYMENT_AND_CONFIG.md` | 2,148 | yes |
  | `openspec/README.md` | 171 | yes |
  | `docs/development/BUILD_AND_PACKAGING.md` | 216 | no |
  | `docs/development/VALIDATION_RUNBOOK.md` | 1,557 | no |
  | `docs/development/RELEASING.md` | 281 | no |
  | `docs/agents/` (`change-workflow.md`, `domain.md`) | 1,024 | no |
  | `docs/prompts/` (five files) | 172 | no |

  Every step reads 5,669 lines through `load.common`; design adds `ROADMAP.md`.
  Most of `TESTING.md` and `DEPLOYMENT_AND_CONFIG.md` is market material most steps
  never use.
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
  `openspec/README.md#plan-closeout-requirements`, many by part number.
  `scripts/check_doc_citations.py` checks that a cited path exists, not its anchor.
- **Checks that enforce guidance.** Comment hygiene, history wording, local
  imports, decision destinations, version bumps, the capability and specification
  indexes, citations, public content and secrets, the pre-push check, the
  architecture and packaging checks, and the workflow's default checks.
- **Restatement.** Skills restate guidance where a step applies it, never stricter
  than its source (`docs/agents/change-workflow.md`, "Skills"); the skills cite the
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
| `AGENTS.md` "Domain docs", `docs/agents/domain.md` | split: workflow (the workflow's terms in its specification); repository (the market's homes) | `workflow/terms.md`; `AGENTS.md` | Ambiguous: whether "one home per term" is engineering |
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
| `docs/agents/change-workflow.md` | workflow; its step table's validation parts and links to `market-change-workflow` split out | `docs/agents/change-workflow.md`; `openspec/specs/market-change-workflow/README.md` | the direction rule |
| `RELEASING.md` | repository, document-level tags | stays whole (D10), but for its versioning policy, which moves to engineering (D10 as amended) | a procedure |
| `VALIDATION_RUNBOOK.md` | outside the guidance set: no frontmatter, no layer-table row | stays whole (D10, 48 F1) | a procedure, not guidance |
| `openspec/config.yaml` | outside the guidance set; its restatements as rows | stays (D23) | |
| `docs/prompts/` | outside the guidance set | untouched (D12) | |

### D3 — Shared layers in `docs/guidance/`; capability guidance beside its capability

The initial migration organizes shared guidance as `docs/guidance/engineering/` and
`docs/guidance/workflow/`, each with a `README.md` holding its tag table (D18). The
organization is for people navigating the tree, and may change: the tag defines a
file's layer, the workflow attaches no meaning to directories, and a lift-out
selects files by layer tag, which the direction rule keeps cheap.
The workflow's guide, `docs/agents/change-workflow.md`, is not guidance: it becomes
the change workflow's operator handbook, holding only what the owner needs to know,
beside the other handbooks in `docs/`, with no frontmatter; what agents need of it
moves out by the rule under "Settled at round 2's triage" (amended at round 2's
triage, 58 O7).

Repository guidance sits beside the system it pertains to: a section of
`TESTING.md` or `DEPLOYMENT_AND_CONFIG.md` that pertains to one capability moves to
a guidance file in `openspec/specs/<capability>/`, such as
`openspec/specs/resource-pool-management/testing.md`, whose place gives its
capability. Guidance spanning several systems stays in this repository's
cross-system documents. `AGENTS.md` remains the entry: the layers, where each
lives, this repository's own rules, and its exceptions (D9).

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
the hook and every skill see the expanded list. Shared and cross-system guidance is
read exactly as before; capability guidance is read with its capability (D22).
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
`selects` or `overrides`. The table sits beside the component it applies to; an
exception spanning several systems, such as this repository's choice of the public
case or the buyer CLIs' test seams, sits in `AGENTS.md`, which both harnesses keep
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
beside their capabilities, and its cross-system deployment stays; overlap with the
operator handbook is flagged in the inventory rather than settled by the agent.
`RELEASING.md` is a procedure and stays whole, with document-level tags; a section
of a procedure that states policy rather than a step is classified by D1 like any
other, so `RELEASING.md`'s versioning policy moves to engineering, its repository
reasons staying and citing it (amended at round 1's triage, 31 O1e). The validation
runbook is a procedure outside the guidance set: it carries no frontmatter and no
row in `AGENTS.md`'s layer table, and moves nothing (48 F1).
`BUILD_AND_PACKAGING.md` stays repository material, any uv convention that holds
anywhere moving out tagged `tool`.

Rejected: extracting procedures too, which scatters runbooks nobody follows in
pieces.

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
table, `workflow` of the workflow table, and `repository` of `AGENTS.md`'s. The
layer model itself — the test and the link direction — is workflow material, stated
for readers in `docs/guidance/workflow/README.md` and normatively by CW-g7lt and
CW-d2rw; a row naming another layer's word is not a link, so the engineering table's
description of its layer may say what it holds without the workflow. This repository's table is a section of
`AGENTS.md` and lists only tags neither shared layer has; capability tags are not
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
- **31 O1c — Tags are atoms, selected conjunctively.** The partition assumes a later
  loader reads a file when a session carries every tag the file carries; there are
  no compound tags. A file carries only the tags its content needs, and content
  needing another tag set goes in another file. A tool a developer, build, or
  deployment runs has a tool tag; a library code imports carries its language's tag.
  "This repository uses X" is repository material; how to use X well is engineering
  tagged X, for any X. The loader change inherits or revises this assumption.
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
  `docs/agents/domain.md` is removed once its rows move.
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
   `openspec/README.md`, and `docs/agents/change-workflow.md`, and every citation
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

Until round 6, each round adds the guidance files it creates to `load.common` by
path, so later sessions on the branch read them. Rounds 2 to 5 follow one another
directly (D15).

## Open Questions

None. Loading by tag, removing the skills' restatements, moving a layer out of the
repository, and citing guidance held outside it are later changes, recorded as the
lesser goal's unowned gaps.
