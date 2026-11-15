# Tasks

Sections follow `design.md`'s implementation cadence: the inventory (sections 1–2),
the workflow layer (3), the engineering layer (4–5), the repository layer at the
root and across systems (6), the repository layer beside each capability (7), and
the code (8–9), then closeout (10). Every move follows the inventory as round 1's
triage corrected it (D2), its files and their tags as "Files and their tags" gives
them (31 O1c); a destination named below is the one the design's hard-case sample
gives, and the corrected inventory overrides it.

The documents the change removed are named by their former paths without the leading
`docs/`: `agents/change-workflow.md` (moved to `docs/change-workflow-handbook.md`),
`agents/domain.md`, `development/BUILD_AND_PACKAGING.md`, and
`development/RELEASING.md` (task 14.11).

Sections 3 onward were replanned against round 1's triage (the amended D8 and D10,
and "Settled at round 1's triage"). The notes under sections 1 and 2 and the round's
triage notes use the earlier numbering: their section 4 is now sections 4 and 5,
their 5 is 6, their 6 is 7, their 7 and 8 are 8 and 9, and their 9 is 10; their
tasks 3.2, 3.4, 5.3, 6.2, and 9.6 are now 3.2, 3.4, 6.3, 7.2, and 10.5.

**Deduplication in every moving section (31 O1b).** A section merges into one home
the copies the corrected inventory marks as duplicates that agree. For each pair
whose copies differ, or whose merge would change what the guidance says, it writes
one proposed text and lists the pair — both forms and the proposal — in its notes,
for its round's triage to review with the owner; it never assumes the change. It
lists too each place a document outside the guidance — the operator handbook, the
validation runbook, a README — contradicts the guidance as moved, for the same
triage's fixes.

Rounds 2 to 5 edit `.agents/workflow.toml` and the skills, which lie outside the
inert paths, so each of their commits runs the functional pre-commit hooks:
relocking, the packaging check, and every suite.

**What the closing checks report until closeout.** `scripts/change-workflow run
pre-commit layer-engineering-guidance` fails on two checks every section expects,
and on nothing else: the documentation citations, from the change's own documents,
of files it creates, removes, or moves (`docs/agents/`, `BUILD_AND_PACKAGING.md`,
`RELEASING.md`, the hard-case sample's provisional destinations), which task 14.11
resolves; and the specification index, which wants the twelve `CW-*` entries the
change adds and CW-pkug's link to its renamed heading, which task 14.9 writes.

**Replanned at the return to design (D24 to D35).** Sections 10 to 13 divide the
five cross-system documents by D25's kinds, as one round (D30): the inventory of
what remains in them (10), the rules out of the three description documents (11),
`BUILD_AND_PACKAGING.md` and `RELEASING.md` dissolved into rules and handbooks (12),
and the documents naming the new layout, with D25's principle (13). Closeout, which
had not started, is renumbered from 10 to 14 and amended: a reference in the notes
above to task 10.n is now task 14.n. The new round's inventory is written before its
text moves and reviewed with the moves in the round's triage (D30, D34), its rows
governing sections 11 to 13 as round 1's govern sections 3 to 7. Sections 11 and 12
edit skills, scripts, and tests outside the inert paths, so their commits run the
functional pre-commit hooks.

## 1. Inventory of the root and workflow documents

Delivers the first half of the inventory (D2): `AGENTS.md`, `openspec/README.md`,
`agents/change-workflow.md`, `agents/domain.md`, and
`docs/development/ARCHITECTURE.md`, classified by D1's test, with destinations by
D3 and D8–D10, tags by D7 and D17–D19, and exceptions by D9. No guidance text moves.
Files: `openspec/changes/layer-engineering-guidance/inventory.md` (new).

- [x] 1.1 Create `inventory.md` with its sections table — columns `Source` (document
  and heading, or the part of a heading's text a split row covers), `Layer`, `Tags`,
  `Destination` (file, and heading where it joins one), `Reason`, `Ambiguous` (empty,
  or what the test did not decide) — and an opening paragraph saying the inventory
  is change history and that the corrected rows govern every later section (D2).
  Verify the file exists with that header.
  Note: one table per document under `## Sections`, each with the six columns; the
  opening gives the reading conventions (one layer per row, the destination
  shorthand, "stays", "neutralized", closeout rows, how exceptions are marked).
  Evidence: inspected.
- [x] 1.2 Classify every heading of `AGENTS.md` and `openspec/README.md` at every
  level, splitting a section into one row per layer its text holds (D1), the
  closeout parts one row per part with the part's layer and the layer of the rule it
  confirms (D8), and each exception the text states — a case selected, a shared rule
  overridden — marked as one, with where its table goes (D9). Verify by listing the
  two documents' headings (`grep -n '^#' AGENTS.md openspec/README.md`) and finding a
  row for each.
  Note: every heading has a row (Grep against the Source cells), fenced examples
  covered by rows of their own. Closeout parts 5, 7, and 8 are repository rows (D8),
  the rest workflow rows naming the layer of the rule each confirms, part 2's import
  rule split out as engineering, Python. One exception stated: the public case,
  selected.
- [x] 1.3 Classify every heading of `agents/change-workflow.md`,
  `agents/domain.md`, and `docs/development/ARCHITECTURE.md` the same way,
  including the workflow guide's links to this repository's documents and its step
  table's validation parts (D1's direction), and `ARCHITECTURE.md`'s engineering
  rules and the subsections filed under "Deterministic database-concurrency tests"
  (D10). Verify every heading has a row.
  Note: every heading has a row. The guide's further references to this repository
  (`dev`, protected branches, hook commands, the CI baseline, the clone's remote,
  bootstrap, evidence paths, waiver parts, `ROADMAP` examples) each have a
  repository row, neutralized in the guide.
- [x] 1.4 Verify: every row has a layer, tags from the tags the inventory proposes,
  a destination, and a reason; every row the test did not decide says why in
  `Ambiguous`; `git diff --stat` against the section's start shows only
  `inventory.md` changed; and `scripts/change-workflow run pre-commit
  layer-engineering-guidance` reports no failure but the two the preamble expects.
  End-to-end: none; the inventory changes no behaviour.
  Note: 196 complete rows, each with its layer as first tag and every tag in the
  inventory's list (Grep). The diff held `inventory.md`, this task list, and the
  change's index row set to `in implementation`. `run pre-commit` failed only on the
  two expected checks; index, tasks, skills, and strict OpenSpec passed. End-to-end:
  none confirmed, as planned. Owed by validation: nothing.

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
  Note: every heading of both documents has a row (fenced TOML comments included),
  split rows coming from full reads. Capability sections go beside thirteen
  capabilities, written `specs/<capability>/<file>`, a shorthand the citation check
  does not read. Four section 1 rows were amended in place (`ARCHITECTURE.md`'s
  "Local development" split; "Operator lifecycle controls" to `test-seams.md`; the
  deterministic-sequence rule to `system-tests.md`; the packaging check's reason as
  an engineering rule). Evidence: inspected.
- [x] 2.2 Give `BUILD_AND_PACKAGING.md`, `VALIDATION_RUNBOOK.md`, and `RELEASING.md`
  each a document-level row with its tags, and a row for each section holding
  general method, such as a uv convention that holds in any repository (D10).
  Verify each document has its row.
  Note: each document has a "The document as a whole" row, and every heading a row.
  `BUILD_AND_PACKAGING.md`'s general method goes to the packaging files; the three
  engineering rows inside documents D10 kept whole were decided at round 1's triage
  (D10 as amended). The runbook beyond its opening and sections 10 and 29 is
  classified by heading as procedure.
- [x] 2.3 Add a restatements table: every place a `change-*` or `guidance-review`
  skill, or `openspec/config.yaml`, restates or cites a guidance rule — the file and
  its section, the rule's source today, and the destination the rule moves to — so
  later sections re-point each citation and the loader change inherits the list
  (D11, D23). Verify by searching the skills and `openspec/config.yaml` for citations
  of the guidance documents and finding a row for each.
  Note: `## Restatements`, 57 rows, from Grep over the eleven skills and a reading of
  each skill's loading, planning, and checking steps and every bullet of
  `openspec/config.yaml`; uncited restatements are found by reading, not
  mechanically. The skills' own `dev`, `.snapshot/`, and make-target references are
  instructions naming this repository, not restatements; moving them is
  `extract-change-workflow-repository`'s.
- [x] 2.4 Add the proposed vocabulary: the engineering, workflow, and repository
  tag tables as D18 shapes them (`Tag | Kind | Description`, each layer's own tag as
  its first row), holding exactly the tags the rows of sections 1 and 2 use. Verify
  every tag used in a row appears in one table, and every table row is used.
  Note: `## Proposed vocabulary`; `configuration`, `packaging`, and `deployment`
  settled as engineering topics, `versioning` and the tool tags new. Every row's tags
  are in the tables and every table tag is used (Grep over 406 rows).
- [x] 2.5 Add the draft classification of the checks (D13): each check enforcing
  guidance — comment hygiene, history wording, local imports, decision
  destinations, version bumps, the capability and specification indexes, citations,
  public content, secrets, the pre-push check, the architecture and packaging
  checks, the workflow's default checks (change index, tasks, agent skills, strict
  validation), and the guidance check — with the rule it enforces, that rule's
  layer, and where the check runs. Verify every target `make check-repository`,
  `make check-packaging`, and `make pre-push` run has a row.
  Note: `## Draft classification of the checks`, 25 rows, every target the three run
  among them.
- [x] 2.6 Verify: sections 1 and 2 together give every heading of every document in
  `design.md`'s Context table but `docs/prompts/` a row; only `inventory.md`
  changed; `scripts/change-workflow run pre-commit layer-engineering-guidance`
  reports no failure but the two the preamble expects. End-to-end: none; the
  inventory changes no behaviour.
  Note: 406 complete rows; every heading of the five documents has a row (Grep).
  Only `inventory.md` and this task list changed. `run pre-commit` failed only on the
  two expected checks. End-to-end: none confirmed, as planned. Owed by validation:
  nothing.

Round 1's triage (reviews 29–31, the orchestrator's record 27; `design.md`, "Settled
at round 1's triage"):

- 31 O1a–O1g and 29 F1, fixed: the inventory is corrected by the owner's rules, its
  "Rules from round 1's triage" applying them row by row — 429 rows, `Ambiguous`
  holding only what a later triage settles. The dispositions amend D8 and D10.
  Evidence: inspected; `run pre-commit` failed only on the two expected checks.

Round 1's second review (review 48; validation of `23b54361c` waived by the owner,
the commit changing only change documents):

- 48 F1: the validation runbook stays outside the guidance set, with no frontmatter
  and no layer-table row; D10, its hard-case sample row, the inventory, and task 6.3
  say so.
- 48 F2: the hand-laid graph's `overrides` row goes beside its capability, in
  `openspec/specs/change-workflow/diagrams.md` (task 7.2).
- The change returned to planning, which replanned sections 3 onward against
  round 1's triage.

## 3. The workflow layer

Delivers the workflow layer (D1, D3, D8 as amended, D16–D19; 31 O1b, O1e, O1f):
`docs/guidance/workflow/` with its README and tag table, the closeout list with
roadmap currency and the guidance placement part, workflow material moved out of
the root documents and the workflow guide and deduplicated, `agents/domain.md`
removed, every citation re-pointed. Files: `docs/guidance/workflow/*.md` (new);
`AGENTS.md`; `openspec/README.md`; `agents/change-workflow.md`;
`agents/domain.md` (removed); `openspec/specs/market-change-workflow/README.md`;
`openspec/specs/change-workflow/README.md`; `openspec/specs/planning-governance/spec.md`
(Evidence only); `.agents/skills/change-*/SKILL.md`,
`.agents/skills/guidance-review/SKILL.md`; `.agents/workflow.toml`.

- [x] 3.1 Write `docs/guidance/workflow/README.md`: frontmatter `tags: [workflow]`;
  the layer model — the three layers, D1's test, and the link direction, citing
  CW-g7lt and CW-d2rw (D18 as recorded); what the layer holds and how its files are
  organized (flat, organization carrying no meaning, D19, CW-n6dm); and its
  `## Tags` table, `workflow` its first row, holding exactly the tags the layer's
  files carry as "Files and their tags" gives them (D18). The step and role tags no
  file carries (`design`, `plan`, …, `owner`, `skills`, `engine`, `records`) are
  left out and listed in the section's notes, the open question the round's triage
  settles. Verify every tag a workflow file carries is in the table, and every table
  row is carried.
  Note: the table holds `workflow`, `openspec`, `changes`, and `closeout`, each
  carried; the step and role tags stay out (D24). Evidence: inspected (Grep over the
  frontmatter).
- [x] 3.2 Write `docs/guidance/workflow/closeout.md` (D8 as amended, D16):
  frontmatter; the ordered list of the workflow's parts — comment hygiene, import
  placement, documentation compliance, narrative compression, roadmap currency,
  campaign index currency, the repository's own closeout parts as its root guidance
  names them, promotion, guidance placement, documentation citations, archival —
  each part under its own heading carrying its text from
  `openspec/README.md`, "Plan closeout requirements", with every repository command and
  path replaced by what the repository's guidance names (roadmap currency updates
  "the repository's roadmap", 31 O1f); an engineering principle inside a part, such
  as completion not being proved by the change's own suites, cited from the part and
  left to its engineering row (31 O1g); the guidance placement part as D16 words it;
  and the promotion story from `AGENTS.md`'s "Cross-references must resolve" (D6).
  Verify no make target, no repository path, and no link to a file the inventory
  tags `repository` appears in it.
  Note: ten workflow parts under their headings, the repository's own parts at
  position 7 by role; checks named by role, their commands in `openspec/README.md`
  (task 3.4). Grep finds no make target, repository path, or repository-tagged link
  in any workflow file. Part 6's index-check account merged into the guide (its
  citation now CW-jyff, task 3.14); part 10's tombstone account went to
  `market-change-workflow`'s "The closing checks". Evidence: inspected.
