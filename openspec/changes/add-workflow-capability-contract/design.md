# Design: add the workflow capability contract

Status: design settled. The decisions below are the owner's, reached in the design
discussion. The ledger (`interventions.jsonl`) records where the owner decided
otherwise than the agent recommended.

## Context

- **The inventory exists.** `specify-change-workflow-and-engine` (archived
  2026-11-05) listed every assumption the workflow makes about a repository in two
  tables: `change-workflow`'s `README.md`, "What an adopting repository provides",
  eighteen roles, seventeen of them "expected to be replaced by" this change; and
  `market-change-workflow`'s `README.md`, how this repository fills each, held
  complete for the make targets and paths the skills, step table, and make fragment
  name by `scripts/tests/test_change_workflow_assumptions.py`.
- **Three kinds of assumption.** The inventory holds commands the skills run (the
  make targets), documents and paths the skills read (the guidance documents, the
  OpenSpec tree, the change index), and this repository's values held as constants
  in the engine: `push.PROTECTED = ("main", "dev")`, `push.DEFAULT_REMOTE`,
  `push.PRE_PUSH_CHECKS` (two of this repository's scripts, run with the engine's
  interpreter), `review.DEFAULT_BASE`, `clone.DEFAULT_FROM`,
  `clone.BOOTSTRAP_COMMAND`, `steps._FORBIDDEN_MODEL`, `hook.REQUIRED`,
  `records.DOCUMENTATION`, `history.VALIDATION`, and `history.E2E_LOGS`.
  `change-workflow`'s "Current limits" names this change's configuration file as
  their replacement.
- **The workflow's own operations are already commands.** The guarded push, round
  views, clones, history, cost, and the index, task, push, and skill checks are
  subcommands of `scripts/change-workflow` (CW-r3ka); their make targets are the
  fragment `workflow.mk`, a convenience outside the surface (CW-h8vm) whose role
  `extract-change-workflow-repository` owns.
- **The closing checks are one composite.** `make check-change`
  (`scripts/check_change.py`) runs the engine's checks (agent skills, task list,
  change index), the pinned strict OpenSpec validation, the checks of the workflow's
  documents held as this repository's scripts (decision destinations, the spec
  index), and this repository's and engineering guidance's checks.
- **The step table grants broadly.** Implementation, triage, and the merge may run
  `make validate-*` and `make check-*`; nothing protects `.agents/`, since `[common]`
  denies edits only under `.claude/**`. The unattended-run marker,
  `CHANGE_WORKFLOW_UNATTENDED`, is `1` and names no step.
- **Make exits 2 whenever a recipe fails,** so no exit-status convention richer than
  zero and non-zero survives the commonest implementation.
