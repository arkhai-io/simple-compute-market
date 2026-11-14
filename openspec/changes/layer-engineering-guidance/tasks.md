# Tasks

Sections follow `design.md`'s implementation cadence: the inventory (sections 1–2),
the workflow layer (3), the engineering layer (4–5), the repository layer at the
root and across systems (6), the repository layer beside each capability (7), and
the code (8–9), then closeout (10). Every move follows the inventory as round 1's
triage corrected it (D2), its files and their tags as "Files and their tags" gives
them (31 O1c); a destination named below is the one the design's hard-case sample
gives, and the corrected inventory overrides it.

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
and on nothing else: the documentation citations of files the change creates until
they exist — and of the hard-case sample's provisional destinations in `design.md`,
which closeout's citation part resolves (task 10.11) — and the specification index,
which wants `change-workflow/index.md` entries for CW-g7lt, CW-d2rw, CW-p9sa,
CW-x4ex, CW-n6dm, and CW-r8cg, entries closeout's promotion writes (task 10.9). Any
other failure is the section's to fix. Correction, section 3: from section 3 on, the
citations check also reports the change's own `design.md`, `inventory.md`, and
`tasks.md` citing `docs/agents/domain.md`, which section 3 removes; they are change
history, resolved with the rest at closeout (task 10.11). From task 3.13 on, the
same holds for their citations of `docs/agents/change-workflow.md`, which moves to
`docs/change-workflow-handbook.md`. Correction, task 3.16 and 3.12: the
specification index check also wants CW-pkug's entry linked to its renamed heading,
"Closeout changes only inert paths", and entries for the requirements section 3
proposes — CW-s7rq, CW-b5cf, CW-e3gt, CW-o9hd, CW-t2lw, and CW-w6vy — all kept by
round 3's triage; closeout's promotion writes them (task 10.9, 86 F1).

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

Delivers the workflow layer (D1, D3, D8 as amended, D16–D19; 31 O1b, O1e, O1f):
`docs/guidance/workflow/` with its README and tag table, the closeout list with
roadmap currency and the guidance placement part, workflow material moved out of
the root documents and the workflow guide and deduplicated, `docs/agents/domain.md`
removed, every citation re-pointed. Files: `docs/guidance/workflow/*.md` (new);
`AGENTS.md`; `openspec/README.md`; `docs/agents/change-workflow.md`;
`docs/agents/domain.md` (removed); `openspec/specs/market-change-workflow/README.md`;
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
  carried (`openspec-documentation.md`, `changes.md`, `closeout.md`; `workflow` by
  all seven). `change-references.md` carries `comments` and `terms.md` `terms`,
  engineering tags a workflow file may use (D18): they belong in the engineering
  README's table, which section 4 writes and section 5 completes, so until then they
  are in no table. The README cites the ids by name, unlinked, since they reach
  `spec.md` only at the archive. Evidence: inspected (Grep over the frontmatter);
  no test applies.
- [x] 3.2 Write `docs/guidance/workflow/closeout.md` (D8 as amended, D16):
  frontmatter; the ordered list of the workflow's parts — comment hygiene, import
  placement, documentation compliance, narrative compression, roadmap currency,
  campaign index currency, the repository's own closeout parts as its root guidance
  names them, promotion, guidance placement, documentation citations, archival —
  each part under its own heading carrying its text from
  `openspec/README.md#plan-closeout-requirements` with every repository command and
  path replaced by what the repository's guidance names (roadmap currency updates
  "the repository's roadmap", 31 O1f); an engineering principle inside a part, such
  as completion not being proved by the change's own suites, cited from the part and
  left to its engineering row (31 O1g); the guidance placement part as D16 words it;
  and the promotion story from `AGENTS.md`'s "Cross-references must resolve" (D6).
  Verify no make target, no repository path, and no link to a file the inventory
  tags `repository` appears in it.
  Note: ten workflow parts under their headings, the repository's own parts listed
  at position 7 by role. Grep finds no `make `, `docs/development`, `AGENTS`,
  `ROADMAP`, `ARCHITECTURE`, `.snapshot`, `dev`, or `openspec/README` in any
  workflow file; the paths it names are OpenSpec's layout (`openspec/specs/`,
  `openspec/changes/archive/`) and the engine's command, both workflow material
  (D1). Checks are named by role: "the repository's comment check", "index check",
  "citation check", "guidance check"; `openspec/README.md` names the commands (task
  3.4). Engineering rules a part confirms are named, not linked, since their files
  do not exist until sections 4 and 5: comments describing the current system
  (Comment hygiene), citations resolving (Campaign index currency, Documentation
  citations). Part 8's engineering reason stays with part 8 in `openspec/README.md`
  for section 4 to move. Part 2's import rule itself is engineering, Python (row
  219): parked in `AGENTS.md`'s "Package and dependency discipline", which section
  5 moves to `dependencies-python.md`; the part keeps its per-section scoping.
  Part 6's account of the index check merges into the guide's "The review
  directory", which it duplicated, and the part cites it. Part 10's tombstone
  account went to `market-change-workflow`'s "The closing checks" (row 229).
  Evidence: inspected; no test applies.
- [x] 3.3 Move the rest of the workflow material to the files the corrected
  inventory names — `working-model.md`, `openspec-documentation.md`, `changes.md`,
  `change-references.md`, and `terms.md` — each with the frontmatter "Files and
  their tags" gives, the roadmap's and the capability index's roles among them
  (31 O1f); delete the moved text from `AGENTS.md`, `openspec/README.md`, and
  `docs/agents/domain.md`, keeping in place, under their final headings, what the
  inventory leaves there. Verify each workflow row of the inventory sits in its
  destination and no longer in its source.
  Note: every workflow row of the four source tables (Grep for `| workflow |`) is in
  its destination and gone from its source. What the inventory leaves in place:
  `AGENTS.md` keeps a "Working model" heading pointing to `working-model.md`, with
  this repository's completion criteria (packaging and typing checks, `make
  check-comment-hygiene`, `make check-packaging`, `ARCHITECTURE.md`) and two
  engineering criteria for sections 4–5; "Documentation ownership" keeps its
  repository bullets and the provenance bullet; "Python comments and docstrings"
  keeps the neutral rule, the check, and the Prefer example; "Deferred work" and
  "Domain docs" keep their repository rows. Engineering rows of moved sections are
  parked in `AGENTS.md` until sections 4–5 move them: `domain.md`'s rule for terms
  (row 250, "Domain docs") and part 2's import rule (above). `openspec/README.md`
  keeps the pin, its placement table (the provenance row with it, for section 5),
  "The index check" (row 211, a new heading for the check's paragraph), "This
  repository's closeout parts", and "Current capability documentation", which takes
  the capability index check (row 151). "Implementation completion checklist" and
  "Contributor workflow" are merged into `working-model.md` and gone. Evidence:
  inspected; no test applies.
- [x] 3.4 Leave this repository's closeout parts — packaging and end-to-end pipeline
  evidence — in `openspec/README.md` under `## This repository's closeout parts`,
  naming the commands each runs; and add to `AGENTS.md` the rows naming that section
  and this repository's roadmap, `docs/development/ROADMAP.md`, so closeout,
  planning, and review find both through the root guidance before section 6
  rewrites it (D8 as amended). Verify both rows' links resolve, the first to its
  heading.
  Note: the section also tables the commands the workflow's parts name by role
  (comment hygiene, campaign index currency, promotion's index check, documentation
  citations), only those the parts named before; section 6 adds `make
  check-guidance`. `AGENTS.md` gains "Where the guidance lives", a three-row table
  (the workflow's guidance, this repository's closeout parts, its roadmap) that
  section 6 extends into the layer table. Both links resolve: the heading
  `## This repository's closeout parts` slugs to `#this-repositorys-closeout-parts`,
  and `docs/development/ROADMAP.md` exists. Evidence: inspected; no test applies.
