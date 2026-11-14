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

Round 3's repeat pass (review 100, validation 97, the owner's notes 99 — none —, the
orchestrating session's record 98), fixed in its triage session:

- 100 F1: the handbook's opening no longer says validation runs before every review,
  nor that the workflow reaches a merged pull request. By the owner's choice it
  describes the whole lifecycle through the merge and says where the workflow stops:
  archive cleanup ends it, drafting the merge commit message and pull request
  description and copying the history, the orchestrating session opens the pull
  request, and its review and merge are the owner's; validation runs "wherever a
  later step relies on" the change's commits.
- 98 R1 (validation started waived parts before finding the waiver): no action in
  this change; the owner deferred it, with 73 R1, to workflow maintenance after this
  change merges.
- Evidence: inspected; no focused suite applies to a document. `scripts/change-workflow
  run pre-commit layer-engineering-guidance` ran `pre-commit` alone, the fix lying
  only under inert paths: index, tasks, skills, and strict OpenSpec validation
  passed; `make check-repository` failed only on the two the preamble expects
  (citations of files the change creates or removed, and the specification index,
  task 10.9). End-to-end: none.
- The fresh-context check of the diff against `ad02f56e9` found the first wording
  had archive cleanup end by drafting, though it copies the history after, and left
  unsaid who opens the pull request; both fixed. It found the validation clause
  accurate and nothing on citations or wording relative to the change.

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
  Note: the table holds `engineering`, `testing`, `dependencies`, `persistence`,
  `python`, `helm`, and `ansible`, each carried by a file of this section (Grep over
  the frontmatter). The organization paragraph states D7's split (a principle's file
  and its tool form's file) beside D19. `comments` and `terms`, which two workflow
  files carry, join the table with section 5's files. Evidence: inspected; no test
  applies.
- [x] 4.2 Move the engineering testing material to the fifteen files, each with the
  frontmatter "Files and their tags" gives, each general rule given a neutral
  example in place of this repository's (31 O1a), each language or tool form in the
  file its tags give (D7, 31 O1c), and the operator-control rule's test half in
  `test-seams.md` (31 O1g); this repository's statement of each rule stays as its
  instance and cites the engineering file. Verify each engineering testing row of
  the inventory sits in its destination, and no file of this section names a
  package, service, document, or make target of this repository.
  Note: every engineering row of the `TESTING.md` table, and `ARCHITECTURE.md`'s
  testing rows (aggregate targets, the levels, the deterministic-sequence rule, the
  test double, the concurrency tests), `AGENTS.md`'s "Tests and diagnostics" rule
  row, and `openspec/README.md`'s part 8 reason (task 4.7) sit in the file their row
  names, checked row by row against the inventory. Two rows of the `TESTING.md`
  table bound for other topics wait for section 5: the secret-canary method and the
  private-dependency rule (`repository-content.md`). A Grep of the sixteen files for
  this repository's names (`make `, `kit/`, `arkhai`, `storefront`, `alkahest`,
  `lane`, `payments`, `buyer`, the guidance documents, relative links out of the
  directory) finds none; every link is to a file of this section. `test-seams.md`
  names the operator-control rule's production half without a link, since
  `implementation.md` is section 5's; section 5 adds the link. Evidence: inspected;
  no test applies.
- [x] 4.3 Deduplicate the testing material as the preamble says (31 O1b), listing
  among the differing pairs the test levels the skills name (unit, library
  integration, application integration, system) against `TESTING.md`'s (unit,
  integration, smoke, system), which the restatements table records. Verify every
  duplicate row this section moves is merged or listed.
  Note: the pairs, and the wording the move changed, are under "Section 4's
  differing pairs" below: the test-level names, the two test-double statements
  (row 511), and the runbook's observation method beside `system-tests.md`
  (row 666). Rows 162 and 370 (the dependency questions) and 563 (a document kind's
  method beside the handbook) were written for the old section 4, which held the
  whole engineering layer; their material is section 5's, whose deduplication
  (task 5.5) lists them; the inventory's cells still say "section 4's triage" in
  the old numbering the preamble explains.
  Non-guidance documents: the validation runbook's observation method adds to
  `system-tests.md`'s and is left as it is; a Grep of `e2e-tests/README.md`, the
  tools' READMEs, `helm/README.md`, and the operator handbook for the moved rules'
  terms (outcomes, sleeps, raw calls, deterministic controls) found only statements
  that agree. Evidence: inspected; no test applies.
