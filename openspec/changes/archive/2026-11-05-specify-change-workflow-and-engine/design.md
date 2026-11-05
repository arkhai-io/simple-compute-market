# Design: specify the change workflow and its engine

Status: design settled, revised by the triages of design reviews 18 (F1–F4) and
25 (F1–F3), and of pre-closeout review 71 (F1, F2); implemented, closed out, and
archived, each decision's permanent location in the design-promotion record at the
end. The decisions below are the owner's, reached in
the design discussion and those triages. The ledger (`interventions.jsonl`) records
where the owner decided otherwise than the agent recommended.

## Context

- **Engine package.** `scripts/change_workflow/` holds one concern per module, on
  the standard library alone. Its `__init__.py` lists fifteen of them and omits
  `common` and `subagents`. `common.py` hardcodes `STEPS` and `KINDS` apart from
  `graph`, and anchors the engine to its place in this repository with
  `ROOT = Path(__file__).resolve().parents[2]`. `run_change_step.py`, beside it in
  `scripts/`, runs its command line.
- **The engine is not a package with scripts beside it.** The package imports the
  standalone scripts: `cli.py` imports `change_clone`; `log.py`, `review.py`, and
  `convert.py` import `find_change`; `convert.py` imports `change_next_step`, which
  imports the package back, a cycle resolved through `sys.path`. The next-step
  computation imports `_DEPENDENCY`, `INDEX`, `Row`, and `index_rows` from
  `check_change_index.py`, so the change index's format is an engine input.
- **Engine scripts outside the package.** `change_next_step.py` (the next-step
  computation), `change_clone.py`, `round_view.py`, `change_history.py`,
  `find_change.py`, `change_cost.py`, and the checks `check_change_index.py`,
  `check_tasks.py`, `check_push_ready.py`, and `check_agent_skills.py`, with the
  Claude Code hook `post_compaction_context.py` and the shell completion
  `scripts/completions/make-change.bash`.
- **This repository's scripts that import the engine.** `check_change.py`,
  `check_doc_citations.py`, and `validate_slice.py` import `find_change`;
  `validate_parallel.py` imports `change_clone`. The starting direction's "a
  repository never imports the engine" does not hold today.
- **The Makefile holds engine logic.** Only the `Makefile` launches a step
  interactively (`claude "/change-design $(CHANGE)"`), refuses an archived change
  for design, planning, implementation, and the merge (`find_change.py --active`),
  holds the `round-view-closed` precondition, names the orchestrating session's
  model and effort, defaults the merge's branch to `dev`, and turns `ALLOW` into
  grants.
- **This repository's own material.** `change_namespace.py`, `validate_slice.py`,
  `ci_evidence.py`, `fetch-e2e-logs.py`, `validate_parallel.py`, and the `helm/`
  targets serve this repository's validation; `check_change.py` composes engine
  checks with engineering ones.
- **Step table.** `scripts/change_workflow/steps.py` reads
  `.claude/change-steps.toml`: each step's skill, Claude Code permission rules,
  models, and `resume_from`.
- **Outcome and log.** An outcome conforms to `.agents/change-outcome.schema.json`
  and names a target in the graph. `log` is the workflow log's only writer, and
  every line carries `"format": 2`. `convert` brings older records into that
  format; `remove-workflow-log-conversion` removes it. The engine also parses
  Markdown records: a validation record's `- **Commit:**` and `- **Result:**`
  lines (`records.py`), and a review's reviewed commit.
- **Harnesses.** `harness` runs a step as headless Claude Code (`claude -p`) and a
  review in Codex's read-only sandbox (`codex exec`) first.
- **The specification as it stands.** `change-workflow`'s specification has 24
  requirements in 1,952 lines, every one over the 500 characters that
  `@fission-ai/openspec` 1.14.1 rejects under `--strict`. Some hold for any
  repository; others, such as "Each Helm validation is isolated in its change's
  namespace", only for this one. Its Evidence omits `change-merge` from the leaf
  skills. About 25 files cite it by requirement name.