- **Where the commands run in the skills.** `make check-change` before every commit
  of every committing step; `make check-packaging` and `make test` before a commit
  that changes code (implementation, triage's fixes, the merge); `make lock` before a
  code commit when a dependency changed, and in the merge after one side of a
  conflicted lock is taken; `make check-packaging` and `make
  check-architecture-change` once in closeout, before the archive; validation's
  parts, preflight, and dispatches in validation; the teardown and capacity record in
  archive cleanup. `make code-snapshot` is named once, in triage, and is legacy.

## Principles

The owner stated these in the discussion. Each governs the decisions below and is
promoted as the proposal's "Knowledge to promote" names.

- **P1 — Inversion of control.** Each field of the configuration configures one
  operation of a skill or the engine, and exists only where something uses it.
- **P2 — Nothing committed that runtime can supply.** A value Git or the
  invocation can supply is never committed configuration.
- **P3 — The workflow provides the hooks.** It offers a hook at every point a
  repository would reasonably intervene; adopters change what a hook runs and add no
  hook keys.
- **P4 — Removal is deliberate.** A repository may remove a safeguard of the
  workflow only by a deliberate, visible act, never by omission.

## The configuration, as this repository declares it

```toml
# .agents/workflow.toml — what the change workflow assumes about this repository.
# Every field configures one operation of a skill or the engine. Values Git or the
# invocation supplies are not here: the branch a change lands on, the remote, the
# kube context.

[repository]
# Engine, guarded push: refuses to push these, whichever step asks.
protected-branches = ["main", "dev"]
# Engine, next-step computation: after a pre-closeout review, a commit changing only
# these paths or a change's records needs no new validation. Pre-commit: a commit
# changing only these runs only `pre-commit`.
inert-paths = ["openspec/", "docs/"]

[hooks]
# change-implement, change-triage, change-merge: after the step's last functional
# change (any edit outside `inert-paths`, a merge's resolutions included), before
# the pre-commit hooks.
after-functional-change = ["make lock"]
# Every step that commits, before each commit, after the workflow's default checks.
# `make check-change`, the owner's complete closing check, runs `run pre-commit`.
pre-commit = "make check-repository CHANGE={change} CHANGE_BASE={base}"
# Also before a commit that changes a path outside `inert-paths`.
pre-commit-functional = ["make check-packaging", "make test"]
# change-closeout, once, before the archive.
pre-archive = ["make check-packaging", "make check-architecture-change CHANGE={change}"]
# Engine, guarded push: before anything is sent, under Git's hook contract.
pre-push = "make pre-push REMOTE={remote}"
# Engine, `clone`: as a clone is made, in the background; implementation and
# validation wait for it.
post-clone = "make init"

[defaults]
# The workflow's default checks this repository has turned off, each with its reason.
disable = []

[openspec]
# The default pre-commit's validation and closeout's archive run the CLI through this.
command = "bunx @fission-ai/openspec@1.14.0"

[load]
# Every step's skill reads these as it starts; the post-compaction hook re-reads them.
common = ["AGENTS.md", "docs/development/ARCHITECTURE.md", "docs/development/TESTING.md",
          "docs/development/DEPLOYMENT_AND_CONFIG.md", "openspec/README.md"]
# A step's own additions.
design = ["docs/development/ROADMAP.md"]

[models]
# `start orchestrate`: the orchestrating session's model and effort.
orchestrator = { model = "claude-opus-5-5", effort = "medium" }
# Wrapper: each step's models in order of preference.
review   = [{ harness = "codex",  model = "gpt-6-sol",       effort = "high" },
            { harness = "claude", model = "claude-opus-5-5", effort = "high" }]
design   = [{ harness = "claude", model = "claude-opus-5-5",   effort = "high" }]
validate = [{ harness = "claude", model = "claude-sonnet-5-5", effort = "medium" }]
# … one row per step

[validation]
# change-validate, before any part: a failure ends validation as environmental.
preflight = ["make check-uv-version"]

[validation.parts.pipeline]
# Started first, right after the guarded push: it is the slowest part.
start    = "make run-e2e"
collect  = "make fetch-e2e-logs E2E_AFTER_RUN={after}"
evidence = ".snapshot/e2e-logs/"

[validation.parts.ci]
# Started once for each `Owed by validation:` line of a complete section, each run
# named by its workflow (`run ci start <change> --owed <workflow>`).
owed     = true
start    = "make run-ci WORKFLOW={owed}"
collect  = "make validate-ci WORKFLOW={owed} CI_AFTER_RUN={after}"
evidence = ".snapshot/validation/"

[validation.parts.local]
run      = "make validate-local"
evidence = ".snapshot/validation/"

[validation.parts.helm]
# After local, never beside it: they share Docker and the CPU.
after    = "local"
run      = "make validate-helm CHANGE={change}"
evidence = ".snapshot/validation/"
# change-archive-cleanup: record what the release used, then remove the change's
# namespace and images.
cleanup  = ["make record-capacity CHANGE={change}", "make -C helm teardown CHANGE={change}"]
```

## Decisions

### D1 — One configuration file declares what the workflow assumes

`.agents/workflow.toml` is the one place the workflow reads what it assumes about a
repository: the commands it runs, the documents its skills load, and the values the
engine held as constants. A value is a field when another adopting repository could
reasonably need a different one (P1) and neither Git nor the invocation supplies it
(P2). The workflow's own conventions stay fixed in the engine: a change's
`reviews/` layout, versioned by the record set's format; the outcome schema's path,
which ships with the workflow; the step table's path, provisional and replaced by
`sandbox-unattended-workflow-steps` and `add-workflow-harness-adapters`; the
`workspace` remote, which the engine names when it clones; the harness's
`CLAUDE_CODE_SESSION_ID` and `.claude/settings.local.json`; the graph diagram's path;
OpenSpec's root and the change index, which OpenSpec and the workflow fix; and the
model rules no two models of one vendor on a row and Codex only on the review
(CW-zq4h).

Rejected: commands only, which leaves the gap's own wording unmet and the engine
holding this repository's values, contrary to the first-adopter principle in
`market-change-workflow`'s `README.md`; commands and documents without the engine's
values, for the same reason; splitting the engine's values into a change of their
own, since both halves share one loader, one check, and one file, and a split would
mostly duplicate review and validation.

### D2 — Hooks are named by when they run

A repository's commands are hooks on the workflow's lifecycle, in one `[hooks]`
table, each named by the moment it runs, as Git names its hooks:
`after-functional-change`, `pre-commit`, `pre-commit-functional`, `pre-archive`,
`pre-push`, and `post-clone`. Validation's preflight and parts, and a part's cleanup,
are hooks of validation's own profile (D3). The set covers every moment a repository
would reasonably intervene (P3): a change set up, after a functional change, before a
commit and before a functional commit, before a push, before validation and its
parts, before the archive, and after the change lands. A repository changes what a
hook runs and adds no hook key; a hook the workflow adds later is a compatible
change.

A hook holds one command or a list. A list runs every command in order, whatever an
earlier one reported; each is recorded (D10) and the hook fails if any failed, so one
call reports every failure.

`after-functional-change` is what runs after a step changes functionality, before
it commits: this repository relocks. Validation never runs it, since validation
makes no functional change (CW-af15). The merge's case is the same moment: resolving
a conflict outside the inert paths is a functional change, and the skill takes one
side of a conflicted derived file before the hook rebuilds it.

Rejected: operations named by what they do (`test`, `lock`, `packaging-check`),
which do more or less than their names in another repository; one command per hook,
its composition moved into the repository's targets, since lists are clearer and
adopters only need not add keys; nesting hooks by phase, which spreads the lifecycle
across tables.

### D3 — Validation runs the parts the configuration declares

Which parts validation has, their order, and their shape are the repository's,
declared under `[validation.parts]`, not written into the skill. A part declares
`run`, one long command, or `start` and `collect`, a dispatch that returns at once
and a wait for what it started; `owed = true` when it runs once per `Owed by
validation:` line of a complete section, with `{owed}` the line's workflow; `after`,
the part it must follow; `evidence`, where its logs go, which the skill diagnoses
from and history copies; and `cleanup`, what archive cleanup runs for it.
`[validation] preflight` runs before any part, a failure ending validation as
environmental. The skill keeps the workflow's rules: push first, start the slow
parts first, waivers, diagnosis, and the result. What the agent is told about one
repository's failures is `add-skill-extension-points`' work.

The skill learns the parts from the engine, never from the file (14 F1):
`scripts/change-workflow config parts <change> [--json]` prints the preflight, then
each run of a part in declaration order, with its shape (`run`, or `start` and
`collect`), the part it comes `after`, and its evidence. An owed part is listed once
per `Owed by validation:` line of a complete section, the engine reading them from
`tasks.md`, each run named by its part and that line's workflow (`ci ci.yml`); an owed
part with no such line is listed `not owed`. With no part declared the step was
refused before it started (D12). Waivers are not in the plan: whether one has lapsed
is judged against earlier records' `Parts:` and `Commit:` lines, which stays the
skill's. "Start the slow parts first" follows from the shape: every `start` is a
dispatch that returns at once, so the skill dispatches those, then runs the `run`
parts in order, keeping each `after`. For this repository, with section 3 owing
`ci.yml`:

```text
preflight            make check-uv-version
pipeline             start, collect      evidence .snapshot/e2e-logs/
ci ci.yml            start, collect      owed by section 3   evidence .snapshot/validation/
local                run                 evidence .snapshot/validation/
helm                 run   after local   evidence .snapshot/validation/
```

Archive cleanup runs the cleanup of every part that declares one, with one call,
`scripts/change-workflow run cleanup <change>`, which runs them in declaration order
as one list (D2), so archive cleanup needs no plan. A cleanup tolerates finding
nothing to clean (CW-ikmm), so cleanup reads no field of the validation record.
Whatever tracked file a cleanup writes, archive cleanup commits on its own.

Rejected: individual capabilities the skill sequences, which keeps one repository's
validation in the skill; one engine operation running every part (14 F1), which
would run dispatches and long parts concurrently past a tool call's limits and move
waivers and retries across the engine's boundary; a top-level `[cleanup]` table, which separates a part's
cleanup from the part that leaves resources behind; choosing cleanups by the parts
the latest validation ran, which would make the record's `Parts:` line a new parsed
field of the public record format.

### D4 — The landing branch and the remote are derived

The branch a change lands on is the branch the workspace had checked out when the
orchestrating session created the change's clone, or the clone's `--from`. The engine
records it with the clone and exposes it as `find --json`'s `base`; the merge, the
review's base, and the closing checks' diff base read it. An argument overrides it
for one run. A change worked in place, or started without orchestration, has none
recorded: its steps take the argument and refuse without one. Running orchestration
again from another branch does not move it.

Clone removal reads it too (14 F4): a clone is removed only once its branch is
merged into its recorded landing branch on its upstream's remote, and that remote
holds every commit of the clone, where removal checked `origin/dev` and `origin`. A
clone made before the engine recorded a landing branch takes `--base <branch>` at
removal and refuses without it.

The remote is the branch's upstream unless an argument overrides it. `clone` gives a
new change branch its landing branch's upstream remote as its upstream
configuration, so the first push needs no fallback; a branch with neither upstream
nor argument refuses to push.

Rejected: a committed `lands-on` value and remote, which P2 rules out; falling back
to the remote's default branch, which here is `main` while changes land on `dev`;
falling back to `remote.pushDefault` or the only remote other than `workspace`,
fallbacks the owner did not want; an explicit base at every clone removal (14 F4),
which can disagree with the base the merge used.

### D5 — Models are an ordered preference per step, in the configuration

Each step's models, in order of preference with harness and effort, and the
orchestrating session's model and effort, move from `.claude/change-steps.toml` into
`[models]`. The forbidden-models rule (`steps._FORBIDDEN_MODEL`, MCW-y37w, and
CW-zq4h's clause letting a repository forbid models) is removed: a repository that
never wants a model does not list it. The engine keeps refusing two models of one
vendor on a row and Codex on any step but the review. The step table keeps each
step's skill, its permission rules, and `resume_from`.

Rejected: a forbidden-models list; leaving the models in the step table, which mixes
the repository's preference with permissions the sandbox change replaces.

### D6 — The documents a step loads come from the configuration

`[load] common` lists the documents every step's skill reads as it starts, and
`[load] <step>` a step's additions. `scripts/change-workflow config load <step>`
prints the resolved list, so no skill merges the two itself, and the post-compaction
hook re-reads `common`, not knowing the session's step. The entries are paths;
`layer-engineering-guidance`'s tags can replace them later, since a tag resolves to
what a path names.

Rejected: a single list for every step, since steps already need different
documents; tags now, before their vocabulary exists.

### D7 — Inert paths

`[repository] inert-paths` names the paths a change to which alters nothing
validation or a code check would prove: here `openspec/` and `docs/`, and in another
repository images or metadata. After a pre-closeout review, a commit changing only
inert paths or changes' records needs no new validation, where the engine read
`records.DOCUMENTATION`; the requirements naming `openspec/` and `docs/` name the
repository's inert paths instead. A path belongs in the list only where the
closing checks cover what it can break: `docs/development/ARCHITECTURE.toml` sits
under `docs/` but the packaging checks read it, which is safe because closeout's
`pre-archive` runs them again before the archive.

The same list tiers the pre-commit hooks: a commit changing a path outside it runs
`after-functional-change`, then `pre-commit-functional`, then `pre-commit`; any
other runs only `pre-commit`. The skill does not decide which tier it is in: the
paths the commit changes do. So `scripts/change-workflow run pre-commit <change>`
reads the tier itself from the worktree's changes against `HEAD` — staged, unstaged,
and untracked — and, when any lies outside the inert paths, runs
`after-functional-change` and `pre-commit-functional` before `pre-commit`, each
still held to the engine's hook table (D9). The skill then stages what the hooks
rebuilt, such as a lock, with its own edits. A review's clean worktree runs
`pre-commit` alone, which changes nothing (CW-y6mj).

Rejected: the names `documentation-paths`, which is narrower than the files it
holds, `revalidation-exempt`, which names only one use, and `non-functional-paths`,
which collides with non-functional requirements; one pre-commit line for every
commit, which makes every design commit build the wheelhouse and run the suite; a
repository target that tiers itself, which duplicates the engine's list; tiers keyed
by step, which puts back in the skills the knowledge P1 moves out.

### D8 — Commands receive their values through placeholders

A declared command names the values it needs as placeholders the engine fills in,
each value shell-quoted, and runs it with `sh -c` from the repository's root:
`{change}`, `{base}` (D4), `{remote}`, `{after}` (D10), and `{owed}` (D3), filled
from `run`'s `--owed <workflow>`, which an owed part requires and any other part
refuses (14 F2). The
vocabulary is closed and defined per hook: `{remote}` only in `pre-push`, `{owed}`
only in an owed part, `{after}` only in a `collect`. A placeholder the engine does
not know, or one not available where it is used, is refused when the configuration
is checked (D13). A value of the owner's machine — `HELM_CONTEXT`, and
`HELM_ALL_SCENARIOS` when the owner asks for every scenario — is no field and no
placeholder (P2): it reaches the command through the environment, which make
already reads, and the skill no longer interprets it from validation's arguments.

Rejected: environment variables the workflow exports, which make the repository's
own code read the workflow's variable names; positional arguments appended, which
make reads as targets.

### D9 — The engine holds which step may run each hook

Which steps may invoke each hook is the workflow's structure, held in the engine
beside the graph and changed by no repository:

| Hook | Steps |
|---|---|
| `after-functional-change`, `pre-commit-functional` | implement, triage, merge |
| `pre-commit` | design, plan, implement, triage, merge, closeout, archive cleanup, review |
| `pre-archive` | closeout |
| validation's preflight and parts | validate |
| `cleanup`, every part's cleanup as one list | archive cleanup |

`pre-push` and `post-clone` are run only by the engine's own `push` and `clone`. A
skill invokes a hook through `scripts/change-workflow run`. The unattended-run marker
names the run's step, and `run` refuses a hook the step is not listed for, naming
both; with no marker, as in an interactive run, nothing is restricted. The marker is
internal (CW-5qne). A forged marker is a step breaking its skill, which the deny
rules and the skill already govern; making forgery impossible needs credentials the
step does not hold, `sandbox-unattended-workflow-steps`' work.

The list governs what a step asks the engine to run, not what commands it may run:
the step table, and its profile after the sandbox change, does that. Each writing
step's rules gain `Bash(scripts/change-workflow run *)` and keep their grants for
engineering work (`make test*`, `uv run pytest`, `make init*`, `make typecheck*`,
`make check-*`); the rules that only ran what is now a hook are removed: validation's
`make validate-*`, `make run-e2e`, `make run-ci *`, `make fetch-e2e-logs*`, `make
dist-clean`, and `make check-uv-version`, and archive cleanup's `make -C helm
teardown*` and `make record-capacity*`. Commands no skill invokes — `make typecheck`,
`make init`, `make reinit`, `make dist`, `make helm-values-schema` — are permissions,
not hooks.

Rejected: per-step lists in the configuration, which would let an adopter give
validation `after-functional-change` against CW-af15; a `hooks` key on each step
table row, a provisional file; a per-run token matched against the runs in progress,
which a step can read; keeping every rule, which leaves validation's commands
runnable around the engine.

### D10 — Exit status, an engine-written closing line, a kept marker, and the invocation record

A declared command promises its exit status, zero or not, and, for a `start`, that
its last line of standard output is the marker its `collect` waits past. The engine
passes the command's output through and writes one closing line in a fixed form the
shipped skills match, naming the hook or part, the commit, the result, the exit
status, and the evidence directory; it is internal, as the marker is. The engine
keeps a `start`'s marker in the validation's own state, keyed by the commit, the
part, and, for an owed part, its owed workflow (14 F2), so owed runs dispatched side
by side never share one; a retried `start` replaces its key's marker, so a collect
always waits past the newest dispatch. It fills `{after}` from it, so the skill
passes none. Classifying a failure as
caused by the commit, environmental, or of unknown cause stays the skill's, from the
evidence (CW-a1nz).

Every invocation through `run` or `push` is recorded on the run's log line as
`invoked` (14 F5): for each hook or part and each command of a list, its name, part,
owed workflow, and phase, the command it resolved to, its exit status, when it
started, and how long it took. An unattended run's line is the wrapper's; an
interactive run's is the one `record` writes, `run` and `push` keeping the
invocations by the session's id until then. An invocation outside any session is not
recorded. `post-clone` belongs to no step's run: the orchestrating session starts it
in the background, and it outlives the call. Its record is the clone's bootstrap
state (CW-8npg), which holds its log and exit status and gains the command it
resolved to. The field is optional, so the record set's format does not move. A hook's
output stays in the run's transcript, which history copies with `reviews/`. With the
validation record and the evidence directories, the engine's record is the durable
account of what ran and how it ended, one the agent cannot write.

Rejected: a structured result file each command writes, which moves part of the
diagnosis into repository code and asks every adopter to write a format, though a
later workflow may add it as an optional placeholder; a result line every
repository's command prints in the workflow's wording, which the engine can write
itself; a marker keyed by commit and part alone, or owed runs started and collected
one at a time (14 F2), which collide or give up concurrent dispatch; an owning run
invented for the clone's bootstrap, or `pre-push` left off the pushing run's line
(14 F5).

### D11 — Default checks run unless disabled by name

The workflow's default checks for a hook run before the hook's declared commands,
which add to them. `pre-commit`'s default checks are `index`, `tasks`, `skills`, and
`openspec` (the strict validation of the change, or of every specification for an
archived change). A repository turns one off only by naming it under `[defaults]
disable`, with a reason, which `config` lists (P4); anything not listed runs. The
same checks run alone as `scripts/change-workflow check change <change>`.

`[openspec] command` names how the CLI is run; it defaults to `openspec` on the path.
The default validation and closeout's archive use it, through `scripts/change-workflow
openspec <arguments>` (D16). Decision destinations and the spec index stay this
repository's checks; whether they move into the engine is
`extract-change-workflow-repository`'s open question of what moves. Bootstrapping a
repository's first configuration is not this change's.

The owner's closing check stays complete (14 F3). `make check-change CHANGE=<change>`
runs `scripts/change-workflow run pre-commit <change>`, unrestricted with no
unattended marker (D9): the four defaults, then the hook. The hook names a new
repository-only target, `make check-repository`, which is `check_change.py` without
the four: comment hygiene, documentation citations, the spec index, decision
destinations, history wording, version bumps, local imports, and the capability
index. No check runs twice, and nothing recurses.

Rejected: defaults no repository can turn off, since the owner wants removal
possible when deliberate; a declared hook replacing the default, kept only by listing
it, which removes a safeguard by omission; a `{default}` token the list must contain,
the same omission; no engine checks at pre-commit, which leaves each adopter to wire
them; `make check-change` trimmed to the repository's checks, with the guide and its
callers moved to the engine's command (14 F3), which leaves the familiar target
silently partial.

### D12 — A field is required or optional

A required field's absence makes the engine refuse a step that needs it, naming the
field; an explicit empty value counts as declared, so a repository can say "nothing
here" deliberately (P4). Required: `hooks.pre-commit-functional`, how a functional
change is checked; `validation.parts`, at least one, since a round advances only on
a passed validation (CW-tnp6); `repository.protected-branches`; and `models` for each
step run unattended and for the orchestrating session. Optional, skipped when absent
with the run record saying so: `after-functional-change`, `pre-archive`, `pre-push`
(CW-p7kq), `post-clone`, `validation.preflight`, a part's `cleanup` (CW-ikmm),
`load`, `inert-paths`, `defaults`, and `openspec`.

Rejected: permissive defaults for every hook, which let a repository adopt without
deciding how a functional change is checked.

### D13 — The configuration is checked whenever it is read

Every subcommand that reads the configuration checks all of it as it loads it, as
`steps.py` refuses a malformed step table, and refuses, naming the field, on an
unknown table or key (adopters add none, P3, so one is a typo or a newer workflow's),
a wrong type, or a placeholder unavailable where it is used. A missing required field
refuses only the steps that need it, and `start` checks before launching anything. No
file means every field is absent. A person runs the same check as
`scripts/change-workflow check config`.

Rejected: checking only at `start`, which lets `push` or `next` read a malformed file.

### D14 — The configuration is protected from steps

`[common]` denies `Edit(.agents/workflow.toml)` and `Write(.agents/workflow.toml)`,
beside `.claude/**`, so no step changes what its own hooks run. Only the file is
denied, since a workflow change edits skills under `.agents/`. It changes as a
tracked edit by the owner, or by the orchestrating session on the owner's word. The
sandbox change's planned invariant check that the configuration is unchanged covers
it again.

Rejected: leaving it unprotected, which lets implementation change what its own
pre-commit runs; denying all of `.agents/`, which blocks workflow changes.

### D15 — Place, format, and key style

`.agents/workflow.toml`, in TOML, which the engine reads on the standard library and
which carries each field's reason in comments, as the step table does. Keys are
kebab-case, as Git's hook names are; the step table keeps its own keys.

### D16 — The configuration's resolution and the operations that read it

`scripts/change-workflow config` lists every field and how it resolved — declared,
default, disabled, or absent — with the command it resolves to, and `--json` gives the
structured form. `config load <step>` prints a step's documents (D6), `config parts
<change>` validation's plan (D3), and `openspec <arguments>` runs the configured
OpenSpec command (D11), so no skill reads the file's internals. The step table's pinned `bunx` and `npx` OpenSpec rules become
`Bash(scripts/change-workflow openspec *)`.

Rejected: listing only in `check config`'s report, which gives a program nothing to
parse; skills reading `config --json` to find a command, which makes them interpret
the file.

### D17 — The skills invoke hooks; the fragment's targets stay

Every repository target a skill runs itself moves behind `run`: `make check-change`
(the skills run `run pre-commit`, which `make check-change` wraps for the owner),
`make test`, `make lock`, `make check-packaging`, validation's parts, its preflight,
the teardown, and the capacity record (`run cleanup`). The skills keep telling the owner to run the
fragment's targets (`make review`, `make round-view`, and the rest), whose role
`extract-change-workflow-repository` owns.

### D18 — The inventory becomes the configuration's description

`change-workflow`'s "What an adopting repository provides" describes the
configuration: each field, who uses it, and how. The roles outside it are the make
fragment, the conventions the workflow fixes, and the derived landing branch and
remote. MCW-5tgp states that this repository's configuration declares the
workflow's fields and how it provides what the file does not hold: the step table's
engineering grants and the fragment. `test_change_workflow_assumptions.py` keeps
failing on a make target or path the skills or step table name that the provisions
omit; the engine's check of the file (D13) holds the rest.

### D19 — Compatibility

| Interface | Change | Compatible |
|---|---|---|
| `run` (with `run cleanup` and `--owed`), `config`, `config load`, `config parts`, `check config`, `check change`, `openspec` | new subcommands | yes |
| `.agents/workflow.toml` | a new public input, versioned by the engine's release | yes, as new |
| `hooks.pre-commit-functional`, `validation.parts`, `repository.protected-branches`, `models` | roles an adopter must now provide | no: a minor change while the major version is 0; this repository, the only adopter, provides them here |
| `clone-remove` | judges a merge against the recorded landing branch and upstream remote; `--base` for a clone with none recorded | yes for clones it creates; a clone made before it needs `--base` |
| `find --json`'s `base`; the log line's `invoked` | optional fields added | yes |
| The step table loses `models` and `[orchestrator]` | a provisional schema changes | allowed |
| CW-zq4h's clause letting a repository forbid models | an obligation removed | no (minor) |
| CW-hdxi's fallback to the repository's default branch | a step with no recorded or given base now refuses | no (minor) |
| The fragment's `CHANGE_WORKFLOW_MERGE_FROM` and `CHANGE_WORKFLOW_REVIEW_BASE` | removed | outside the surface |
| The unattended marker names the step | internal | n/a |

### D20 — The repository-side fixes this change carries

Small, understood fixes that the decisions need, kept in the change
(`openspec/README.md`, "Defects found during a change"):

- `make pre-push` runs both public-content checks under Git's hook contract, and
  `scripts/hooks/pre-push` calls it, so the pair is defined once rather than in the
  hook and in `push.PRE_PUSH_CHECKS`.
- `make run-e2e` and `make run-ci` end their output with the bare marker their
  collect waits past, and the validation skill stops running `gh run list` itself.
- `make dist-clean` folds into the parts' own commands.
- `make code-snapshot`, its triage sentence, and its role and provision rows are
  removed: no skill needs it.
- `check_change.py` drops the checks the default `pre-commit` runs, reads its base
  from `find --json`, and becomes `make check-repository`, the `pre-commit` hook's
  command; `make check-change` runs `scripts/change-workflow run pre-commit` and
  stays the complete closing check (14 F3).

### D21 — Implementation cadence

One round, reviewed once, in three sessions:

1. **The configuration contract in the engine:** the loader and its check (D13);
   `config`, `config load`, `config parts`, `check config`, `check change`, `run`
   (with `run cleanup` and `--owed`), and `openspec`; hooks and their lists, the
   defaults and `disable`, the placeholders; the marker naming the step and the
   engine's hook table (D9); the kept marker keyed by commit, part, and owed
   workflow, the closing line, and `invoked`, for `run` and `push` (D10).
2. **The held values and this repository's file:** each constant replaced by the
   file or a derivation — the protected branches, the remote, `pre-push`, the clone
   recording its base and setting the upstream, clone removal judging the merge
   against that base and its upstream's remote, `--base` for an older clone, the
   bootstrap's state recording its command, the review base and `find --json`'s
   `base`, the inert paths, history reading the parts' evidence, the hook's `load`;
   the models moved and the forbidden rule removed; this repository's
   `.agents/workflow.toml` and its Makefile targets (D20). The step table's `models`
   and `[orchestrator]` removal and the deny rules (D14) are `.claude/` edits only the
   owner or the orchestrating session makes.
3. **The callers:** the skills moved to `run`, `openspec`, and `config load`; the
   step table's rules (D9), again a `.claude/` edit; `check_change.py` as `make
   check-repository` and `make check-change` running `run pre-commit`; the guide; and
   the assumptions test and its tables (D18).

## Open Questions

- **A structured result from a validation part.** Parts report only an exit status
  and a marker (D10). Revisit when a repository needs a part to report its own
  environmental failures; an optional `{result}` placeholder would add it
  compatibly.
- **Moving decision destinations and the spec index into the engine's defaults.**
  They stay this repository's checks (D11). Revisit in
  `extract-change-workflow-repository`'s design, which decides what moves.
- **Loading guidance by tag.** `[load]` holds paths (D6). Revisit when
  `layer-engineering-guidance` settles its tag vocabulary.