- [x] 3.3 Move the rest of the workflow material to the files the corrected
  inventory names — `working-model.md`, `openspec-documentation.md`, `changes.md`,
  `change-references.md`, and `terms.md` — each with the frontmatter "Files and
  their tags" gives, the roadmap's and the capability index's roles among them
  (31 O1f); delete the moved text from `AGENTS.md`, `openspec/README.md`, and
  `agents/domain.md`, keeping in place, under their final headings, what the
  inventory leaves there. Verify each workflow row of the inventory sits in its
  destination and no longer in its source.
  Note: every workflow row of the four source tables sits in its destination and is
  gone from its source. `openspec/README.md` keeps the pin, its placement table, "The
  index check", "This repository's closeout parts", and "Current capability
  documentation" (with the capability index check); "Implementation completion
  checklist" and "Contributor workflow" merged into `working-model.md`. Engineering
  rows parked in `AGENTS.md` were moved by sections 4 and 5. Evidence: inspected.
- [x] 3.4 Leave this repository's closeout parts — packaging and end-to-end pipeline
  evidence — in `openspec/README.md` under `## This repository's closeout parts`,
  naming the commands each runs; and add to `AGENTS.md` the rows naming that section
  and this repository's roadmap, `docs/development/ROADMAP.md`, so closeout,
  planning, and review find both through the root guidance before section 6
  rewrites it (D8 as amended). Verify both rows' links resolve, the first to its
  heading.
  Note: the section also tables the commands the workflow's parts name by role.
  `AGENTS.md`'s "Where the guidance lives" gained the two rows (the roles table,
  task 6.1). Both links resolve. Evidence: inspected.
- [x] 3.5 Remove `agents/domain.md` once its rows have moved (31 O1e), and
  re-point its citations, `AGENTS.md`'s "Domain docs" included. Verify the file is
  gone and `grep -rn 'agents/domain.md'` over the tracked tree outside
  `openspec/changes/` finds nothing.
  Note: removed with `git rm`; Grep outside `openspec/changes/` finds nothing.
  `align-package-paths-with-layers`' design and proposal now say "the domain docs
  (since removed)". Evidence: `make check-doc-citations CHANGE=` (task 3.10).