- [x] 4.4 Delete the moved text from its sources, leaving in each what the inventory
  keeps, and re-point every citation of what moved, skills included. Verify `grep
  -rn` over the tracked tree outside `openspec/changes/archive/` and
  `docs/prompts/` finds no citation of a heading this section removed, and no
  engineering file links to a file the inventory tags `workflow` or `repository`
  (D1's direction).
  Note: `TESTING.md` keeps every heading but "Coverage Contract Between Levels",
  each reduced to this repository's instances with a citation of its engineering
  file; its opening drops the current-practice clause (row 443). `ARCHITECTURE.md`'s
  "Testing strategy" keeps its pointers, the lanes, and the doubles' examples, citing
  the files; its aggregate-targets sentence and "Deterministic database-concurrency
  tests" body become citations, the latter heading kept for the subsections sections
  5–7 move. `AGENTS.md`'s "Tests and diagnostics" keeps its two repository bullets
  under a pointer to the engineering files, and "Amend a rule or comply"'s example
  names `test-levels.md`, since the levels now change there. Re-pointed, from a Grep
  for `TESTING.md` over every tracked permanent document and code file: the
  test-level citations in `change-review`, `change-plan`, `change-design`,
  `change-implement` (both), and `change-triage` (their restatements kept, D11); the
  change index's citation of "Tests wait on events, never on durations";
  `site-capacity`'s companion (seeding state no API expresses); `ROADMAP.md`'s
  command-module and stage-wait rows; `openspec/README.md`'s placement row for
  `TESTING.md`, which named it the home of test-level jurisdiction; `TESTING.md`'s
  own "rejection-path rule"; the root `README.md`'s "testing boundaries" link;
  `market-change-workflow`'s provisions row "The guidance documents every step
  reads", which names each engineering file by path, as the assumptions test
  requires once a skill names one; and, outside the plan, the docstrings and comments of
  seventeen test modules and e2e helpers that cited `TESTING.md` for a level
  definition, the rejection-path or parity rule, the no-sleeps rule, or the
  command-module convention, now naming the engineering file. Citations of
  `TESTING.md` for what it still holds (the migration-test instances, the lanes, the
  frps tests, the chart render tests' home) were left. `openspec/config.yaml` cites
  no heading and is left (D23). A Grep for the removed heading and its anchor
  (`coverage-contract-between-levels`) outside the archive, `docs/prompts/`, and
  this change finds nothing; the other changes citing `TESTING.md` anchors cite
  headings that stay, and their plans to promote into `TESTING.md` meet the move at
  their own merge (D15). Each engineering file links only to files of the same
  directory. Evidence: inspected; `make check-agent-skills` OK; the edited test
  modules run in `run pre-commit`'s suites (task 4.6).
- [x] 4.5 Add the README and each new testing file to `load.common` by path. Verify
  `scripts/change-workflow config load common` prints them.
  Note: the step table denies `.agents/workflow.toml` to every step, so the
  orchestrating session made the edit on the owner's standing word (seq 74), as the
  section named it: the sixteen paths appended after `closeout.md`, and the comment
  saying the engineering files follow the workflow's. `scripts/change-workflow
  config load common` prints the twelve documents before them and the sixteen
  engineering files after. Evidence: inspected.
- [x] 4.6 Verify the section as task 3.10 does. End-to-end: none; no pipeline
  scenario reads guidance, and none is owed.
  Note: `make check-agent-skills` OK. `make check-doc-citations CHANGE=` (unscoped)
  reports, outside this change's own documents, only failures older than section 3
  (other changes citing scripts and an `architecture.md` that no longer exist).
  `scripts/change-workflow run pre-commit layer-engineering-guidance`, last run after
  both fresh-context checks' fixes: `after-functional-change` (relock) passed,
  changing no lock; `pre-commit-functional` (`make check-packaging`, `make test`,
  every suite, the edited test modules among them) passed, `make
  test-release-tooling` with 2867 passed (unit), among them
  `test_change_workflow_assumptions.py` and `test_change_workflow_config.py`, the
  first run having failed on the provisions row until it named the engineering files
  by path; `pre-commit`'s default checks — change index, tasks, skills, and strict
  OpenSpec validation, "is valid" — passed; and `make check-repository` failed only
  on the two the preamble expects: citations of files the change creates or removed,
  from its own documents, and the specification index wanting the twelve `CW-*`
  entries and CW-pkug's renamed link (task 10.9). Comment hygiene and history wording
  passed among its other six checks. The first fresh-context check found the End-to-end
  part short of the workflow's rule for a repository part, citations of `TESTING.md`
  left on moved rules (code, `site-capacity`, `ROADMAP.md`, the placement row), and
  unlisted generalizations; the second, a widened library-integration sentence that
  contradicted two docstrings, a dropped form of the wait rule, a narrowed
  signed-message rule, the real-server exception missing from
  `test-determinism.md`, the README restating the workflow's tag rule, docstrings
  citing a file without the heading, and the provisions row; all fixed. Declined:
  adding heading anchors to the docstrings that cite `test-levels.md` for a level's
  definition, since the file as a whole is that definition. End-to-end scenarios
  covering the section: none confirmed, as planned. Owed by validation: nothing.
- [x] 4.7 Before 4.6's verification (58 O1): move the argument of
  `openspec/README.md`'s "End-to-end pipeline" part — that a change is not complete
  because its own suites pass, and what the end-to-end tier catches — to the
  engineering testing file 31 O1g names; drop its blocker sentence, which restates
  `working-model.md`'s "any unrun check is disclosed"; and leave the part as one
  declarative statement of what this repository's closeout records (the run at the
  closeout's code, its result, the scenarios exercising the change), citing both.
  Verify the part holds no instruction or argument beyond that statement.
  Note: the argument is `testing.md`'s "Work is not complete because its own tests
  pass" (row 226), "a change" read as any unit of work and "cannot settle" as
  "cannot do its work". The part is one sentence of what the closeout records,
  citing that heading and `working-model.md`'s "Implement" for the disclosure of an
  unrun check. Evidence: inspected; no test applies.

Section 4's differing pairs (31 O1b), for the round's triage — each the source
forms, then the text the section wrote:

- **The test levels' names (the restatements table's `change-plan`,
  `change-implement`, and `change-triage` rows).** The skills name four levels:
  unit, library integration, application integration through the typed client,
  and system. `TESTING.md` named unit, integration, smoke, and system, with
  "library packages" and a "third flavour" of real external processes described
  inside integration. Proposed: `test-levels.md` keeps `TESTING.md`'s four levels
  and names integration's three forms — application integration, library
  integration, and external-process integration — so the skills' names are
  integration's forms; the skills keep their restatement (D11), now citing
  `test-levels.md`. The skills leave out smoke, since a section's suites never run
  against a deployed stack; that stands.
- **A test double mirrors its producer (row 511).** `ARCHITECTURE.md`'s "Testing
  strategy" paragraph and `TESTING.md`'s "Private Service Dependencies" second
  paragraph agreed; merged into `test-doubles.md` as their union, keeping
  `TESTING.md`'s reason (a test against a double proves the client's handling of a
  decision, not the decision's arithmetic) and `ARCHITECTURE.md`'s "a double of a
  service" for "a double of a private service".
- **An observation's outcome (row 666).** `system-tests.md` takes `TESTING.md`'s
  per-observation outcome (made, failed, unproven; a stage not collected is not
  run). The validation runbook's "Observations the qualification owes" states the
  same outcome and adds three rules: an observation is never inferred from another,
  a failed or unproven outcome is sorted by its cause, and the candidate is frozen
  with every observation made again on a new one. The forms do not contradict, so
  the runbook is left as it is. Open for the triage: whether `system-tests.md` also
  states that an observation is never inferred from another, which holds anywhere.
- **Wording the move changed beyond neutralizing examples.** `test-levels.md` names
  integration's forms (above). `testing.md`'s "Work is not complete because its own
  tests pass" reads part 8's "a change" as any unit of work. `helm-render-tests.md`
  states as a rule that every chart's render tests run from one entry point, from
  the source's reason for calling each from `test-render.sh`. `test-seams.md`'s third
  trap says a timer loop waits through something that returns on a pause request,
  from the controller's `idle`, the source's instance. `system-tests.md` says a
  deadline is reached by moving the record's time into the past and stepping the loop
  that acts on it, from `TESTING.md`'s VM lease-end paragraph, and reads "a scenario
  that makes a deal" as one "that performs the work a locally verifiable scenario
  performs — a purchase, say". `testing-python.md` gives the command-module rule and
  the no-sleeps form each a neutral code example.
- **The End-to-end pipeline part against the workflow's rule for a repository's
  part (task 4.7).** Task 4.7 asked for one declarative statement of what the
  closeout records, its blocker sentence dropped; `closeout.md`'s "The repository's
  own closeout parts" asks each such part to say what it confirms, the command it
  runs, and what a failure means. Proposed, both held in one sentence: the part
  records the run at the closeout's code, dispatched by `make run-e2e` and collected
  by `make fetch-e2e-logs`, its result, and the scenarios; a failed run returns the
  change to implementation; a run that could not be made is recorded as unrun,
  naming its cause and the change that owns it — the blocker sentence's content
  that `working-model.md`'s disclosure of an unrun check does not state.

Section 4 notes (handoff):

- `.agents/workflow.toml` (task 4.5) is the orchestrating session's to edit, on the
  owner's word (seq 74): the section stopped before 4.5, named the edit, and was
  resumed once it was made; section 5's task 5.7 meets the same stop.
- A skill naming a new guidance path must find it in `market-change-workflow`'s
  provisions row, path by path, or `test_change_workflow_assumptions.py` fails.
- Inventory row 734 recommends `change-design` name `docs/guidance/engineering/`
  beside `ARCHITECTURE.md` for an owner's principle that holds anywhere; it fits
  section 5, whose implementation rules are such principles.
- `test-seams.md`'s "Pause the loop, then advance it explicitly" names the
  production half — the implementation guidance's operator-control rule — without a
  link, since `implementation.md` is section 5's; section 5 adds the link when it
  writes that rule.
- Left in `TESTING.md` for section 5: the secret-canary method under "Marketplace
  Identity Verification" and the private-dependency rule opening "Private Service
  Dependencies", both `repository-content.md` rows. Left for section 7: every
  capability section, the negotiation-runtime instance among them; for section 5 or
  6, `ARCHITECTURE.md`'s subsections under "Deterministic database-concurrency
  tests", whose body is now a citation.
- The engineering README's table holds only this section's tags; `comments` and
  `terms`, which `change-references.md` and `workflow/terms.md` carry, join with
  section 5's files (task 5.4).

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
  Note: twenty-four files; `implementation-python.md` is not created, since the
  route pattern's package split gives no reason of Python's own — the thin client
  package exists so a caller need not install service code, which holds in any
  language — open for the triage, as row 384 asks. Every engineering row of the
  `AGENTS.md`, `openspec/README.md`, `domain.md`, `ARCHITECTURE.md`, `TESTING.md`
  (the two left by section 4), `DEPLOYMENT_AND_CONFIG.md`, `BUILD_AND_PACKAGING.md`,
  and `RELEASING.md` tables not moved by section 4 sits in the file its row names,
  checked row by row: `AGENTS.md`'s and the checklist's to `documentation.md`,
  `rules.md`, `comments.md`, `diagrams.md`, `dependencies.md`,
  `dependencies-python.md` (part 2's import rule among them), `packaging.md`,
  `repository-content.md`, and `terms.md`; `ARCHITECTURE.md`'s to
  `implementation.md` (composition from one component, the standalone component,
  thin controllers, the route pattern, the authority test, operator lifecycle
  controls, no speculative guard code, an existing library), `persistence.md`
  (accepted representations, schema changes, atomic cutovers), and, for "Local
  development", `configuration.md`; `DEPLOYMENT_AND_CONFIG.md`'s to
  `configuration.md`, `configuration-python.md`, `definition-documents.md`,
  `deployment.md`, `kubernetes.md`, `helm.md`, and `migrations.md`;
  `BUILD_AND_PACKAGING.md`'s to the five packaging files, the project layout split
  into its Python, uv, and Hatchling rows with this repository's selection of
  Hatchling staying (29 F1); and `RELEASING.md`'s versioning policy and lower-bounds
  paragraph to `versioning.md` and `versioning-python.md` (D10 as amended). The
  rules the check classification names for `check-uv-setup`, `check-locks`,
  `check-python-version`, `check-project-layout`, and `check-uv-version` are each
  stated in a packaging file. The route pattern's diagram moved with `git mv` beside
  `implementation.md` (`route-contract-pattern.drawio` and `.svg`), its one
  repository word, "pydantic", made "schema", so it is redrawn neutrally as row 384
  asks; `ARCHITECTURE.md` keeps that its wire models are pydantic models. A Grep of
  the twenty-four files for this repository's names (`arkhai`, `market_`,
  `storefront`, `alkahest`, `kit/`, `make `, `.dist`, `uv_project`, `reinit`,
  `ARKHAI`, `helm/`, `mockMode`, `EIP-191`, `registry`, `docs/`, `openspec`, the uv
  minimum and lock revision) finds none; every link is to a file of the same
  directory. Two helper subagents wrote the configuration and deployment files and
  the packaging and versioning files, from the inventory's rows; this session wrote
  the rest and read theirs. Evidence: inspected; no test applies.
- [x] 5.2 Write `rules.md` from "Amend a rule or comply" as a framework for when an
  exception to shared guidance is expected — exceptions expected once other
  repositories change the shared guidance, the rule's purpose of stopping an owner
  from declaring everything an exception kept — proposing its wording in the
  section's notes for the round's triage to review (31 O1e, D9). Verify the notes
  hold the proposed wording beside the source's.
  Note: `rules.md` has three headings — "Amend a rule or comply", for a rule the
  repository owns; "When an exception is expected", for shared guidance the
  repository does not own alone, a selected case or an overridden rule declared with
  its reason beside what it applies to; and "What an exception is not", which keeps
  the rule's purpose. The source and the proposed text are under "Section 5's
  differing pairs" below. It names no table or workflow requirement, since D9's
  table shape is CW-x4ex's and an engineering file may not cite the workflow; the
  repository's tables are section 6's and 7's. `AGENTS.md`'s heading keeps the
  testing-levels example and cites `rules.md`. The guide's two dropped citations of
  the rule, which section 3 left for this section, landed in CW-s7rq's requirement
  text ("proposes amending the guidance"), which carries no link, so none was added.
  Evidence: inspected; no test applies.
- [x] 5.3 Write what may enter a repository (D6) in `repository-content.md`: what
  holds in every repository, what a public repository additionally refuses, and
  what a private one may hold — the last limited to what a private repository may
  hold that a public one may not, the one piece of new guidance this change writes —
  from `AGENTS.md`'s "Public repository discipline", with "Cross-references must
  resolve"'s rule in `documentation.md`. Verify the private-repository part adds no
  obligation.
  Note: "In every repository" holds no credentials, fixtures that are obviously
  fixtures, and referring to work that is not here (its Prefer and Avoid examples
  kept); "In a public repository" holds the opening (world-readable, permanently),
  the refused list with wallet addresses as the example of account identifiers (row
  177), `TESTING.md`'s private-dependency rule (row 510), and its secret-canary
  method (row 495), each with neutral wording; the opening states that a design note
  is as public as code (row 178's neutral example). "In a private repository" names
  what the public part refuses that a private repository may hold, keeps the
  credentials and fixture rules, and ends "Nothing here obliges a private repository
  to hold any of it": it adds no obligation. The citation rule is
  `documentation.md`'s "Citations resolve". `AGENTS.md` keeps "This repository is
  public" (section 6's exception row), the pairing rule, the local-configuration
  statement, and the cited directories, each citing its file; "Never enters this
  repository" and "Referring to work that is not here" are gone from it, and no
  citation named either. `TESTING.md`'s "Private Service Dependencies" and both its
  canary bullets cite the file. Evidence: inspected; no test applies.
- [x] 5.4 Complete the engineering README's `## Tags` table with the tags this
  section's files carry (D18). Verify every tag an engineering file carries is in
  the table, and every table row is carried.
  Note: twenty-one rows, the inventory's engineering vocabulary in its order:
  `engineering`, eleven topics, and the tools `python`, `uv`, `hatchling`, `docker`,
  `kubernetes`, `helm`, `ansible`. A Grep over the forty engineering files'
  frontmatter, the README's among them, finds every tag they carry in the table and every row carried;
  `comments` and `terms` are carried too by `workflow/change-references.md` and
  `workflow/terms.md`, as D18 lets a workflow file use a lower layer's tags.
  Evidence: inspected; no test applies.
- [x] 5.5 Deduplicate as the preamble says (31 O1b). Verify every duplicate row this
  section moves is merged or listed.
  Note: the pairs, and the wording the move changed, are under "Section 5's
  differing pairs" below: rows 162 and 370 (the dependency questions and the import
  and declaration sentences, merged into `dependencies.md`, the two sources keeping
  their instances and citing it), row 563 (the method's "Validate before the
  release" beside the operator handbook, merged), the current-state rows 141, 236,
  443, and 520 (merged into `documentation.md`), and the provenance rows 152 and
  204 (merged, the placement table's row citing the file). Rows 148 and 167, and the
  handbook overlaps of rows 550, 565, 570, 571, 575, 578, and 582, are repository
  material: their cells' "section 5's triage" is the old numbering, section 6's now.
  Non-guidance documents the moved guidance contradicts, for the round's fixes:
  `e2e-tests/README.md`'s configuration table, which puts `.env` as a file layer
  between `config.yml` and `settings.toml`, where `configuration-python.md` has
  dotenv values join the environment layer above every profile; and the operator
  handbook's opening, which says `DEPLOYMENT_AND_CONFIG.md` holds "the method every
  definition document follows", now `definition-documents.md`, which that document
  cites (stale rather than contrary). `tools/README.md`'s standalone components and
  `docs/domain-authoring/README.md`'s versioning advice agree. Evidence: inspected;
  no test applies.
- [x] 5.6 Delete the moved text from its sources, leaving in each what the inventory
  keeps, and re-point every citation of what moved, skills included. Verify as task
  4.4 does.
  Note: each source keeps its repository instances under their headings, citing the
  engineering file. Headings removed: `AGENTS.md`'s "Never enters this repository"
  and "Referring to work that is not here", and "Python comments and docstrings"
  renamed "Comments" since the rule is no longer Python's alone there;
  `ARCHITECTURE.md`'s "No speculative guard code" and "Prefer an existing library",
  "Implementation rules" keeping its examples and a citation; and
  `DEPLOYMENT_AND_CONFIG.md`'s "Reconciliation follows the document, not the
  process". `RELEASING.md`'s "Versioning policy" stays as a pointer naming this
  repository's check and `VersionedEnvelope`, since many documents cite it.
  `ARCHITECTURE.md`'s "Operators" and `DEPLOYMENT_AND_CONFIG.md`'s key-meaning
  sentence cite `versioning.md`; its "Local development" rules cite
  `configuration.md`. Re-pointed, from a Grep for each removed or reduced heading
  and anchor and for each moved rule's source: `change-review` (the documentation
  questions), `change-implement` (comments, imports, `TYPE_CHECKING`),
  `change-closeout` (task 5.10), `change-archive-cleanup` and `guidance-review` (the
  public case), and `change-design` (an owner's principle that holds anywhere may go
  to `docs/guidance/engineering/`, inventory row 734); the docstrings and messages of
  `check_comment_hygiene.py`, `check_history_wording.py`, `check_local_imports.py`,
  `check_version_bumps.py`, and the five packaging check scripts, and a `Makefile`
  comment; `evidence_routes.py`'s, the bare-metal storefront `config.py`'s, and
  the API-credits service `database.py`'s docstrings (the last found by the
  fresh-context check, the first Grep having missed it); `physical-provisioning`'s companion (the route pattern);
  `market-change-workflow`'s provisions rows, naming each new file by path and
  `docs/guidance/engineering/` among where documentation lives, as the assumptions
  test requires once a skill names them; `openspec/README.md`'s provenance row; and
  other changes' documents citing a moved rule (`redesign-authenticated-requests`,
  `check-storefront-environment-reads`, `relay-vm-access-without-a-dashboard`'s
  promotion rows, its completed task records left as history). Citations of what
  stays were left. A Grep for each removed heading and its anchor outside the
  archive, `docs/prompts/`, and this change finds nothing; each engineering file
  links only to files of its directory. Evidence: inspected; `make
  check-agent-skills` OK; `run pre-commit`'s functional suites, which import the
  edited modules, passed (task 5.8), though no test reads a docstring or the check
  scripts' re-pointed failure messages.