- **What a delta can do.** OpenSpec's archive appends ADDED requirements at the
  end of `## Requirements` (the last three requirements of `change-workflow` are
  exactly `workflow-steps-name-next-step`'s ADDED ones), and a delta changes only
  requirement blocks. A spec has one level of outline.
- **Diagrams.** The workflow has one, `change-workflow-graph`, in
  `docs/development/diagrams/`. `make change-graph`
  (`scripts/change_workflow/diagram.py`) compares its hand-laid source with the
  graph table.
- **Architecture checks.** `docs/development/ARCHITECTURE.toml` skips `scripts/`.
- **Dependents.** `add-workflow-capability-contract`,
  `sandbox-unattended-workflow-steps`, `add-skill-extension-points`,
  `extract-change-workflow-repository`, and `add-workflow-harness-adapters` gate
  their design on this change reaching `archived`.
- **Other changes editing `change-workflow`.** `remove-workflow-log-conversion`,
  `workflow-round-review-without-merges`, and `shorten-long-requirements`, all
  `ready for design`.

## Principles

The owner stated these in the discussion. Each governs the decisions below and is
promoted as the proposal's "Knowledge to promote" names.

- **Documentation follows the specification.** A component's documents take its
  specification's organization.
- **A component's `README.md` is its most human-readable document.** The
  procedural index of its requirements is a separate `index.md`.
- **A diagram is held to code only when generated deterministically from a
  well-structured source.** Otherwise it is maintained like any other
  documentation.
- **This repository is the workflow's first adopter.** What every adopting
  repository will need is worked out here first.
- **The engine's promise is its command.** Conveniences, such as make targets,
  ship without a compatibility promise.

## Decisions

### D1. One change

The specification restructure, the documentation, the engine review and its
fixes, the surface classification, and the assumptions inventory land as one
change. The documentation is written in line with the restructured
specification, and the dependents are not started before the whole update is
done.

Rejected: splitting the process specification's restructure into its own change,
so the dependents could start once the engine was described; splitting three ways,
which would classify a surface before the engine's boundary was drawn.

### D2. One `change-workflow` capability, organized by its index

The workflow and its engine stay one capability. Its requirements are organized
by its `index.md` (D15), not by their order in `spec.md`, which an archive does
not preserve.

Rejected: a separate `change-workflow-engine` capability. One audience may want
only one half, but the structure a second capability would give is given by the
index, and one capability keeps one path and keeps a rule that is both process and
enforcement in one requirement.

### D3. This repository's workflow requirements in `market-change-workflow`

What holds only for this repository moves to a capability of its own,
`market-change-workflow`: the Helm validation namespace and capacity record,
validation's local, Helm, pipeline, and CI parts, the CI dispatch list and the
comparison with `dev`, and this repository's values (protected branches `main` and
`dev`, the merge's default branch, the model policy's forbidden models, the
clone's bootstrap). The seam: a general requirement states the rule and where a
repository's part plugs in ("validation's parts are the repository's"; "the push
MUST refuse the repository's protected branches"); this repository's capability
states what it adds. It is the shape every adopting repository will have, and this
repository works it out first.

Rejected: a final part of `change-workflow`, which extraction would have to move
again; the existing subject capabilities (`test-compatibility`,
`deployment-state`), which know nothing of the workflow; leaving the clauses
inline.

### D4. The engine consolidated behind one command

Every engine script moves into `scripts/change_workflow/` as a module, with
relative imports, and is reached through one executable, `scripts/change-workflow`,
whose name extraction installs unchanged and which nothing can import:

```text
scripts/change-workflow start <step> <change> [--unattended] [--allow …] [--sections …] [--session …] [--arguments …] [--fresh]
scripts/change-workflow next | record | note | review | find | clone | clone-remove | clone where
scripts/change-workflow round-view | round-done | watch | cost | history | push
scripts/change-workflow check index | check tasks | check push | check skills | check graph
scripts/change-workflow hook post-compaction | convert
```

The engine includes: the package; the next-step computation; clones, round
views, history, record lookup, and cost; the index, task-list, push, and skill
checks; the post-compaction hook; the shell completion. The Makefile's entry logic
— the interactive launch, the archived-change refusal, the round-view
precondition, the grants — moves into `start`. The old scripts are removed rather
than kept as shims, and every caller is moved: skills, the step table's rules, the
`Makefile`, the guide, the completion, the hook wiring, the tests.

The workflow's make targets move into the package as a fragment,
`scripts/change_workflow/workflow.mk`, which the root `Makefile` includes after
setting this repository's values (`CHANGE_WORKFLOW_MERGE_FROM := dev`,
`CHANGE_WORKFLOW_REVIEW_BASE := dev`); the fragment declares its defaults with
`?=`. At extraction the CLI prints the installed fragment's path for the include.

Every operation the scripts offer today carries over (CW-r3ka), and each
subcommand not classified otherwise by name in D6 is public (CW-5qne):

| Today | The command |
|---|---|
| `run_change_step.py run <step> <change> …` | `start <step> <change> --unattended …` |
| a step's make target without `UNATTENDED` (`claude "/change-<step> <change>"`) | `start <step> <change>` |
| `claude --model … --effort … "/change-orchestrate <change>"` in the `Makefile` | `start orchestrate <change>`, on the step table's `[orchestrator]` row (D5, 3) |
| `run_change_step.py resume`, `review`, `record`, `convert`, `log`, `watch`, `denials`, `note` | the same names, same arguments |
| `change_next_step.py <change> [--plain]` | `next <change> [--plain]` |
| `find_change.py [--active] [--records] <change>` | `find [--active] [--records] [--json] <change>` |
| `change_clone.py create`, `remove` | `clone`, `clone-remove`; `clone where` is new (D6) |
| `round_view.py start`, `done`, `check` | `round-view`, `round-done`, `check round-view` |
| `change_history.py sync` | `history` |
| `change_cost.py <change>` | `cost <change>` |
| `check_change_index.py`, `check_tasks.py`, `check_push_ready.py check`, `check_agent_skills.py` | `check index`, `check tasks`, `check push`, `check skills` |
| `check_push_ready.py push` | `push` |
| `post_compaction_context.py` | `hook post-compaction` |
| `python3 -m change_workflow.diagram` in `make change-graph` | `check graph` |

`check round-view` is what the repository's own targets that refuse while a round
view is open (`validate-local`, `run-ci`, `code-snapshot`, …) and the skills call;
`start`, `review`, and `push` run the same check themselves, as their make targets'
`round-view-closed` prerequisite did.

Settled at review 71's triage (71 F1): the engine reaches a repository's own check
only as a command. The merge before closeout brought `dev`'s refusal of private
content into the guarded push as an import of `scripts/check_public_content.py`,
which loaded only because the command puts `scripts/` on the path. The push now
runs the repository's pre-push check, where one exists, as Git runs a pre-push hook
— the remote as its argument, one line naming the branch and `HEAD` on its input —
and refuses with its reasons when it fails (CW-p7kq). The check's path is an
inventory entry (D5, 6; D13), `push.PRE_PUSH_CHECK`; this repository provides
`scripts/check_public_content.py --pre-push`, the check its Git hook already runs
(MCW-q8vd). Rejected there: keeping the import and recording it, which leaves the
engine unable to load outside this repository; leaving the scan to Git's pre-push
hook, which each checkout enables by hand, so a clone without it would push
unchecked.