- [x] 3.6 Give `agents/change-workflow.md` frontmatter tagging it `workflow`,
  and move what the inventory finds of this repository in it — its links to
  `market-change-workflow`, its step table's validation parts, `dev`, the hook
  commands, the CI baseline, the clone's remote and evidence paths, and the rest the
  inventory's rows name — to `openspec/specs/market-change-workflow/README.md`,
  stating it there in this repository's terms, and neutralize the guide's text
  (D1's direction). Verify the guide links to no file the inventory tags
  `repository`.
  Note: every repository row of the guide (rows 259–281) is neutralized in the guide
  and stated in `market-change-workflow`'s README (the evidence paths, `make
  validate-parallel`, `dev` as a prerequisite's base, the orchestrator's merges, the
  CI baseline, the completion script, the hook commands, `make check-change`'s
  unrestricted run, the five closing rules). Grep finds no repository name in the
  guide. The tagging is undone by the handbook (task 3.13). Evidence:
  `test_change_workflow_assumptions.py` (unit).
- [x] 3.7 Deduplicate the workflow material as the preamble says (31 O1b): merge
  agreeing copies, and list in the section's notes each differing pair the
  inventory's `Ambiguous` cells name for this layer, with both forms and the
  proposed text, and each contradiction a non-guidance document now holds. Verify
  every duplicate row this section moves is merged or listed.
  Note: rows 149, 187, 199, 235, 240 and part 6's account are merged or listed under
  "Section 3's differing pairs"; the root `README.md`'s contributor-workflow link
  re-pointed; no other contradiction found. Evidence: inspected.
- [x] 3.8 Re-point every citation of moved workflow material, by name and never by
  part number (D8): the skills, from the inventory's restatements table, including
  `change-closeout`'s count of the parts and their order; `change-workflow`'s README
  and spec text; `openspec/specs/planning-governance/spec.md`'s Evidence, outside
  the archive's merge (D14); and every other document citing
  `openspec/README.md`, "Plan closeout requirements", or another moved heading. The
  skills' restatements stay as they are (D11). Verify `grep -rn` over the tracked
  tree outside `openspec/changes/archive/` and `docs/prompts/` finds no citation of
  a heading this section removed.
  Note: re-pointed: the eight workflow skills (`change-closeout` counting the parts by
  name, with a guidance placement paragraph), `planning-governance`'s Evidence,
  `openspec/specs/README.md`, `BUILD_AND_PACKAGING.md`, the root `README.md`, the
  change index's history note, three check scripts' docstrings, a `Makefile`
  comment, a test fixture string, and 48 citations in 47 other changes' `tasks.md`
  with other changes' design and proposal lines. Grep outside the archive,
  `docs/prompts/`, and this change finds no citation of a removed heading. Evidence:
  `make check-agent-skills` OK.
- [x] 3.9 Add each new `docs/guidance/workflow/` file to `load.common` in
  `.agents/workflow.toml` by path, keeping its comment current, so later sessions on
  the branch read them (design, "Implementation cadence"); and add each repository
  path a skill now names to `openspec/specs/market-change-workflow/README.md`'s "How
  this repository provides the workflow's roles". Verify `scripts/change-workflow
  config load common` prints the new files, and `pytest -q
  scripts/tests/test_change_workflow_assumptions.py` (unit) passes.
  Note: the README's provisions name the new files. The step table denies every step
  `.agents/workflow.toml`; the owner confirmed the refusal stands, so the
  orchestrating session made the edit on their word (the seven workflow files after
  `openspec/README.md`), as it made every later edit of that file. `config load
  common` prints them; `test_change_workflow_assumptions.py`,
  `test_change_workflow_config.py`, `test_post_compaction_context.py` (unit): 91
  passed.
- [x] 3.10 Verify the section: `make check-agent-skills`; `make check-doc-citations`
  run unscoped reports nothing it did not report before the section; `pytest -q
  scripts/tests/test_change_workflow_assumptions.py scripts/tests/test_change_workflow_config.py`
  (unit); and `scripts/change-workflow run pre-commit layer-engineering-guidance`,
  whose functional hooks run every suite, reports no failure but the two the
  preamble expects. End-to-end: none; no pipeline scenario reads guidance, and none is
  owed.
  Note: `make check-agent-skills` OK; unscoped citations report only failures older
  than the section, its own breaks fixed; unit suites 91 passed; `run pre-commit`
  (relock, `make check-packaging`, `make test`, defaults) passed but for the two
  expected checks. End-to-end: none confirmed, as planned. Owed by validation:
  nothing.

Section 3's differing pairs (31 O1b), accepted as written at round 2's repeat triage
(72 F1; `design.md`): the documents are promoted at closeout, after the code's last
review, and "implemented" no longer includes them (rows 149, 235, 240); Implement's
and the checklist's completion lists are one list in `working-model.md` (rows 235,
240); the citation check runs after promotion, `closeout.md`'s Promotion telling the
story (rows 182, 184); OpenSpec's layout and the capability index's role merged
(rows 149, 199); a change's records (row 187) and the index check (part 6) merged
into the guide; and the move's smaller neutralizations.

Round 2's triage (reviews 56, 57, 58; `design.md`, "Settled at round 2's triage"):

- Fixed in the triage session: the workflow README's "What the workflow's guidance
  holds" (58 O5), dropping its claim that the guide is guidance (58 O7);
  `closeout.md`'s opening cites the companion and gains "The repository's own
  closeout parts" (58 O5, O4); `working-model.md` opens with its subject (58 O2);
  `AGENTS.md`'s "Working model" removed (58 O9); phrases relative to the migration
  rewritten (58 O3); the root `README.md` points to `AGENTS.md` and validates with
  the pinned validator (58 O8).
- Tasks added: 4.7 (58 O1), 5.9 (58 O3), 5.10 (58 O6), 6.5's amendment (58 O1),
  9.4's amendment (56 F1).
- The change returned to planning for the workflow's operator handbook (58 O7; D3 as
  amended): tasks 3.11–3.16.

Appended at round 2's triage's return to planning: the workflow's operator handbook
(D3 as amended; 58 O5, 58 O7). Section 3 is complete again only when these are. They
undo task 3.6's tagging of the guide, which stands as done. Files:
`agents/change-workflow.md`, moved to `docs/change-workflow-handbook.md`;
`docs/guidance/workflow/*.md`; `openspec/specs/change-workflow/README.md`, and its
`spec.md`'s Evidence; `openspec/specs/market-change-workflow/README.md`; `AGENTS.md`;
`.agents/skills/*/SKILL.md`; `scripts/change_workflow/next_step.py`,
`scripts/tests/test_change_next_step.py`, `scripts/tests/test_change_workflow_records.py`;
the active changes' documents under `openspec/changes/` that cite the guide;
`openspec/changes/layer-engineering-guidance/inventory.md`.

- [x] 3.11 Reclassify the inventory's rows for the guide (its `agents/change-workflow.md`
  table) by 58 O5's test: each statement's home is the workflow's specification or
  its companion (wrong if the engine or a skill behaved otherwise), the workflow's
  guidance (wrong if a change's work product were otherwise), or the handbook
  (telling the owner what to do or type), with the destination file and heading,
  the reason naming the test, and `Ambiguous` saying where the test does not decide;
  and drop the guide from "Files and their tags". Verify every row of the guide's
  table names one of the three homes.
  Note: 51 rows by statement group, each naming its home and a reason by the test,
  section 1's rows kept beneath as superseded history; the guide is dropped from
  "Files and their tags". The audit against `spec.md` and the companion was made by
  three read-only helper subagents. Evidence: inspected.
- [x] 3.12 Move the guide's agent-facing content by those rows (58 O7): a guidance
  statement into the `docs/guidance/workflow/` file its row names — a new file there
  carrying its frontmatter, joining the workflow table's tags (D18) and `load.common`
  by path; a statement of what the workflow does that a `change-workflow`
  requirement already states, deleted with the handbook citing the requirement where
  the owner needs it (31 O1b); an explanation the requirements do not hold, into
  `openspec/specs/change-workflow/README.md` under the heading its row names; and a
  statement of what the workflow does that no requirement states and that is no
  explanation, given a proposed home — a requirement added to this change's
  `change-workflow` delta where 58 O5's test reads it as the specification's, or the
  guidance file where it reads it as guidance — and listed with its source form in
  the section's notes, for the round's triage to review with the owner, as 31 O1b's
  differing pairs are; the handbook cites the proposed home (72 F2). Verify each
  moved row sits in its destination and no longer in the guide.
  Note: no new guidance file. Into the guidance: the `Owed by validation:` line
  (`working-model.md`, "Plan") and "One change per branch" (`changes.md`). Into the
  companion: the engine's details under "The command and its tiers", "Reviews are
  files", "The intervention ledger", and "Restrictions bind unattended runs only".
  Six proposed requirements in the delta, listed under "Section 3's proposed homes".
  Evidence: strict validation in `run pre-commit` (task 3.15).
- [x] 3.13 Make the handbook (D3 as amended, 58 O7): move the guide with `git mv` to
  `docs/change-workflow-handbook.md`, beside `docs/operator-handbook.md`; remove its
  frontmatter, so it is outside the guidance set (D21); keep only what the owner
  needs to know — starting each step, orchestrating a change, reading a round,
  waivers and directions, the ledger as the record of the owner's corrections —
  rewritten for the owner where a passage addressed agents; and embed the workflow's
  diagrams from `openspec/specs/change-workflow/diagrams/` by link. Remove the empty
  `docs/agents/` directory. Verify the handbook carries no frontmatter, names no
  rule a step must follow without citing its home or its proposed home (72 F2), and
  embeds the diagrams.
  Note: moved with `git mv` and rewritten for the owner, with no frontmatter,
  embedding the graph, step-run, state, and engine-parts diagrams; restructured at
  round 3's triage, citing no requirement id (88 O1–O4). Corrected from the guide:
  `make change-cost` marks inseparable dollars partial; a workspace round view holds
  review, validation, triage, and implementation (CW-78ul). Git holds nothing of
  `docs/agents/` (`rmdir` was refused). Evidence: inspected.
- [x] 3.14 Re-point every citation of the guide to where its statement now lands:
  `AGENTS.md`'s "Where the guidance lives" table (the handbook is no workflow
  guidance) and "Agent skills"; every skill citing it; `change-workflow`'s README
  and `spec.md`'s Evidence; `market-change-workflow`'s README, its statement of how
  this repository provides the workflow's roles included;
  `scripts/change_workflow/next_step.py`'s message and the two tests naming the path;
  and the active changes' documents under `openspec/changes/` outside the archive.
  Verify `grep -rn 'docs/agents/'` over the tracked tree, outside
  `openspec/changes/archive/` and this change's own documents, finds nothing.
  Note: re-pointed: `AGENTS.md`; the skills to the requirement stating each rule
  (CW-q3dm, CW-d5ac, CW-t9bx, CW-9pbk, CW-r8vz, CW-k2rv, CW-hak6, CW-e7lm) or the
  handbook; `change-workflow`'s README and Evidence; `market-change-workflow`'s
  provisions, the handbook read by no step; `closeout.md`'s index-check citation to
  CW-jyff; `next_step.py`'s message and the two tests; eight other changes' documents
  and the change index's history notes. Grep finds no `docs/agents/` outside the
  archive and this change. Evidence: the scripts suites (task 3.15).
- [x] 3.15 Verify the appended tasks, and round 2's triage fixes committed unchecked
  with the return: `make check-agent-skills`; `pytest -q
  scripts/tests/test_change_next_step.py scripts/tests/test_change_workflow_records.py
  scripts/tests/test_change_workflow_assumptions.py scripts/tests/test_change_workflow_config.py`
  (unit); `make check-doc-citations` run unscoped reports nothing it did not report
  before section 3; `scripts/change-workflow config load common` prints every
  workflow guidance file; and `scripts/change-workflow run pre-commit
  layer-engineering-guidance`, whose functional hooks run every suite, reports no
  failure but the two the preamble expects. End-to-end: none; no pipeline scenario
  reads guidance or the handbook, and none is owed. Run after task 3.16, which it
  verifies too.
  Note: `make check-agent-skills` OK; the four suites ran inside `make
  test-release-tooling`, 2867 passed (unit), a direct `pytest` run being refused;
  unscoped citations report only failures older than section 3; `config load common`
  prints the seven workflow files and checks the whole configuration (CW-w8ne),
  standing in for the refused `check config`; `run pre-commit`: functional tier
  passed, strict validation "is valid", `make check-repository` failing only on the
  two expected checks. End-to-end: none confirmed, as planned. Owed by validation:
  nothing.
- [x] 3.16 State closeout's rule in inert paths, and give the workflow default inert
  paths (71 O1; design, "Settled at round 2's repeat triage"). In this change's
  `change-workflow` delta, add CW-pkug as modified — closeout changes only the
  repository's inert paths and changes' records, and a closeout part that would
  change any other path returns the change to implementation — keeping its scenario
  and adding one where a part would re-point a citation inside a skill; and CW-n7ra
  as modified — where a repository declares no inert paths, the workflow's default
  applies, `openspec/` and every Markdown file (`**/*.md`), and a declaration, an
  empty one included, replaces the default — with a scenario for a repository
  declaring none. Rewrite `closeout.md`'s opening to say closeout changes only the
  repository's inert paths, citing CW-pkug by id, and `change-closeout`'s
  restatement ("changes documentation only") to match. Add `AGENTS.md` to
  `inert-paths` in `.agents/workflow.toml`: the step table denies every step that
  file, so the orchestrating session makes the edit on the owner's word, as task
  3.9's, and the section checks it is in the worktree before committing. List both
  modified requirements' text in the section's notes for the round's triage, as
  task 3.12's proposed homes. Verify `scripts/change-workflow openspec validate
  layer-engineering-guidance --strict` passes and `scripts/change-workflow check
  config` accepts the configuration.
  Note: CW-pkug renamed "Closeout changes only inert paths" and modified, CW-n7ra
  modified with the default, each with its scenarios, in the delta; round 3's triage
  widened both to exempt the archive's own writes (71 O1). `closeout.md`'s opening
  cites CW-pkug and `change-closeout` restates it; the orchestrating session added
  `AGENTS.md` to `inert-paths`. Verified through `run pre-commit`'s strict
  validation and `config load common`, the direct forms being refused (task 3.15).
  The two tests naming an undeclared configuration's Markdown file as not inert were
  flipped by task 8.4.

Round 2's repeat triage (reviews 71, 72, 73; `design.md`, "Settled at round 2's
repeat triage"): 72 F1, section 3's pairs accepted as written; 72 F2, an agent rule
no requirement states is given a proposed home (tasks 3.12, 3.13); 71 O1, closeout
in inert paths and the default inert paths (tasks 3.16, 8.4, 14.9's amendment);
71 O2, the handbook move as tasks 3.11–3.15; 73 R1, deferred to workflow
maintenance after this change merges.

Section 3's proposed homes (72 F2, 71 O1), all kept at round 3's triage (`design.md`,
"Settled at round 3's triage"); their texts are in the `change-workflow` delta:
CW-s7rq (a skill restates guidance no stricter than its source), CW-b5cf (an
unattended step's calls take the forms its rules match), CW-e3gt (a step checks its
entry before it works), CW-o9hd (the orchestrating session tells the owner what it
starts and leaves the owner's actions to them), CW-t2lw (a triage's records take
their written shapes), CW-w6vy (waivers are recommended and recorded where they are
given); `changes.md`'s "One change per branch" and `working-model.md`'s `Owed by
validation:` line as guidance; CW-pkug renamed and modified, and CW-n7ra modified.
The guide's engine details stay the companion's, and the refusals of `round-view`,
`round-done`, and `change-clone-remove` the handbook's.

Section 3's re-run notes: which repository owns the handbook once the workflow moves
out is `extract-change-workflow-repository`'s design; the handbook names no
repository document.

Round 3's triage (review 86, validation 87, the owner's notes 88; `design.md`,
"Settled at round 3's triage"), fixed in the triage session:

- 72 F2: every proposed home kept.
- 71 O1: CW-pkug exempts the archive's own writes — the change's documents and their
  move, its index row, its merged deltas — with a scenario for `inert-paths = []`;
  CW-n7ra, `closeout.md`, and `change-closeout` match.
- 86 F1: task 14.9 amended with the six requirements' index entries; the proposal's
  "Knowledge to promote" gains its 72 F2 line.
- 88 O1–O4: the handbook restructured in the order the owner needs it, citing no
  requirement id (88 O2).
- Evidence: `run pre-commit`, functional tier and defaults passed, `make
  check-repository` failing only on the two expected checks. End-to-end: none.

Round 3's repeat pass (review 100, validation 97, the owner's notes 99 — none —, the
orchestrating session's record 98):

- 100 F1: the handbook's opening describes the lifecycle through the merge and where
  the workflow stops (`design.md`, "Settled at round 3's triage").
- 98 R1: deferred, with 73 R1, to workflow maintenance after this change merges.
- Evidence: `run pre-commit` (inert paths only) passed but for the two expected
  checks. End-to-end: none.

## 4. The engineering layer: testing

Delivers the engineering layer's README and its testing files (D1, D3, D7, D17–D19;
31 O1a, O1b, O1c, O1g): the fifteen files "Files and their tags" tags `testing` —
`testing.md`, `test-levels.md`, `test-seams.md`, `test-determinism.md`,
`integration-tests.md`, `system-tests.md`, `test-doubles.md`, `contract-fixtures.md`,
`conformance-tests.md`, `boundary-changes.md`, `migration-tests.md`,
`concurrency-tests.md`, `testing-python.md`, `helm-render-tests.md`, and
`ansible-checks.md` — general rules given neutral examples, moved out of the
repository documents and deduplicated, every citation re-pointed. Files:
`docs/guidance/engineering/README.md` and those files (new); `AGENTS.md`;
`docs/development/ARCHITECTURE.md`, `TESTING.md`, `VALIDATION_RUNBOOK.md` only
where 31 O1b brings it in line; skills and documents citing moved text;
`.agents/workflow.toml`.

- [x] 4.1 Write `docs/guidance/engineering/README.md`: frontmatter `tags:
  [engineering]`; what the layer holds; its organization (D19); and its `## Tags`
  table, `engineering` its first row, holding the tags this section's files carry
  (D7, D18); section 5 completes it. Verify every tag a file of this section
  carries is in the table.
  Note: `engineering`, `testing`, `dependencies`, `persistence`, `python`, `helm`,
  and `ansible`, each carried; the organization paragraph states D7's split beside
  D19. Evidence: inspected.
- [x] 4.2 Move the engineering testing material to the fifteen files, each with the
  frontmatter "Files and their tags" gives, each general rule given a neutral
  example in place of this repository's (31 O1a), each language or tool form in the
  file its tags give (D7, 31 O1c), and the operator-control rule's test half in
  `test-seams.md` (31 O1g); this repository's statement of each rule stays as its
  instance and cites the engineering file. Verify each engineering testing row of
  the inventory sits in its destination, and no file of this section names a
  package, service, document, or make target of this repository.
  Note: every engineering testing row (`TESTING.md`'s, `ARCHITECTURE.md`'s testing
  rows, `AGENTS.md`'s "Tests and diagnostics" rule, part 8's reason) sits in its
  file, checked row by row; Grep finds no repository name, and every link stays in
  the directory. Evidence: inspected.
- [x] 4.3 Deduplicate the testing material as the preamble says (31 O1b), listing
  among the differing pairs the test levels the skills name (unit, library
  integration, application integration, system) against `TESTING.md`'s (unit,
  integration, smoke, system), which the restatements table records. Verify every
  duplicate row this section moves is merged or listed.
  Note: listed under "Section 4's differing pairs"; rows 162, 370, and 563 are
  section 5's (task 5.5). The non-guidance documents agree with the moved rules.
  Evidence: inspected.
- [x] 4.4 Delete the moved text from its sources, leaving in each what the inventory
  keeps, and re-point every citation of what moved, skills included. Verify `grep
  -rn` over the tracked tree outside `openspec/changes/archive/` and
  `docs/prompts/` finds no citation of a heading this section removed, and no
  engineering file links to a file the inventory tags `workflow` or `repository`
  (D1's direction).
  Note: `TESTING.md` keeps every heading but "Coverage Contract Between Levels", each
  reduced to its instances citing the engineering file; `ARCHITECTURE.md`'s testing
  passages cite the files. Re-pointed: the test-level citations in six skills
  (restatements kept, D11), the change index, `site-capacity`'s companion,
  `ROADMAP.md`, `openspec/README.md`'s placement row, the root `README.md`,
  `market-change-workflow`'s provisions row, and seventeen test modules' and e2e
  helpers' docstrings. Grep finds no citation of the removed heading outside the
  archive, `docs/prompts/`, and this change. Evidence: `make check-agent-skills` OK;
  the edited modules ran in task 4.6's suites.
- [x] 4.5 Add the README and each new testing file to `load.common` by path. Verify
  `scripts/change-workflow config load common` prints them.
  Note: made by the orchestrating session on the owner's standing word (seq 74);
  `config load common` prints the sixteen engineering files. Evidence: inspected.
- [x] 4.6 Verify the section as task 3.10 does. End-to-end: none; no pipeline
  scenario reads guidance, and none is owed.
  Note: `make check-agent-skills` OK; unscoped citations report only failures older
  than section 3; `run pre-commit`, after both fresh-context checks' fixes:
  functional tier (`make test-release-tooling`, 2867 passed, unit) and defaults
  passed, `make check-repository` failing only on the two expected checks.
  End-to-end: none confirmed, as planned. Owed by validation: nothing.
- [x] 4.7 Before 4.6's verification (58 O1): move the argument of
  `openspec/README.md`'s "End-to-end pipeline" part — that a change is not complete
  because its own suites pass, and what the end-to-end tier catches — to the
  engineering testing file 31 O1g names; drop its blocker sentence, which restates
  `working-model.md`'s "any unrun check is disclosed"; and leave the part as one
  declarative statement of what this repository's closeout records (the run at the
  closeout's code, its result, the scenarios exercising the change), citing both.
  Verify the part holds no instruction or argument beyond that statement.
  Note: the argument is `testing.md`'s "Work is not complete because its own tests
  pass"; the part is one sentence citing it and `working-model.md`'s "Implement",
  worded as "Section 4's differing pairs" records. Evidence: inspected.

Section 4's differing pairs (31 O1b), accepted at round 4's triage (`design.md`,
"Settled at round 4's triage"):

- The test levels' names: `test-levels.md` keeps unit, integration, smoke, and
  system, and names integration's three forms — application, library, and
  external-process integration — so the skills' names are integration's forms; the
  skills keep their restatement (D11), citing `test-levels.md`, and leave out smoke.
- A test double mirrors its producer (row 511): merged into `test-doubles.md`.
- An observation's outcome (row 666): `system-tests.md` states made, failed, or
  unproven, and adds that an observation is never inferred from another; the
  runbook's other qualification rules stay its own.
- Wording the move changed beyond neutral examples: `testing.md` reads "a change" as
  any unit of work; `helm-render-tests.md` states one entry point for every chart's
  render tests as a rule; `system-tests.md` reaches a deadline by moving the
  record's time into the past and stepping the loop.
- The End-to-end pipeline part: one sentence recording the run at the closeout's
  code (`make run-e2e`, `make fetch-e2e-logs`), its result, and the scenarios; a
  failed run returns the change to implementation; a run that could not be made is
  recorded as unrun, naming its cause and owner.

## 5. The engineering layer: everything else

Delivers the rest of the engineering layer (D1, D3, D6, D7, D10 as amended,
D17–D19; 29 F1; 31 O1a, O1b, O1c, O1e, O1g): the remaining files "Files and their
tags" gives — `documentation.md`, `rules.md`, `comments.md`, `diagrams.md`,
`dependencies.md`, `dependencies-python.md`, `implementation.md`,
`implementation-python.md` only if this section finds the route pattern's Python
form, `repository-content.md`, `terms.md`, `persistence.md`, `migrations.md`,
`configuration.md`, `configuration-python.md`, `definition-documents.md`,
`deployment.md`, `kubernetes.md`, `helm.md`, `packaging.md`, `packaging-python.md`,
`packaging-uv.md`, `packaging-hatchling.md`, `packaging-docker.md`, `versioning.md`,
and `versioning-python.md` — with the exceptions framework, deduplicated, every
citation re-pointed. Files: those files (new); `docs/guidance/engineering/README.md`;
`AGENTS.md`; `docs/development/ARCHITECTURE.md`, `TESTING.md`,
`DEPLOYMENT_AND_CONFIG.md`, `BUILD_AND_PACKAGING.md`, `RELEASING.md`;
`docs/operator-handbook.md` and `VALIDATION_RUNBOOK.md` only where 31 O1b brings them
in line; skills and documents citing moved text; `.agents/workflow.toml`.

- [x] 5.1 Move the remaining engineering material to its files, each with the
  frontmatter "Files and their tags" gives, each general rule given a neutral
  example (31 O1a), each tool or language form in the file its tags give (D7,
  31 O1c): the project layout's Python, uv, and Hatchling rows to their packaging
  files, this repository's selection of Hatchling staying (29 F1); `RELEASING.md`'s
  versioning policy to `versioning.md` and `versioning-python.md`, its repository
  reasons staying and citing them (D10 as amended); and the operator-control rule's
  production half to `implementation.md` (31 O1g). Verify each remaining engineering
  row of the inventory sits in its destination, and no file of this section names a
  package, service, document, or make target of this repository.
  Note: twenty-four files, `implementation-python.md` not created (round 4's triage,
  row 384). Every remaining engineering row sits in its file, checked row by row;
  the rules the packaging checks enforce are each stated in a packaging file. The
  route pattern's diagram moved with `git mv` beside `implementation.md`, flat
  (`mkdir` was refused), redrawn neutrally. Grep finds no repository name, and every
  link stays in the directory. Evidence: inspected.
- [x] 5.2 Write `rules.md` from "Amend a rule or comply" as a framework for when an
  exception to shared guidance is expected — exceptions expected once other
  repositories change the shared guidance, the rule's purpose of stopping an owner
  from declaring everything an exception kept — proposing its wording in the
  section's notes for the round's triage to review (31 O1e, D9). Verify the notes
  hold the proposed wording beside the source's.
  Note: `rules.md`'s "Amend a rule or comply", "When an exception is expected", and
  "What an exception is not", accepted at round 4's triage; it names no table or
  workflow requirement, an engineering file citing no workflow file. Evidence:
  inspected.
- [x] 5.3 Write what may enter a repository (D6) in `repository-content.md`: what
  holds in every repository, what a public repository additionally refuses, and
  what a private one may hold — the last limited to what a private repository may
  hold that a public one may not, the one piece of new guidance this change writes —
  from `AGENTS.md`'s "Public repository discipline", with "Cross-references must
  resolve"'s rule in `documentation.md`. Verify the private-repository part adds no
  obligation.
  Note: "In every repository", "In a public repository" (with the private-dependency
  rule and the secret-canary method), and "In a private repository", which ends
  "Nothing here obliges a private repository to hold any of it"; the citation rule
  is `documentation.md`'s "Citations resolve". Evidence: inspected.
- [x] 5.4 Complete the engineering README's `## Tags` table with the tags this
  section's files carry (D18). Verify every tag an engineering file carries is in
  the table, and every table row is carried.
  Note: twenty-one rows — `engineering`, eleven topics, seven tools; every tag the
  forty files carry is in the table and every row carried. Evidence: inspected.
- [x] 5.5 Deduplicate as the preamble says (31 O1b). Verify every duplicate row this
  section moves is merged or listed.
  Note: listed under "Section 5's differing pairs"; the two contradicting
  non-guidance documents (`e2e-tests/README.md`'s `.env` layer, the operator
  handbook's opening) were fixed at round 4's triage. Evidence: inspected.
- [x] 5.6 Delete the moved text from its sources, leaving in each what the inventory
  keeps, and re-point every citation of what moved, skills included. Verify as task
  4.4 does.
  Note: each source keeps its instances citing the engineering file. Headings
  removed: `AGENTS.md`'s "Never enters this repository" and "Referring to work that
  is not here"; `ARCHITECTURE.md`'s "No speculative guard code" and "Prefer an
  existing library"; `DEPLOYMENT_AND_CONFIG.md`'s "Reconciliation follows the
  document, not the process". Re-pointed: five skills, the check scripts' docstrings
  and messages, a `Makefile` comment, three modules' docstrings,
  `physical-provisioning`'s companion, `market-change-workflow`'s provisions,
  `openspec/README.md`'s provenance row, and three other changes' documents. Grep
  finds no citation of a removed heading. Evidence: `make check-agent-skills` OK; the
  functional suites passed (task 5.8), though no test reads the re-pointed
  docstrings or messages.
- [x] 5.7 Add each new file to `load.common` by path. Verify `scripts/change-workflow
  config load common` prints them.
  Note: made by the orchestrating session (seq 74); `config load common` prints the
  forty engineering files. Evidence: inspected.
- [x] 5.8 Verify the section as task 3.10 does. End-to-end: none; no pipeline
  scenario reads guidance, and none is owed.
  Note: `make check-agent-skills` OK; unscoped citations report only older failures;
  `run pre-commit`, run again after the fresh-context check's fixes: functional tier
  and defaults passed, `make check-repository` failing only on the two expected
  checks. End-to-end: none confirmed, as planned. Owed by validation: nothing.
- [x] 5.9 Before 5.8's verification (58 O3): `documentation.md` states that
  permanent documentation and guidance describe the system they apply to
  declaratively and read as timeless even while they change constantly, with no
  wording relative to a migration or a planned change. Verify the rule is in
  `documentation.md` and no file of sections 3 to 5 phrases guidance relative to
  this change's move.
  Note: `documentation.md`'s "Permanent documents describe the current state",
  merged with rows 141, 236, 443, and 520; Grep of `docs/guidance/` finds no wording
  relative to this change's move. Evidence: inspected.
- [x] 5.10 Before 5.8's verification (58 O6): in `docs/guidance/workflow/closeout.md`,
  each part names and links the rules it confirms, each to its own layer's file —
  "Comment hygiene" the engineering comment rule (`comments.md`) and the workflow's
  change-references rule separately, "Documentation citations" and "Campaign index
  currency" the engineering citation rule (`documentation.md`), "Import placement"
  the import rule (`dependencies-python.md`) — and "Documentation compliance" also
  confirms the permanent documents the change wrote against `documentation.md`'s
  current-state rule (5.9), besides placement; `change-closeout`'s restatement is
  re-pointed to match (D11). Verify every rule a part names is linked to a file of
  its layer, and `make check-agent-skills` passes.
  Note: each part links its rules at their headings, and `change-closeout` cites the
  same files; `changes.md`'s "Defects found during a change" links
  `implementation.md#composition-from-one-component`. `make check-agent-skills` OK.
  Evidence: inspected.

Section 5's differing pairs (31 O1b, 31 O1e), accepted at round 4's triage
(`design.md`, "Settled at round 4's triage"):

- The exceptions framework (row 146): `rules.md` as task 5.2 records; `AGENTS.md`
  kept "amend the rule first or make the work comply", declaring an exception only
  as `rules.md` says.
- The dependency questions and import sentences (rows 162, 368, 370): merged into
  `dependencies.md` and `dependencies-python.md`, the sources citing them.
- Validate before the release (row 563): merged into `definition-documents.md`, the
  `Recreate` reason made conditional.
- Current state and provenance (rows 141, 152, 204, 236, 443, 520): merged into
  `documentation.md`.
- Wording that changes what a rule says: `implementation.md`'s authority test states
  as rules what the source gave through an instance; `configuration.md`'s pod
  environment rule is narrower than the source (row 531); `documentation.md` defines
  "permanent document"; `migrations.md` states generally that the application starts
  only once the migration succeeds; `kubernetes.md` states `enableServiceLinks` as a
  rule for a pod whose loader reads a prefixed override layer; `helm.md` leaves out
  "`null` removes a key"; `packaging.md` derives the set of internal packages from
  the lock; `packaging-uv.md` adds "No source path to a sibling" and a lock's
  currency; `versioning.md` drops the link to semver.org.

Round 4's triage (review 109, validation 110, owner's notes 111; `design.md`,
"Settled at round 4's triage"):

- 109 F1: `packaging.md`'s "Nothing is maintained by hand" is against aggregate
  lists (recast at round 5, 126 F1).
- 109 F2: the dormant-validator fixture rule is dropped from `contract-fixtures.md`
  and `testing-python.md`.
- Section 4's open pair: `system-tests.md` adds that an observation is never
  inferred from another.
- Section 5's open items: `packaging-uv.md` takes the relock-to-revision rule;
  `e2e-tests/README.md` puts `.env` values in the environment layer; the operator
  handbook cites `definition-documents.md`; no `implementation-python.md`.
- 111 O1: `test_change_workflow_assumptions.py` reads a directory the guidance
  provision names, ending in `/`, as every Markdown file beneath it, with a unit
  test; the provisions row names `docs/guidance/`.
- 111 O4 and O2 amend tasks 6.1, 6.3, and 6.5; 111 O3 is task 9.3.
- Evidence: `make test-release-tooling` (unit), 2868 passed; `run pre-commit`
  passed but for the two expected checks. End-to-end: none.

## 6. The repository layer at the root and across systems

Delivers the repository layer's root and cross-system guidance (D3, D8 as amended,
D9, D10 as amended, D13, D17, D18, D21's manual override; 31 O1b, O1f):
`AGENTS.md` rewritten as the entry, `openspec/README.md` as this repository's guide,
the cross-system documents tagged and deduplicated, and the classification of the
checks. Files: `AGENTS.md`; `openspec/README.md`; `docs/development/ARCHITECTURE.md`,
`TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`, `BUILD_AND_PACKAGING.md`, `RELEASING.md`;
`openspec/specs/market-change-workflow/README.md`.

- [x] 6.1 Rewrite `AGENTS.md` (D3, D9, D18): frontmatter `tags: [repository]`; the
  three layers and where each lives; its layer table naming every repository
  guidance document by path, which is the guidance check's manual override (D21),
  with the closeout-parts and roadmap rows of task 3.4; the repository's `## Tags`
  table, `repository` its first row, listing only tags neither shared layer has and
  a repository document carries (D18) — `architecture` carried by
  `ARCHITECTURE.md`, `checks` kept only if this section names a guidance document
  carrying it, and otherwise listed in the notes for the round's triage, the open
  question the inventory records; the `## Exceptions to shared guidance` table for
  every multi-system exception the inventory found — the public case selected, the
  buyer CLIs' test seams and `ARKHAI_IDENTITY_CREDENTIAL` overridden; and this
  repository's own rules. Verify every repository row of the inventory whose
  destination is `AGENTS.md` sits there, and each exception row cites a guidance
  file and has the kind `selects` or `overrides`.
  Amended at round 4's triage (111 O4): `AGENTS.md` restates no shared rule, each
  repository rule stating only what is particular here and linking the shared rule;
  reshaped at round 5's triage to hold only what can be nowhere else (127 O1).
  Note: `AGENTS.md` holds "The change workflow", "What every session reads", "Where
  the guidance lives" (the layer table, then a separate roles table for the closeout
  parts, their checks, and the roadmap, which is no guidance), "Exceptions to shared
  guidance", and "Rules for every agent here". Exceptions: the public case
  (`selects`) and `ARKHAI_IDENTITY_CREDENTIAL` (`overrides`, the storefronts and the
  provisioning service only, correcting inventory row 525); the CLIs' test-seam row
  was removed at round 5's triage. No `checks` tag. The repository's tag table moved
  to `docs/guidance/repository/README.md` (task 11.1). Evidence: inspected, and by
  the fresh-context check.
- [x] 6.2 Finish `openspec/README.md` as this repository's OpenSpec guide (D3, D8):
  frontmatter; its placement table naming `docs/guidance/` and capability guidance
  files beside capabilities; the validator pin; the capability index itself, whose
  role the workflow states (31 O1f); its closeout parts naming `make check-guidance`
  where the guidance placement part runs the repository's guidance check (D21).
  Verify it holds no row the inventory tags `workflow`.
  Note: frontmatter `tags: [repository, openspec]`; the placement table gains rows for
  `AGENTS.md`, the shared guidance directories, and a capability's guidance file
  (later rewritten by tasks 12.5 and 13.4); "Current capability documentation" links
  the index's role; the checks table names `make check-guidance`; "Packaging" is
  reduced to its checks (58 O1). No `workflow` row. Evidence: inspected.
- [x] 6.3 Give `ARCHITECTURE.md`, `TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`,
  `BUILD_AND_PACKAGING.md`, and `RELEASING.md` frontmatter with the tags their
  content needs (D10, D17) — `VALIDATION_RUNBOOK.md` stays outside the guidance set,
  with no frontmatter and no layer-table row (48 F1) — and move what the inventory
  finds misfiled across systems, such as "Public repository content checks" and
  "Validation namespaces" to `market-change-workflow`'s README. Verify each document
  opens with its frontmatter and appears in `AGENTS.md`'s layer table, and the
  runbook does neither.
  Amended at round 4's triage (111 O2): each document's opening states what it holds
  as the repository layer.
  Note: frontmatter on each document, each a row of `AGENTS.md`'s layer table, the
  runbook in neither. Moved: "Public repository content checks" to
  `market-change-workflow`'s README under "This repository's checks", its agent rules
  repeated in `AGENTS.md`; "Validation namespaces" into "The change's namespace";
  "Artifact publishing destination" to `RELEASING.md`; the atomic-cutover instance
  into "Accepted representations and application views". The tags' reach went to
  task 6.5's revisit and D28. Evidence: inspected.
- [x] 6.4 Write the classification of the checks (D13) in
  `openspec/specs/market-change-workflow/README.md` as `### What each check enforces`
  under "This repository's checks": a table of each check, the rule it enforces
  linked to its guidance, that rule's layer, and where it runs, from the inventory's
  corrected draft, the guidance check marked as enforcing workflow rules from this
  repository's script. Verify every row of the draft is in the table.
  Note: twenty-five rows in the draft's order, each rule linked to the file stating
  it; the guidance check reads "workflow, enforced from this repository's script";
  the first four rows are the workflow's default checks; the architecture check's CI
  row says pushes and pull requests to `dev` and `staging`. Evidence: inspected, and
  by the fresh-context check.
- [x] 6.5 Deduplicate the repository material as the preamble says (31 O1b),
  including the handbook and runbook duplicates the inventory recommends for one
  home. Verify every duplicate row this section moves is merged or listed.
  Amended at rounds 2 and 4 (58 O1; 111 O2, O4): "Packaging" cites the checks'
  home for what each enforces, and every cross-system instance links its shared rule
  without paraphrasing it. Amended at round 5's triage (S6 tag reach) and by the
  owner before section 7 (138 note 2): the pre-closeout revisit weighs splitting
  `docs/development/` by reader or by tag, or into tagged files under
  `docs/guidance/repository/`; it was settled as D24 to D35, sections 10 to 13.
  Note: listed under "Section 6's differing pairs"; the handbook overlaps are section
  7's (task 7.3). Every section citing `docs/guidance/` was read, a paraphrase of
  the shared rule replaced by the instance and a link. Outside the plan:
  `TESTING.md`'s link to the runbook's section 21 corrected. Evidence: inspected.
- [x] 6.6 Re-point every citation of what this section moved, and verify the
  section as task 3.10 does. End-to-end: none; no pipeline scenario reads guidance,
  and none is owed.
  Note: re-pointed: the "Secret scanning" and "Validation namespaces" citations,
  `TESTING.md`'s citation of the dependency discipline, and
  `check_capability_index.py`'s docstring; every new anchor checked by Grep and the
  fresh-context check. `make check-agent-skills` OK; unscoped citations report only
  older failures; `run pre-commit`: functional tier (`make test-release-tooling`,
  2868) and defaults passed, `make check-repository` failing only on the two
  expected checks. End-to-end: none confirmed, as planned. Owed by validation:
  nothing.

Section 6's differing pairs (31 O1b), accepted at round 5's triage (`design.md`,
"Settled at round 5's triage"):

- What `ARCHITECTURE.md` and `DEPLOYMENT_AND_CONFIG.md` hold (row 148): the
  placement table their one home, the `ARCHITECTURE.md` row adding the system's
  shape and deployment topology; "neither replaces a specification's normative
  requirements" in the paragraph below it.
- The architecture check's bullet (row 167): merged into `ARCHITECTURE.md`.
- The real-provisioning lane (row 484): `TESTING.md`'s adoption form stands; the
  runbook's section 25 brought in line at round 5's triage.
- The accepted purchase qualification (row 497) and the migrations after v0.3.0
  (row 575): both copies kept, neither contradicting.
- The `Makefile`'s `clobber-wheels` (109 F1): a chosen subset, no change.
- The paraphrase sweep's wording, which changes nothing this repository does.

Round 5's triage (review 126, the owner's notes 127; `design.md`, "Settled at
round 5's triage"):

- 127 O1: `AGENTS.md` holds what can be nowhere else (task 6.1). Moved out: the
  `deploy-local` rule, the packaging checks with `typecheck`, the comment and
  citation checks' scopes (to `market-change-workflow`'s "The closing checks"), and
  draw.io (later `repository/diagrams.md`, task 11.3); the pointer sections removed;
  the `Makefile` comments and `check_doc_citations.py` re-pointed; the inventory's
  rows corrected. Left: `render-diagrams-from-source`'s proposal meets the move at
  its merge (D15).
- 126 F1: `packaging.md`'s "Nothing is maintained by hand" admits a chosen list.
- S6 CLI exception: the row left `AGENTS.md`; `TESTING.md`'s "Command modules" names
  the roadmap's gap; D9 and inventory row 450 corrected.
- S6 row 484: the runbook's section 25 matches `composed_listing.py`'s adoption.
- Evidence: `run pre-commit`, functional tier (`test_check_doc_citations.py` among
  the suites) and defaults passed, `make check-repository` failing only on the two
  expected checks. Owed by validation: the fix commit.

## 7. The repository layer beside each capability

Delivers capability guidance beside its capability and the steps that read it (D3,
D9, D10, D22; CW-p9sa, CW-x4ex, CW-r8cg; 31 O1b, O1d, O1e): the capability sections
of `TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`, and `ARCHITECTURE.md` moved into
guidance files in `openspec/specs/<capability>/`, deduplicated, with their
exceptions — the hand-laid graph's beside `change-workflow` — and the seven skills
reading them. Files: `openspec/specs/<capability>/*.md` (new guidance files, the
inventory's `specs/<capability>/<file>` destinations written at full paths), among
them `openspec/specs/change-workflow/diagrams.md`; the companions where the inventory
places a description of the system; `docs/development/TESTING.md`,
`DEPLOYMENT_AND_CONFIG.md`, `ARCHITECTURE.md`;
`.agents/skills/change-{design,plan,implement,review,triage,merge,closeout}/SKILL.md`.

- [x] 7.1 Move each section the corrected inventory places beside a capability — by
  the owner of what it governs (31 O1d) — into a guidance file in that capability's
  directory, each with frontmatter `tags: [repository, <topic>]` and no capability
  tag (D18), or into its companion where the inventory says the text describes the
  system, deleting it from its source. Verify each such row sits in its destination,
  and no file in a capability directory but `spec.md`, its companion, and `index.md`
  lacks frontmatter.
  Note: six `testing.md` files (`negotiation-protocol`, `resource-pool-management`,
  `site-capacity`, `market-composition`, `marketplace-identity`,
  `test-compatibility`) and twelve `configuration.md` files (`storefront-publication`,
  `settlement-configuration`, `resource-pool-management`, `site-capacity`,
  `marketplace-identity`, `registry-discovery`, `market-composition`,
  `physical-provisioning`, `compute-provisioning-contract`, `settlement-servicing`,
  `contact-exchange-settlement`, `introduction-delivery`), each opening with what it
  holds and linking the rules it instances; "Durable fulfillment acceptance" merged
  into `fulfillment/architecture.md` (task 7.3); the paragraphs filed under
  "Alkahest release models" placed at round 6's triage (141 F1). Wording changed only
  where it was relative to a change or to the source's layout. Every file in a
  capability directory but `spec.md`, the companion, and `index.md` opens with
  `tags`. Evidence: inspected.
- [x] 7.2 Put each exception the inventory found that applies to one capability in
  that capability's guidance file, as an `## Exceptions to shared guidance` row
  (D9, CW-x4ex): at least the hand-laid change-workflow graph's `overrides` row
  against `docs/guidance/engineering/diagrams.md`, in a new
  `openspec/specs/change-workflow/diagrams.md` (`tags: [repository, diagrams]`)
  citing the "Current limits" bullet on generating the graph (31 O1e, 48 F2). Verify
  each row cites a guidance file and sits beside the one capability it applies to.
  Amended at round 5's triage (127 O1): moving the graph's sentence removes
  `AGENTS.md`'s "Diagrams" heading.
  Note: row 159 is the only single-capability exception: `change-workflow/diagrams.md`
  `overrides` `diagrams.md`'s "A diagram is held to code only when generated",
  citing the companion's "Routing is code, with the model as backstop" and its
  "Current limits" bullet. `AGENTS.md`'s "Diagrams" is gone. Evidence: inspected.
- [x] 7.3 Deduplicate the capability material as the preamble says (31 O1b). Verify
  every duplicate row this section moves is merged or listed.
  Note: "Durable fulfillment acceptance" merged into the fulfillment companion's
  "Fulfillment acceptance and dispatch acknowledgement"; the handbook overlaps are
  listed under "Section 7's differing pairs". Evidence: inspected.
- [x] 7.4 Extend the seven skills' reading lists — `change-design`, `change-plan`,
  `change-implement` (both of its lists), `change-review`, `change-triage`,
  `change-merge`, and `change-closeout` — so that wherever each reads a capability's
  specification and companion it also reads every other Markdown file in the
  capability's directory but its `index.md` (D22, CW-r8cg). Verify `make
  check-agent-skills` passes and each skill's list names the guidance files.
  Note: each skill reads "every other Markdown file in its directory but its
  `index.md`: the capability's own guidance" — triage for each cited specification,
  merge for every touched capability (design review 19 F2). `make
  check-agent-skills` OK. Evidence: inspected.
- [x] 7.5 Re-point every citation of what this section moved, and verify the
  section as task 3.10 does. End-to-end: none; no pipeline scenario reads guidance,
  and none is owed.
  Note: re-pointed: citations in `DEPLOYMENT_AND_CONFIG.md`, `TESTING.md`, the
  operator handbook, `kit/arkhai-payments/README.md`, three quickstarts,
  `deployment-state`'s companion, the VM storefront's `examples/README.md` and
  `settings.toml` comment, and two active changes' promotion records
  (`multi-domain-storefront-composition`, `add-persistent-buyer-profiles`). `make
  check-agent-skills` OK; scoped citations report only this change's own
  documents; `run pre-commit` (the seven skills and `settings.toml`): functional
  tier and defaults passed, `make check-repository` failing only on the two expected
  checks. End-to-end: none confirmed, as planned. Owed by validation: nothing.

Owner's direction to section 7 (138 note 1): "What every session reads" names
`docs/guidance/engineering/` and `docs/guidance/workflow/` as two rows, settled at
round 6's triage (138 O1).

Section 7's differing pairs (31 O1b), kept at round 6's triage: rows 550, 565, 570,
and 571 unchanged; rows 578 and 582, the handbook's "Payments access" table gaining
the two conditions the settlement file names.

Round 6's triage (review 141, validation 142, the owner's notes 138 and 143;
`design.md`, "Settled at round 6's triage"):

- 141 F1: the publication migration is `storefront-publication/configuration.md`'s
  "Migrating publication configuration"; the VM storefront's retired inventory keys
  join `DEPLOYMENT_AND_CONFIG.md`'s retired-settings list; the production cutover
  sequence is the operator handbook's "Migrating settlement and publication
  configuration" under "Upgrading a deployment"; inventory row 578 corrected.
- 138 O1: task 9.3 compares the files the table and `load.common` name.
- Outside the plan: the VM storefront's `settings.toml` comment repaired, a fragment
  `c22086fa3` left.
- Kept: `AGENTS.md`'s capability-guidance sentence, the tag widening (task 6.5's
  revisit), and `guidance-review`'s reading (outside D22's seven).
- Evidence: `run pre-commit` (`settings.toml`): functional tier and defaults passed,
  `make check-repository` failing only on the two expected checks. Owed by
  validation: the fix commit, its `settings.toml` change taking Helm and the pipeline
  out of seq 113's waiver.

## 8. `[load]` directory entries

Delivers directory entries in `[load]` (D5; CW-l7hn, modified). Files:
`scripts/change_workflow/config.py`, `scripts/change_workflow/hook.py` where its
handling needs it; `scripts/tests/test_change_workflow_config.py`,
`scripts/tests/test_change_workflow_hooks.py`.

- [x] 8.1 Make `config.documents()` expand an entry ending in `/` into the Markdown
  files beneath it, recursively, in sorted path order, each document once across
  `load.common` and `load.<step>`, and refuse with a `StepError` naming the entry a
  directory entry that is missing, unreadable, or holds no Markdown file; literal
  entries and an absent or empty list resolve as before. `config load` reports the
  refusal as an error rather than a traceback. Verify with unit tests: a directory
  entry expands in sorted order in place of the directory; an entry naming a missing
  directory, a file, an unreadable directory, and a directory with no Markdown each
  refuse naming the entry; a literal missing file is still printed; and the
  existing "Design loads the roadmap" test passes.
  Note: `Configuration.documents(step, root)` takes the repository's root;
  `directory_documents` walks with `Path.walk`, an unreadable subdirectory refusing
  too; the refusal is a `ConfigError` raised before anything prints.
  `test_change_workflow_config.py` (unit, through the CLI over temporary trees): the
  cases above passed.
- [x] 8.2 Verify the post-compaction hook names the expanded files for a directory
  entry, and, for a refused entry, tells the session the documents to re-read are
  unknown (CW-l7hn's scenario "A directory entry names nothing"), with unit tests in
  `test_change_workflow_hooks.py`.
  Note: the tests are in `test_post_compaction_context.py`, where `hook.py` is
  tested (the plan's file was a slip); the hook says "the workflow configuration
  cannot be read or its load.common resolved". Unit: passed.
- [x] 8.3 Verify the section: `pytest -q scripts/tests/test_change_workflow_config.py
  scripts/tests/test_change_workflow_hooks.py` (unit), then `make test-release-tooling`,
  and `scripts/change-workflow run pre-commit layer-engineering-guidance`.
  End-to-end: none; the engine's loading runs in no pipeline scenario, and none is
  owed. Run after task 8.4, which it verifies too, adding
  `scripts/tests/test_change_workflow_records.py` to the unit run.
  Note: six suites (unit): 579 passed; `make test-release-tooling`: 2893 passed;
  `run pre-commit`: functional tier and defaults passed, `make check-repository`
  failing only on the two expected checks. End-to-end: none confirmed, as planned.
  Owed by validation: nothing.
- [x] 8.4 Give the engine the default inert paths of CW-n7ra as task 3.16 modifies
  it (71 O1): where `repository.inert-paths` is absent, the configuration's inert
  paths are `openspec/` and `**/*.md`; a declared list, an empty one included,
  replaces the default. Keep `records.inert`'s and `records.exempting`'s docstrings
  current. Files: `scripts/change_workflow/config.py`,
  `scripts/change_workflow/records.py`, and their tests. Verify with unit tests: an
  absent key yields the default; a declared list yields itself; an empty list yields
  no inert path; and `records.inert` treats a nested Markdown file as inert under
  the default.
  Note: `config.DEFAULT_INERT_PATHS` and `Configuration.repository_inert_paths()`,
  called by every reader (`hooks.py`, `review.py`, `next_step.py`); `records.inert`
  and `exempting` take a sequence, never None. Unit: the config, records, hooks
  (CW-n7ra's two scenarios), review, and next-step tests passed. This repository
  declares its own list, so nothing here changes.

## 9. `make check-guidance`

Delivers the guidance check and `load.common` collapsed to one entry (D5, D9, D15,
D16, D21; MCW-c4ek, modified; CW-g7lt, CW-d2rw, CW-x4ex as checked rules), and the
fixes the check finds in the guidance. Files: `scripts/check_guidance.py` (new),
`scripts/tests/test_check_guidance.py` (new); `scripts/check_change.py`,
`scripts/tests/test_check_change.py`; `Makefile`; `.agents/workflow.toml`; guidance
files the check finds wanting.

- [x] 9.1 Write `scripts/check_guidance.py`, standard library only like the other
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
  Note: a layer's vocabulary is the table under "Tags" whose first row is the
  layer's tag; exceptions are the table under "Exceptions to shared guidance"; the
  layer table is `AGENTS.md`'s `Layer | Guidance` table, not the roles table. Files
  read are those Git tracks or would track; anchors are slugged as GitHub renders
  them, nothing in a fence or code span read as a heading or link. Two further
  conditions: tags that are no list, and a layer-table document that does not exist.
  `test_check_guidance.py`: 49 passed (unit, and one integration test of the file
  lister). The listings run as `python3 scripts/check_guidance.py`, which no step's
  rules allow directly.
- [x] 9.2 Add `make check-guidance` to the `Makefile` and to `scripts/check_change.py`'s
  checks, so `make check-repository` runs it, and name it in `check-repository`'s
  help text. Verify `test_check_change.py` (unit) covers the new check and passes.
  Note: the ninth check, `guidance`; `test_check_change.py` (unit): 18 passed.
- [x] 9.3 Collapse `load.common` to `AGENTS.md`, `docs/guidance/`, the cross-system
  documents, and `openspec/README.md` (D5), with its comment current. Verify
  `scripts/change-workflow config load common` prints every guidance file sections 3
  to 5 listed by path, and nothing more under `docs/guidance/`.
  Amended at rounds 5 and 6 (127 O1, 138 O1): verify that `AGENTS.md`'s "What every
  session reads" and `load.common` agree by the files they name.
  Note: made by the orchestrating session on the owner's standing word: `common =
  ["AGENTS.md", "docs/guidance/", "docs/development/ARCHITECTURE.md",
  "docs/development/TESTING.md", "docs/development/DEPLOYMENT_AND_CONFIG.md",
  "openspec/README.md"]`. `config load common` printed 52 files, the same set as
  before; the table's directory rows hold every file `docs/guidance/` expands to,
  and its other rows are `load.common`'s other entries. Unit suites passed.
- [x] 9.4 Run `make check-guidance` over the tree and fix in the guidance whatever it
  reports — a missing tag, an unused row, a stale anchor, an upward link — each fix
  following the corrected inventory. Verify `make check-guidance` passes.
  Amended at round 2's triage (56 F1): this change's own documents name removed
  headings in prose, and the delta's scenario "A guidance link's section moved" uses
  a neutral example.
  Note: the first run reported ten stale anchors: seven this change's own, fixed as
  amended, and three older ones fixed outside the plan (`market-change-workflow`'s
  README, `api-credits`' companion, `multi-domain-storefront-composition`'s promotion
  record). `make check-guidance`: OK, 73 files, 3 exception rows.
- [x] 9.5 Verify the section: `pytest -q scripts/tests/test_check_guidance.py
  scripts/tests/test_check_change.py` (unit), then `make test-release-tooling`, and
  `scripts/change-workflow run pre-commit layer-engineering-guidance`, which now runs
  the guidance check. End-to-end: none; no pipeline scenario runs the closing
  checks, and none is owed.
  Note: the two suites: 67 passed; `make test-release-tooling`: 2937, then 2942 in
  the functional hooks; `run pre-commit` passed but for the two expected checks,
  after test fixtures that tripped comment hygiene were renamed;
  `test_change_clone.py::test_the_bootstrap_failed` flaked once (a `waitpid` race)
  and passed on rerun. End-to-end: none confirmed, as planned. Owed by validation:
  nothing.
  Fixed at round 7's triage (157 F1): `_capability_guidance` excludes only the
  companion — `README.md` beside an `index.md`, `architecture.md` otherwise — with
  `test_an_untagged_architecture_md_beside_an_index`. `test_check_guidance.py`: 50
  passed; `make check-guidance`: 73 files; `run pre-commit` passed but for the two
  expected checks, `domains/apicredits`' `test_distribution_install.py` flaking once
  and passing on rerun.

## 10. Inventory of the cross-system documents by kind

Delivers the map the round's moves follow (D34, D25, D28; D30): every section of
the five cross-system documents as they stand, with its kind, destination, and tags.
No text moves in this section. Files:
`openspec/changes/layer-engineering-guidance/inventory.md`.

- [x] 10.1 Add a part to `inventory.md`, "Cross-system documents by kind", after
  "Draft classification of the checks", opened by a paragraph saying it was written
  at the return to design, is reviewed with the moves in the round's triage rather
  than before them (D30, D34), and governs sections 11 to 13. One row per section of
  `docs/development/ARCHITECTURE.md`, `TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`,
  `BUILD_AND_PACKAGING.md`, and `RELEASING.md` as they stand, or per part of a
  section whose text holds more than one kind, with the columns `Source`, `Kind`,
  `Destination`, `Tags`, `Reason`, and `Ambiguous`:
  - **Kind** by D25's test: `description` (what the system is and why), `rule` (wrong
    if a change's work product were otherwise), or `procedure` (what the owner or an
    operator does or types).
  - **Destination**: `stays` for description, under the heading it has or the one the
    row names; `repository/<file>`, abbreviating `docs/guidance/repository/<file>`,
    for a rule, a file per subject named by its subject (D27); for a procedure, the
    heading it takes in `docs/release-handbook.md`, the owner's handbook (D25), or in
    `docs/operator-handbook.md` for an operator's (141 F1).
  - **Tags**: for each rule file, `repository` and the topic and tool tags naming
    what it covers (D28), from `docs/guidance/repository/`'s table as `AGENTS.md`'s
    "Tags" gives it now or a lower layer's; a new repository tag only where no
    existing tag names the subject and a file carries it (D18).
  - **Ambiguous**: what the test did not decide, for the triage —
    `ARCHITECTURE.md`'s "Package and dependency layers", which states its rules
    through a description of the layers, the known case; overlap with a handbook or
    capability guide (31 O1b).

  Then a table "Repository files and their tags": each file under
  `docs/guidance/repository/` — `README.md` and `diagrams.md` (D29) among them —
  with its tags and the rows it takes, and the tags the three description documents
  keep. Verify every heading of the five documents outside a fenced block has a row,
  every destination file is in the table, and every tag is in a vocabulary.
  Note: one table per document and one for `openspec/README.md`'s draw.io paragraph,
  then "Repository files and their tags" (31 files) and "Capability guidance tags",
  which re-tags four capability configuration files (`deployment`, `versioning`;
  applied in task 11.1). Every heading of the five documents has a row, every
  destination is in the files table, and every tag is the engineering table's or the
  repository's. The opening records how D25's test was read: this repository's
  instance of a shared rule is a rule; what named components are or do is
  description. No section is an operator's procedure, so the operator handbook gains
  nothing (task 12.2). Evidence: inspected; the fresh-context check's fixes made.
- [x] 10.2 Verify the section: `scripts/change-workflow check tasks
  layer-engineering-guidance` and `scripts/change-workflow run pre-commit
  layer-engineering-guidance`, inert paths only, failing on nothing the preamble
  does not expect. End-to-end: none; no pipeline scenario reads guidance, and none is
  owed.
  Note: `check tasks` was refused; `make check-tasks` and `run pre-commit`'s tasks
  check passed in its place. `run pre-commit` (inert paths) passed but for the two
  expected checks. End-to-end: none, and none owed.

## 11. The repository's rules out of the description documents

Delivers the repository layer's directory and the rules of the three description
documents in it (D27, D28, D29, D32): `docs/guidance/repository/` with its README and
the repository's tag table, the rule rows of `ARCHITECTURE.md`, `TESTING.md`, and
`DEPLOYMENT_AND_CONFIG.md` moved into its files, and the draw.io rule. Files:
`docs/guidance/repository/*.md` (new); `docs/development/ARCHITECTURE.md`,
`TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`; `AGENTS.md` ("Tags"); `openspec/README.md`;
`openspec/specs/change-workflow/diagrams.md`; whatever cites a moved section.

- [x] 11.1 Write `docs/guidance/repository/README.md`, `tags: [repository]`: what the
  layer holds (guidance naming this repository's packages, services, tools,
  documents, or targets, spanning its systems — one capability's beside it), how its
  files are organized (flat, one subject each, named by subject; the directory is
  navigation and carries no meaning, CW-n6dm), that a file's tags name what it
  covers (D28), and its "Tags" table, moved whole from `AGENTS.md` with every row the
  inventory adds. `AGENTS.md`'s "Tags" section is replaced by a sentence linking the
  README's table (D32, D18). Verify `make check-guidance` finds one repository
  vocabulary, in the README.
  Note: the table holds `repository` and `architecture`. `AGENTS.md` keeps no "Tags"
  heading, since the check refuses one over no table; its link sits in "Where the
  guidance lives". The four capability configuration files carry their new tags
  (section 10). `make check-guidance`: OK, 97 files, one repository vocabulary.
- [x] 11.2 Move each `rule` row of `ARCHITECTURE.md`, `TESTING.md`, and
  `DEPLOYMENT_AND_CONFIG.md` into its file under `docs/guidance/repository/`, with the
  frontmatter the inventory gives, deleting it from its source. Each file opens by
  saying what it holds, and states only what is particular here, linking the shared
  rule it applies by name rather than paraphrasing it (111 O4); it may link the
  description documents, which are repository guidance. A heading moved whole keeps
  its text, wording changed in the move listed in the notes (31 O1b). Verify each
  `rule` row sits in its destination and its source no longer holds it.
  Note: 22 files hold the three documents' rule rows, each opening with what it holds
  and linking the description it rests on; a description reading on from a moved
  rule keeps a pointer naming the rule file without restating it. Inspected row by
  row. `ARCHITECTURE.md`'s map lost its "Implementation rules" row here. Wording
  changed in the moves (31 O1b): references re-worded for the new file and relative
  links re-rooted; `package-versions.md` gives `ARCHITECTURE.md`'s reason ("Sites and
  storefronts are deployed and upgraded together by one business") for its "Until
  then"; `migrations-at-startup.md` says "The migrations after a chain's baseline are
  fail-forward"; `compose-stacks.md` joins both documents' lane-target rule; bold
  lead-ins became headings. Correction (section 13's round check): seven files keep
  the bold lead-in under its new heading, and the inventory names some headings
  other than the files use; `package-layers.md`'s "placement tests" link
  `family-kits.md`'s.
- [x] 11.3 Move the draw.io paragraph from `openspec/README.md`'s "Documentation
  placement" into `docs/guidance/repository/diagrams.md`, `tags: [repository,
  diagrams]`, linking `docs/guidance/engineering/diagrams.md` (D29), and re-point
  `openspec/specs/change-workflow/diagrams.md`'s opening, which cites the rule in
  `openspec/README.md`. Verify `openspec/README.md` no longer names draw.io.
  Note: `diagrams.md`'s "Drawn in draw.io" links the engineering file's "Source
  beside export"; `change-workflow/diagrams.md` cites it; `openspec/README.md` no
  longer names draw.io (Grep).
- [x] 11.4 Deduplicate as the preamble says (31 O1b): a rule the inventory marks as
  stated twice merges into one home, and a pair whose copies differ is proposed and
  listed for the triage.
  Note: merged, the copies agreeing, into `compose-stacks.md`,
  `service-configuration.md`, `service-databases.md`, `lane-doubles.md`,
  `deal-scenarios.md`, `deterministic-tests.md`, and `package-versions.md`. One pair
  differed — a locally verifiable scenario's doubles — and `deal-scenarios.md` takes
  `ARCHITECTURE.md`'s form (`design.md`, "Settled in implementation"). No document
  outside the guidance contradicts the moved rules.
- [x] 11.5 Re-point every citation of what this section moved, outside the archive
  and `docs/prompts/`, as task 7.5 did: the description documents, the handbooks
  and quickstarts, `README.md`, `e2e-tests/README.md`, the runbook, the
  specifications and companions, the skills, the comments of `Makefile`,
  `helm/Makefile`, `helm/scripts/test-render.sh`, and the scripts, and the active
  changes' documents that cite a moved heading by anchor or in prose (`changes.md`,
  "One change per branch"), found by Grep for each moved heading's anchor and
  quoted name. Verify the section: `make check-guidance` passes;
  `make check-doc-citations CHANGE=layer-engineering-guidance` and unscoped report
  nothing from a file this section wrote or edited; `make check-agent-skills`;
  `scripts/change-workflow run pre-commit layer-engineering-guidance`, its functional
  hooks run for the skills and scripts it edits, failing on nothing the preamble does
  not expect. Fresh-context check of the moves against the inventory. End-to-end:
  none; no pipeline scenario reads guidance, and none is owed. Owed by validation:
  nothing.
  Note: re-pointed: the specifications and companions, the operator handbook, the
  `Makefile`, `helm/Makefile`, and `test-render.sh` comments,
  `ARCHITECTURE.toml`'s header, the architecture scripts' and test's docstrings,
  thirteen `pyproject.toml` comments, `BUILD_AND_PACKAGING.md`, `change-implement`,
  twelve active changes' documents, and two change-index rows. Beyond comments,
  `scripts/architecture.py`'s failure message names `package-layers.md`, a code edit
  beyond D35's list kept so the message points to the rule. Not yet recorded as
  deferred work: code comments predating the change cite `ARCHITECTURE.md` headings
  that no longer exist ("Buyer negotiation policy surface", "Capacity and the Site
  Authority", "API-credits market domain") in `core/buyer`, `core/storefront`,
  `kit/policy`, `kit/site`, and the domains, and
  `provisioning/compute/service/tests/integration/` cites "Architecture.md — Testing
  Strategy — Integration Tests". Checks: `make check-guidance` OK (97 files); scoped
  citations report only the expected ones, unscoped adding only other changes'
  older ones; `make check-agent-skills` OK; `make test-release-tooling` 2943 passed;
  `run pre-commit`: functional tier passed (`test_change_clone.py`'s known flake once,
  passing on rerun), `pre-commit` failing only on the two expected checks; the
  fresh-context check's findings fixed.

## 12. `BUILD_AND_PACKAGING.md` and `RELEASING.md` dissolved; procedures to handbooks

Delivers the two documents' rules in the repository layer, every procedure of the
five documents in a handbook, and the two documents removed (D25, D27, D10 as
amended). Files: `docs/guidance/repository/*.md`; `docs/release-handbook.md` (new);
`docs/operator-handbook.md`; `development/BUILD_AND_PACKAGING.md` and
`RELEASING.md` (removed); `openspec/README.md` ("Packaging"); `AGENTS.md` (the layer
table); `scripts/tests/test_publish_matrix.py`; `.github/workflows/publish-pypi.yml`
(comments); the `scripts/check_*.py` and `scripts/uv_project.py` docstrings and
messages naming `BUILD_AND_PACKAGING.md`; whatever cites either document.

- [x] 12.1 Move each `rule` row of `BUILD_AND_PACKAGING.md` and `RELEASING.md` into
  its file under `docs/guidance/repository/`, as task 11.2 moves rules — the
  published-package table into the file the inventory names for it, and the
  packaging checks' descriptions into theirs; `openspec/README.md`'s "Packaging" part
  cites the checks' new home for what each enforces (58 O1). Verify each row sits in
  its destination.
  Note: `project-layout.md`, `wheelhouse.md`, `python-version.md`, `locks.md`,
  `images.md`, and `packaging-checks.md` written; `project-environments.md` gains
  "Project environments"; `published-packages.md` holds the published set and its
  table under "Published packages" (read by `test_publish_matrix.py`) and "One import
  package each"; `package-versions.md` gains "Versioning policy". "Packaging" cites
  `packaging-checks.md#checks`. Merged, the copies agreeing: `RELEASING.md`'s "Local
  development" into `wheelhouse.md`, and `DEPLOYMENT_AND_CONFIG.md`'s storefront
  images into `images.md`. Wording changed only in openings and references.
  Inspected row by row.
- [x] 12.2 Write `docs/release-handbook.md`, with no frontmatter and outside the
  guidance set (D25): opened by who reads it and what it holds, beside the operator
  handbook and the change workflow's handbook, then `RELEASING.md`'s `procedure` rows
  moved whole under the headings the inventory gives — the one-time setup, cutting a
  release, the per-release migration-floor decision, troubleshooting, and how the
  publish workflow works, for the owner who runs it — each linking the rules it
  applies. Move every operator `procedure` row of the five documents into
  `docs/operator-handbook.md` under the heading the inventory gives (141 F1). Verify
  each `procedure` row sits in its handbook.
  Note: the handbook holds "How the publish workflow works", "One-time setup for a
  package", "Cutting a release", "The migration floor", "Import package renames",
  "Where artifacts are pushed", and "Troubleshooting", each moved whole and linking
  the rules it applies, two clauses added naming `published-packages.md`. The
  operator handbook gains nothing: no operator procedure is a section of the five
  documents.
- [x] 12.3 Remove `BUILD_AND_PACKAGING.md` and `RELEASING.md` once every row of
  theirs has moved, and remove their rows from `AGENTS.md`'s layer table, which the
  guidance check refuses for a missing file. Verify neither file exists and every
  row of theirs in the inventory names a destination that holds it.
  Note: removed with `git rm`, with their rows; `make check-guidance` OK (102
  files); every row of theirs names a file that holds it (inspected).
- [x] 12.4 Point `scripts/tests/test_publish_matrix.py` at the published-package
  table's new file, its module constant, docstrings, and failure messages naming it;
  `.github/workflows/publish-pypi.yml`'s two comments name the same file. Verify
  `pytest -q scripts/tests/test_publish_matrix.py` (unit) passes against the moved
  table, its existing cases still failing a package with no row or a row stating
  other dependencies.
  Note: the constant is `PUBLISHED_PACKAGES`, the reader `_published_rows`, and the
  messages name `published-packages.md`, the logic unchanged; `publish-pypi.yml`'s
  comments name the file. Unit, through `make test-release-tooling`: passes; the
  failure paths are the unchanged `pytest.fail` and `assert`, with no negative run.
- [x] 12.5 Re-point every citation of the two removed documents and of what this
  section moved, outside the archive and `docs/prompts/`, as task 11.5 does: the
  docstrings and messages of `scripts/check_locks.py`, `check_project_layout.py`,
  `check_python_version.py`, `check_uv_setup.py`, `check_uv_version.py`, and
  `uv_project.py`; `tools/README.md`; `api-credits/architecture.md`,
  `deployment-state/architecture.md`, and `market-change-workflow/README.md`'s "What
  each check enforces"; the description documents; and the active changes' documents
  citing either file, by path alone too, since the citation check fails a removed
  path. Verify the section: the tests of each script whose message changed (unit),
  `pytest -q scripts/tests/test_check_locks.py scripts/tests/test_check_project_layout.py
  scripts/tests/test_check_python_version.py scripts/tests/test_check_uv_setup.py
  scripts/tests/test_check_uv_version.py scripts/tests/test_uv_project.py
  scripts/tests/test_publish_matrix.py`; `make check-packaging`; `make
  check-guidance`; `make check-doc-citations` unscoped reporting no citation of the
  removed files outside this change's own documents and the archive;
  `scripts/change-workflow run pre-commit layer-engineering-guidance`, its functional
  hooks run, failing on nothing the preamble does not expect. Fresh-context check of
  the moves against the inventory. End-to-end: none; no pipeline scenario reads
  these documents, and none is owed. Owed by validation: nothing; the
  `publish-pypi.yml` edit is comments.
  Note: re-pointed: the six scripts' docstrings and messages, each naming the files
  holding its conventions (corrected at section 13's round check to name
  `wheelhouse.md`, `python-version.md`, and `packaging-checks.md` where they apply);
  `tools/README.md`; the two companions; `market-change-workflow/README.md`; the
  description documents and `migration-chain-tests.md`; six active changes and two
  active change-index rows, each placed by D25. `openspec/README.md`'s placement
  table drops the two rows and gains the handbook's. Checks: `make check-guidance` OK
  (102 files); unscoped citations name the removed files only from this change's own
  documents; `run pre-commit`: functional tier (`make check-packaging`, `make test`,
  `make test-release-tooling` 2943 passed, every listed suite among them) passed,
  `pre-commit` failing only on the two expected checks. No test asserts the changed
  messages; they were inspected. The fresh-context check's findings fixed.

## 13. The documents naming the layout, and the three kinds

Delivers the entry, the placement table, and the shared layers' READMEs as the new
layout leaves them, and D25's principle as engineering guidance (D25, D28, D31,
D32, D33; D10 as amended). Files: `docs/guidance/engineering/documentation.md`;
`docs/guidance/workflow/README.md`; `docs/guidance/engineering/README.md`;
`AGENTS.md`; `openspec/README.md`; the openings and document map of
`docs/development/ARCHITECTURE.md`, `TESTING.md`, and `DEPLOYMENT_AND_CONFIG.md`.

- [x] 13.1 Add to `docs/guidance/engineering/documentation.md` a section, "A
  document holds one kind of material", stating D25's three kinds — a description of
  the system, read by every reader and written once; rules a change must satisfy;
  procedures a person runs, kept in handbooks — with a neutral example (D33). It is
  new guidance: the notes give its text for the triage (31 O1b). The workflow README's
  "What the workflow's guidance holds" links it as the workflow's instance.
  Note: the section is written with its billing-ledger example (its text is the
  file's, raised by no finding at round 8); the file's opening and definition of a
  permanent document name the kinds, and the `documentation` tag's description too.
  The workflow README closes "What the workflow's guidance holds" with the division
  as its instance.
- [x] 13.2 Reword the workflow README's "The layers of guidance" sentence "A file
  carries the tags its whole content needs and no more, so content needing other
  tags goes in another file" to D28's rule — a file's tags name what it covers, and
  content on another subject goes in another file — and say the same in
  `docs/guidance/engineering/README.md`'s "Tags", assuming no selection formula
  (D28, 31 O1c as amended).
  Note: the three layer READMEs say it; Grep finds the old wording nowhere outside
  the change's own documents.
- [x] 13.3 Rewrite `AGENTS.md` for the layout (D32): "Where the guidance lives" says
  this repository's guidance is this file, `openspec/README.md`,
  `docs/guidance/repository/`, the description documents, and the guidance beside
  each capability; its layer table names `docs/guidance/repository/` (its README) and
  the three description documents; "What every session reads" gains a repository row
  for `docs/guidance/repository/` beside the engineering and workflow rows. No edit
  of `load.common` is owed: its `docs/guidance/` entry covers the new files and it
  keeps the description documents by path. Verify, as task 9.3: the table's three
  directory rows hold every Markdown file `scripts/change-workflow config load common`
  expands `docs/guidance/` to, and its other rows are `load.common`'s other entries.
  Note: done as planned, the opening also saying a topic's rules are under
  `docs/guidance/repository/` and its description under `docs/development/`, and
  "Where the guidance lives" naming the handbooks outside the guidance. Verified:
  `config load common` expands `docs/guidance/` to exactly the three directories'
  files, and the table's other rows are `load.common`'s other entries; no
  `load.common` edit.
- [x] 13.4 Rewrite `openspec/README.md`'s "Documentation placement" table and the
  paragraph after it (D31, D33): the description documents' rows say each holds the
  description of its topic; a row for `docs/guidance/repository/`, the rules
  spanning this repository's systems, where a change promotes such a rule; the
  handbooks' rows — the operator handbook, the change workflow's handbook, and
  `docs/release-handbook.md`; and no row for the two removed documents. `AGENTS.md`'s
  sentence pointing here for what each repository document holds stays true.
  Note: done as planned; the paragraph after names D25's principle, linking
  `documentation.md`, and maps the workflow's cross-system documents role to the
  three description documents and `docs/guidance/repository/`, so promotion and
  guidance placement find both homes.
- [x] 13.5 Rewrite the openings of `ARCHITECTURE.md`, `TESTING.md`, and
  `DEPLOYMENT_AND_CONFIG.md`, and `ARCHITECTURE.md`'s purpose line and document map,
  to say each holds the description of its topic and to link the repository rules
  and the handbooks for the rest; a document-map row for a section that left goes
  with it (D27, D10 as amended).
  Note: done as planned; `ARCHITECTURE.md`'s map gains a missing "Operator lifecycle
  controls" row, and its "Production and staging" sentence names the rule files.
  `TESTING.md` links no handbook: its one procedure, running the lanes in GitHub
  Actions, is task 14.3's to move.
- [x] 13.6 Verify the round: `make check-guidance`; `make check-doc-citations
  CHANGE=layer-engineering-guidance` and unscoped, reporting only what the preamble
  expects; `make check-agent-skills`; `scripts/change-workflow config load common`
  listing the repository files; `scripts/change-workflow run pre-commit
  layer-engineering-guidance`, failing on nothing the preamble does not expect; a
  fresh-context check of sections 10 to 13 against D24 to D35 and the inventory.
  End-to-end: none; no pipeline scenario reads guidance, and none is owed. Owed by
  validation: nothing.
  Note: `make check-guidance` OK (102 files); `make check-agent-skills` OK; scoped
  citations report only the expected ones, unscoped adding only other changes'
  older ones; `config load common` lists every repository file; `run pre-commit`:
  relock passed, `make test` failed twice in `domains/apicredits`'
  `test_distribution_install.py` (an `ImportError` in the throwaway venv, a package
  the round does not touch, passing on rerun), `pre-commit` failing only on the two
  expected checks. The fresh-context check found the tasks met and no rule text
  lost; its findings were fixed. Declined, for closeout's documentation compliance
  and guidance placement (14.3, 14.10): pointer sentences in the description
  documents that name a component's behaviour and link its rule; `helm-charts.md`'s
  integer section; the bold lead-ins repeating their headings; the workflow README
  calling the specification a description; and no placement row for
  `openspec/README.md` itself, which predates the round.
  Round 8's triage (176, 177, 178; `design.md`, "Settled in implementation"): 176 F1,
  `ARCHITECTURE.md`'s hook-merging criterion moved to `production-code.md`, "Domain
  hooks", its inventory row split; `TESTING.md`'s gate passages and
  `DEPLOYMENT_AND_CONFIG.md`'s release-topology sentences stay, for 14.3 to re-check;
  178 O1, the inventory's "Dev's packaging and release changes, for the merge",
  from which the merge places `dev`'s text; 178 O2, the published-packages table's
  future an unowned row in the change index's package campaign. Checks: `make
  check-guidance` OK (102 files); `check index` OK; `run pre-commit` (inert paths)
  failing only on the two expected checks; the fresh-context check's findings fixed.

## 14. Closeout

The closeout task, in the order this change itself gives it (D8 as amended): the
workflow's parts from `docs/guidance/workflow/closeout.md`, roadmap currency among
them, with this repository's parts — packaging and end-to-end pipeline evidence —
from `openspec/README.md`'s "This repository's closeout parts" at the position the
list names. They are the eleven parts of `openspec/README.md`'s former "Plan
closeout requirements", reordered, plus guidance placement (D16). Replanned against round 1's triage;
nothing in it had started. Replanned at the return to design: renumbered from 10,
and amended for D24 to D35; nothing in it had started.

- [x] 14.1 Comment hygiene. Confirm; do not do it here. Run `make
  check-comment-hygiene` and `make check-history-wording`, and read the comments
  sections 8, 9, and 12 added or changed in `scripts/change_workflow/config.py`,
  `scripts/check_guidance.py`, the `scripts/check_*.py` messages, and their tests;
  anything reported returns the change to implementation.
  Confirmed: both checks OK. Every comment and docstring line the diff from `dev`
  (`cd2506b76`) adds in a `.py`, `.toml`, `.sh`, or `Makefile` was read; each
  describes the current system, names no change, review, or task, and cites
  requirements by id only.
- [x] 14.2 Import placement. Confirm; run `make check-local-imports` over the code
  sections 8, 9, and 12 added; an import that should move returns the change to
  implementation.
  Confirmed: `make check-local-imports` OK against `dev`; no function-local import
  added.
- [x] 14.3 Documentation compliance. Re-check each decision's destination against
  the placement rules as this change left them — `docs/guidance/workflow/openspec-documentation.md`,
  `openspec/README.md`'s "Documentation placement", CW-p9sa, and
  `documentation.md`'s "A document holds one kind of material" (D25) — directly, not
  by waiting for the closeout review.
  This part also moves the procedures left in a description or rules file (184 F1,
    D25 as amended there), against the text the merge of `dev` leaves. Move each step a
    person performs to the procedure document for its reader, and leave the
    description or rule it rests on in place, worded declaratively:
    - `TESTING.md`'s "To run the lanes in GitHub Actions…": its opening two
      sentences (push, `make run-e2e`, then `make fetch-e2e-logs`) go to
      `e2e-tests/README.md`'s "End-to-end lanes". What the two targets do — the
      run's selection, the logs' layout, the ZIP — stays as description.
    - `TESTING.md`'s "Set the allowance before publishing an offer…": the step goes
      to `e2e-tests/README.md`'s "Real-provisioning qualification", which already
      sets `PAYMENTS.DISPUTE_WINDOW_SECONDS`. The constraint stays in `TESTING.md`:
      the dispute window covers the allowance plus the authority's minimum filing
      window.
    - `chart-render-tests.md`'s "Obtaining Helm where its download host is
      unreachable" goes to `VALIDATION_RUNBOOK.md`'s Helm render prerequisites.
      Any rule in it ("keep it out of the repository") stays, unless shared
      guidance already states it.
    - The same class among the inventory's `Ambiguous` notes:
      - the first paragraph of `qualification-evidence.md` (row 1096), which
        instructs the qualifier, goes to the runbook's section 29;
      - `DEPLOYMENT_AND_CONFIG.md`'s "To set a value to `None`… use…" and
        "recover with `helm rollback`" (row 1120), which are operator steps (D34),
        go to the operator handbook.
    - `openspec/README.md`'s "Documentation placement" gains a row naming the
      validation runbook and a project's `README.md` as the homes of a developer's
      procedures. Its paragraph on the three kinds names them beside the
      handbooks.
    - Update the inventory rows 1090, 1092, 1096, 1100, and 1120 to the new
      destinations.
  Done. Moved: the lanes' dispatch and fetch steps, `E2E_AFTER_RUN` among them, to
  `e2e-tests/README.md`'s "End-to-end lanes" (its "CI/CD" now points there),
  `TESTING.md` keeping what the two targets do; the allowance step to
  "Real-provisioning qualification", `TESTING.md` keeping the dispute window's
  constraint; obtaining Helm to the runbook's section 5, `chart-render-tests.md`
  keeping "kept out of the repository" under "The supported Helm" (no shared rule
  states it); `qualification-evidence.md`'s first paragraph reworded as the rules it
  rests on, its missing steps added to the runbook's section 29; the two operator
  steps to a new operator handbook section, "Storefront configuration under Helm",
  `DEPLOYMENT_AND_CONFIG.md` keeping the behaviour, worded declaratively.
  `openspec/README.md`'s placement table gains the developer's-procedures row and its
  paragraph names the runbook and a project's README; the five inventory rows name
  the new homes. Each decision's destination, as the design-promotion record lists
  it, was re-checked against the placement rules: each sits where they place it. The
  permanent documents the change wrote were read for wording relative to the change
  (by a read-only helper, its findings checked before fixing): fixed `deal-scenarios.md`'s
  "Today"/"still", the workflow README's and the companion's "moves with a neutral
  example", and a truncated sentence round 6 left in the operator handbook's
  configuration migration ("Validation reaches beyond what `config migrate`
  reads"); `python-version.md`'s "To change the version…" and
  `ARCHITECTURE.md`'s "No new site read … should be added" restated declaratively.
  The two items 13.6 declined and round 8 left here still read as description:
  `TESTING.md`'s gate passages describe how the stage set is built, cite
  `test-doubles.md`, and are held by the stage test; `DEPLOYMENT_AND_CONFIG.md`'s
  "Release topology" describes what the charts refuse and the targets do. Left for
  the closeout review, as wording that predates this change and was only moved or
  re-pointed: several "today"/"not yet" sentences in `ARCHITECTURE.md`,
  `DEPLOYMENT_AND_CONFIG.md`, and two capability configuration files, and
  `deterministic-tests.md`'s past-tense account of the traps behind its seams.
- [x] 14.4 Narrative compression. Shorten the completed task notes to final
  behaviour, material evidence, deferred work, and destinations, moving any
  alternatives or review rationale into `design.md` first. `inventory.md` stays as
  change history (D2).
  Done: sections 1–13's notes, handoffs, and triage blocks shortened (this file
  from 3,456 lines to about 1,650), each triage disposition kept as one line naming
  where it landed. Moved into `design.md` first: 100 F1 and 98 R1 under "Settled at
  round 3's triage", and a new "Settled in implementation" (157 F1, round 7's
  declined points, section 11's differing pair, 176 F1, 178 O1, 178 O2). Task text is
  unchanged; `make check-tasks` OK.
- [x] 14.5 Roadmap currency. Record that no update of the repository's roadmap,
  `docs/development/ROADMAP.md`, is owed: the lesser goal this change serves lives
  in the change index, and no roadmap goal or gap row changes.
  Recorded: no roadmap edit owed. `ROADMAP.md` names no goal or gap on guidance; its
  two citations of guidance files were re-pointed in sections 4–5. Named in the
  design-promotion record.
- [x] 14.6 Campaign index currency. Set this change's row in
  `openspec/changes/README.md` to `in closeout` and link it to its archive; in the
  lesser goal, rewrite the current-state paragraph "The guidance agents load is not
  layered" to the layered guidance as it now stands, and narrow the gap row this
  change owned to loading by tag, removing the skills' restatements, moving a layer
  out, and citing guidance held elsewhere, each still unowned. Leave the dependents'
  `Depends on` (`add-skill-extension-points`, `extract-change-workflow-repository`)
  to archive cleanup. Name the update in the design-promotion record.
  Done: the row is `in closeout`, its link moved to the archive at 14.12; the lesser
  goal's current state describes the layered guidance, and its gap row is narrowed to
  loading by tag, the skills' restatements, moving a layer out, and citing guidance
  held elsewhere, all unowned, linking this change's archive for its inventory. Also
  recorded as an unowned row in the package campaign: code comments that cite
  `ARCHITECTURE.md` headings absent since before this change, found while
  re-pointing (11.5). The dependents' `Depends on` are left to archive cleanup; the
  campaign graph is unchanged. `scripts/change-workflow check index` OK. Named in
  the design-promotion record.
- [x] 14.7 Packaging. Run `make check-packaging` and resolve every failure; run
  `make check-architecture-change CHANGE=layer-engineering-guidance`; run `make
  check-agent-skills`, since the change edited `.agents/`.
  Done: `scripts/change-workflow run pre-archive layer-engineering-guidance` passed
  at `6a4ce53c2` (`make check-packaging`: every check OK; `make
  check-architecture-change`: the change owns no architecture row); `make
  check-agent-skills` OK.
- [x] 14.8 End-to-end pipeline. Confirm the pipeline passes at the closeout's code
  and record the run and its result; no scenario exercises this change's behaviour,
  which no deployed service reads. If it cannot run for an unrelated reason, record
  the blocker and its owner, and treat it as unrun.
  Recorded from validation 191, of `9ece4505c`, the merge of `dev` at `cd2506b76`
  and the code the closeout commit carries (`6a4ce53c2` changed only the index):
  e2e.yml run 43753261711 succeeded (native-ansible-gate passed; api-credits 4,
  bare-metal 98, VM 293 passed); local and Helm passed; CI owed nothing. Scenarios
  exercising the change: only those using `e2e-tests/` helpers `buy.py` and
  `compute_deal.py`, whose diff is a re-pointed citation (VM and bare-metal lanes,
  passed); otherwise the change is guidance and no scenario reads it. 9.x's owed
  Helm and pipeline observation of its fix commit is covered by the same run.
- [x] 14.9 Promotion. Write the permanent documents the proposal's "Knowledge to
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
  enforces", `openspec/specs/change-workflow/diagrams.md`, and `planning-governance`'s
  Evidence. `change-workflow/spec.md` and `market-change-workflow/spec.md` are
  written by the archive in 14.12. No id is retired.
  Amended at round 2's repeat triage (71 O1): the companion's "Closeout and
  archival" states closeout's rule in inert paths, and its "A repository's
  configuration" the default inert paths; `change-workflow/index.md`'s summary lines
  for CW-pkug and CW-n7ra are revised to match.
  Amended at round 3's triage (86 F1, 72 F2, 71 O1): `change-workflow/index.md` also
  gains an entry, with its summary line and link, for each requirement section 3
  proposed and the triage kept — CW-s7rq under "4. The engine", "Skills from one
  source"; CW-b5cf under "Permissions"; CW-e3gt under "The next-step computation";
  CW-o9hd under "The orchestrating session"; CW-t2lw under "3. Reviews and triage",
  "Triage"; and CW-w6vy under "1. The process", "The owner's directions" — and
  CW-pkug's entry links its renamed heading, its summary line naming the archive's
  own writes as exempt; the companion's "Closeout and archival" names that exemption
  beside the inert paths, and its "A repository's configuration" (under "Inert paths
  and the documents a step loads") says that with an empty declaration only changes'
  records and the archive's own writes are exempt. Verify `make check-spec-index`
  reports no `change-workflow` requirement unlisted.
  Amended at the return to design (D24 to D35): confirm the destinations sections 11
  to 13 wrote — `docs/guidance/repository/README.md` and its "Tags" (D27, D32),
  `docs/guidance/repository/diagrams.md` (D29), `documentation.md`'s "A document
  holds one kind of material" and the workflow README's "What the workflow's guidance
  holds" linking it (D25, D33), the workflow README's "The layers of guidance" and the
  engineering README's "Tags" (D28), `AGENTS.md`'s "What every session reads", "Where
  the guidance lives", and its link to the repository's tags (D32),
  `openspec/README.md`'s "Documentation placement" (D27, D33), and the description
  documents' openings (D27). D24, D26, D30, D31, D34, and D35 have no destination; no
  requirement or index entry changes for them.
  Done. `change-workflow/README.md`: a new "The repository's guidance is layered"
  under "The public surface" (D1, D3, D4, D6, D9, D19, D22, D28); "Closeout and
  archival" states closeout's rule in inert paths with the archive's own writes
  exempt and why, and the closeout list by layer with the guidance placement part
  (D8, D16, 71 O1); "Inert paths and the documents a step loads" gives the default
  inert paths and the empty declaration, and directory entries failing closed (D5,
  71 O1); its "Current limits" bullet on `[load]` names the loader's questions as
  unowned. `change-workflow/index.md`: the group "The repository's guidance" with the
  six ids; CW-s7rq, CW-b5cf, CW-e3gt, CW-o9hd, CW-t2lw, and CW-w6vy in their groups;
  CW-pkug's link to its renamed heading and its line; CW-n7ra's and CW-l7hn's lines
  revised. `market-change-workflow/index.md`'s MCW-c4ek line names the guidance check,
  and its README's "The closing checks" adds the guidance check and its guidance set
  (D15, D21). The other destinations were confirmed present. The design-promotion
  record is complete in `design.md`. `make check-spec-index
  CHANGE=layer-engineering-guidance` OK. The archive writes both `spec.md` files; no
  id is retired.
- [x] 14.10 Guidance placement (D16). Read each guidance section the change added,
  moved, or rewrote — every row of the corrected inventory, the rows of its
  "Cross-system documents by kind" as the round's triage left them, and what 14.9
  wrote — against the layer test, D25's kinds, adjacency, and exception placement;
  move what is misplaced and re-point its citations; run `make check-guidance`.
  Report for the closeout review any placement needing a decision.
  Done, by a read-only helper over every guidance file, the description documents,
  and the capability guidance, its findings checked before acting. The engineering
  and workflow layers name nothing of this repository and link no higher layer; the
  four exception rows sit where CW-x4ex places them, none recording tech debt. Moved
  or fixed: the procedures 14.3 names; `python-version.md`'s procedure sentence; the
  companion's sentence naming this repository's `load.common`, removed so the
  workflow's companion stays repository-neutral. `make check-guidance` OK (103 files,
  4 exception rows). Reported for the closeout review, each a placement decision this
  closeout does not settle: (1) `site-capacity/configuration.md` and
  `settlement-servicing/configuration.md` govern what `storefront-publication`'s and
  `deal-lifecycle`'s specifications state, against the reviewed inventory rows 548
  and 581; (2) material on profiles, the umbrella alias, the payments-check CLI, and
  run-log migration in `registry-discovery`, `settlement-configuration`, and
  `marketplace-identity` guidance reads as `deployment-state`'s, which has no
  guidance file; (3) description inside rule files — `chart-render-tests.md`'s
  catalogue of what each render test asserts, `ansible-gates.md`'s account of each
  gate, `images.md`'s "The `market` binary"; (4) operator steps in capability
  guidance (`introduction-delivery`'s re-delivery, `settlement-configuration`'s
  drain-before-change and legacy-override replacement, `storefront-publication`'s
  rollback steps and `pool-override` flags) and in `DEPLOYMENT_AND_CONFIG.md`'s
  upgrade "Remedy" column; (5) rule sentences left in `ARCHITECTURE.md` (carrier
  modules' imports, site admission's reach, `SettlementTarget` as a noun, fulfillment
  by physical identity, designs recording ordering) and `TESTING.md` (mock results
  not substituting for physical qualification); (6) `DEPLOYMENT_AND_CONFIG.md`'s
  "Bare-metal role configuration" and `qualification-evidence.md`'s guest probe,
  each possibly one capability's; (7) `service-databases.md`'s "each service owns its
  own database", a portable rule with no engineering counterpart; (8)
  `registry-discovery/configuration.md` and `physical-provisioning/configuration.md`
  possibly owing the `deployment` tag.
- [x] 14.11 Documentation citations. Run `make check-doc-citations
  CHANGE=layer-engineering-guidance` and resolve every match, the hard-case
  sample's provisional destinations, the inventory's, and the change's own citations
  of `BUILD_AND_PACKAGING.md` and `RELEASING.md` included; then
  `scripts/change-workflow openspec validate layer-engineering-guidance --strict`.
  Done: the 11 matches, all the change's own records naming the documents it
  removed, now write them by their former paths without the leading `docs/`, as a
  line at the head of `design.md`, `inventory.md`, and this file says; the hard-case
  sample's provisional destinations all exist. `make check-doc-citations
  CHANGE=layer-engineering-guidance` OK; unscoped it reports only other changes'
  citations of removed scripts and of `change-workflow/architecture.md`, as before
  the change. `scripts/change-workflow openspec validate layer-engineering-guidance
  --strict`: valid.
- [x] 14.12 Archival. Archive with `scripts/change-workflow openspec archive
  layer-engineering-guidance -y`, which merges the `change-workflow` and
  `market-change-workflow` deltas into their specifications (no `--skip-specs`), and
  link the change's row to its archive directory.
  Done: archived as `openspec/changes/archive/2026-11-15-layer-engineering-guidance/`,
  merging the deltas (the permanent specifications held none of them): twelve
  requirements added, CW-pkug renamed, CW-pkug, CW-n7ra, CW-l7hn, and MCW-c4ek
  modified. The diff of both `spec.md` files was read: each requirement appears once,
  as its delta states it, and nothing else changed. The row links the archive, and
  `scripts/change-workflow run pre-commit layer-engineering-guidance` passes.