- [x] 5.7 Add each new file to `load.common` by path. Verify `scripts/change-workflow
  config load common` prints them.
  Note: the step table denies `.agents/workflow.toml` to every step, so the section
  stopped and named the edit, and the orchestrating session made it on the owner's
  standing word (seq 74): the twenty-four paths appended after `ansible-checks.md`,
  the comment unchanged, since it already says the engineering files follow the
  workflow's, each by path. `scripts/change-workflow config load common` prints the
  twelve documents before them and the forty engineering files. Evidence: inspected.
- [x] 5.8 Verify the section as task 3.10 does. End-to-end: none; no pipeline
  scenario reads guidance, and none is owed.
  Note: `make check-agent-skills` OK. `make check-doc-citations CHANGE=` (unscoped)
  reports, outside this change's own documents, only failures older than section 3
  (other changes citing scripts and an `architecture.md` that no longer exist).
  `scripts/change-workflow run pre-commit layer-engineering-guidance`, nineteen
  paths outside the inert paths: `after-functional-change` (relock) passed;
  `pre-commit-functional` (`make check-packaging`, `make test`, every suite,
  `make test-release-tooling` with `test_change_workflow_assumptions.py` and
  `test_change_workflow_config.py` among its unit suites) passed; `pre-commit`'s
  default checks passed; and `make check-repository` failed only on the two the
  preamble expects — citations of files the change creates or removed, from its own
  `design.md`, `inventory.md`, `proposal.md`, and `tasks.md`, and the specification
  index wanting the twelve `CW-*` entries and CW-pkug's renamed link (task 10.9).
  Comment hygiene and history wording passed among its other six checks. The
  fresh-context check's fixes after that run touched documents, one docstring, and
  the change's notes; the whole run, functional tier included, was made again on
  them, with the same result: every hook and suite passed but those two expected
  checks. End-to-end
  scenarios covering the section: none confirmed, as planned. Owed by validation:
  nothing.