- [x] 3.5 Remove `docs/agents/domain.md` once its rows have moved (31 O1e), and
  re-point its citations, `AGENTS.md`'s "Domain docs" included. Verify the file is
  gone and `grep -rn 'docs/agents/domain.md'` over the tracked tree outside
  `openspec/changes/` finds nothing.
  Note: removed with `git rm`; Grep outside `openspec/changes/` finds nothing.
  Outside the plan: `align-package-paths-with-layers`' design and proposal cited it
  five times, which the unscoped citations check then failed; they now say "the
  domain docs (since removed)" without a path. Their content was already stale
  before this section: they describe a "platform context" that `domain.md` had not
  held since an earlier change, a contradiction left for that change's design.
  Evidence: inspected; `make check-doc-citations CHANGE=` (below).
- [x] 3.6 Give `docs/agents/change-workflow.md` frontmatter tagging it `workflow`,
  and move what the inventory finds of this repository in it — its links to
  `market-change-workflow`, its step table's validation parts, `dev`, the hook
  commands, the CI baseline, the clone's remote and evidence paths, and the rest the
  inventory's rows name — to `openspec/specs/market-change-workflow/README.md`,
  stating it there in this repository's terms, and neutralize the guide's text
  (D1's direction). Verify the guide links to no file the inventory tags
  `repository`.
  Note: every repository row of the guide's table (rows 259–281) is neutralized in
  the guide. Most instances were already stated in `market-change-workflow`'s
  README; it gains the evidence paths (`.snapshot/validation/<commit>/`, the `ci`
  part's `<short commit>/ci/`, `.snapshot/e2e-logs/<run>/`), `make
  validate-parallel`, `dev` as the base a prerequisite is proposed from, the
  orchestrator's merges, and the CI baseline, the completion script, the hook
  commands in its provisions table, `make check-change`'s unrestricted run, and the
  five closing rules with their targets, which the README had pointed to the guide
  for. Neutral examples replace the `ROADMAP` default-acceptance finding (a renamed
  companion heading), the ledger's ROADMAP redirection (cite the requirement by
  id), the `ALLOW` rule (`Bash(gh run view *)`), and the Helm-and-pipeline waiver
  ("the deployment part"). Also neutralized, beyond the rows: "validation
  dispatches the end-to-end pipeline itself" and the clone's "wheelhouse" and
  `.snapshot/`. The guide's citations of `AGENTS.md`'s "Amend a rule or comply" are
  dropped, not re-pointed: the guide may not cite `AGENTS.md`, and
  `engineering/rules.md` is section 5's, which should add them. Grep finds no
  `AGENTS.md`, `openspec/README`, `docs/development`, `market-change-workflow`,
  `ROADMAP`, `dev`, `.snapshot`, `make check-change `, or Helm in the guide. Evidence:
  inspected; `test_change_workflow_assumptions.py` (unit, below).
- [x] 3.7 Deduplicate the workflow material as the preamble says (31 O1b): merge
  agreeing copies, and list in the section's notes each differing pair the
  inventory's `Ambiguous` cells name for this layer, with both forms and the
  proposed text, and each contradiction a non-guidance document now holds. Verify
  every duplicate row this section moves is merged or listed.
  Note: the five `Ambiguous` duplicates for this section (rows 149, 187, 199, 235,
  240) and part 6's index-check account are merged or listed under "Section 3's
  differing pairs" below, with the wording changes the move made beyond the
  inventory's neutralizations. Non-guidance documents: the root `README.md`'s
  "OpenSpec contributor workflow" link now names the working model and this
  repository's OpenSpec guide; `TESTING.md` and `DEPLOYMENT_AND_CONFIG.md` cite
  `openspec/README.md` (documentation placement), which stays; no other
  contradiction found (Grep for closeout part counts, "Contributor workflow",
  `domain.md`, "Asking the owner"). Evidence: inspected; no test applies.
- [x] 3.8 Re-point every citation of moved workflow material, by name and never by
  part number (D8): the skills, from the inventory's restatements table, including
  `change-closeout`'s count of the parts and their order; `change-workflow`'s README
  and spec text; `openspec/specs/planning-governance/spec.md`'s Evidence, outside
  the archive's merge (D14); and every other document citing
  `openspec/README.md#plan-closeout-requirements` or another moved heading. The
  skills' restatements stay as they are (D11). Verify `grep -rn` over the tracked
  tree outside `openspec/changes/archive/` and `docs/prompts/` finds no citation of
  a heading this section removed.
  Note: re-pointed, from the restatements table and a Grep for every removed heading
  and anchor: the eight workflow skills (`change-closeout` now counts the workflow's
  parts and the repository's by name, covers comment hygiene through the
  repository's parts in its step 3 and promotion, guidance placement, citations, and
  archival in step 4, and gains a brief guidance placement paragraph);
  `planning-governance`'s Evidence (part numbers to `closeout.md`'s headings and
  `openspec/README.md#packaging`); `openspec/specs/README.md`; `BUILD_AND_PACKAGING.md`;
  the root `README.md`; the change index's history note; the docstrings of
  `scripts/check_spec_index.py`, `check_decision_destinations.py`, and
  `check_local_imports.py`; a `Makefile` comment; a fixture string in
  `test_change_workflow_assumptions.py`; and, by a helper subagent, the 48 citations
  in 47 other changes' `tasks.md`, plus eight "in `openspec/README.md`'s order"
  lines and `add-skill-extension-points`' design and proposal. `change-workflow`'s
  README and spec cited none. Citations of `openspec/README.md`'s "Documentation
  placement", which stays, were left. The Grep over the tracked tree outside the
  archive, `docs/prompts/`, and this change's own directory finds no citation of a
  removed heading; this change's own documents cite them as history. Evidence:
  inspected; `make check-agent-skills` OK.
- [x] 3.9 Add each new `docs/guidance/workflow/` file to `load.common` in
  `.agents/workflow.toml` by path, keeping its comment current, so later sessions on
  the branch read them (design, "Implementation cadence"); and add each repository
  path a skill now names to `openspec/specs/market-change-workflow/README.md`'s "How
  this repository provides the workflow's roles". Verify `scripts/change-workflow
  config load common` prints the new files, and `pytest -q
  scripts/tests/test_change_workflow_assumptions.py` (unit) passes.
  Note (in progress): the README's provisions name the new files ("The guidance
  documents every step reads", and `docs/guidance/` with `docs/guidance/workflow/`
  under "Where specifications and documentation live", which the test required once
  `change-review` named them), and the unit tests pass. The edit of
  `.agents/workflow.toml` was refused: the step table denies every step that file,
  so this task's `load.common` edit is the owner's or the orchestrator's, as a
  `.claude/` edit is. The edit wanted: append to `common`, after
  `"openspec/README.md"`, the seven paths `docs/guidance/workflow/README.md`,
  `working-model.md`, `openspec-documentation.md`, `changes.md`,
  `change-references.md`, `terms.md`, and `closeout.md` (each with its
  `docs/guidance/workflow/` prefix), and add to its comment that the workflow's
  guidance files follow the root and cross-system documents, each by path. Sections
  4, 5, and 9 edit the same file and meet the same refusal.
  Correction: the owner confirmed the refusal stands, and the orchestrating session
  made the edit on their word, as named above; it is committed with the section.
  `scripts/change-workflow config load common` prints the five documents before and
  the seven new files after them; `test_change_workflow_assumptions.py`,
  `test_change_workflow_config.py`, and `test_post_compaction_context.py` (unit): 91
  passed.
- [x] 3.10 Verify the section: `make check-agent-skills`; `make check-doc-citations`
  run unscoped reports nothing it did not report before the section; `pytest -q
  scripts/tests/test_change_workflow_assumptions.py scripts/tests/test_change_workflow_config.py`
  (unit); and `scripts/change-workflow run pre-commit layer-engineering-guidance`,
  whose functional hooks run every suite, reports no failure but the two the
  preamble expects. End-to-end: none; no pipeline scenario reads guidance, and none is
  owed.
  Note: `make check-agent-skills` OK. `make check-doc-citations CHANGE=` (unscoped)
  reports, outside this change's own documents, only failures older than the section
  (other changes citing scripts and an `architecture.md` that no longer exist); the
  section's breaks — `align-package-paths-with-layers` citing `domain.md`, and a
  placeholder path in `changes.md` — were fixed. The unit suites (unit): 91 passed.
  `scripts/change-workflow run pre-commit layer-engineering-guidance`:
  `after-functional-change` (relock) passed and changed no lock;
  `pre-commit-functional` (`make dist-clean`, `make check-packaging`, `make test`,
  every suite) passed; `pre-commit`'s default checks — change index, tasks, skills,
  strict OpenSpec validation — passed, and `make check-repository` failed only on
  the two the preamble expects: citations of files the change creates, with the
  change's own `domain.md` citations as the preamble's correction says, and the six
  `CW-*` entries `index.md` lacks. End-to-end scenarios covering the section: none
  confirmed, as planned. Owed by validation: nothing.

Section 3's differing pairs (31 O1b), for the round's triage — each the source
forms, then the text the section wrote:

- **When the documents are promoted (rows 149, 235, 240).** `AGENTS.md`'s Implement
  made implementation complete only once behaviour was in `spec.md`, rationale in
  the companion, and architecture in `ARCHITECTURE.md`, and "Documentation
  ownership" said durable knowledge is promoted "before a change is considered
  implemented"; `openspec/README.md`'s checklist said the same ("Subsystem-specific
  durable knowledge is present in `openspec/specs`"). Its "Contributor workflow"
  (step 5), `AGENTS.md`'s Plan ("Promotion happens post code-review"), and the
  closeout parts had the documents written at closeout. Proposed, taking the
  closeout side, which is what the workflow does: `working-model.md`'s Implement
  completes the code, the decisions' classification and the promotion record, no
  change references, and the checks run or disclosed, and a paragraph says closeout
  writes the documents; `openspec-documentation.md` says knowledge is promoted
  "before a change is archived … at closeout, after the code's last review".
- **The completion list (rows 235, 240).** Implement's and the checklist's items
  merged into one list; the checklist's classification of each decision
  (permanent, temporary, superseded, rejected) and "satisfy the change
  specification" joined it, and its validation evidence is "run and their
  validation evidence recorded, or any unrun check disclosed". The kinds of check
  ("packaging, and typing"; "package, typing") are neutralized to "the checks the
  plan names — focused, integration, and the repository's own", the kinds staying
  in `AGENTS.md`'s "Working model" (row 143). "Contributor workflow"'s steps merged
  into Discuss and Plan (read the root guidance and architecture; audit the delta;
  identify permanent documentation impact; plan only once the design is ready).
- **When citations are checked (rows 182, 184; part 10).** `AGENTS.md`'s
  "Cross-references must resolve" said to run a cross-reference check "before
  promoting documentation"; part 10 runs the citation check after promotion "so the
  documents it wrote are there to resolve". Proposed, part 10's order:
  `closeout.md`'s Promotion tells the story, its `dev` neutralized and "this has
  happened in this repository" generalized, and says the citation check catches
  it; `AGENTS.md` keeps the engineering rule and cites the two parts.
- **OpenSpec's layout (rows 149, 199).** `AGENTS.md`'s bullets and
  `openspec/README.md`'s introduction agreed; merged as the union of their
  descriptions. The capability index bullets agreed; merged as the role ("a
  canonical capability documentation index, through which a reader finds every
  normative contract and companion"), the path and its check going to
  `openspec/README.md`'s "Current capability documentation" (row 151).
- **A change's records (row 187).** `AGENTS.md`'s paragraph agreed with the guide's
  "History and removal"; removed from `AGENTS.md`, whose pointer to the guide now
  names the records.
- **The index check (part 6).** Part 6's account agreed with the guide's "The
  review directory", which adds that each dependency is listed and not archived;
  merged into the guide, which `closeout.md` cites.
- **Wording the move changed beyond the inventory's neutralizations.** The import
  rule parked in `AGENTS.md` says "the change's own diff" for the source's "the
  section's own diff" (row 219: the engineering file reads "what a change adds"),
  and the closeout part keeps the per-section scoping. `closeout.md`'s comment
  hygiene names the rules it confirms rather than citing `AGENTS.md`; its archival
  says a hand-made promotion "before archival became closeout's last part" for
  "before this rule"; the diagrams line in `openspec-documentation.md` says "each
  diagram's source and its export" for ".drawio source and .svg export", draw.io
  being this repository's selection (row 161). `changes.md`'s promotion-record
  example and template checkbox are neutral (rows 212, 232). `terms.md`'s third
  row, the repository's terms "in the home the repository's root guidance names",
  stands for the market's row. The guide's opening no longer names this
  repository's own part.

Section 3 notes (handoff):

- The `.agents/workflow.toml` edit (task 3.9) was refused, as the step table denies
  every step that file; the owner confirmed the refusal stands, and the orchestrating
  session made the edit on their word. Sections 4, 5, and 9 edit the same file: the
  plan should give those edits to the orchestrator, as it gives `.claude/` edits,
  and each section checks the edit is in its worktree before committing.
- Open for the triage, as task 3.1 asks: no workflow file carries a step or role tag
  (`design`, `plan`, `implement`, `review`, `triage`, `validate`, `archive-cleanup`,
  `orchestrate`, `owner`, `skills`, `engine`, `records`), so the README's table
  leaves them out; they return only if a later section splits `working-model.md` or
  the guide by step.
- Engineering material parked in `AGENTS.md` for later sections, beside what was
  there: the rule for terms from `domain.md` (section 5, `engineering/terms.md`),
  part 2's import rule (section 5, `dependencies-python.md`), the engineering
  completion criteria under "Working model" (section 5, `documentation.md` and
  `comments.md`). Section 4 moves part 8's reason, still in `openspec/README.md`.
- Places in workflow files where an engineering rule is named, unlinked, until its
  file exists: `closeout.md`'s Comment hygiene (comments describe the current
  system), Campaign index currency and Documentation citations (citations
  resolve), and Import placement ("the repository's guidance on imports");
  `changes.md`'s "Defects found during a change" (composition from one component,
  `engineering/implementation.md`); the guide's two dropped citations of "Amend a
  rule or comply" (`engineering/rules.md`). Sections 4–5 add the links.
- The fresh-context check found, and the section fixed: unlisted wording changes
  (listed above, or reverted where they added guidance — `change-references.md`
  widened to code and configuration, `changes.md` adding a change's records,
  `openspec/README.md` naming two checks the parts never named, a sentence added to
  `working-model.md`); `terms.md` stating "one home per term" (engineering, row
  250); duplicates inside the workflow layer (deferred work, "production code does
  not depend on `openspec/changes/`"); row 151's check left in `AGENTS.md`; the
  guide's `make check-change` statement left unrestated; an inconsistent waiver
  example; eight other changes' "in `openspec/README.md`'s order" lines; and a
  false re-pointing in `align-package-paths-with-layers`. Declined: the duplicate
  "not a harmless forward reference" across `AGENTS.md` and `closeout.md` was
  resolved by trimming `closeout.md`'s copy, not by moving the engineering rule,
  which is section 5's.

Round 2's triage (reviews 56, 57, 58), fixes and the return:

- Fixes, made in the triage session: `docs/guidance/workflow/README.md` gains "What
  the workflow's guidance holds", the rule dividing the workflow's specification,
  guidance, and operator handbook (58 O5), and drops its sentence calling the guide
  workflow guidance (58 O7); `closeout.md`'s opening is trimmed to cite the
  companion's "Closeout and archival" rather than restate it (58 O5), and gains "The
  repository's own closeout parts" with a neutral example (58 O4);
  `working-model.md` opens with its subject and links the phases (58 O2);
  `AGENTS.md`'s "Working model" section is removed, the typing checks joining
  "Tests and diagnostics" and "Amend a rule or comply" taking its own heading
  (58 O9) — section 5 writes the two engineering criteria it held from the
  inventory's rows rather than moving them; four phrases relative to the migration
  are rewritten in the workflow's `README.md`, `closeout.md`'s Archival, and
  `changes.md` (58 O3); the root `README.md`'s reading list becomes a pointer to
  `AGENTS.md`, and its validation command `scripts/openspec validate --all
  --strict`, which applies the validator's pin (58 O8). Committed as the
  work-in-progress commit of the return, unchecked by the round's checks; the
  replanned round's checks cover them.
- Tasks added: 4.7 (58 O1), 5.9 (58 O3), 5.10 (58 O6), 6.5's amendment (58 O1),
  9.4's amendment (56 F1).
- Why the change returns to planning: the owner settled at this triage that the
  workflow's guide is not guidance but the change workflow's operator handbook (D3
  as amended; "Settled at round 2's triage", 58 O7) — no frontmatter, beside the
  other handbooks in `docs/`, holding only what the owner needs, embedding the
  workflow's diagrams, its agent-facing content moved to the specification, its
  companion, or `docs/guidance/workflow/` by 58 O5's rule, and its 31 citations
  outside the changes (skills, specifications, `AGENTS.md`, `next_step.py`, two test
  files) and other changes' documents re-pointed. No section plans that work: the
  inventory's rows for the guide (258–281) need reclassifying by audience, and
  section 3's task 3.6 tagged the guide `workflow`, which the handbook undoes. The
  owner reads the round again (`make round-view`) after planning, before round 3,
  and may give further notes and run another review and triage then.

Appended at round 2's triage's return to planning: the workflow's operator handbook
(D3 as amended; 58 O5, 58 O7). Section 3 is complete again only when these are. They
undo task 3.6's tagging of the guide, which stands as done. Files:
`docs/agents/change-workflow.md`, moved to `docs/change-workflow-handbook.md`;
`docs/guidance/workflow/*.md`; `openspec/specs/change-workflow/README.md`, and its
`spec.md`'s Evidence; `openspec/specs/market-change-workflow/README.md`; `AGENTS.md`;
`.agents/skills/*/SKILL.md`; `scripts/change_workflow/next_step.py`,
`scripts/tests/test_change_next_step.py`, `scripts/tests/test_change_workflow_records.py`;
the active changes' documents under `openspec/changes/` that cite the guide;
`openspec/changes/layer-engineering-guidance/inventory.md`.

- [x] 3.11 Reclassify the inventory's rows for the guide (its `docs/agents/change-workflow.md`
  table) by 58 O5's test: each statement's home is the workflow's specification or
  its companion (wrong if the engine or a skill behaved otherwise), the workflow's
  guidance (wrong if a change's work product were otherwise), or the handbook
  (telling the owner what to do or type), with the destination file and heading,
  the reason naming the test, and `Ambiguous` saying where the test does not decide;
  and drop the guide from "Files and their tags". Verify every row of the guide's
  table names one of the three homes.
  Note: 51 rows, by statement group, each naming its home — the specification (with
  the requirements stating it, or "proposed"), the companion, the guidance, or the
  handbook — and a reason naming the test; section 1's rows are kept beneath as
  superseded history, and its repository rows, moved at task 3.6, are named in the
  table's preamble. The audit of every guide statement against `spec.md` and the
  companion was made by three read-only helper subagents, one per third of the guide,
  each verifying the requirement text it cited; their findings are the rows. The
  guide is dropped from "Files and their tags", and the restatements' and checks'
  rows citing its headings name where each now lands. Evidence: inspected; no test
  applies to a change document.
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
  Note: no new guidance file was needed, so neither the workflow table nor
  `load.common` changes. Into the guidance: the `Owed by validation:` line
  (`working-model.md`, "Plan") and one change per branch (`changes.md`, a new heading).
  Into the companion: the command's synopsis and `start`'s, `find --json`'s,
  `clone-remove --base`'s, and `wait`'s details ("The command and its tiers"); the
  review publishing check's reading, `sent_back`, `refused`, the external review, the
  record set's tree, and the workflow log's lines ("Reviews are files"); the ledger's
  line, `revises`, and the standing and cleanup waivers' lines ("The intervention
  ledger"); one command per Bash call and the harness's refused shapes
  ("Restrictions bind unattended runs only"); and the stale sentence pointing to the
  guide for the waiver criteria, which CW-q3dm states, dropped. Six proposed
  requirements in the `change-workflow` delta, listed under "Section 3's proposed
  homes" below. Everything else the guide said is stated by a requirement or the
  companion already, or is the owner's and stays in the handbook; the inventory's
  rows name which. Evidence: inspected; the strict validation runs in `run
  pre-commit` (task 3.15).
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
  Note: moved with `git mv`, then rewritten for the owner: no frontmatter; sections
  "Starting a step", "Orchestrating a change", "A change in its own clone",
  "Reviews" (with "Default acceptance"), "Waivers", "The ledger", and "The engine's
  command"; a statement of what the workflow does cites the requirement stating it,
  the companion's heading, or its proposed requirement (CW-o9hd, CW-t2lw), cited by
  id unmarked, since a "proposed" would go stale at the archive — a proposal round
  3's triage drops takes its citation with it; the
  agent-facing rules are gone to the specification, companion, guidance, or a
  proposed requirement. Repository references the rewrite first brought back (a
  link to `market-change-workflow`, MCW-3i99, the review models' vendors) were
  neutralized after the fresh-context check, as task 3.6 had the guide. Kept as the
  owner meets them, with no requirement to cite: the refusals of `round-view`,
  `round-done`, and `change-clone-remove`, named in the paragraph after "Section 3's
  proposed homes". It embeds the graph, step-run, state, and engine-parts
  diagrams from `openspec/specs/change-workflow/diagrams/`. Corrected while rewriting,
  as the audit found the guide wrong: `make change-cost` marks inseparable dollars
  partial (the guide said "a range"); a workspace round view holds review,
  validation, triage, and implementation (CW-78ul; the guide said "every step that
  could commit"); the `start` refusals, now in the companion. The empty `docs/agents/`
  directory could not be removed: `rmdir` was refused (no rule allows it), and Git
  tracks no empty directory, so the repository holds nothing of it. Evidence:
  inspected; no test applies.
- [x] 3.14 Re-point every citation of the guide to where its statement now lands:
  `AGENTS.md`'s "Where the guidance lives" table (the handbook is no workflow
  guidance) and "Agent skills"; every skill citing it; `change-workflow`'s README
  and `spec.md`'s Evidence; `market-change-workflow`'s README, its statement of how
  this repository provides the workflow's roles included;
  `scripts/change_workflow/next_step.py`'s message and the two tests naming the path;
  and the active changes' documents under `openspec/changes/` outside the archive.
  Verify `grep -rn 'docs/agents/'` over the tracked tree, outside
  `openspec/changes/archive/` and this change's own documents, finds nothing.
  Note: `AGENTS.md`'s table drops the guide and "Change workflow" points to the
  handbook; the skills' citations go to the requirement stating each rule (the
  waiver criteria to CW-q3dm in seven skills; default acceptance to CW-d5ac,
  CW-t9bx, and CW-9pbk; revisiting to CW-r8vz; interrupting to CW-k2rv; history to
  CW-hak6; waiving parts to CW-e7lm), `change-orchestrate`'s move into a clone to the
  handbook, and `change-review`'s guidance basis drops the guide; `change-workflow`'s
  README and `spec.md`'s Evidence name the handbook; `market-change-workflow`'s
  provisions drop the guide from the documents every step reads, saying the handbook
  is read by none; `closeout.md`'s index-check citation goes to CW-jyff;
  `next_step.py`'s message and the two tests name the handbook's path; eight other
  changes' documents name it; and the change index's history notes say "the
  workflow's guide (now `docs/change-workflow-handbook.md`)", as `domain.md`'s were
  handled. Of the other changes, those whose touched material moved off the guide
  were re-pointed to it: `test-affected-suite-selection` to the companion, which
  describes the hooks, and `add-skill-extension-points` to the companion and
  `closeout.md`; the rest name the handbook, for what changes for the owner. A Grep
  for `docs/agents/` outside the archive and this change finds nothing. Evidence:
  the scripts suites (unit), as task 3.15 records.
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
  Note: `make check-agent-skills` OK. The four unit suites ran inside `make
  test-release-tooling`, which runs every suite under `scripts/tests`: 2867 passed
  (unit); a direct `pytest` run of the four was refused in the forms tried (no rule
  allows `uv run --directory scripts pytest`, and `scripts/` has no pytest of its
  own). `make check-doc-citations CHANGE=` (unscoped) reports, outside this change's
  own documents, only failures older than section 3 (other changes citing scripts and
  an `architecture.md` that no longer exist). `scripts/change-workflow config load
  common` prints the seven workflow guidance files after the five root and
  cross-system documents; it reads and checks the whole configuration, as every
  reader does (CW-w8ne), standing in for `check config`, which was refused here.
  `scripts/change-workflow run pre-commit layer-engineering-guidance`, last run after
  the fresh-context checks' fixes: `after-functional-change` (relock) passed, changing
  no lock; `pre-commit-functional` (`make dist-clean`, `make check-packaging`, `make
  test`, every suite) passed; `pre-commit`'s default checks — change index, tasks,
  skills, and `scripts/openspec validate layer-engineering-guidance --strict`, "is
  valid" — passed, standing in for task 3.16's direct strict validation, which was
  refused here; and `make check-repository` failed only on the two the preamble
  expects, as corrected above: citations of files the change creates or removed
  (from its own `design.md`, `proposal.md`, `inventory.md`, and `tasks.md`), and the
  specification index wanting the six `CW-*` entries, the six proposed ones, and
  CW-pkug's link moved to its renamed heading. End-to-end scenarios covering the
  section: none confirmed, as planned. Owed by validation: nothing.
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
  Note: CW-pkug is renamed, "Closeout changes only inert paths", and modified, with a
  scenario for a citation inside a skill; CW-n7ra is modified with the default and a
  scenario for a repository declaring none; both texts are under "Section 3's
  proposed homes" below. `closeout.md`'s opening cites CW-pkug, and
  `change-closeout`'s opening restates it. The orchestrating session's edit of
  `.agents/workflow.toml`, `AGENTS.md` appended to `inert-paths`, was in the worktree
  as the routing note said, and is committed with the section; no further edit of
  that file was needed. `scripts/change-workflow openspec validate … --strict` and
  `check config` were each refused here (no rule allows those forms): the strict
  validation ran as `run pre-commit`'s default check instead, and `config load
  common`, which checks the whole configuration as every reader does (CW-w8ne),
  accepted it (task 3.15). Two tests keep naming an undeclared configuration's
  Markdown file as not inert (`test_change_workflow_records.py`'s `None` case and
  `test_change_next_step.py`'s `inert_paths=lambda _: None` case): task 8.4's default
  flips them, and they are section 8's to change.

Round 2's repeat triage (reviews 71, 72, 73): the owner accepted section 3's
differing pairs as written (72 F1); task 3.12 gives an agent rule no requirement
states a proposed home for the triage, and 3.13's check accepts it (72 F2); task
3.16, task 8.4, and 10.9's amendment carry closeout's rule restated in inert paths
and the workflow's default inert paths (71 O1); the handbook move is 3.11–3.15, the
next round (71 O2). The orchestrator's routing observations (73 R1) are workflow
maintenance after this change merges, outside it.

Section 3's proposed homes (72 F2, 71 O1), for round 3's triage — each a statement
of the guide no requirement stated, its source, and the home proposed; the full
texts are in this change's `change-workflow` delta:

- **CW-s7rq A skill restates guidance no stricter than its source.** Source, the
  guide's "Skills": "A skill that restates a rule from the guidance restates it
  briefly where its step applies it, and cites it; it is never stricter than its
  source. A step that needs a stricter rule proposes amending the guidance."
  Proposed as a requirement: how a skill is written is the skills' behaviour.
- **CW-b5cf An unattended step's calls take the forms its rules match.** Source,
  "Skills" (one command per Bash call, the Read tool, the refused shapes) and "The
  engine's command" (`wait`, never `tail -f`). Proposed as a requirement, the
  harness's shapes explained in the companion.
- **CW-e3gt A step checks its entry before it works.** Source, "Skills": planning,
  the merge, closeout, and archive cleanup ask the computation as they start;
  "the steps that act on a task list run it first".
- **CW-o9hd The orchestrating session tells the owner what it starts and leaves the
  owner's actions to them.** Source, "Orchestrating a change": it says when it starts
  a long turn, rereads the files after a takeover, and, told that the owner closed an
  interactive step before it recorded, starts nothing for it and gives the owner the
  command, never running it.
- **CW-t2lw A triage's records take their written shapes.** Source, "Default
  acceptance" (the `Classification:` line, the table's heading, default fixes made
  with the round's others), "The ledger" (the JSON line's keys, `revises`, the
  advancing exit's `next`), and "Reviews" (an external review saved verbatim,
  triaged with its kind, its fields assigned by triage). Restated today only by
  `change-triage`.
- **CW-w6vy Waivers are recommended and recorded where they are given.** Source,
  "Waivers": the recommendation in the step's existing message; planning's and the
  merge after the archive's recommendations; validation taking a standing waiver
  only from the log; a standing waiver's ledger line by where it was given; archive
  cleanup's `validated` line.
- **Guidance, `changes.md`'s "One change per branch".** Source, "Skills": a note in
  another change's documents, or a follow-up's proposal, written on the current
  branch lands with the current change. Proposed as guidance: what a change's work
  lands as. Its prerequisite sentence cites CW-dtpz rather than naming a branch,
  since CW-dtpz says "the development branch" and the guide "the branch the change
  lands on".
- **Guidance, `working-model.md`'s "Plan", the `Owed by validation:` line.** Source,
  "Reviews": what a plan writes for evidence only a push produces. Stated before
  only by `change-plan`; CW-5h8e states that it is owed, not where the plan says so.
- **CW-pkug, renamed and modified (71 O1).** Was "Closeout changes documentation
  only": "Closeout MUST change documentation only; a closeout part that would need a
  code change MUST return the change to implementation." Now "Closeout changes only
  inert paths": "Closeout MUST change only the repository's inert paths and changes'
  records; a closeout part that would change any other path MUST return the change
  to implementation", its scenario kept and one added for a citation inside a skill.
- **CW-n7ra, modified (71 O1).** Its last sentence was "The engine MUST read no
  inert path of its own; with none declared, no path is inert and only changes'
  records are exempt where a requirement exempts them." Now: "Where a repository
  declares none, the workflow's default MUST apply: `openspec/` and every Markdown
  file, `**/*.md`. A declaration, an empty one included, MUST replace the default;
  with an empty one, no path is inert and only changes' records are exempt where a
  requirement exempts them", with a scenario for a repository declaring none and one
  for an empty declaration.

Read as the companion's rather than as requirements, by this section's judgement
for the triage to revisit: the engine details the guide stated and no requirement
does — the command's synopsis, `find --json`'s fields, `wait`'s bound, the publishing
check's reading, the `sent_back` and `refused` fields, the record set's names, the
workflow log's line kinds. Each describes how the engine works rather than a rule a
step follows, so it went to the companion; promoting any to a requirement is the
triage's call. Kept in the handbook, as what the owner meets running a command: the
refusals of `round-view`, `round-done`, and `change-clone-remove` that no
requirement states — by 58 O5's test the engine's behaviour, so the triage may move
them to the companion, the handbook keeping their remedies.

Open for round 3's triage, found by the second fresh-context check: under CW-n7ra as
modified, a repository declaring `inert-paths = []` makes no path inert, and CW-pkug
as modified would then send every promotion and the archive's own writes back to
implementation. 71 O1 settled both texts; whether CW-pkug exempts the archive's
writes and the permanent documents closeout promotes, or an empty declaration is
accepted as making closeout impossible, is the owner's.

Section 3's re-run notes (handoff):

- Two fresh-context checks ran on the diff; their right findings are fixed (the
  handbook's uncited statements, its repository references, closeout's examples
  that leaned on this repository's inert paths, `market-change-workflow`'s list of
  inert paths missing `AGENTS.md`, wording of CW-t2lw, CW-b5cf, CW-o9hd, CW-w6vy,
  and CW-n7ra's scenarios, an inventory row's wrong citation, two other changes'
  re-pointing, and overstated notes). Declined: adding closeout to the
  `inert-paths` comment in `.agents/workflow.toml` — the comment names who reads the
  field, which is the engine, and the file is the orchestrating session's to edit;
  and dropping the handbook from `extract-change-workflow-repository`'s list of what
  moves with the workflow — the handbook now names no repository document, and which
  repository owns it is that change's design.
- Stale until closeout's promotion (task 10.9), as planned: the companion's
  "Closeout and archival" still says closeout changes documentation only, and
  `index.md` links CW-pkug's old heading.
- Section 8 (task 8.4) flips two test cases that name an undeclared configuration's
  Markdown file as not inert (task 3.16's note).
- The companion gained engine details from the guide, unpromoted by any
  requirement; the triage may move any into a requirement (above).
- `docs/agents/` stays on disk empty in this clone: `rmdir` was refused. Git holds
  nothing of it.
- The audit of the guide against `spec.md` and the companion, and both checks, ran
  as read-only helper subagents; an outage earlier in the session failed the first
  attempts, which were rerun.
- Not read in full this session: `ARCHITECTURE.md`, `TESTING.md`, and
  `DEPLOYMENT_AND_CONFIG.md`, which the section does not touch, and `spec.md` and the
  companion beyond the requirements and headings the section cites, which the
  helpers read.

Round 3's triage (review 86, validation 87, the owner's notes 88), fixes made in the
triage session (design, "Settled at round 3's triage"):

- 72 F2: every proposed home above is kept, and both judgement calls stand; nothing
  to edit.
- 71 O1: CW-pkug exempts the archive's own writes — the change's own documents and
  their move into the archive, its index row, and its deltas merged into the
  specifications — with a scenario for `inert-paths = []`; CW-n7ra's empty
  declaration names that exemption beside changes' records; `closeout.md`'s opening
  and `change-closeout`'s restatement match. The fresh-context check found the first
  form, exempting only the move and the merge, left closeout's task notes and index
  row unexempt, which would have kept the loop; widened.
- 86 F1: task 10.9 amended with the six proposed requirements' index entries and
  the companion's restatements; the proposal's "Knowledge to promote" gains its 72 F2
  line.
- 88 O1–O4: `docs/change-workflow-handbook.md` restructured in the order the owner
  needs it — an introduction, a table of contents, orchestrating a change (starting,
  what a change asks of the owner, reading a round, triage, interventions common
  before rare), parallel changes with the state diagram, the steps (the graph, the
  step table, a paragraph per step on its responsibility, entry, and exits, review
  options), the state on disk, the engine with its parts and step-run diagrams, and
  customization. 88 O2: it cites no requirement id, its introduction linking the
  specification, its index, and the companion once (revises 72 F2 for the handbook;
  task 3.13's check of citing each rule's home no longer applies to it). The
  inventory's guide table notes that its handbook headings name the earlier layout.
- Evidence: inspected; no focused suite applies to a document. `scripts/change-workflow
  run pre-commit layer-engineering-guidance`, run after the fresh-context check's
  fixes, ran the functional tier, since `change-closeout`'s skill lies outside the
  inert paths: `after-functional-change` passed; `pre-commit-functional` passed
  (`make test`, every suite); `pre-commit`'s defaults passed (index, tasks, skills,
  strict OpenSpec validation, "is valid"); `make check-repository` failed only on the
  two the preamble expects — citations of files the change creates or removed, from
  its own documents, and the specification index wanting the twelve `CW-*` entries
  and CW-pkug's renamed link (task 10.9). Comment hygiene passed among its other six
  checks. End-to-end: none; no scenario reads the handbook or guidance.
- The fresh-context check of the diff against `d1df2948f` found, and the triage
  fixed: the handbook's closeout paragraph and the restatements missing the archive's
  exemption, a stale "outside the inert paths" in `change-closeout`, the
  customization section saying no step edits the skills or guidance, inert paths
  described as needing no validation at all, a deployed-validation bullet stating
  one repository's cluster as fact, the merge's exits read as a fallback, and dropped
  details (the pre-closeout review's inert-path ancestor, failed validations and
  closeout's return among the owner's stops, the default rule's last condition, the
  merge's choice of branch without `FROM`, an external review's file name, the
  `after-functional-change` hook). It found nothing on unimplemented behaviour, links
  and anchors, or wording relative to the change.

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

- [ ] 4.1 Write `docs/guidance/engineering/README.md`: frontmatter `tags:
  [engineering]`; what the layer holds; its organization (D19); and its `## Tags`
  table, `engineering` its first row, holding the tags this section's files carry
  (D7, D18); section 5 completes it. Verify every tag a file of this section
  carries is in the table.
- [ ] 4.2 Move the engineering testing material to the fifteen files, each with the
  frontmatter "Files and their tags" gives, each general rule given a neutral
  example in place of this repository's (31 O1a), each language or tool form in the
  file its tags give (D7, 31 O1c), and the operator-control rule's test half in
  `test-seams.md` (31 O1g); this repository's statement of each rule stays as its
  instance and cites the engineering file. Verify each engineering testing row of
  the inventory sits in its destination, and no file of this section names a
  package, service, document, or make target of this repository.
- [ ] 4.3 Deduplicate the testing material as the preamble says (31 O1b), listing
  among the differing pairs the test levels the skills name (unit, library
  integration, application integration, system) against `TESTING.md`'s (unit,
  integration, smoke, system), which the restatements table records. Verify every
  duplicate row this section moves is merged or listed.
- [ ] 4.4 Delete the moved text from its sources, leaving in each what the inventory
  keeps, and re-point every citation of what moved, skills included. Verify `grep
  -rn` over the tracked tree outside `openspec/changes/archive/` and
  `docs/prompts/` finds no citation of a heading this section removed, and no
  engineering file links to a file the inventory tags `workflow` or `repository`
  (D1's direction).
- [ ] 4.5 Add the README and each new testing file to `load.common` by path. Verify
  `scripts/change-workflow config load common` prints them.
- [ ] 4.6 Verify the section as task 3.10 does. End-to-end: none; no pipeline
  scenario reads guidance, and none is owed.
- [ ] 4.7 Before 4.6's verification (58 O1): move the argument of
  `openspec/README.md`'s "End-to-end pipeline" part — that a change is not complete
  because its own suites pass, and what the end-to-end tier catches — to the
  engineering testing file 31 O1g names; drop its blocker sentence, which restates
  `working-model.md`'s "any unrun check is disclosed"; and leave the part as one
  declarative statement of what this repository's closeout records (the run at the
  closeout's code, its result, the scenarios exercising the change), citing both.
  Verify the part holds no instruction or argument beyond that statement.

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

- [ ] 5.1 Move the remaining engineering material to its files, each with the
  frontmatter "Files and their tags" gives, each general rule given a neutral
  example (31 O1a), each tool or language form in the file its tags give (D7,
  31 O1c): the project layout's Python, uv, and Hatchling rows to their packaging
  files, this repository's selection of Hatchling staying (29 F1); `RELEASING.md`'s
  versioning policy to `versioning.md` and `versioning-python.md`, its repository
  reasons staying and citing them (D10 as amended); and the operator-control rule's
  production half to `implementation.md` (31 O1g). Verify each remaining engineering
  row of the inventory sits in its destination, and no file of this section names a
  package, service, document, or make target of this repository.
- [ ] 5.2 Write `rules.md` from "Amend a rule or comply" as a framework for when an
  exception to shared guidance is expected — exceptions expected once other
  repositories change the shared guidance, the rule's purpose of stopping an owner
  from declaring everything an exception kept — proposing its wording in the
  section's notes for the round's triage to review (31 O1e, D9). Verify the notes
  hold the proposed wording beside the source's.
- [ ] 5.3 Write what may enter a repository (D6) in `repository-content.md`: what
  holds in every repository, what a public repository additionally refuses, and
  what a private one may hold — the last limited to what a private repository may
  hold that a public one may not, the one piece of new guidance this change writes —
  from `AGENTS.md`'s "Public repository discipline", with "Cross-references must
  resolve"'s rule in `documentation.md`. Verify the private-repository part adds no
  obligation.
- [ ] 5.4 Complete the engineering README's `## Tags` table with the tags this
  section's files carry (D18). Verify every tag an engineering file carries is in
  the table, and every table row is carried.
- [ ] 5.5 Deduplicate as the preamble says (31 O1b). Verify every duplicate row this
  section moves is merged or listed.
- [ ] 5.6 Delete the moved text from its sources, leaving in each what the inventory
  keeps, and re-point every citation of what moved, skills included. Verify as task
  4.4 does.
- [ ] 5.7 Add each new file to `load.common` by path. Verify `scripts/change-workflow
  config load common` prints them.
- [ ] 5.8 Verify the section as task 3.10 does. End-to-end: none; no pipeline
  scenario reads guidance, and none is owed.
- [ ] 5.9 Before 5.8's verification (58 O3): `documentation.md` states that
  permanent documentation and guidance describe the system they apply to
  declaratively and read as timeless even while they change constantly, with no
  wording relative to a migration or a planned change. Verify the rule is in
  `documentation.md` and no file of sections 3 to 5 phrases guidance relative to
  this change's move.
- [ ] 5.10 Before 5.8's verification (58 O6): in `docs/guidance/workflow/closeout.md`,
  each part names and links the rules it confirms, each to its own layer's file —
  "Comment hygiene" the engineering comment rule (`comments.md`) and the workflow's
  change-references rule separately, "Documentation citations" and "Campaign index
  currency" the engineering citation rule (`documentation.md`), "Import placement"
  the import rule (`dependencies-python.md`) — and "Documentation compliance" also
  confirms the permanent documents the change wrote against `documentation.md`'s
  current-state rule (5.9), besides placement; `change-closeout`'s restatement is
  re-pointed to match (D11). Verify every rule a part names is linked to a file of
  its layer, and `make check-agent-skills` passes.

## 6. The repository layer at the root and across systems

Delivers the repository layer's root and cross-system guidance (D3, D8 as amended,
D9, D10 as amended, D13, D17, D18, D21's manual override; 31 O1b, O1f):
`AGENTS.md` rewritten as the entry, `openspec/README.md` as this repository's guide,
the cross-system documents tagged and deduplicated, and the classification of the
checks. Files: `AGENTS.md`; `openspec/README.md`; `docs/development/ARCHITECTURE.md`,
`TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`, `BUILD_AND_PACKAGING.md`, `RELEASING.md`;
`openspec/specs/market-change-workflow/README.md`.

- [ ] 6.1 Rewrite `AGENTS.md` (D3, D9, D18): frontmatter `tags: [repository]`; the
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
- [ ] 6.2 Finish `openspec/README.md` as this repository's OpenSpec guide (D3, D8):
  frontmatter; its placement table naming `docs/guidance/` and capability guidance
  files beside capabilities; the validator pin; the capability index itself, whose
  role the workflow states (31 O1f); its closeout parts naming `make check-guidance`
  where the guidance placement part runs the repository's guidance check (D21).
  Verify it holds no row the inventory tags `workflow`.
- [ ] 6.3 Give `ARCHITECTURE.md`, `TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`,
  `BUILD_AND_PACKAGING.md`, and `RELEASING.md` frontmatter with the tags their
  content needs (D10, D17) — `VALIDATION_RUNBOOK.md` stays outside the guidance set,
  with no frontmatter and no layer-table row (48 F1) — and move what the inventory
  finds misfiled across systems, such as "Public repository content checks" and
  "Validation namespaces" to `market-change-workflow`'s README. Verify each document
  opens with its frontmatter and appears in `AGENTS.md`'s layer table, and the
  runbook does neither.
- [ ] 6.4 Write the classification of the checks (D13) in
  `openspec/specs/market-change-workflow/README.md` as `### What each check enforces`
  under "This repository's checks": a table of each check, the rule it enforces
  linked to its guidance, that rule's layer, and where it runs, from the inventory's
  corrected draft, the guidance check marked as enforcing workflow rules from this
  repository's script. Verify every row of the draft is in the table.
- [ ] 6.5 Deduplicate the repository material as the preamble says (31 O1b),
  including the handbook and runbook duplicates the inventory recommends for one
  home. Verify every duplicate row this section moves is merged or listed.
  Amended at round 2's triage (58 O1): `openspec/README.md`'s "Packaging" part is
  reduced to the checks it runs, citing `BUILD_AND_PACKAGING.md` for what each
  enforces rather than restating it.
- [ ] 6.6 Re-point every citation of what this section moved, and verify the
  section as task 3.10 does. End-to-end: none; no pipeline scenario reads guidance,
  and none is owed.

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

- [ ] 7.1 Move each section the corrected inventory places beside a capability — by
  the owner of what it governs (31 O1d) — into a guidance file in that capability's
  directory, each with frontmatter `tags: [repository, <topic>]` and no capability
  tag (D18), or into its companion where the inventory says the text describes the
  system, deleting it from its source. Verify each such row sits in its destination,
  and no file in a capability directory but `spec.md`, its companion, and `index.md`
  lacks frontmatter.
- [ ] 7.2 Put each exception the inventory found that applies to one capability in
  that capability's guidance file, as an `## Exceptions to shared guidance` row
  (D9, CW-x4ex): at least the hand-laid change-workflow graph's `overrides` row
  against `docs/guidance/engineering/diagrams.md`, in a new
  `openspec/specs/change-workflow/diagrams.md` (`tags: [repository, diagrams]`)
  citing the "Current limits" bullet on generating the graph (31 O1e, 48 F2). Verify
  each row cites a guidance file and sits beside the one capability it applies to.
- [ ] 7.3 Deduplicate the capability material as the preamble says (31 O1b). Verify
  every duplicate row this section moves is merged or listed.
- [ ] 7.4 Extend the seven skills' reading lists — `change-design`, `change-plan`,
  `change-implement` (both of its lists), `change-review`, `change-triage`,
  `change-merge`, and `change-closeout` — so that wherever each reads a capability's
  specification and companion it also reads every other Markdown file in the
  capability's directory but its `index.md` (D22, CW-r8cg). Verify `make
  check-agent-skills` passes and each skill's list names the guidance files.
- [ ] 7.5 Re-point every citation of what this section moved, and verify the
  section as task 3.10 does. End-to-end: none; no pipeline scenario reads guidance,
  and none is owed.

## 8. `[load]` directory entries

Delivers directory entries in `[load]` (D5; CW-l7hn, modified). Files:
`scripts/change_workflow/config.py`, `scripts/change_workflow/hook.py` where its
handling needs it; `scripts/tests/test_change_workflow_config.py`,
`scripts/tests/test_change_workflow_hooks.py`.

- [ ] 8.1 Make `config.documents()` expand an entry ending in `/` into the Markdown
  files beneath it, recursively, in sorted path order, each document once across
  `load.common` and `load.<step>`, and refuse with a `StepError` naming the entry a
  directory entry that is missing, unreadable, or holds no Markdown file; literal
  entries and an absent or empty list resolve as before. `config load` reports the
  refusal as an error rather than a traceback. Verify with unit tests: a directory
  entry expands in sorted order in place of the directory; an entry naming a missing
  directory, a file, an unreadable directory, and a directory with no Markdown each
  refuse naming the entry; a literal missing file is still printed; and the
  existing "Design loads the roadmap" test passes.
- [ ] 8.2 Verify the post-compaction hook names the expanded files for a directory
  entry, and, for a refused entry, tells the session the documents to re-read are
  unknown (CW-l7hn's scenario "A directory entry names nothing"), with unit tests in
  `test_change_workflow_hooks.py`.
- [ ] 8.3 Verify the section: `pytest -q scripts/tests/test_change_workflow_config.py
  scripts/tests/test_change_workflow_hooks.py` (unit), then `make test-release-tooling`,
  and `scripts/change-workflow run pre-commit layer-engineering-guidance`.
  End-to-end: none; the engine's loading runs in no pipeline scenario, and none is
  owed. Run after task 8.4, which it verifies too, adding
  `scripts/tests/test_change_workflow_records.py` to the unit run.
- [ ] 8.4 Give the engine the default inert paths of CW-n7ra as task 3.16 modifies
  it (71 O1): where `repository.inert-paths` is absent, the configuration's inert
  paths are `openspec/` and `**/*.md`; a declared list, an empty one included,
  replaces the default. Keep `records.inert`'s and `records.exempting`'s docstrings
  current. Files: `scripts/change_workflow/config.py`,
  `scripts/change_workflow/records.py`, and their tests. Verify with unit tests: an
  absent key yields the default; a declared list yields itself; an empty list yields
  no inert path; and `records.inert` treats a nested Markdown file as inert under
  the default.

## 9. `make check-guidance`

Delivers the guidance check and `load.common` collapsed to one entry (D5, D9, D15,
D16, D21; MCW-c4ek, modified; CW-g7lt, CW-d2rw, CW-x4ex as checked rules), and the
fixes the check finds in the guidance. Files: `scripts/check_guidance.py` (new),
`scripts/tests/test_check_guidance.py` (new); `scripts/check_change.py`,
`scripts/tests/test_check_change.py`; `Makefile`; `.agents/workflow.toml`; guidance
files the check finds wanting.

- [ ] 9.1 Write `scripts/check_guidance.py`, standard library only like the other
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
- [ ] 9.2 Add `make check-guidance` to the `Makefile` and to `scripts/check_change.py`'s
  checks, so `make check-repository` runs it, and name it in `check-repository`'s
  help text. Verify `test_check_change.py` (unit) covers the new check and passes.
- [ ] 9.3 Collapse `load.common` to `AGENTS.md`, `docs/guidance/`, the cross-system
  documents, and `openspec/README.md` (D5), with its comment current. Verify
  `scripts/change-workflow config load common` prints every guidance file sections 3
  to 5 listed by path, and nothing more under `docs/guidance/`.
- [ ] 9.4 Run `make check-guidance` over the tree and fix in the guidance whatever it
  reports — a missing tag, an unused row, a stale anchor, an upward link — each fix
  following the corrected inventory. Verify `make check-guidance` passes.
  Amended at round 2's triage (56 F1): before that gate, this change's own
  documents (`design.md`, `tasks.md`, `inventory.md`) name each heading the change
  removed in prose — `` `openspec/README.md`, "Plan closeout requirements" `` —
  rather than as an anchored citation, and the `market-change-workflow` delta's
  scenario "A guidance link's section moved" uses a neutral example rather than a
  real removed anchor, which would otherwise fail the check from the permanent
  `spec.md` once archived. Task 10.11 remains the final sweep.
- [ ] 9.5 Verify the section: `pytest -q scripts/tests/test_check_guidance.py
  scripts/tests/test_check_change.py` (unit), then `make test-release-tooling`, and
  `scripts/change-workflow run pre-commit layer-engineering-guidance`, which now runs
  the guidance check. End-to-end: none; no pipeline scenario runs the closing
  checks, and none is owed.

## 10. Closeout

The closeout task, in the order this change itself gives it (D8 as amended): the
workflow's parts from `docs/guidance/workflow/closeout.md`, roadmap currency among
them, with this repository's parts — packaging and end-to-end pipeline evidence —
from `openspec/README.md`'s "This repository's closeout parts" at the position the
list names. They are `openspec/README.md#plan-closeout-requirements`'s eleven
parts, reordered, plus guidance placement (D16). Replanned against round 1's triage;
nothing in it had started.

- [ ] 10.1 Comment hygiene. Confirm; do not do it here. Run `make
  check-comment-hygiene` and `make check-history-wording`, and read the comments
  sections 8 and 9 added to `scripts/change_workflow/config.py`,
  `scripts/check_guidance.py`, and their tests; anything reported returns the change
  to implementation.
- [ ] 10.2 Import placement. Confirm; run `make check-local-imports` over the code
  sections 8 and 9 added; an import that should move returns the change to
  implementation.
- [ ] 10.3 Documentation compliance. Re-check each decision's destination against
  the placement rules as this change left them — `docs/guidance/workflow/openspec-documentation.md`,
  `openspec/README.md`'s "Documentation placement", and CW-p9sa — directly, not by
  waiting for the closeout review.
- [ ] 10.4 Narrative compression. Shorten the completed task notes to final
  behaviour, material evidence, deferred work, and destinations, moving any
  alternatives or review rationale into `design.md` first. `inventory.md` stays as
  change history (D2).
- [ ] 10.5 Roadmap currency. Record that no update of the repository's roadmap,
  `docs/development/ROADMAP.md`, is owed: the lesser goal this change serves lives
  in the change index, and no roadmap goal or gap row changes.
- [ ] 10.6 Campaign index currency. Set this change's row in
  `openspec/changes/README.md` to `in closeout` and link it to its archive; in the
  lesser goal, rewrite the current-state paragraph "The guidance agents load is not
  layered" to the layered guidance as it now stands, and narrow the gap row this
  change owned to loading by tag, removing the skills' restatements, moving a layer
  out, and citing guidance held elsewhere, each still unowned. Leave the dependents'
  `Depends on` (`add-skill-extension-points`, `extract-change-workflow-repository`)
  to archive cleanup. Name the update in the design-promotion record.
- [ ] 10.7 Packaging. Run `make check-packaging` and resolve every failure; run
  `make check-architecture-change CHANGE=layer-engineering-guidance`; run `make
  check-agent-skills`, since the change edited `.agents/`.
- [ ] 10.8 End-to-end pipeline. Confirm the pipeline passes at the closeout's code
  and record the run and its result; no scenario exercises this change's behaviour,
  which no deployed service reads. If it cannot run for an unrelated reason, record
  the blocker and its owner, and treat it as unrun.
- [ ] 10.9 Promotion. Write the permanent documents the proposal's "Knowledge to
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
  written by the archive in 10.12. No id is retired.
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
- [ ] 10.10 Guidance placement (D16). Read each guidance section the change added,
  moved, or rewrote — every row of the corrected inventory, and what 10.9 wrote —
  against the layer test, adjacency, and exception placement; move what is misplaced
  and re-point its citations; run `make check-guidance`. Report for the closeout
  review any placement needing a decision.
- [ ] 10.11 Documentation citations. Run `make check-doc-citations
  CHANGE=layer-engineering-guidance` and resolve every match, the hard-case
  sample's provisional destinations and the inventory's included; then
  `scripts/change-workflow openspec validate layer-engineering-guidance --strict`.
- [ ] 10.12 Archival. Archive with `scripts/change-workflow openspec archive
  layer-engineering-guidance -y`, which merges the `change-workflow` and
  `market-change-workflow` deltas into their specifications (no `--skip-specs`), and
  link the change's row to its archive directory.
