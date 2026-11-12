# Tasks

Sections follow `design.md`'s implementation cadence: the inventory (sections 1–2),
the workflow layer (3), the engineering layer (4), the repository layer at the root
and across systems (5), the repository layer beside each capability (6), and the
code (7–8), then closeout (9). Every move follows the inventory as round 1's triage
corrected it (D2); a destination named below is the one the design's hard-case
sample gives, and the corrected inventory overrides it.

Rounds 2 to 5 edit `.agents/workflow.toml` and the skills, which lie outside the
inert paths, so each of their commits runs the functional pre-commit hooks:
relocking, the packaging check, and every suite.

**What the closing checks report until closeout.** `scripts/change-workflow run
pre-commit layer-engineering-guidance` fails on two checks every section expects,
and on nothing else: the documentation citations of files the change creates until
they exist — and of the hard-case sample's provisional destinations in `design.md`,
which closeout's citation part resolves (task 9.11) — and the specification index,
which wants `change-workflow/index.md` entries for CW-g7lt, CW-d2rw, CW-p9sa,
CW-x4ex, CW-n6dm, and CW-r8cg, entries closeout's promotion writes (task 9.9). Any
other failure is the section's to fix.

## 1. Inventory of the root and workflow documents

Delivers the first half of the inventory (D2): `AGENTS.md`, `openspec/README.md`,
`docs/agents/change-workflow.md`, `docs/agents/domain.md`, and
`docs/development/ARCHITECTURE.md`, classified by D1's test, with destinations by
D3 and D8–D10, tags by D7 and D17–D19, and exceptions by D9. No guidance text moves.
Files: `openspec/changes/layer-engineering-guidance/inventory.md` (new).