- [x] 5.9 Before 5.8's verification (58 O3): `documentation.md` states that
  permanent documentation and guidance describe the system they apply to
  declaratively and read as timeless even while they change constantly, with no
  wording relative to a migration or a planned change. Verify the rule is in
  `documentation.md` and no file of sections 3 to 5 phrases guidance relative to
  this change's move.
  Note: `documentation.md`'s "Permanent documents describe the current state" holds
  it, merged with `AGENTS.md`'s and the checklist's current-state rows (141, 236) and
  with the "corrected in place" clause `TESTING.md`'s and `DEPLOYMENT_AND_CONFIG.md`'s
  openings dropped (rows 443, 520). A Grep of `docs/guidance/` for "now", "no
  longer", "moved", "previously", "formerly", "used to", "will be", "this change",
  and section numbers finds only text describing the system — a change being closed
  out, a contract moved across a boundary, a shape a producer no longer emits, the
  change-references Avoid example, and the rule's own list of such words — none
  relative to this change's move. Evidence: inspected; no test applies.
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
  Note: "Comment hygiene" names the two rules separately, linking
  `comments.md#comments-describe-the-current-system` and `change-references.md`;
  "Import placement" links `dependencies-python.md#imports-go-at-module-level` in
  place of "the repository's guidance on imports"; "Documentation compliance" adds
  the current-state confirmation, linking `documentation.md`'s heading; "Campaign
  index currency" and "Documentation citations" link `documentation.md#citations-resolve`.
  "Promotion" names the citation check's purpose without a rule of its own, and the
  repository's own parts are named by role, as 58 O6 says. `change-closeout`'s step
  3 cites the same files for comment hygiene, import placement, and documentation
  compliance, and step 4's citations check cites `documentation.md`. Outside the
  plan: `workflow/changes.md`'s "Defects found during a change" links
  `implementation.md#composition-from-one-component`, the unlinked rule section 3 left
  for this section. `make check-agent-skills` OK. Evidence: inspected.