Settled in implementation (sections 2 and 3): `start` reads which steps refuse an
archived change from the graph — every node of a step carrying the `NOT_ARCHIVED`
entry guard, archive cleanup's `ARCHIVED` refusing an active one — and runs the
round-view check for the steps whose make targets had `round-view-closed`
(implementation, triage, the merge, closeout, validation, archive cleanup), not
design, planning, or orchestration. Where it differs from the targets it replaced:
`--allow`, `--session`, and `--fresh` are refused without `--unattended`; sections
are named by how many they expand to (`section 2`, `sections 1-3`); interactive
sections are checked. `clone where <change>` shares `clone`'s parser, so a change
named `where` cannot be cloned by name. The four importers reach the command through
one repository helper, `scripts/workflow_command.py`, which runs it as a process and
raises its refusal; `validate_parallel.py`'s tests wait for a clone's bootstrap by
polling `clone where`'s report text, which is outside the promise, so a rewording
would end the wait early. The root `Makefile` gives a fragment variable a
repository value for one target by a target-specific assignment after the include
(`validate: ARGUMENTS += …` for `HELM_ALL_SCENARIOS`). The post-compaction hook runs
`cd "$CLAUDE_PROJECT_DIR" && scripts/change-workflow hook post-compaction` (38 F1), and
the orchestrating skill runs a clone's command as `cd <clone> && scripts/change-workflow
…`, since the command acts on its working directory's repository.

Rejected: classifying only, which would make the surface eight script paths
extraction breaks; fixing the defects and leaving the scripts in place, for the
same reason.

### D5. Fixes are limited to what blocks the surface

A defect that keeps the surface from being stated truthfully is fixed; any other
is recorded in `change-workflow`'s `README.md` "Current limits" or as a gap owned
by a later change. A defect an implementation session finds that blocks the
surface returns the change to design; one that does not is recorded, not fixed.

Fixed here:

1. The step and kind vocabulary is derived from `graph`, not hardcoded in
   `common.py`.
2. The engine resolves the repository it acts on from the working directory's Git
   top level, refusing outside a repository, instead of from its own file's
   location. In this repository and in a clone the result is the same directory.
3. The orchestrating session's model and effort are an `[orchestrator]` row of
   the step table, with no permission rules, instead of a value in the
   `Makefile`.
4. The package's module list is complete.

Recorded:

5. `scripts/` is outside the architecture checks; the engine's own layering is
   extraction's (`extract-change-workflow-repository`).
6. Repository paths hardcoded in modules (`.claude/change-steps.toml`,
   `.agents/change-outcome.schema.json`, `openspec/changes/`, `reviews/`, the
   `workspace` remote) are inventory entries (D13), replaced by
   `add-workflow-capability-contract`'s configuration file.
7. The step table's place and Claude Code rule syntax are provisional (D8),
   replaced by `sandbox-unattended-workflow-steps` and
   `add-workflow-harness-adapters`.
8. `convert` is ported as a provisional subcommand (D11).

Settled in implementation (section 1): `STEPS` and `KINDS` are declared in `graph`
itself, since `common` cannot import `graph`, which imports it; the triage-outcome
checks moved from `records` to `outcome` for the same cycle, and the computation's
step-to-phase map is derived from the table too. The repository is `git rev-parse
--show-toplevel` of the working directory, resolved once by `cli`; the step table, the
outcome schema, and the diagram source are paths relative to it, so the engine's tests
pass only when pytest runs inside a checkout, as every make target runs it.

Rejected: fixing every behaviour-preserving structural defect, whose extent no
reviewer could bound in advance.

### D6. Interfaces are tiered, and repositories call only the command

An interface is **public** (an adopter, a person, or a runner may rely on it),
**provisional** (public, with a named successor expected), or **internal** (only
the engine and its shipped skills use it).

| Interface | Tier |
|---|---|
| `start`, `next`, `record`, `note`, `review`, `find` (`--records`, `--json`), `clone`, `clone-remove`, `clone where`, `round-view`, `round-done`, `watch`, `cost`, `history`, `check index`/`tasks`/`push`/`skills`, `push`, their flags, exit-status categories, and structured outputs | public |
| Those subcommands' report text for a person | outside the promise |
| Skill names `change-<step>` and `change-orchestrate`, and their argument forms (`<change>`, `<change> sections 3-4`, `<change> from <branch>`) | public |
| `hook post-compaction` | provisional: the installer and the harness adapters take its wiring |
| `convert` | provisional: `remove-workflow-log-conversion` removes it |
| `check graph` | internal: it holds the engine's own graph diagram to the graph table (D12), which no adopter, person, or runner relies on |
| The unattended-run marker in a step's environment | internal |
| The make fragment's targets and `CHANGE_WORKFLOW_*` variables | a convenience outside the surface, with no compatibility promise |

`CLAUDE_CODE_SESSION_ID` is the harness's, an assumption in the inventory (D13).

What an output promises is what a program reads (18 F3): its structured form —
`find --json`, `next`'s JSON, `clone where`'s path — its exit status's category,
and its refusal of a malformed argument. Text written for a person — `history`'s
and `cost`'s reports, a check's messages, `next`'s plain form — is outside the
compatibility promise, and rewording it changes no public interface. Every
subcommand's exit status is one of three categories: 0, success; 1, a refusal or a
failed check, its reason on standard error; 2, a usage error, such as a malformed or
missing argument.

A repository calls the engine only as the command. The four importers move to it:
`check_change.py`, `check_doc_citations.py`, and `validate_slice.py` through
`find --json <change>`, which prints `name`, `directory`, `archived`, `records`
(the records directory, or `null` when this checkout holds none), and `format`
(D8), and refuses an unknown change, naming it; `validate_parallel.py` through
`clone where <change>`, which, refusing an unknown change before it looks for a
clone (25 F2), tells four cases apart:

| Case | Exit | Output |
|---|---|---|
| The change does not exist | 1 | the change's name, on standard error |
| The change's clone exists and is usable | 0 | the clone's path |
| No clone directory exists: the change is worked in place | 0 | nothing |
| A clone directory exists but is unusable — not a clone of the workspace, its branch not checked out, its bootstrap not succeeded | 1 | the reason, on standard error |

so that neither a broken clone nor a misspelled name is taken for a change worked
in place.

Settled in implementation (section 2): the statuses that moved into the categories
are `check tasks` exiting 1, not 2, for an unknown change; `push` exiting 1 for any
failed `git push` rather than Git's status; and a backwards section range and
`convert`'s qualifiers without `--next` exiting 2. A harness that cannot be started is
a refusal naming it. Pre-closeout review 62 (62 F1) held the exit-1 rule on every
path: each check's failures, `history`'s refusals, a stopped run's reason, an
interactive session's status, and a failed push name their reason on standard error,
OK lines staying on standard output.

Rejected: everything reachable public, which would freeze plumbing and the
fragment; only what a repository's files name, which would leave `record`,
`round-view`, and the runner's commands internal; every output public, report text
included (18 F3), which would freeze wording no caller parses.

### D7. The graph's vocabulary is public and closed

The node names, the review kinds, and the target shape are public; renaming or
removing one is incompatible, adding one compatible. The graph's structure —
exits, joins, guards — is normative in `change-workflow` and changes only by an
OpenSpec change of the workflow, never by an adopting repository. A reader meeting
a node or kind it does not know reports it by name rather than routing, and the
target shape admits new values of `step` and `kind`, so a later extension is
additive.

Settled in implementation (section 4): the next-step computation names the owner at
the first line of the current format naming a step, node, or kind the graph does not
declare, before it reads any branch decision, and routes on no line at all, earlier
ones included; the log's writer refuses such a line, a review with no kind among
them.

Rejected: extension by declaration in a repository's configuration, which would
turn the code table into data with no caller; treating the graph as internal,
which its presence in every outcome and log rules out.

### D8. One format version for a change's record set

The log's `format` versions everything the engine writes and reads for one change:
the log lines and the outcomes and decisions they embed, the records' layout and
names, the fields parsed from records, and, where a log exists, the ledger line.
It moves when any of them changes incompatibly, with a migration command. `next`
and `find --json` output carry the same `format`, and the outcome schema states
its format in its `$id`. An engine refuses a format it does not read, naming it.

A reader tells older, current, and newer formats apart before it routes or writes
(18 F2): a log line with no `format`, or a lower one, is older, and the owner
converts it with `convert`; a higher one is newer, and both the reader and `convert`
refuse it, naming the format, rather than converting it backward. A log is the
format's only authority, so the engine marks a change's format before anything
else records: `start` opens the log, before any step it starts runs, interactive or
unattended, with a line carrying the format, which the next-step computation reads
for no route. With no log, or an empty one, numbered records under `reviews/` are
older, as today; a ledger alone, or nothing, is read as the reader's format.

A ledger with no log carries no format (25 F1). A step started outside the
command, by a slash command, can append ledger lines before its closing `record`
opens the log, or leave them with no log if the session ends unrecorded, and
nothing the engine runs can make such a session mark the format first. The
workflow therefore handles the absence rather than promising it away: the format
versions the ledger only where a log exists, a ledger with no log is read in the
reader's format, and `change-workflow`'s `README.md` names the case in "Current
limits" — an older release reading a newer slash-command-only change's ledger
cannot tell it is newer. The session's closing `record` ends the case, since the
log it opens then governs the ledger.

What follows from these rules, settled in implementation (section 4): `start` refuses
records of an older format — a log holding an older line, or numbered records with no
line logged — naming `convert`, since its opening line would otherwise mark them
current, and refuses a newer log; the log's appender refuses a newer log, so no line
of this format follows one; the next-step computation refuses a newer log as it
refuses an unknown change, exit 1 with the reason on standard error; and `start
orchestrate` opens no log, since the orchestrating session is no step. A mark that is
no whole number is read as newer, never converted backwards.

Also settled in section 4: `FORMAT` lives in `common`, since `find` cannot import
`log`; the outcome schema's `$id` is `urn:change-workflow:change-outcome:format:2`,
`outcome.load_schema` refuses a schema stating another format or none, and the copy
given to Claude Code leaves the `$id` out, since it constrains nothing a step writes.
`start` writes its opening line before the wrapper's own refusals, so an unattended
start the wrapper refuses leaves the line: it marks the format, not a run, and moving
it into the wrapper would add a line to every wrapper run's log for a run that never
started either way.

The step table is
provisional and unversioned; the change index and the task list are public inputs
versioned by the engine's release. Extraction adds the engine's own version
beside `format` on each line.

| Format | Tier |
|---|---|
| Log line, outcome schema, records layout and names, parsed record fields, ledger line (versioned where a log exists), `next` and `find --json` output | public |
| Change index row and status legend, `tasks.md` section layout | public input |
| Step table schema | provisional |
| Transcripts' and progress files' contents, runs-in-progress records, round-view state, clone bootstrap status | internal |

Rejected: a marker per format, whose combinations a reader would have to handle
for records read together; no markers beyond the log's, which would need a table
from engine versions to formats; for a change with no log (18 F2), inference alone,
which cannot tell a newer engine's unlogged records from older ones, and a manifest
file in `reviews/`, a second marker beside the log's; for a ledger with no log
(25 F1), the engine as the ledger's only writer, opening the log before the first
line, which nothing could enforce on a session that edits the file itself, and a
`format` on every ledger line, which agents would write by hand and every existing
ledger lacks.

### D9. Semantic versioning

An incompatible change to a public interface bumps the major version, a
compatible one the minor, a change limited to internals the patch; before 1.0.0,
an incompatible change bumps the minor, as semantic versioning allows for
`0.y.z`. Incompatible: removing or renaming a public subcommand, flag, output
field, skill, argument form, node, or kind, or changing one's meaning; a record-set
change an older engine would misread; removing an obligation adopters rely on, or
adding a role an adopter must provide. A provisional interface may change when its
named successor lands. A change to the make fragment or to this repository's own
targets never moves the engine's version. Nothing is versioned before extraction;
until then each workflow change's proposal names the public interfaces it changes
and whether each change is compatible, and review checks it.

Rejected: deferring the rules to extraction, against the acceptance boundary.

### D10. The specification is rewritten against its outline

The requirements of `change-workflow` are written anew from the outline its
`index.md` will hold, each stating one behaviour in under 500 characters with its
cases as scenarios. Every old requirement is REMOVED, its `**Migration**` naming
the ids that hold its rules; every new requirement is ADDED. A `trace.md` in this
change's directory maps every MUST clause and every scenario of the old
specification to the id that holds it, or to "dropped" with the reason; review
holds its completeness. The draft outline, for shape:

```text
1. The process          phases and the owner's touchpoints; the graph as process;
                        the owner's directions; discussion steps; a prerequisite
                        halting a design; index transitions