- [x] 1.1 Create `inventory.md` with its sections table — columns `Source` (document
  and heading, or the part of a heading's text a split row covers), `Layer`, `Tags`,
  `Destination` (file, and heading where it joins one), `Reason`, `Ambiguous` (empty,
  or what the test did not decide) — and an opening paragraph saying the inventory
  is change history and that the corrected rows govern every later section (D2).
  Verify the file exists with that header.
  Note: the table is split into one table per document under `## Sections`, each with
  the same six columns, so the owner can correct a document's rows together. The
  opening also gives the reading conventions: one layer per row, the
  `engineering/`/`workflow/` destination shorthand, "stays", "neutralized", how
  closeout rows name the layer of the rule they confirm, and how exceptions are marked
  (**Exception (selects|overrides)** at the head of `Reason`, with the table named).
  Evidence: inspected; no test applies to a change document.
- [x] 1.2 Classify every heading of `AGENTS.md` and `openspec/README.md` at every
  level, splitting a section into one row per layer its text holds (D1), the
  closeout parts one row per part with the part's layer and the layer of the rule it
  confirms (D8), and each exception the text states — a case selected, a shared rule
  overridden — marked as one, with where its table goes (D9). Verify by listing the
  two documents' headings (`grep -n '^#' AGENTS.md openspec/README.md`) and finding a
  row for each.
  Note: every heading `grep -n '^#'` lists has a row (checked with Grep against the
  inventory's Source cells). The grep's hits inside fenced blocks are covered as the
  inventory's legend says: `AGENTS.md`'s comment examples by the comment rows, and
  `openspec/README.md`'s three template headings by rows of their own. Closeout parts 5,
  7, and 8 are repository rows (D8); the other eight are workflow rows naming the
  layer of the rule each confirms, and part 2's import rule itself is split out as
  engineering, Python. One exception is stated in the text: the public case, selected,
  in `AGENTS.md`'s table.
- [x] 1.3 Classify every heading of `docs/agents/change-workflow.md`,
  `docs/agents/domain.md`, and `docs/development/ARCHITECTURE.md` the same way,
  including the workflow guide's links to this repository's documents and its step
  table's validation parts (D1's direction), and `ARCHITECTURE.md`'s engineering
  rules and the subsections filed under "Deterministic database-concurrency tests"
  (D10). Verify every heading has a row.
  Note: every heading has a row (checked as in 1.2). Beyond the sample, the workflow
  guide names this repository in more places than its links and step table: `dev`
  as the integration branch and the protected branches, the hook commands, the CI
  baseline, the clone's remote, bootstrap, and evidence paths, the waiver parts, and
  `ROADMAP` examples; each has a repository row, neutralized in the guide. One
  exception candidate is flagged rather than marked: `ARKHAI_IDENTITY_CREDENTIAL`
  becomes an `overrides` row only if section 2 moves the secrets rule to engineering.
- [x] 1.4 Verify: every row has a layer, tags from the tags the inventory proposes,
  a destination, and a reason; every row the test did not decide says why in
  `Ambiguous`; `git diff --stat` against the section's start shows only
  `inventory.md` changed; and `scripts/change-workflow run pre-commit
  layer-engineering-guidance` reports no failure but the two the preamble expects.
  End-to-end: none; the inventory changes no behaviour.
  Note: 196 rows, each with six cells, one of the three layers, that layer as its
  first tag, a destination, and a reason (Grep over the rows); every tag a row uses is
  in the inventory's "Tags the rows use" list, and every listed tag is used. The diff
  against `699ab24c1` holds `inventory.md` (new) and, besides this task list, one
  edit the implementation skill makes on a change's first section: the change's index
  row set to `in implementation`. No guidance text moved. `scripts/change-workflow run
  pre-commit layer-engineering-guidance` fails only on the two the preamble expects —
  the citations of files the change creates (from `design.md`, `proposal.md`, and
  `tasks.md`; none from `inventory.md`) and the six `CW-*` entries `index.md` lacks;
  the index, tasks, skills, and strict OpenSpec checks pass. End-to-end scenarios
  covering the section: none confirmed, as planned. Owed by validation: nothing.

Section 1 notes (handoff):

- The rows hold more `Ambiguous` entries than the sample: each records the
  recommendation the owner can accept or correct in round 1's triage. The ones most
  likely to change later sections: whether "Amend a rule or comply" admits declared
  exceptions (D9); whether `docs/agents/domain.md` is removed; whether `ARCHITECTURE.md`'s
  one-capability summaries stay (recommended) or move beside their capabilities;
  whether "Durable fulfillment acceptance" joins fulfillment's companion
  (recommended) rather than becoming a guidance file; whether the draw.io and Python
  forms of short rules get files of their own (D7).
- Workflow tags use the step names (`plan`, `implement`, `validate`), not the sample's
  `planning`, so a later loader selects by step; the inventory's legend says so.
- "Tags the rows use" is a flat list with each tag's proposed layer; section 2 turns
  it into the D18 tables (task 2.4). `configuration`, `packaging`, and `deployment`
  are placed provisionally: section 2's rows on `DEPLOYMENT_AND_CONFIG.md` and
  `BUILD_AND_PACKAGING.md` decide their layer.
- Section 2 should look for `dev`, `.snapshot/`, and make targets inside workflow
  text, as the fresh-context check found the guide's sample split too coarse; and
  should settle `ARCHITECTURE.md`'s "Operator lifecycle controls" principle together
  with `TESTING.md`'s "Pause the loop, then advance it explicitly".
- This session read `TESTING.md` through its first 600 lines and
  `DEPLOYMENT_AND_CONFIG.md` by its heading outline only; section 2 classifies both
  and reads them in full.

## 2. Inventory of the repository documents, restatements, vocabulary, and checks

Delivers the rest of the inventory (D2, D10, D11, D13, D18, D23):
`docs/development/TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`, `BUILD_AND_PACKAGING.md`,
`VALIDATION_RUNBOOK.md`, and `RELEASING.md`; the restatements in the skills and in
`openspec/config.yaml`; the proposed vocabulary tables; and the draft classification
of the checks. No guidance text moves. Files: `inventory.md`.

- [x] 2.1 Classify every heading of `TESTING.md` and `DEPLOYMENT_AND_CONFIG.md`:
  general method to engineering with the neutral example it needs named in
  `Reason`, Python, uv, and Helm forms split from a neutral principle into their own
  rows (D7), capability sections beside the capability they pertain to (D3, D10),
  cross-system material staying, and overlap with `docs/operator-handbook.md`
  flagged in `Ambiguous` (D10). Verify every heading has a row.
  Note: every heading `grep '^#'` lists in both documents has a row (Grep over the
  inventory's Source cells), the five TOML comments in `DEPLOYMENT_AND_CONFIG.md`'s
  fenced blocks included. That proves each heading has a row, not that each
  paragraph under it does; the split rows come from reading both documents in full,
  and the second fresh-context check found one paragraph without a row (the
  provisioning service's stored-pool refusal), now its own. Beyond the sample: the Python testing forms gather in one
  `engineering/testing-python.md` rather than one file beside each neutral file
  (flagged); Kubernetes, Helm, and Dynaconf forms have their own files; and
  `DEPLOYMENT_AND_CONFIG.md`'s Kubernetes section, which the sample keeps whole, is
  split into its general rules and its charts (flagged). Capability sections go
  beside thirteen capabilities as `testing.md` or `configuration.md`, written
  `specs/<capability>/<file>` so the citation check reads no file a corrected row
  may never create; "Validation namespaces" goes to `market-change-workflow`'s
  README, as a description of the system. Handbook overlap is flagged on definition
  documents, the registry's secret profile, payments access, and the upgrade's
  migrations list. Two exceptions are marked, both **overrides** in `AGENTS.md`: the
  buyer CLIs' test seams and `ARKHAI_IDENTITY_CREDENTIAL`. Four section 1 rows that
  waited on this section, or that its rows place differently, are amended in place:
  `ARCHITECTURE.md`'s "Local development" rules, split into an engineering row and a
  repository one; "Operator lifecycle controls", now in `engineering/test-seams.md`
  beside "Pause the loop, then advance it explicitly"; "Testing strategy"'s
  deterministic-sequence rule, now in `engineering/system-tests.md` with `TESTING.md`'s
  discipline; and "Tests and diagnostics"' reason for the packaging check, split out
  as an engineering packaging rule. Evidence: inspected; no test applies to a change
  document.
- [x] 2.2 Give `BUILD_AND_PACKAGING.md`, `VALIDATION_RUNBOOK.md`, and `RELEASING.md`
  each a document-level row with its tags, and a row for each section holding
  general method, such as a uv convention that holds in any repository (D10).
  Verify each document has its row.
  Note: each document opens with a row whose Source is "The document as a whole";
  every heading of the three also has a row, since 2.6 asks for every heading of
  every document in the Context table. `BUILD_AND_PACKAGING.md`'s general method
  moves to `engineering/packaging.md`, `packaging-uv.md`, `packaging-docker.md`, and
  `packaging-python.md`. Three rows are engineering by D1's test inside documents
  D10 keeps whole: `RELEASING.md`'s "Versioning policy" and the closing paragraph of
  "Import package renames", and the runbook's per-observation method under
  "Observations the qualification owes". Each keeps D10's destination, `stays`, and
  puts the move (`versioning.md`, `packaging-python.md`, `system-tests.md`) as the
  recommendation in `Ambiguous` for the owner, since a corrected row cannot override
  a settled decision. The runbook was read for its opening, section 10, and section
  29; its other sections are classified by heading as procedure, so whether they
  hold further general method was not checked paragraph by paragraph.
- [x] 2.3 Add a restatements table: every place a `change-*` or `guidance-review`
  skill, or `openspec/config.yaml`, restates or cites a guidance rule — the file and
  its section, the rule's source today, and the destination the rule moves to — so
  later sections re-point each citation and the loader change inherits the list
  (D11, D23). Verify by searching the skills and `openspec/config.yaml` for citations
  of the guidance documents and finding a row for each.
  Note: `## Restatements`, 57 rows. Every hit of a Grep over the eleven skills for
  the guidance documents' paths and `ROADMAP` has a row, as do the uncited
  restatements found by searching for "in prose", "current system", "lowest level",
  and "module level" and by reading each skill's loading, planning, and checking
  steps, and each of `openspec/config.yaml`'s context paragraphs and rule groups,
  every bullet of each. The fresh-context checks found gaps — `change-triage`'s
  `ROADMAP` examples, `change-plan`'s layer ordering, `rules.design`, and bullets
  missing from `rules.tasks` and `rules.specs` — now covered;
  the search for restatements without a citation remains a reading, not a
  mechanical check. Found on the way: `change-plan`, `change-implement`, and
  `change-triage` name four test levels (unit, library integration, application
  integration, system) where `TESTING.md` names unit, integration, smoke, and
  system; recorded on their rows for section 4. Not in the table: the 29 places the
  skills name `dev` or a `.snapshot/` path, and the make targets they run (section
  1's handoff asked this section to look). They are the skills' own instructions
  naming this repository, not restated guidance, so they are neither re-pointed nor
  inherited by the loader; task 3.7 lists the repository paths a skill names in
  `market-change-workflow`'s README, and moving them out of the skills is
  `extract-change-workflow-repository`'s.
- [x] 2.4 Add the proposed vocabulary: the engineering, workflow, and repository
  tag tables as D18 shapes them (`Tag | Kind | Description`, each layer's own tag as
  its first row), holding exactly the tags the rows of sections 1 and 2 use. Verify
  every tag used in a row appears in one table, and every table row is used.
  Note: `## Proposed vocabulary` replaces section 1's flat list. `configuration`,
  `packaging`, and `deployment` are settled as engineering topics; `versioning` and
  the tools `uv`, `docker`, `kubernetes`, `helm`, `dynaconf`, and `ansible` are new.
  A Grep requiring every row's Tags cell to consist only of the tables' tags matches
  all 406 rows; no engineering row uses a workflow or repository tag, and no
  workflow row a repository tag; each table tag appears in a row.
- [x] 2.5 Add the draft classification of the checks (D13): each check enforcing
  guidance — comment hygiene, history wording, local imports, decision
  destinations, version bumps, the capability and specification indexes, citations,
  public content, secrets, the pre-push check, the architecture and packaging
  checks, the workflow's default checks (change index, tasks, agent skills, strict
  validation), and the guidance check — with the rule it enforces, that rule's
  layer, and where the check runs. Verify every target `make check-repository`,
  `make check-packaging`, and `make pre-push` run has a row.
  Note: `## Draft classification of the checks`, 25 rows: the eight checks
  `scripts/check_change.py` runs, `check-packaging`'s `dist` prerequisite and five
  checks, both scripts `make pre-push` runs and the target itself, the four default
  checks, and `check-architecture-change`, `check-uv-version`, `audit-secrets`
  (which refuses nothing), and the guidance check to come.
- [x] 2.6 Verify: sections 1 and 2 together give every heading of every document in
  `design.md`'s Context table but `docs/prompts/` a row; only `inventory.md`
  changed; `scripts/change-workflow run pre-commit layer-engineering-guidance`
  reports no failure but the two the preamble expects. End-to-end: none; the
  inventory changes no behaviour.
  Note: 406 rows, each with six cells, one of the three layers, that layer as its
  first tag, a destination, and a reason (Grep over the rows); section 1's headings
  were checked in 1.2–1.3, and every heading of `TESTING.md`,
  `DEPLOYMENT_AND_CONFIG.md`, `BUILD_AND_PACKAGING.md`, `VALIDATION_RUNBOOK.md`, and
  `RELEASING.md` has a row (Grep over the Source cells against each document's
  `grep '^#'`, fenced comments included). The worktree changes only `inventory.md`
  and this task list. `scripts/change-workflow run pre-commit
  layer-engineering-guidance` fails only on the two the preamble expects — the
  citations of files the change creates (from `design.md`, `proposal.md`, and
  `tasks.md`; none from `inventory.md`) and the six `CW-*` entries `index.md` lacks;
  the index, tasks, skills, and strict OpenSpec checks pass. A shell loop over the
  headings was refused (no rule allows it), so the heading check was made with Grep.
  End-to-end scenarios covering the section: none confirmed, as planned. Owed by
  validation: nothing.

Section 2 notes (handoff):

- Round 1's triage corrects the rows of both sections before any text moves. The
  `Ambiguous` cells most likely to change later sections: the one Python testing
  file (`testing-python.md`) against one beside each neutral file; splitting
  `DEPLOYMENT_AND_CONFIG.md`'s Kubernetes section, which the sample kept whole; the
  three engineering rows D10 keeps in place (`RELEASING.md`'s "Versioning policy"
  and its compatibility paragraph, the runbook's observation method), whose moves
  would need D10 read as procedures staying whole and policy inside them moving —
  a reading the owner may take, or send to design; which
  capability takes "Host Requirement Enforcement", "Payment Receipts in Tests", the
  storefront startup paragraphs, and the provisioning definition documents; whether
  "Validation namespaces" joins `market-change-workflow`'s README; and the handbook
  and runbook duplicates recommended for one home ("Accepted Arkhai purchase
  qualification", the v0.3.0 migrations list, the settlement cutover sequence).
- The engineering layer has grown well past the sample's file list: the rows name
  39 engineering files, one of them (`comments-python.md`) recommended against
  (testing alone is `test-levels`, `testing`,
  `test-seams`, `test-determinism`, `integration-tests`, `system-tests`,
  `test-doubles`, `contract-fixtures`, `conformance-tests`, `boundary-changes`,
  `migration-tests`, `concurrency-tests`, `helm-render-tests`, `ansible-checks`, and
  `testing-python`). Section 4 is sized for the sample; it may be worth the owner
  weighing, at the round's triage, whether section 4 splits.
- Exceptions found across both sections, for section 5's `AGENTS.md` table: the
  public case (selects), the buyer CLIs' test seams (overrides), and
  `ARKHAI_IDENTITY_CREDENTIAL` (overrides). None was found that applies to one
  capability alone, so section 6's task 6.2 may have nothing to place unless the
  triage finds one.
- Capability guidance destinations are written `specs/<capability>/<file>`, a
  shorthand the citation check does not read, so the inventory stays out of the
  preamble's expected citation failures; section 6 writes them at full paths.
- `deployment` moved from the repository table to the engineering one, so
  `AGENTS.md`'s table (section 5) holds only `repository`, `architecture`, and
  `checks`.
- Not read in full this session: `ARCHITECTURE.md` beyond its build, deployment,
  operator-controls, and testing sections, which section 1 inventoried; and
  `VALIDATION_RUNBOOK.md` beyond its opening, failure diagnostics, and section 29,
  whose other sections are classified by heading as procedure.

Round 1's triage (reviews 29–31, the orchestrator's record 27):

- Fix, 31 O1 / 29 F1: the inventory is corrected by the owner's rules, stated in its
  "Rules from round 1's triage" and in `design.md`, "Settled at round 1's triage":
  general rules move to engineering (31 O1a), duplicates are deduplicated with each
  wording change reviewed (31 O1b), tags are atoms selected conjunctively and files
  partitioned to match (31 O1c), the project-layout row splits into Python, uv,
  Hatchling, and repository rows (29 F1), multi-capability sections go beside their
  owner (31 O1d), the settled-decision rows are decided (31 O1e), the roadmap's and
  capability index's roles are the workflow's (31 O1f), and the within-layer
  placements stand (31 O1g). 429 rows; the `Ambiguous` column now holds only what a
  later triage settles: 21 duplicate pairs (31 O1b), the exceptions framework's
  wording (31 O1e), and the route pattern's Python form.
- The dispositions amend D8 (roadmap currency is a workflow part) and D10 (policy
  inside a procedure moves), so tasks 3.2, 3.4, and 9.6, and closeout's order, no
  longer match the design; sections 3–6 owe the deduplication and its review
  (31 O1b), section 3 the removal of `docs/agents/domain.md`, section 4 the
  exceptions framework, section 6 the diagram exception row (31 O1e, placed by
  48 F2); and the
  engineering layer now names 40 files, against section 4's one session. The plan
  is amended after the next implementation review's triage, which the owner chose
  before any return to planning.
- Open for section 3's triage: under the conjunctive model, no workflow file carries
  a step or role tag (`design`, `plan`, …), since `working-model.md` and the guide
  serve every step; D18 removes a table row no file uses unless a file is split by
  step. Open for section 5's triage: no repository document as a whole carries the
  repository tag `checks`, whose passages lie across five documents.
- Evidence: inspected; no test applies to a change document. `scripts/change-workflow
  run pre-commit layer-engineering-guidance` fails only on the two failures the
  preamble expects (citations of files the change creates, none from `inventory.md`;
  the six `CW-*` index entries); the index, tasks, skills, and strict OpenSpec checks
  pass. A fresh-context check of the diff found the design's settled list missing
  31 O1g and 29 F1, two stale hard-case sample rows, a `versioning.md` citation the
  rows did not carry, `RELEASING.md`'s document tags, workflow rows tagged beyond
  their file's set, and no carrier named for `architecture` and `checks`; all fixed,
  `checks` recorded as open above. An inline `python3 -I -c` listing destination
  files' tags was denied (no rule allows it); the check was made with Grep and the
  fresh-context subagent.

Round 1's second review (review 48 at `23b54361c`; the owner's notes, record 47,
had none; validation of `23b54361c` waived by the owner, the commit changing only
change documents):

- Edit, 48 F1: the validation runbook stays outside the guidance set, as 31 O1e
  settled — no frontmatter and no row in `AGENTS.md`'s layer table, since D21 would
  otherwise discover it twice over. D10, its hard-case sample row, the inventory's
  preamble and document row, and task 5.3 now say so.
- Edit, 48 F2: the hand-laid graph's `overrides` row moves from `AGENTS.md` to a new
  guidance file beside the capability it applies to,
  `openspec/specs/change-workflow/diagrams.md` (`tags: [repository, diagrams]`), as
  CW-x4ex requires; task 6.2 places it. The inventory's row 155 and O1e rule and
  `design.md`'s O1e bullet name it.
- The change returns to planning, as round 1's triage arranged: the plan owes the
  amendments listed above — tasks 3.2, 3.4, 9.6 and closeout's order against D8 as
  amended; the deduplication and its review in sections 3–6; `domain.md`'s removal
  in section 3; the exceptions framework in section 4; and whether section 4's 40
  engineering files take one session or more. Evidence: inspected; no test applies
  to a change document.

## 3. The workflow layer

Delivers the workflow layer (D1, D3, D8, D16–D19): `docs/guidance/workflow/` with
its README and tag table, the closeout list with the guidance placement part, and
workflow material moved out of the root documents and the workflow guide, every
citation of it re-pointed. Files: `docs/guidance/workflow/*.md` (new); `AGENTS.md`;
`openspec/README.md`; `docs/agents/change-workflow.md`, `docs/agents/domain.md`;
`openspec/specs/market-change-workflow/README.md`; `openspec/specs/change-workflow/README.md`;
`openspec/specs/planning-governance/spec.md` (Evidence only);
`.agents/skills/change-*/SKILL.md`, `.agents/skills/guidance-review/SKILL.md`;
`.agents/workflow.toml`.

- [ ] 3.1 Write `docs/guidance/workflow/README.md`: frontmatter `tags: [workflow]`;
  the layer model — the three layers, D1's test, and the link direction, citing
  CW-g7lt and CW-d2rw; what the layer holds and how its files are organized (flat,
  organization carrying no meaning, D19, CW-n6dm); and its `## Tags` table from the
  corrected inventory, `workflow` its first row (D18). Verify the table holds every
  tag the layer's files use.
- [ ] 3.2 Write `docs/guidance/workflow/closeout.md` (D8, D16): frontmatter; the
  ordered list of the workflow's parts — comment hygiene, import placement,
  documentation compliance, narrative compression, campaign index currency, the
  repository's own closeout parts as its root guidance names them, promotion,
  guidance placement, documentation citations, archival — each part under its own
  heading carrying its text from `openspec/README.md#plan-closeout-requirements`
  with every repository command replaced by what the repository's guidance names
  (D8); the guidance placement part as D16 words it; and the promotion story from
  `AGENTS.md`'s "Cross-references must resolve" (D6). Verify no make target, and no
  link to a file the inventory tags `repository`, appears in it.
- [ ] 3.3 Move the rest of the workflow material to the files the corrected
  inventory names — on the hard-case sample's reading, `working-model.md`,
  `openspec-documentation.md`, `changes.md`, `change-references.md`, and `terms.md`
  — each with frontmatter, deleting the moved text from `AGENTS.md`,
  `openspec/README.md`, and `docs/agents/domain.md`, and keeping in place, under
  their final headings, what the inventory leaves there. Verify each workflow row of
  the inventory sits in its destination and no longer in its source.
- [ ] 3.4 Leave this repository's closeout parts — roadmap currency, packaging,
  end-to-end pipeline — in `openspec/README.md` under `## This repository's closeout
  parts`, naming the commands each runs; and add to `AGENTS.md` the row naming that
  section, so closeout, planning, and review find the parts through the root
  guidance before section 5 rewrites it (D8). Verify the row's link resolves to the
  heading.
- [ ] 3.5 Give `docs/agents/change-workflow.md` frontmatter tagging it `workflow`,
  and move what the inventory finds of this repository in it — its links to
  `market-change-workflow`, its step table's naming of this repository's validation
  parts — to `openspec/specs/market-change-workflow/README.md`, stating it there in
  this repository's terms (D1's direction). Verify the guide links to no file the
  inventory tags `repository`.
- [ ] 3.6 Re-point every citation of moved workflow material, by name and never by
  part number (D8): the skills, from the inventory's restatements table, including
  `change-closeout`'s count of the parts and its order; `change-workflow`'s README
  and spec text; `openspec/specs/planning-governance/spec.md`'s Evidence, outside
  the archive's merge (D14); and every other document citing
  `openspec/README.md#plan-closeout-requirements` or another moved heading. The
  skills' restatements stay as they are (D11). Verify `grep -rn` over the tracked
  tree outside `openspec/changes/archive/` and `docs/prompts/` finds no citation of
  a heading this section removed.
- [ ] 3.7 Add each new `docs/guidance/workflow/` file to `load.common` in
  `.agents/workflow.toml` by path, keeping its comment current, so later sessions on
  the branch read them (design, "Implementation cadence"); and add each repository
  path a skill now names to `openspec/specs/market-change-workflow/README.md`'s "How
  this repository provides the workflow's roles". Verify `scripts/change-workflow
  config load common` prints the new files, and `pytest -q
  scripts/tests/test_change_workflow_assumptions.py` (unit) passes.
- [ ] 3.8 Verify the section: `make check-agent-skills`; `make check-doc-citations`
  run unscoped reports nothing it did not report before the section; `pytest -q
  scripts/tests/test_change_workflow_assumptions.py scripts/tests/test_change_workflow_config.py`
  (unit); and `scripts/change-workflow run pre-commit layer-engineering-guidance`,
  whose functional hooks run every suite, reports no failure but the two the
  preamble expects. End-to-end: none; no pipeline scenario reads guidance, and none is
  owed.

## 4. The engineering layer

Delivers the engineering layer (D1, D3, D6, D7, D10, D17–D19):
`docs/guidance/engineering/` with its README and tag table, general rules given
neutral examples, engineering material moved out of the repository documents, every
citation re-pointed. Files: `docs/guidance/engineering/*.md` (new); `AGENTS.md`;
`docs/development/ARCHITECTURE.md`, `TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`,
`BUILD_AND_PACKAGING.md`; skills and documents citing moved text;
`.agents/workflow.toml`.

- [ ] 4.1 Write `docs/guidance/engineering/README.md`: frontmatter `tags:
  [engineering]`; what the layer holds; its organization (D19); and its `## Tags`
  table from the corrected inventory, `engineering` its first row, with the topic
  and tool tags (D7, D18). Verify the table holds every tag the layer's files use.
- [ ] 4.2 Move the engineering material to the files the corrected inventory names,
  each with frontmatter, each general rule given a neutral example in place of this
  repository's, and each language or tool form in its own file beside its neutral
  principle (D7); this repository's examples stay in the repository documents as
  local illustration. Verify each engineering row of the inventory sits in its
  destination, and no engineering file names a package, service, document, or make
  target of this repository.
- [ ] 4.3 Write what may enter a repository (D6): what holds in every repository,
  what a public repository additionally refuses, and what a private one may hold —
  the last limited to what a private repository may hold that a public one may not,
  the one piece of new guidance this change writes — from `AGENTS.md`'s "Public
  repository discipline", with "Cross-references must resolve"'s rule in the
  documentation file. Verify the private-repository part adds no obligation.
- [ ] 4.4 Delete the moved text from its sources, leaving in each what the inventory
  keeps, and re-point every citation of what moved, skills included. Verify `grep
  -rn` over the tracked tree outside `openspec/changes/archive/` and
  `docs/prompts/` finds no citation of a heading this section removed, and no
  engineering file links to a file the inventory tags `workflow` or `repository`
  (D1's direction).
- [ ] 4.5 Add each new `docs/guidance/engineering/` file to `load.common` by path.
  Verify `scripts/change-workflow config load common` prints them.
- [ ] 4.6 Verify the section as section 3.8 does. End-to-end: none; no pipeline
  scenario reads guidance, and none is owed.

## 5. The repository layer at the root and across systems

Delivers the repository layer's root and cross-system guidance (D3, D8, D9, D13,
D17, D18, D21's manual override): `AGENTS.md` rewritten as the entry,
`openspec/README.md` as this repository's guide, the cross-system documents tagged,
and the classification of the checks. Files: `AGENTS.md`; `openspec/README.md`;
`docs/development/ARCHITECTURE.md`, `TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`,
`BUILD_AND_PACKAGING.md`, `VALIDATION_RUNBOOK.md`, `RELEASING.md`;
`openspec/specs/market-change-workflow/README.md`.

- [ ] 5.1 Rewrite `AGENTS.md` (D3, D9, D18): frontmatter `tags: [repository]`; the
  three layers and where each lives; its layer table naming every repository
  guidance document by path, which is the guidance check's manual override (D21),
  and the closeout-parts row of section 3.4; the repository's `## Tags` table,
  `repository` its first row, listing only tags neither shared layer has; the
  `## Exceptions to shared guidance` table for every multi-system exception the
  inventory found — at least the public case selected, and the buyer CLIs' test
  seams overridden; and this repository's own rules. Verify every repository row of
  the inventory whose destination is `AGENTS.md` sits there, and each exception row
  cites a guidance file and has the kind `selects` or `overrides`.
- [ ] 5.2 Finish `openspec/README.md` as this repository's OpenSpec guide (D3, D8):
  frontmatter; its placement table naming `docs/guidance/` and capability guidance
  files beside capabilities; the validator pin; its closeout parts naming `make
  check-guidance` where the guidance placement part runs the repository's guidance
  check (D21). Verify it holds no row the inventory tags `workflow`.
- [ ] 5.3 Give `ARCHITECTURE.md`, `TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`,
  `BUILD_AND_PACKAGING.md`, and `RELEASING.md` frontmatter with their tags (D10,
  D17) — `VALIDATION_RUNBOOK.md` stays outside the guidance set, with no frontmatter
  and no layer-table row (48 F1) — and move what the inventory finds misfiled across
  systems — on the sample's reading, "Public repository content checks" to
  `market-change-workflow`'s README. Verify each document opens with its frontmatter
  and appears in `AGENTS.md`'s layer table.
- [ ] 5.4 Write the classification of the checks (D13) in
  `openspec/specs/market-change-workflow/README.md` as `### What each check enforces`
  under "This repository's checks": a table of each check, the rule it enforces
  linked to its guidance, that rule's layer, and where it runs, from the inventory's
  corrected draft, the guidance check marked as enforcing workflow rules from this
  repository's script. Verify every row of the draft is in the table.
- [ ] 5.5 Re-point every citation of what this section moved, and verify the
  section as section 3.8 does. End-to-end: none; no pipeline scenario reads guidance,
  and none is owed.

## 6. The repository layer beside each capability

Delivers capability guidance beside its capability and the steps that read it (D3,
D9, D10, D22; CW-p9sa, CW-x4ex, CW-r8cg): the capability sections of `TESTING.md`,
`DEPLOYMENT_AND_CONFIG.md`, and `ARCHITECTURE.md` moved into guidance files in
`openspec/specs/<capability>/`, with their exceptions, and the seven skills reading
them. Files: `openspec/specs/<capability>/*.md` (new guidance files);
`docs/development/TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`, `ARCHITECTURE.md`;
`.agents/skills/change-{design,plan,implement,review,triage,merge,closeout}/SKILL.md`.

- [ ] 6.1 Move each section the corrected inventory places beside a capability into
  a guidance file in that capability's directory — on the sample's reading,
  `openspec/specs/resource-pool-management/testing.md`,
  `openspec/specs/negotiation-protocol/testing.md`,
  `openspec/specs/marketplace-identity/configuration.md`, and
  "Durable fulfillment acceptance" beside `fulfillment` — each with frontmatter
  `tags: [repository, <topic>]` and no capability tag (D18), deleting it from its
  source. Verify each such row sits in its destination, and no file in a capability
  directory but `spec.md`, its companion, and `index.md` lacks frontmatter.
- [ ] 6.2 Put each exception the inventory found that applies to one capability in
  that capability's guidance file, as an `## Exceptions to shared guidance` row
  (D9, CW-x4ex). Verify each cites a guidance file.
- [ ] 6.3 Extend the seven skills' reading lists — `change-design`, `change-plan`,
  `change-implement` (both of its lists), `change-review`, `change-triage`,
  `change-merge`, and `change-closeout` — so that wherever each reads a capability's
  specification and companion it also reads every other Markdown file in the
  capability's directory but its `index.md` (D22, CW-r8cg). Verify `make
  check-agent-skills` passes and each skill's list names the guidance files.
- [ ] 6.4 Re-point every citation of what this section moved, and verify the
  section as section 3.8 does. End-to-end: none; no pipeline scenario reads guidance,
  and none is owed.

## 7. `[load]` directory entries

Delivers directory entries in `[load]` (D5; CW-l7hn, modified). Files:
`scripts/change_workflow/config.py`, `scripts/change_workflow/hook.py` where its
handling needs it; `scripts/tests/test_change_workflow_config.py`,
`scripts/tests/test_change_workflow_hooks.py`.

- [ ] 7.1 Make `config.documents()` expand an entry ending in `/` into the Markdown
  files beneath it, recursively, in sorted path order, each document once across
  `load.common` and `load.<step>`, and refuse with a `StepError` naming the entry a
  directory entry that is missing, unreadable, or holds no Markdown file; literal
  entries and an absent or empty list resolve as before. `config load` reports the
  refusal as an error rather than a traceback. Verify with unit tests: a directory
  entry expands in sorted order in place of the directory; an entry naming a missing
  directory, a file, an unreadable directory, and a directory with no Markdown each
  refuse naming the entry; a literal missing file is still printed; and the
  existing "Design loads the roadmap" test passes.
- [ ] 7.2 Verify the post-compaction hook names the expanded files for a directory
  entry, and, for a refused entry, tells the session the documents to re-read are
  unknown (CW-l7hn's scenario "A directory entry names nothing"), with unit tests in
  `test_change_workflow_hooks.py`.
- [ ] 7.3 Verify the section: `pytest -q scripts/tests/test_change_workflow_config.py
  scripts/tests/test_change_workflow_hooks.py` (unit), then `make test-release-tooling`,
  and `scripts/change-workflow run pre-commit layer-engineering-guidance`.
  End-to-end: none; the engine's loading runs in no pipeline scenario, and none is
  owed.

## 8. `make check-guidance`

Delivers the guidance check and `load.common` collapsed to one entry (D5, D9, D15,
D16, D21; MCW-c4ek, modified; CW-g7lt, CW-d2rw, CW-x4ex as checked rules), and the
fixes the check finds in the guidance. Files: `scripts/check_guidance.py` (new),
`scripts/tests/test_check_guidance.py` (new); `scripts/check_change.py`,
`scripts/tests/test_check_change.py`; `Makefile`; `.agents/workflow.toml`; guidance
files the check finds wanting.

- [ ] 8.1 Write `scripts/check_guidance.py`, standard library only like the other
  closing checks: the guidance set as D21 gives it — every Markdown file under
  `docs/guidance/`; every Markdown file in a capability directory under
  `openspec/specs/` but its `spec.md`, its companion (`architecture.md`, or
  `README.md` where the capability has an `index.md`), and its `index.md`, found by
  place before its frontmatter is read; every other tracked Markdown file outside
  `openspec/changes/` carrying `tags` frontmatter; and the documents `AGENTS.md`'s
  layer table names. It fails, naming the file, on each of MCW-c4ek's conditions:
  missing `tags`; zero or several layer tags; a tag in neither its layer's table nor
  a lower one's; a table row no file uses; a malformed table; an exception row
  citing no guidance file or naming a kind other than `selects` or `overrides`; a
  link to a guidance file tagged with a higher layer; and, in any tracked Markdown
  file outside `openspec/changes/archive/` and `docs/prompts/`, a citation of a
  guidance file — a Markdown link or a quoted path — whose anchor names no heading
  in it, headings slugged as GitHub renders their anchors. It compares no layer tag
  with a directory (CW-n6dm). `--list [--tag <tag>]` prints each guidance file with
  its tags, and `--list-exceptions` every exception row. Verify with unit tests in
  `test_check_guidance.py` over temporary trees, one per failure condition, each of
  MCW-c4ek's guidance scenarios ("An untagged capability guide", "A guidance link's
  section moved", "Engineering guidance links upward"), a passing tree, the archive
  and `docs/prompts/` exclusions, a workflow-tagged file under an engineering
  directory passing, and both listings.
- [ ] 8.2 Add `make check-guidance` to the `Makefile` and to `scripts/check_change.py`'s
  checks, so `make check-repository` runs it, and name it in `check-repository`'s
  help text. Verify `test_check_change.py` (unit) covers the new check and passes.
- [ ] 8.3 Collapse `load.common` to `AGENTS.md`, `docs/guidance/`, the cross-system
  documents, and `openspec/README.md` (D5), with its comment current. Verify
  `scripts/change-workflow config load common` prints every guidance file sections 3
  and 4 listed by path, and nothing more under `docs/guidance/`.
- [ ] 8.4 Run `make check-guidance` over the tree and fix in the guidance whatever it
  reports — a missing tag, an unused row, a stale anchor, an upward link — each fix
  following the corrected inventory. Verify `make check-guidance` passes.
- [ ] 8.5 Verify the section: `pytest -q scripts/tests/test_check_guidance.py
  scripts/tests/test_check_change.py` (unit), then `make test-release-tooling`, and
  `scripts/change-workflow run pre-commit layer-engineering-guidance`, which now runs
  the guidance check. End-to-end: none; no pipeline scenario runs the closing
  checks, and none is owed.

## 9. Closeout

The closeout task, in the order this change itself gives it (D8): the workflow's
parts from `docs/guidance/workflow/closeout.md`, with this repository's parts from
`openspec/README.md`'s "This repository's closeout parts" at the position the list
names. They are `openspec/README.md#plan-closeout-requirements`'s eleven parts,
reordered, plus guidance placement (D16).

- [ ] 9.1 Comment hygiene. Confirm; do not do it here. Run `make
  check-comment-hygiene` and `make check-history-wording`, and read the comments
  sections 7 and 8 added to `scripts/change_workflow/config.py`,
  `scripts/check_guidance.py`, and their tests; anything reported returns the change
  to implementation.
- [ ] 9.2 Import placement. Confirm; run `make check-local-imports` over the code
  sections 7 and 8 added; an import that should move returns the change to
  implementation.
- [ ] 9.3 Documentation compliance. Re-check each decision's destination against
  the placement rules as this change left them — `openspec/README.md`, "Documentation
  placement", and CW-p9sa — directly, not by waiting for the closeout review.
- [ ] 9.4 Narrative compression. Shorten the completed task notes to final
  behaviour, material evidence, deferred work, and destinations, moving any
  alternatives or review rationale into `design.md` first. `inventory.md` stays as
  change history (D2).
- [ ] 9.5 Campaign index currency. Set this change's row in
  `openspec/changes/README.md` to `in closeout` and link it to its archive; in the
  lesser goal, rewrite the current-state paragraph "The guidance agents load is not
  layered" to the layered guidance as it now stands, and narrow the gap row this
  change owned to loading by tag, removing the skills' restatements, moving a layer
  out, and citing guidance held elsewhere, each still unowned. Leave the dependents'
  `Depends on` (`add-skill-extension-points`, `extract-change-workflow-repository`)
  to archive cleanup. Name the update in the design-promotion record.
- [ ] 9.6 Roadmap currency. Record that no update is owed: the lesser goal lives in
  the change index, not in `docs/development/ROADMAP.md`, and no roadmap goal or gap
  row changes.
- [ ] 9.7 Packaging. Run `make check-packaging` and resolve every failure; run
  `make check-architecture-change CHANGE=layer-engineering-guidance`; run `make
  check-agent-skills`, since the change edited `.agents/`.
- [ ] 9.8 End-to-end pipeline. Confirm the pipeline passes at the closeout's code
  and record the run and its result; no scenario exercises this change's behaviour,
  which no deployed service reads. If it cannot run for an unrelated reason, record
  the blocker and its owner, and treat it as unrun.
- [ ] 9.9 Promotion. Write the permanent documents the proposal's "Knowledge to
  promote" names and complete the design-promotion record: `change-workflow/README.md`'s
  new section "The repository's guidance is layered" under "The public surface"
  (D1, D3, D4, D6, D9, D19), its "A repository's configuration" and its "Current
  limits" bullet on `[load]` (D5), and its "Closeout and archival" (D8);
  `change-workflow/index.md`'s new group "The repository's guidance" under "5. The
  public surface" listing CW-g7lt, CW-d2rw, CW-p9sa, CW-x4ex, CW-n6dm, and CW-r8cg
  with their summary lines, and CW-l7hn's summary line revised for directory entries;
  `market-change-workflow/index.md`'s MCW-c4ek summary line revised for the guidance
  check, and its README's "The closing checks" (D15, D21); and confirm the
  destinations earlier sections already wrote — the guidance READMEs, `AGENTS.md`,
  `openspec/README.md`, `market-change-workflow/README.md`'s "What each check
  enforces", and `planning-governance`'s Evidence. `change-workflow/spec.md` and
  `market-change-workflow/spec.md` are written by the archive in 9.12. No id is
  retired.
- [ ] 9.10 Guidance placement (D16). Read each guidance section the change added,
  moved, or rewrote — every row of the corrected inventory, and what 9.9 wrote —
  against the layer test, adjacency, and exception placement; move what is misplaced
  and re-point its citations; run `make check-guidance`. Report for the closeout
  review any placement needing a decision.
- [ ] 9.11 Documentation citations. Run `make check-doc-citations
  CHANGE=layer-engineering-guidance` and resolve every match; then
  `scripts/change-workflow openspec validate layer-engineering-guidance --strict`.
- [ ] 9.12 Archival. Archive with `scripts/change-workflow openspec archive
  layer-engineering-guidance -y`, which merges the `change-workflow` and
  `market-change-workflow` deltas into their specifications (no `--skip-specs`), and
  link the change's row to its archive directory.