Section 5's differing pairs (31 O1b, 31 O1e), for the round's triage — each the
source forms, then the text the section wrote:

- **The exceptions framework (row 146, 31 O1e).** Source, `AGENTS.md`: "When work
  conflicts with a written rule, amend the rule first or make the work comply;
  never record a private exception to it." Proposed, `rules.md`: "Amend a rule or
  comply" keeps the source for a rule the repository owns, adding that a wrong rule
  is changed where it is written; "When an exception is expected" says shared
  guidance, changed by every repository sharing it, does not fit every one, so an
  exception is expected where it conflicts with a need the repository can state — a
  case it leaves open, selected, or a rule, overridden — declared with its reason
  beside what it applies to, never kept privately or noted at one line of code;
  "What an exception is not" says it never stands in for amending the repository's
  own rule, that holding the repository to more than a shared rule asks is an
  ordinary rule (D9's narrowing), and that declaring everything an exception is
  what the rule prevents, a shared rule fitting no repository being proposed for
  amendment where it is shared. `AGENTS.md` keeps "amend the rule first or make the
  work comply", now "and declare an exception to shared guidance only as
  `rules.md` says".
- **The dependency questions (rows 162, 368, 370).** `ARCHITECTURE.md`'s three
  questions and `AGENTS.md`'s "a change whose edges all point a permitted way has
  answered the direction and knowledge questions, not the ownership one" agreed;
  merged into `dependencies.md`'s "Three questions place a package", with neutral
  examples. `ARCHITECTURE.md` keeps layer, scope, and its ownership examples, and
  `AGENTS.md` that review answers ownership. `ARCHITECTURE.md`'s "Repository
  layers" sentences on every import form and on declared distributions agreed with
  `AGENTS.md`'s bullets; merged into `dependencies.md` and `dependencies-python.md`,
  "Repository layers" citing both.
- **Validate before the release (row 563).** The method's bullet and the operator
  handbook's "Validate a changed document before the release that mounts it"
  agreed; merged into `definition-documents.md`, taking the handbook's "A clean
  validation is the release's go-ahead", and the source's reason, the chart's
  `Recreate`, made conditional: "where a release stops the running service before
  starting its replacement". The handbook is left as it is.
- **Current state and provenance (rows 141, 152, 204, 236, 443, 520).** Agreeing
  copies merged into `documentation.md`; the openings' "corrected in place" joined
  the current-state rule.
- **Wording the move changed beyond neutral examples.** `implementation.md`: the
  authority test states as rules what the source gave through the storefront–site
  instance — a rule one party declares but does not enforce where it decides is
  advisory to the other, and a message missing what it must carry is refused where
  it is acted on rather than read as asking for less (the escrow instance); "nothing
  in their markets requires the difference" reads "nothing their own requirements
  state calls for"; "customer-issue diagnosis" reads "diagnosing a reported
  problem". `persistence.md`: "unsupported mandate forms" reads "a form the reader
  never supported", and "zero nonterminal contracts" reads "no open record using a
  form", their instances staying in `ARCHITECTURE.md`. `repository-content.md`:
  "operator test funds, or ledger reads" reads "operator-held test funds", the
  ledger reads staying in `TESTING.md`'s instance. `configuration.md`: the pod's
  environment rule is narrower than the source, which let a pod set "any variable
  an external subprocess reads" and then said its example is not set on the pod —
  a container sets only the resolver variables, and the service exports such a
  variable from its settings once; the source's carve-out for a value "kept from
  the loader" stays out of the shared rule (row 531). `definition-documents.md`
  adds one sentence summarising the per-kind reasons for entries a document stops
  naming (disable what a declaring document stops naming; retain what others depend
  on or the API registered). `documentation.md` defines "permanent document", which
  no source did, since the file's rules turn on it. `migrations.md` states generally that the application
  starts only once the migration succeeds, which the source said of Compose.
  `kubernetes.md` states the `enableServiceLinks` instance as a rule for any pod
  whose loader reads a prefixed override layer. `helm.md` leaves out "`null` removes
  a key", since Helm removes a subchart's `null` only where its defaults define the
  key. `packaging.md` says "runtime version" for "Python version" and "one store of
  built packages" for "the wheelhouse", and states as a rule that whatever needs the
  set of internal packages derives it from the lock; `packaging-uv.md` adds "No
  source path to a sibling" as the uv form of the wheelhouse principle, from the
  `[tool.uv.sources]` check, and "a lock is current only when it agrees with its
  project, the wheels the tree builds, and that store", from the checks table;
  row 600's history clause reads as the present reason. `versioning.md` reads "a
  change" as "a unit of work merged as one" and drops the link to semver.org, since
  engineering files link only to each other.

Section 5 notes (handoff):

- `.agents/workflow.toml` (task 5.7) was the orchestrating session's edit, as task
  4.5's; section 9's collapse of `load.common` meets the same stop.
- Section 6 inherits, in `AGENTS.md`: the kept repository instances under each
  heading, each citing its engineering file; "Python comments and docstrings"
  renamed "Comments"; the fourth dependency bullet still duplicating
  `ARCHITECTURE.md` (row 167) and "review answers ownership" said twice; and the
  public-case statement for its exception row. In `openspec/README.md`, the
  Packaging part's "Passing test suites do not prove this" restates
  `packaging.md`'s "Packaging checks run before a commit" (task 6.5's amendment).