2. Implementation       sections and sessions; rounds and their reading; validation's
   and validation       general rules; the triage of a round
3. Reviews and triage   review records; lens, basis, severity; triage; the ledger
4. The engine           the command; step runs and outcomes; interactive record; the
                        log and its format; the next-step computation; permissions
                        and the guarded push; models; cost; clones and history;
                        skills from one source
5. The public surface   the tiers; the formats and their version; compatibility;
                        what an adopting repository provides
```

Where each existing requirement goes is decided here (18 F1), at the level of the
requirement and, for a requirement the seam splits, of its clause groups. A general
row's rules stay in `change-workflow`; a split row names what moves to
`market-change-workflow` and the seam the general requirement keeps, where the
repository's part plugs in. `trace.md` refines this table to every MUST clause and
scenario, and MUST agree with it: a clause the trace cannot place as the table
does returns the change to design.

| Existing requirement | Destination | Moves to `market-change-workflow` | Seam kept in `change-workflow` |
|---|---|---|---|
| Phases and owner touchpoints | split | the merge's default branch, `dev` | the merge brings in the branch the change lands on: the one it was branched from unless the owner names another, or the repository's default |
| Index transitions are written by the step that makes them | general | — | the index's path is a role (D13) |
| Review records | general | — | — |
| Finding lens, basis, and severity | general | — | — |
| Triage of every finding | general | — | — |
| Intervention ledger | general | — | — |
| Implementation sections and sessions | general | — | the evidence a section may owe validation is named by validation's parts; CI is this repository's example |
| Validation observes a committed slice | split | building the tested packages from the commit, never from the shared wheelhouse; end-to-end evidence from a pipeline run whose head is the commit; dispatching the owed CI workflows from a fixed list holding none that publishes, a tracked change by the owner to extend; judging named jobs, and comparing every other failing job with `dev`'s latest completed ancestor run; building the service images, the Helm render checks with the chart-to-loader check, a skipped one failing; the Helm end-to-end run of a listed set of scenarios from no persistent state, every unlisted scenario reported as not run against Helm; the scenarios on leftover volumes, an earlier pipeline run, a scenario the charts do not serve, and the four comparisons with `dev` | validation describes one commit and modifies nothing — a clean worktree and an unmoved `HEAD` after every part, else no further evidence; no regenerated tracked file; a condition it could repair fails it; it fixes nothing; results `passed`, `failed`, `inconclusive`; an environmental failure put to the owner with its remedy and rerun on their word, every attempt's evidence kept; the record names the end-to-end scenarios exercising the change with each one's basis; the stale-lock scenario; and the seam: validation's parts are the repository's, and each part's evidence comes from the commit under validation |
| Guarded push of a change branch | split | the protected branches, `main` and `dev`; and the pre-push check this repository provides, which refuses recognizable private content in the branch's name and in every outgoing commit (MCW-q8vd; 71 F2) | the push refuses the repository's protected branches, and runs the repository's pre-push check, where it provides one, before it pushes or reports success, refusing when it fails (CW-p7kq; 71 F1) |
| Triage of an implementation round | general | — | — |
| Harness-neutral agent skills | general | — | the skills' and harnesses' paths are inventory entries (D13) |
| An orchestrating session advances one change | general | — | merges of `dev` become merges of the branch the change lands on; the default is row 1's |
| Unattended step runs end with a structured outcome | general | — | — |
| The next step is computed from the files | general | — | — |
| Discussion steps stay conversations with the owner | general | — | — |
| Unattended runs are held to their step's permissions | general | — | the rule syntax is provisional (D5, 7) |
| A design blocked on a prerequisite halts | general | — | — |
| Unattended steps run on their step's ordered models | split | the forbidden models, Fable and Astra | a repository may forbid models, and the table names none it forbids; the owner's override for one review stands |
| Unattended runs record their cost | general | — | — |
| Each change is worked in its own clone | general | the clone's bootstrap command (`make init`), which the requirement does not name today | the bootstrap is the repository's; the wheelhouse scenario says "environments" |
| Each Helm validation is isolated in its change's namespace | market, whole | the namespace, per-change image tags, volume and Secret setup, in-namespace scenarios, kept logs and scale-down, the memory preflight and its classification, and archive cleanup's removal of the namespace and images and its capacity record | archive cleanup runs the repository's removal of a change's validation resources |
| The workflow graph is declared in code | general | — | — |
| Interactive step runs record their outcome | general | — | — |
| The owner directs a change's next step | general | — | — |

The specification's Purpose drops the Helm namespace, and its Evidence entries for
validation's parts, the CI comparison, the namespace, the capacity record, and the
parallel Helm check move to `market-change-workflow`'s Evidence.

The deltas this design writes hold the behaviours the decisions add (the command,
the tiers, the format and the log's opening line, compatibility, the closed
vocabulary, the roles, the
orchestrator's row, this repository's provision of the roles, and the indexed
organization); the rewrite of the existing requirements, their REMOVED entries,
and the move of this repository's requirements into `market-change-workflow` join
them in round 2 (D14).

Rejected: reorganizing by RENAMED and MODIFIED, which every split for the seam and
the length rule would turn into a disguised rewrite; a per-requirement trace only,
too coarse to check; the trace in this document, which it would swamp; deciding
the destinations only with the trace in round 2 (18 F1), which would leave the
change's largest authority boundary unreviewed until written; mapping every MUST
clause here, which is the trace's first half written twice.

Settled in implementation (sections 8 and 9): 136 requirements joined the nine the
design wrote, in the outline's order; two of the design's were over 500 characters,
so CW-5qne's exit statuses became CW-m7fk and CW-x7jd was tightened. The trace covers
MAY, SHALL, and SHOULD clauses as well as MUST and drops nothing; the two scenarios
the table names in neither column, "A plan owes a workflow that publishes" and "A
dispatched run is cancelled", go with the CI dispatch to `market-change-workflow`,
and the form of owed CI evidence is MCW-gvqb. MCW-7hr1's scenario names the real job,
`test · test-deployment-packaging`. Declined: splitting CW-r9d2, CW-a6ow, and
CW-3tvs, and MCW-7ts3 and MCW-8h0r, each two clauses of one subject. The 500-character
limit is 1.14.1's, which the pinned validator does not apply, so each body was counted
by hand. Review 49's triage (49 F2) moved the code's `Contract:` citations to the ids
that hold their rules, since `make check-doc-citations` checks paths, not headings,
and would not report a citation of a removed requirement's name.

### D11. No hard dependency on the changes editing `change-workflow`

Neither this change nor `remove-workflow-log-conversion`,
`workflow-round-review-without-merges`, or `shorten-long-requirements` waits on
the other. The conversion is its own requirement or requirements and its own
module behind the provisional `convert`, so its removal is REMOVED of known ids
and one module deleted; the round view's mechanics are their own requirements.
Each of the three index rows' `Notes` says this change rewrites `change-workflow`;
`shorten-long-requirements` leaves `change-workflow` out, since this change brings
it and `market-change-workflow` under the length rule. Whichever change lands
second designs against the other's result.

Settled in implementation (section 8): the conversion's ids are CW-qj77, CW-h12x,
CW-42me, CW-o1ca, CW-zniv, CW-ajcm, CW-95xp, and CW-v8mq, the converter's refusal of a
newer log moved out of CW-x7jd into CW-h12x so removing `convert` touches no format
requirement; the round view's are CW-aoby, CW-4svs, CW-9mrq, CW-78ul, CW-n44s,
CW-uq5q, CW-gd24, CW-rgws, and CW-te38.

Rejected: dependencies gating those changes' design, which would hold unrelated
work behind this change; waiting for `remove-workflow-log-conversion`, whose
implementation waits on an event nobody schedules.

### D12. Four diagrams; only a generated diagram is held to code

`change-workflow`'s `README.md` embeds four diagrams from
`openspec/specs/change-workflow/diagrams/`, each a `.drawio` source with its
`.svg` export: the workflow graph, moved there; the engine's parts, with what each
reads and writes; a step run's life, unattended and interactive, from its start
through waiting and resuming to its recorded outcome, with the orchestrating
session's relay as a lane; and where a change's state lives — the checkout, the
clone, the owner's workspace, and the session transcripts. The graph diagram keeps
its comparison with the graph table, at its new path; the others are maintained by
review. `market-change-workflow` has none.

Rejected: a check that the parts diagram's boxes are the package's modules, since
the diagram is not generated from them; separate diagrams of the relay loop and the
round's join, which the step run's life and the graph already draw.

### D13. The assumptions inventory is two-sided, its named targets and paths held by a test

`change-workflow` states, by role, what an adopting repository provides — a
command validating a commit locally, a packaging check before closeout, the change
index at a known path, the guidance documents every step reads, protected
branches, an `origin` remote — as a requirement of its surface, described in its
`README.md` with the skill that uses each role and the change expected to replace
it. `market-change-workflow`'s `README.md` states how this repository provides
each role (`make validate-local`, `make check-packaging`,
`openspec/changes/README.md`, `dev` and `main`, …). A test among the engine's tests
collects every `make <target>` and repository path the skills, the step table, and
the make fragment name, and fails on any the second table does not list, and on a
role either table lacks. That is all the test proves (18 F4). The engine's own
assumptions — the paths its modules hold (`openspec/changes/`, `reviews/`,
`.claude/change-steps.toml`, `.agents/change-outcome.schema.json`,
`.claude/settings.local.json`), the clone's bootstrap command, the default merge
branch, the `workspace` remote, the environment variables it reads
(`CLAUDE_CODE_SESSION_ID`), and the tools it invokes (`git`, `claude`, `codex`,
`gh`) — are entries of the same tables, marked as maintained by review, and the
documents say so rather than calling the inventory test-complete.
`add-workflow-capability-contract` turns each role into a capability and each
provision into its declaration.

Rejected: the inventory in this document only, which nothing would keep current;
one table in `change-workflow`, which would ship this repository's values; a data
file now, which is the configuration file that change owns; extending the test to
the engine's modules by category with AST scans (18 F4), heuristics the owner
would rather the engine's tests not carry; gathering the engine's assumptions into
one module of constants, a structural fix D5 leaves to that change.

Settled in implementation (section 7): seventeen roles, each replaced by
`add-workflow-capability-contract` but the make fragment's, which
`extract-change-workflow-repository` replaces. The test reads only a skill's code —
inline spans and fenced blocks — so prose names nothing; every rule of the step
table; and the fragment's whole text with its own targets. A target keeps the
directory `-C` names and a wildcard as the table grants it; a path is a word under a
directory Git tracks at the root, or a root file but `README.md`. A path Git does not
track (`.snapshot/…`) or outside the repository is not collected, and a provision no
source names any longer is not reported, since D13 asks only that every named one is
listed. The engine's report text names fragment targets (`make round-done`, `make
change-clone`); they are listed in the fragment's provision, not as a role.

### D14. Implementation cadence

Two rounds, each of two sessions:

- **Round 1, the engine consolidated** (D4, D5, D6). Session one: the package, the
  command, its exit categories, `find --json`'s fields and `clone where`'s four
  cases (D6; `format` joins `find --json` in round 2), the make fragment, and the
  four fixes, with the engine's tests. Session
  two: every caller moved to the command — the skills, the step table's rules, the
  root `Makefile`, the four importers, the guide, the completion, and the hook
  wiring. The round changes no behaviour; its validation exercises the rewritten
  step table.
- **Round 2, the conventions and the specifications.** Session one: the index and
  id check (D15), `format` on the outputs and the schema's `$id`, the reader's and
  `convert`'s older, current, and newer formats, and `start`'s opening line (D8),
  the graph
  diagram's move (D12), and the assumptions test (D13) with
  `market-change-workflow`'s `README.md` table it reads, written here because
  closeout cannot add the test. Session two: the `change-workflow` delta rewritten
  with its trace (D10), the `market-change-workflow` delta, and the convention's
  text in `openspec/README.md`.

Closeout then writes the two capabilities' `README.md` and `index.md`, the
diagrams, and the other promotions.

### D15. A capability's documentation is organized by an index of requirement ids

A capability may adopt this organization, and one that does keeps:

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

An id is the capability's prefix and four characters from `[a-z0-9]` chosen at
random (`CW-a8tf`), so changes on different branches never collide; it is never
reused, and a removed requirement's id moves to `index.md`'s retired ids with
where its rule went. An id may be cited, so a citation survives a requirement's
renaming. A check run by `make check-change` fails, in a capability with an
`index.md`, on a requirement with no id, two sharing one, an id `index.md` omits
or lists twice, a listed id in neither `spec.md` nor the change's own deltas, a
retired id in use, a link that does not resolve, or an entry whose link is not to
its own id's requirement heading (added at review 49's triage, 49 F3, since a link
that resolves may still reach another requirement). The deltas clause lets
closeout's promotion write `index.md` before the archive puts the requirement in
`spec.md`.

Settled in implementation (sections 5 and 10): the index declares its prefix on a
`Prefix:` line, upper-case, without which nothing else in the capability is checked;
an entry's first cell is the id's link; the retired ids are the items under `##
Retired ids`, each beginning with the id. With a change named, its deltas count as
the archive will leave them — ADDED and MODIFIED names and a rename's new name
resolve in `spec.md`, a REMOVED requirement and a rename's old name do not — so this
change's own closeout can index requirements whose old names carry no id. Ids are
unlikely, not certain, to collide across branches; the check catches a collision.
Closeout's part 9 also moves a renamed requirement's link and revises a modified
one's summary, without which a rename would fail the check on its old anchor.

`README.md` takes the companion's role in an indexed capability, so until every
capability is converted the companion is `README.md` where `index.md` exists and
`architecture.md` elsewhere; `AGENTS.md`, `openspec/README.md`,
`openspec/config.yaml`, planning-governance's companion requirement, and the
closeout, design, and review skills say so. `change-workflow` and
`market-change-workflow` adopt the organization here;
`change-workflow/architecture.md` becomes its `README.md`. Converting the other
capabilities, and moving their material out of `ARCHITECTURE.md`, is
`index-capability-documentation`'s.

Rejected: the part's name at the front of each requirement's name, flatter than
the structure needs; a parts list inside `spec.md`, which no delta can edit;
ordering only, which every archive breaks; the id on the body's first line, which
a MODIFIED delta could drop; semantic or sequential ids, which encode the
organization or collide across branches.

## Related changes

- **`index-capability-documentation`**, not yet proposed: converts every other
  capability to D15's organization and moves component material out of
  `ARCHITECTURE.md` into components' `README.md`. It merges alongside this
  change's branch.
- **`remove-workflow-log-conversion`**, **`workflow-round-review-without-merges`**,
  **`shorten-long-requirements`**: D11.

## Open Questions

- **Extending the graph from an adopting repository.** Revisit when an adopter,
  this repository included, needs a node or review kind an extension point cannot
  express; D7's reader and target rules keep that extension additive.
- **Generating the graph diagram.** The graph table is a structured source, but
  the diagram is laid out by hand and compared, not generated. Revisit when a
  deterministic layout from the table reads as well as the hand-laid one; until
  then the comparison stays.
- **Shipping the make fragment.** At extraction the CLI prints the installed
  fragment's path for the root `Makefile`'s `include`; the subcommand is
  `extract-change-workflow-repository`'s.

## Design promotion record

`spec.md` rows name the requirements the archive merges from this change's deltas;
every other location was written by hand at closeout.

| Accepted decision | Permanent location |
|---|---|
| Principle: documentation follows the specification, and a component's `README.md` is its most human-readable document | `openspec/README.md#a-capability-organized-by-an-index` |
| Principle: a diagram is held to code only when generated deterministically from a well-structured source | `AGENTS.md#diagrams` |
| Principle: this repository is the workflow's first adopter | `openspec/specs/market-change-workflow/README.md#this-repository-is-the-workflows-first-adopter` |
| Principle: the engine's promise is its command | `openspec/specs/change-workflow/spec.md` CW-r3ka, CW-h8vm; `openspec/specs/change-workflow/README.md#the-command-and-its-tiers` |
| D1 One change | Change history; no permanent destination |
| D2 One `change-workflow` capability, organized by its index | `openspec/specs/change-workflow/index.md`; `openspec/specs/change-workflow/README.md`, its parts following the index's; `openspec/specs/change-workflow/spec.md#purpose` |
| D3 This repository's requirements in `market-change-workflow` | `openspec/specs/market-change-workflow/spec.md` (MCW ids, through the archive), its Purpose and Evidence; `openspec/specs/market-change-workflow/index.md`; `openspec/specs/market-change-workflow/README.md#validations-parts` and `#branches-models-and-the-clones-bootstrap`; `openspec/specs/README.md` |
| D4 The engine consolidated behind one command, the make fragment, the pre-push check run as a command | `openspec/specs/change-workflow/spec.md` CW-r3ka, CW-h8vm, CW-p7kq, and Evidence; MCW-q8vd; `openspec/specs/change-workflow/README.md#its-parts` and `#the-command-and-its-tiers`; `docs/agents/change-workflow.md#the-engines-command`; the lesser goal's current state in `openspec/changes/README.md` |
| D5 Fixes limited to what blocks the surface | Fixes: CW-9fbu (vocabulary from the graph), CW-r3ka (repository from the working directory), CW-w2ld (the `[orchestrator]` row); recorded defects: `openspec/specs/change-workflow/README.md#current-limits` (`scripts/` outside the architecture checks, hardcoded repository paths, the step table's provisional syntax) and `convert` as provisional in `#interfaces-are-tiered` |
| D6 Interfaces tiered; repositories call only the command | CW-5qne, CW-m7fk; `openspec/specs/change-workflow/README.md#interfaces-are-tiered`; `docs/agents/change-workflow.md#the-engines-command` |
| D7 The graph's vocabulary is public and closed | CW-9fbu; `openspec/specs/change-workflow/README.md#the-graphs-vocabulary-is-closed` and `#current-limits` |
| D8 One format version for a change's record set | CW-x7jd, CW-k6qa, CW-lyr4, CW-qj77, CW-h12x; `openspec/specs/change-workflow/README.md#a-changes-records-carry-one-format-version`; a ledger with no log in `#current-limits` |
| D9 Semantic versioning | CW-c2tw; `openspec/specs/change-workflow/README.md#compatibility-is-judged-by-semantic-versioning`; `openspec/README.md#change-documentation-requirements` |
| D10 The specification rewritten against its outline | `openspec/specs/change-workflow/spec.md` (every CW requirement, through the archive; Purpose and Evidence by hand); `openspec/specs/change-workflow/index.md`; `trace.md` stays in this change as its history |
| D11 No hard dependency on the changes editing `change-workflow` | Change history, and those changes' rows' `Notes` in `openspec/changes/README.md` |
| D12 Four diagrams; only a generated diagram is held to code | `openspec/specs/change-workflow/diagrams/` (the graph, the engine's parts, a step run's life, where a change's state lives), embedded in `openspec/specs/change-workflow/README.md#its-parts`, `#a-step-runs-life`, `#where-a-changes-state-lives`, and `#routing-is-code-with-the-model-as-backstop`; CW-66kx; `AGENTS.md#diagrams` |
| D13 The assumptions inventory, two-sided | CW-m4ps, MCW-5tgp; `openspec/specs/change-workflow/README.md#what-an-adopting-repository-provides`; `openspec/specs/market-change-workflow/README.md#how-this-repository-provides-the-workflows-roles`; held by `scripts/tests/test_change_workflow_assumptions.py` |
| D14 Implementation cadence | Change history; no permanent destination |
| D15 A capability's documentation organized by an index of requirement ids | `openspec/specs/planning-governance/spec.md` "Indexed capability documentation" (added) and "Permanent capability architecture companions" (modified), through the archive; `openspec/README.md#a-capability-organized-by-an-index`; `AGENTS.md#documentation-ownership`; `openspec/specs/README.md`; `openspec/config.yaml` |
| Roadmap currency | No goal of `docs/development/ROADMAP.md` covers the workflow: no edit |
| Campaign index currency | `openspec/changes/README.md`: this change's row; the lesser goal "Make the change workflow a tool any repository can adopt"'s current state; its gap "The engine is documented as this repository's contract" removed, closed by this change |