- Kept in `BUILD_AND_PACKAGING.md`, though general uv practice: bringing a lock to
  the running uv's revision (`uv lock --upgrade-package`), which no row moves and
  `market-change-workflow`'s README cites there; a candidate for `packaging-uv.md`.
- The route-contract diagram sits flat beside `implementation.md`: `mkdir` of a
  `diagrams/` directory was refused (no rule allows it), and `git mv` needs its
  destination's directory to exist.
- Two helper subagents wrote the configuration and deployment cluster and the
  packaging and versioning cluster; their per-row reports are summarized in tasks
  5.1, 5.5, and 5.6 and the differing pairs above. A fresh-context check of the diff
  found a missed docstring citation, a canary bullet left restating the method,
  four unlisted wording changes, and a rule given two homes in `helm.md` and
  `configuration.md`; fixed — the helm duplicate trimmed to the chart's derivation,
  `helm.md`'s hex forms restored as alternatives, the comment rule's added
  condition and the dependency-order gloss reverted, the definition of "permanent
  document" listed — and the notes' overstated counts and evidence corrected.
- Not read in full this session: `DEPLOYMENT_AND_CONFIG.md`, `BUILD_AND_PACKAGING.md`,
  and `RELEASING.md`, which the helpers read and edited; this session read their new
  files' headings and `packaging.md`, `versioning.md`, `configuration.md`, and
  `helm.md` whole.

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
