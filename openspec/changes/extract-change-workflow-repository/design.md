# Design: extract the change workflow repository

Status: design settled 2026-11-23 (D1–D24), amended by design review 15's triage
(D4, D5, D6, D8, D14, D18, D21, D22, and D23 added), by the owner's settlement of
planning's question P1 (D24), and by the triage of implementation review 30 (D1, D24,
and D25 added). The change has two halves in one
change: first the workflow becomes a self-contained, versioned, installable
distribution that this repository runs installed from its own tree; then, once a
coordinator has bootstrapped the workflow's own repository from that tree and
released it, this repository adopts the release and removes its copy.

## Context

- **What is on the workflow's side.**
  - The engine: the command `scripts/change-workflow` and its package
    `scripts/change_workflow/`, standard library only. No other script of the engine
    remains: the change lookup and the skills check are its `find` and `skills`
    modules.
  - Eleven skills: the ten `change-*` skills and `guidance-review`.
  - The outcome schema, `.agents/change-outcome.schema.json`.
  - The `change-workflow` capability: its specification, index, companion, and
    diagrams under `openspec/specs/change-workflow/`.
  - The workflow's guidance, `docs/guidance/workflow/`, and the owner's handbook,
    `docs/change-workflow-handbook.md`.
  - The make fragment, `scripts/change_workflow/workflow.mk`, which the root
    `Makefile` includes.
  - The engine's default checks (`index`, `tasks`, `skills`, `openspec`), which are
    modules of the engine, not separate artifacts.
  - The workflow's tests and fixtures under `scripts/tests/`.
- **Checks of this repository's that enforce workflow rules.** `check_spec_index.py`
  and `check_decision_destinations.py` hold nothing of this repository's;
  `check_comment_hygiene.py` holds its file types and exemptions, and
  `check_guidance.py` its layout of `docs/guidance/` and `AGENTS.md`. The citation and
  history-wording checks enforce engineering rules.
- **Repository specifics left the skills already.** `add-skill-extension-points`
  replaced addenda with evidence kinds declared in `[validation]`, guides under
  `.agents/evidence/`, and hooks around each step; `sandbox-unattended-workflow-steps`
  replaced the step table and its deny rules with an engine-owned bubblewrap sandbox,
  so `.claude/settings.json` holds only the post-compaction hook.
- **What the workflow still reaches for by path in the adopting repository.** Its
  guidance and specification; the engineering guidance (25 citations of
  `docs/guidance/engineering/` in eight skills, 7 links from the workflow's guidance
  into `../engineering/`, admitted by CW-n8tr and CW-d2rw); its command at
  `scripts/change-workflow`; its schema (`outcome.SCHEMA`) and graph diagram
  (`diagram.DIAGRAMS`); and its skills, linked from `.claude/skills/` and
  `.codex/skills/` to `.agents/skills/`. `test_change_workflow_assumptions.py` reads
  the roles table of `change-workflow`'s companion.
- **Each checkout runs its own branch's workflow today**, since the engine and the
  skills are in the tree.
- **The Claude Code adapter's writable state is the whole of `~/.claude`**, protecting
  only its settings file, and Codex's is `~/.codex`; this repository's
  `writable.common` grants `~/.local/share/uv`.
- **Nothing of the workflow has been released or deployed.** The repository's tags
  are the market's. Compatibility is owed only to the format-2 records in the owner's
  workspace, which the engine keeps reading.
- **About 95 of this repository's documents outside the archive** cite
  `openspec/specs/change-workflow/` or `docs/guidance/workflow/` by relative path.

## Decisions

### D1 — One change in two halves, paused between them

The change covers both halves. Its first half, (i), makes the workflow a
self-contained, versioned, installable distribution built from this repository's
tree, which this repository then runs installed. Between the halves a coordinator —
an agent the owner runs to coordinate work across repositories — bootstraps the
workflow's repository from what (i) left and releases it; the change waits in
implementation for its evidence (D2). Its second half, (iii), declares the range this
repository accepts, installs the release, removes the in-tree copy, and re-points
this repository's documents. (i) may be merged to `dev` by a preliminary pull request
while the change stays in implementation; `dev` then runs (i) for the whole pause, so
(i) ends complete on its own: the workflow installed from the tree, every check and
suite `dev` and other changes run passing — this change's own index check, run with
the change named, failing only on the `market-change-workflow` delta's two added ids
until 10.2 writes their entries, as every change's does until its entries are written
(`pass-checks-at-every-commit`) — and no citation half-rewritten (30 F1).

Rejected: a follow-up change for (iii), which costs a second design and closeout for
what is mostly deletion and citation rewriting; (i) as a prerequisite, which would
halt this design; finer splits; and deferring the move, which leaves the workflow
unadoptable while `host-change-workflow-runner` depends on it.

### D2 — The gate between the halves

The orchestrating session holds the round after (i), which is the candidate for the
preliminary merge, until the coordinator reports. (iii)'s first section opens with a
decision-gate task whose note records the coordinator's evidence:

1. the workflow repository's public URL;
2. the release's tag, its commit, and the distribution's version;
3. the release's artifacts in the artifact repository this repository already uses —
   a manual build may stand in for a CI pipeline — named by distribution, version,
   and digest, never by the registry's host, project, or path;
4. how to install it, a guide the coordinator provides, kept out of the tree wherever
   it names the registry.

The session that starts the section checks the evidence itself before writing
anything, and ends `stopped`, naming what is missing, when any of it is absent or
fails. Whether the release installs and serves this repository is proven by (iii)'s
own validation. Once `relay-messages-to-step-sessions` lands, the coordinator's report
may reach the orchestrating session directly; nothing here depends on it.

Rejected: widening `blocked` to an external condition, or a new record kind the
computation reads, each a public interface changed for one change's needs; an
informal wait alone, which records nothing and lets an early session proceed; and the
moved files' tree equality as evidence, too strict and immaterial to this repository.

### D3 — The engineering guidance is reached through a pointer

The workflow does not ship engineering guidance. Each user of the workflow brings
their own, and the workflow reaches it through a pointer the engine resolves and
passes to the skills. Here the pointer names this repository's
`docs/guidance/engineering/`; when a later change extracts that guidance to a neutral
home, serving this repository, the workflow's repository, and other repositories of
its owner's, only the pointer changes.

Rejected: shipping the engineering guidance in the workflow's distribution, which
makes the workflow its home and versions it with the workflow; a separate engineering
distribution now, which belongs to that later change; adopters keeping copies at the
same path, which forks them; and folding the rules the workflow needs into its own
guidance, which states each rule twice.

### D4 — The pointer's form, and citations by section name

The pointer is a table with one source key: `path` now, `distribution` added
compatibly by the extraction of the engineering guidance.

```toml
# .agents/workflow.local.toml
[guidance]
engineering = { path = "docs/guidance/engineering/" }
# later: engineering = { distribution = "arkhai-engineering-guidance", version = ">=0.1, <0.2" }
```

A `path` is relative to the checkout's root or begins with `~`; the check refuses a
missing or empty directory. It is required; `engineering = { none = "<reason>" }`
declares that a repository applies none, the reason required as `defaults.disable`
requires one. `config load` prints the pointer's Markdown files with every step's
documents. `config --json` gives the pointer as `guidance.engineering`, mirroring the
table's one key: `{"path": "<the resolved absolute directory>"}`, `{"none":
"<reason>"}`, or `null` while the local file lacks it (D5). The check refuses a `load`
entry overlapping the pointer, so nothing is read twice.

The skills cite engineering guidance by Markdown section name — "the engineering
guidance's section 'Imports go at module level'" — wherever the section sits beneath
the pointer, never by file name. The cited section names are a provisional interface,
its successor naming the guidance by role. `check config` reports a cited section
missing beneath a user's pointer and does not refuse it, since refusing would hold
every user's guidance to this repository's headings. A cited name that heads more
than one section beneath the pointer does not resolve: `check config` reports it as
ambiguous, naming the files, and does not refuse it either, for the same reason. The
workflow's guidance names engineering guidance the same way, in prose, so CW-d2rw's
link rule becomes a rule on what workflow guidance cites.

Three headings repeat across this repository's engineering guidance today, each a
file's title and a section of another file: "Integration tests" and "System tests"
(`integration-tests.md` and `system-tests.md`, and sections of `test-levels.md`), and
"Contract fixtures" (`contract-fixtures.md`, and a section of `testing-python.md`).
(i) makes all three unique in this repository's guidance, whether or not a skill
cites them, so section names start unique here (15 F5, the owner's condition).

Rejected: a bare path, which commits no version and invites a machine path; a Git
source the engine fetches, which puts network Git in the engine; and file names as
the interface, which impose how a user organizes their guidance.

### D5 — Committed configuration and one local file

A setting is local, in one gitignored file the installer writes, exactly when
developers using the workflow on the same repository should be able to give it
different values; otherwise it is committed. Teams share guidance, but it sits in a
different place on each developer's machine.

```toml
# .agents/workflow.toml — committed
[workflow]
version = ">=0.1, <0.2"
[repository]
protected-branches = ["main", "dev"]
inert-paths = ["openspec/", "docs/", "**/README.md", "AGENTS.md"]
# [hooks], [defaults], [openspec], [load], [review], [validation], and the
# repository's [sandbox] paths, as today
```

```toml
# .agents/workflow.local.toml — gitignored, written by `change-workflow install`
[guidance]
engineering = { path = "docs/guidance/engineering/" }
[models]
orchestrator = { model = "claude-opus-5-5", effort = "medium" }
design = [{ harness = "claude", model = "claude-opus-5-5", effort = "high" }]
# each step
[sandbox]
writable.common = ["~/.cache/my-own-tool"]   # extends the committed list, never narrows it
```

Local: the engineering pointer, `[models]` with the orchestrator's, and writable
sandbox paths a developer adds. Committed: everything else, the version range
included. Each key has one home: a key in the wrong file is refused, naming the file
it belongs in; writable sandbox paths alone extend from both. The sandbox protects
the local file as it protects `.agents/workflow.toml`, and a clone links it to the
workspace's, as it links `.claude/settings.local.json`. With no local file, `start`
refuses, naming the missing field and `change-workflow install`; `check config`
reports missing local fields without refusing, so CI, which has no local file, checks
everything it checks now.

`config --json` succeeds without the local file too, exiting 0, so CI's callers of
structured output — this repository's assumptions test reading `roles` (D14) — need
none. It reports the file beside the committed one, and each required local field
it lacks with the status `missing`, distinct from `absent`, which an optional field
takes; what the distribution provides — `roles` and the `workflow` paths (D6) — never
depends on it:

```json
{"file": ".agents/workflow.toml", "exists": true,
 "local": {"file": ".agents/workflow.local.toml", "exists": false},
 "fields": [{"field": "guidance.engineering", "status": "missing"},
            {"field": "models.design", "status": "missing"}],
 "guidance": {"engineering": null},
 "workflow": {"version": "0.1.0", "specification": "…", "schema": "…"},
 "roles": []}
```

A value of the wrong kind in either file is refused as it is today, and a pointer
directory holding no Markdown file is refused (D4). Every caller of a local field is
a step, which `start` guards, so the partial output reaches no step.

Rejected: the whole configuration local, which loses the coupling of hooks to the
branch that changes their targets, review of configuration changes, and CI's checks;
and leaving everything committed, which commits per-developer values and makes the
later split an incompatible change.

### D6 — The workflow's own documents ship with the engine

The workflow's guidance, its specification with index, companion, and diagrams, the
owner's handbook, the outcome schema, and the fragment ship in the distribution as
package data, and the engine finds them beside itself with no setting: they belong to
the same version as the skills that cite them, so nothing about them varies between
developers. `config load <step>` prints, lower layer first, the engineering pointer's
files, the installed workflow guidance, then the repository's `load` entries.
`config --json` names each installed document by its role, never a directory to look
inside, so the package's layout stays internal:

```json
"workflow": {"version": "0.1.0",
             "specification": "…/spec.md", "index": "…/index.md",
             "companion": "…/README.md", "diagrams": "…/diagrams/",
             "guidance": "…/workflow/", "handbook": "…/change-workflow-handbook.md",
             "schema": "…/change-outcome.schema.json", "fragment": "…/workflow.mk"}
```

The shipped skills read the workflow's own documents only through these fields — a
`CW-` requirement id in `workflow.specification`, and a review of a change citing the
workflow reads its installed specification and companion there. `fragment` stays a
subcommand for a `Makefile`'s include (D15). `outcome.SCHEMA` and `diagram.DIAGRAMS`
resolve inside the distribution.

The skills cite the workflow's guidance by section name and its specification by
requirement id, and the distribution's own test fails on a cited section or id that
does not exist in it. This repository's documents cite the workflow in prose by name,
requirement id, and section, with one link to the workflow's repository where a
document first names it; an id and a section mean the same in every version the range
admits, where a link pinned to a tag would be rewritten at every range bump.

In (i), the workflow's documents stop linking out of their own set — the companion's
four links to `market-change-workflow` become neutral text — and stay where they are,
the specification under `openspec/specs/change-workflow/` so workflow changes during
the pause keep their OpenSpec deltas; the distribution packages them from there.
This repository's inbound citations stay relative paths through (i) and are rewritten
in (iii).

Rejected: a pointer for the workflow's own documents, which versions them apart from
the skills citing them; copies installed into each repository; links pinned to a
release; links to the installed copy, a machine path; and a `workflow.documents`
directory with its layout made public, which commits every later release to the
package's internal paths (15 F4).

### D7 — One installed version per machine, checked against each repository's range

The workflow, engine included, is managed like any other external tool a repository
pins: one version is installed per machine, each repository declares the range it
accepts in its committed configuration, and every engine command that reads the
configuration refuses outside it, naming the installed version, the range, and the
fix. Interactive sessions never pass through `start`, so the check runs wherever the
configuration is read, `config load` among them. Records cross an upgrade only through
`format`; a change no longer runs its own branch's engine, and a change that edits the
engine is proven by its tests, not by running its own steps on the edit.

Rejected: versions side by side behind a launcher, with skill stubs or with per-checkout
skill links selecting the version the range picks, which keep each branch on the
workflow it was written against at the cost of a launcher, a version store, and
relinking. The proposal's promise that a change started under one major version
finishes under it goes with them.

### D8 — A wheel, an installer, the command on the path; the channel deferred

The artifact is a Python wheel, built with Hatchling, whose `change-workflow` entry
point carries the skills, the workflow's documents, the schema, and the fragment as
package data read through `importlib.resources`; it installs with `uv tool install`
from an index, a file, or a tag. The command is `change-workflow` on the path; the
shipped skills, the handbook, the fragment, and the post-compaction hook call it.
`scripts/change-workflow` stays through (i) and goes in (iii).

`change-workflow install` writes the version's skills into Claude Code's and Codex's
user skill directories, recording the names it wrote in a manifest beside them so it
removes a skill a later version retired and never touches one it did not write, and
stamping each with its version; every engine command compares the stamp with its own
version and refuses on a mismatch, naming `change-workflow install`, and refuses as
well when a supported harness's user skill directory lacks a skill the version ships
or lacks the manifest. `install` refuses a skill name present in a user skill
directory that its manifest does not record, naming it and writing nothing, rather
than overwriting a skill it did not write. Run in a
checkout, it writes `.agents/workflow.local.toml` where none exists, from the
repository's committed template, `.agents/workflow.local.template.toml`, when the
repository has one, and otherwise as a skeleton naming each required local field; it
never overwrites a local file.

During (i) this repository and its CI install the workflow from the tree and run it
as `change-workflow`, and (i) removes the workflow's project skill links,
`.claude/skills/` and `.codex/skills/`'s `change-*` and `guidance-review` entries, in
the section that switches the skills to `change-workflow`: each harness then finds the
workflow's skills only in its user skill directory, so the preliminary merge exercises
the installed form whatever a harness's rule for a project and a user skill of one
name (15 F2). The skills' sources stay under `.agents/skills/` until (iii), for the
wheel to package and the coordinator to lift.

Rejected: a zipapp, which fits uv's tool management less well and embeds its version;
and installation from a tag alone, a channel rather than an artifact.

### D9 — Names and licence

The repository is `change-workflow`, the wheel `arkhai-change-workflow`, and the
command `change-workflow`; the import package stays `change_workflow` and the
capability `change-workflow`. The licence is MIT, as this repository's and the moved
history's already are.

Rejected: the plain name for the wheel too, which risks a collision on a public
index; prefixing the repository, which differs from what everyone types; a new
product name; and Apache-2.0, a second licence family across the owner's public
repositories.

### D10 — Two more default checks

The specification index check and the decision destinations check become the
engine's default checks, `spec-index` and `decisions`, run by `pre-commit` and `check
change` and turned off only by name; `make check-repository` stops running them, so
each runs once. `check spec-index --json` reports the paths a change's deltas create,
which this repository's citation check reads in place of importing a delta reader.
Comment hygiene and the guidance check stay this repository's scripts until the
workflow's repository works its own changes through the workflow (D17), when they
move there as default checks with their configuration. The citation and
history-wording checks enforce engineering rules and stay here.

Rejected: moving none, which leaves every adopter to re-implement the workflow's own
rules; moving all four now, which builds two configuration tables and rewrites a
618-line check against a layout this change introduces; and deferring all.

### D11 — The version range

The committed `[workflow] version` holds a comma-separated subset of PEP 440's
specifiers (`>=`, `<=`, `>`, `<`, `==`, `!=`, `~=`) over release numbers, parsed on the
standard library. It is required. The engine reads it before checking the rest of the
file, so a newer workflow's keys are reported as a version mismatch, not an unknown
key. `install` and `--version` are exempt from the check, being how a mismatch is
fixed. This repository's range at (iii) is the coordinator's first release line.

Rejected: an exact pin, which needs a commit per release; and a local field, which
would let the range vary between developers.

### D12 — Each log line records the workflow version

Every line the log's writer appends carries `workflow`, the engine's version. It is
informational: nothing routes on it, and `format` stays at 2, since a field an older
reader can ignore moves no format. Records change only when `format` moves, through
`convert`; the proposal's "a minor upgrade migrates records" is withdrawn.

Rejected: a new format version, which nothing requires; and the version on the
opening line only, which loses which version wrote each later line after an upgrade.

### D13 — What is installed is protected

Each adapter protects its harness's user skill directory and the installer's
manifest; the engine protects its own installed distribution, found from its own
location, and `.agents/workflow.local.toml` beside `.agents/workflow.toml`. A
protected path inside a writable directory is mounted read-only, as the configuration
already is. The companion's current limit on Claude Code's writable `~/.claude` is
narrowed accordingly.

Rejected: review alone, too weak for the files that define every later step; and
installing outside the harnesses' state, where the harnesses do not look.

### D14 — How `market-change-workflow` cites the workflow and keeps its roles complete

`config --json` gains `roles`: each role the workflow leaves to a repository, by name,
with the configuration fields that provide it. The distribution's own test holds the
companion's roles table to it; this repository's assumptions test reads the roles
from it, in CI with no local file (D5), and the fragment from the path `fragment`
prints. The MCW requirements and
companion cite CW requirements in prose by id. `market-change-workflow` stays here as
this repository's capability.

Rejected: parsing the installed companion's table, which makes its layout an
interface by accident; and dropping the completeness test.

### D15 — The make fragment's installed path

`change-workflow fragment` prints the path of the installed `workflow.mk`, and an
adopting `Makefile` includes it with `include $(shell change-workflow fragment)`,
saying when the command is missing rather than failing on an empty include. The
fragment's default is `CHANGE_WORKFLOW ?= change-workflow`; it stays outside the
compatibility promise, and `fragment` is public. This repository includes the in-tree
fragment through (i) and switches in (iii).

Rejected: a copy of the fragment in each repository, which goes stale; and each
adopter writing its own targets, which lets the steps' targets diverge.

### D16 — The history is lifted by path, keeping paths

The coordinator lifts the moved files with their history by path, keeping each path
(`git filter-repo` with a path list): what (i)'s wheel packages, its tests and
fixtures, and its project file, which moves to the new repository's root in one
rename. (i) writes the list into the handbook's procedure for the move. The
workflow's archived changes stay in this repository's archive, since they cite its
commits and paths; the new repository starts with an empty archive. Untracked records
stay in the owner's workspace.

Rejected: gathering everything under one directory in (i), which would break
OpenSpec's tree during the pause and is no longer needed; and starting the new
repository without history.

### D17 — The workflow's repository works through the workflow

The workflow's repository works its own changes through the workflow from its first
commit, its OpenSpec tree arriving with the lift at the same paths. Its
configuration, local file, change index, root guidance, and CI are the coordinator's
bootstrap, outside this change; its first changes move comment hygiene and the
guidance check (D10). Validating a release against adopters before publishing is
deferred (Open Questions).

Rejected: starting without the workflow, which loses its discipline where the
workflow itself changes and lets its specification drift; and a restructured layout,
which rewrites every intra-workflow citation and rules out an OpenSpec tree.

### D18 — In-flight changes cross at their merge of `dev`

A branch made before (i)'s preliminary merge carries the workflow's tracked project
skill links, which (i) removes (D8), and a branch made before (iii) the in-tree
engine; its make targets run the in-tree command, and its sessions the skills its
harness picks, until it merges `dev`. (i) moves no `format` (D12), so its records stay
readable by the installed engine. No migration is built, and the handbook says when a
change crosses, and that until then which skill a branch still holding the links runs
is its harness's rule for a project and a user skill of one name. This repository
from (i) on holds no such pair, so nothing checks that rule (15 F2).

Rejected: rebasing every open change at (iii), which a merge does anyway; holding
(iii) until no change is open; and keeping the project links through (i) while
checking each harness's precedence, which probes a harness rule that may change
between its versions, and which left (i) unable to show it ran the installed skills
(15 F2).

### D19 — The lesser goal's section after extraction

At (iii)'s closeout the lesser goal's current state says this repository adopts the
workflow from its repository within its declared range; the gap "The workflow is not
a separately versioned distribution" closes; each open workflow change's row gains a
note that it moves to the workflow's repository, a move the owner or the coordinator
makes.

Rejected: closing the goal and dropping its rows, which loses changes still listed
here; and leaving the section, whose current state this repository no longer holds.

### D20 — The engine's diagrams are redrawn in (i)

The engine-parts and step-run diagrams of `change-workflow`'s companion are redrawn in
(i), with the evidence modules, the actions and hooks around a step, and the parts
this change adds (the installer, the range and stamp checks, `roles`, `fragment`), so
the lifted companion is current. That closes the gap row this change owns.

Rejected: redrawing in (iii), leaving them stale through the pause; and leaving it to
the workflow's repository.

### D21 — What the skills check holds

`check skills` holds two things: the installed skills — each the version ships
present in each supported harness's user skill directory with the manifest, and
stamped with the engine's version (D8) — and, for skills a repository keeps itself —
here OpenSpec's `openspec-*` skills — one source under `.agents/skills/` linked from
each harness's project skill directory, as now. The workflow's own sources, under
`.agents/skills/` through (i) for packaging only, are the distribution's, not the
repository's, so the check asks no project link of them. CW-d8de covers both.

Rejected: dropping the repository's half, which loses the guard against copies of
OpenSpec's skills; and a repository script for an unchanged rule.

### D22 — Implementation cadence

Two rounds. Round 1 is all of (i): the wheel and its package data; `install` with its
manifest and stamp; the version, the range check, and the log's `workflow` field; the
committed and local split and the engineering pointer; the documents served from the
distribution, `config load`'s order, and `config --json`'s additions; `fragment`; the
skills switched to `change-workflow` and to citations by section and id, and the
workflow's project skill links removed; the engineering guidance's three repeated
headings made unique; the sandbox's protections and the skills check; the two new
default checks and `check spec-index --json`; `roles` and this repository's
assumptions test; the workflow's documents made self-contained; the diagrams redrawn;
the `change-workflow` delta applied to the permanent specification and its index
(D23); the handbook's procedure and path list for the move; and this repository and
CI installing from the tree. Its triage ends (i), the orchestrating session holds,
and (i) is the candidate for the preliminary pull request. Round 2 is (iii), after the
coordinator's evidence: the gate section; the range and the installed release; the
in-tree copy removed; this repository's workflow citations rewritten;
`market-change-workflow`, its delta applied by hand (D23), `AGENTS.md`, and the lesser
goal's section. Round 1 is expected to take three sessions
(the engine and installer; the skills and the configuration split; the checks,
documents, and this repository's installed operation) and round 2 two (the gate and
switch; the citation rewrite); planning maps them onto sections. Then closeout, which
archives with `--skip-specs` (D23).

The install target, the skills' switch to `change-workflow`, and the removal of the
workflow's project skill links sit in one section, since this change's later sessions
run whatever is installed from the tree, and a developer reinstalls after each engine
edit.

### D23 — The `change-workflow` delta reaches the permanent specification in (i)

(i)'s last section applies this change's `change-workflow` delta to
`openspec/specs/change-workflow/spec.md`, and writes its `index.md` entries as
promotion would, so the preliminary merge, the wheel built from the tree (D6), and the
coordinator's lift (D16) carry the requirements the release implements, and the
distribution's test of cited ids (CW-lm42) holds the skills' new citations. (iii)
applies the `market-change-workflow` delta by hand as it amends that capability. The
closeout archives with `--skip-specs`, which closeout's "Archival" admits for a
`spec.md` already edited by hand; the delta files stay in the archived change as its
record, and the closeout review compares each hand-applied requirement with its delta.
What holds for the specification holds for the rest of the capability and the
handbook, which also ship in the release and also leave in (iii): the promotions the
proposal's knowledge to promote sends to `change-workflow`'s companion, its diagrams
(D20), and the owner's handbook are written in (i)'s last sections with the
specification, since no closeout in this repository can write a document (iii) has
removed.

This departs, for this change, from "Promotion"'s rule that the archive writes a
`spec.md` the change's deltas cover. The archive cannot write it here: once (iii)
removes the capability, `openspec archive` refuses a MODIFIED requirement whose
specification does not exist, and the strict validation every pre-commit runs does
not catch it (15 F1, checked on a scratch tree with OpenSpec 1.6.0); and the release,
cut between the halves, must carry its own requirements before the closeout.

Rejected: splitting the change in two so (i) archives normally before the lift, which
reverses D1 and costs the second design, review, and closeout D1 avoided; and deleting
the `change-workflow` delta from the change in (iii), which archives normally but
leaves the archived change without its largest specification change.

### D24 — A temporary exception to the packaging layout for the workflow's wheel

The wheel (D8) carries the engine from `scripts/change_workflow/` and the workflow's
documents from where they sit (D6, D16), which no `src/<package>` layout can hold
without moving the specification out of OpenSpec's tree. It is built in that shape
under an `overrides` row of `AGENTS.md`'s "Exceptions to shared guidance", against
`packaging-python.md`'s "One import package per distribution", "Nothing remaps the
package", and "Data files live inside the package", and their Hatchling form; it
spans the engine under `scripts/`, the skills under `.agents/`, and documents under
`docs/` and `openspec/`, so it sits in the root table rather than beside one
capability. `make check-project-layout` admits that one project, naming the row.
The exception lasts until (iii) removes the engine, the wheel's project, and the
row together: it is short-lived, and restructuring the engine to the rule's layout
is not worth doing in a repository it is about to leave. The workflow's repository
restructures, as its own change, so that no `force-include` table remains: the
owner's condition on 32 O1, "this list has to disappear on the arkhai-change-workflow
repo", which the handbook's procedure for the move states. Until then the table is
brittle but not silent: the wheel's test fails when the tree and the wheel disagree.

Planning raised the question (P1) and the owner settled it, declining a return to
design: "This is going to be a temporary exception until step (iii) removes the
engine entirely. It's short lived and isn't worth doing heavy refactoring right now
we move it out of the repo anyway."

Rejected: moving the engine to `src/change_workflow/` with each document linked into
the package directory, a restructuring of code about to leave whose linked build was
unproven; and a generated build tree, a build configuration by another name.

### D25 — Unattended Claude Code runs load the installed skills, and stop without them

The Claude Code adapter launches a step with `--setting-sources project`, so the
owner's user settings never shape an unattended run, and Claude Code loads the user
skill directory only with the user's settings: from section 4, which removed the
project skill links, every unattended Claude Code step started with none of the
workflow's skills (33 R1). The adapter adds the home directory as a working directory
(`--add-dir`), whose `.claude/skills/` Claude Code loads without the user's settings;
the engine's sandbox, not Claude Code's working directories, bounds what a run writes.
Because that rests on a harness behaviour that may change between versions, the
stream holds each run to the skills its opening `init` event lists: a run of an
installed engine whose harness did not load a skill the engine ships is stopped there,
before its first turn, and its model passed over as unavailable, naming each, in a
step and in a Claude review alike (CW-d8de). Codex loads `~/.codex/skills/` and is
unaffected; its events list no loaded skills, so it is not held to them. The owner's
own user skills load beside the workflow's, carrying no rule or hook; and a run the
engine starts unconfined, which it warns of, has the home directory as a working
directory with no sandbox bounding it, a cost of that warned fallback.

Rejected: loading the user's settings (`--setting-sources user,project`), the
documented mechanism, which lets the owner's rules, hooks, and environment shape every
unattended run, so runs differ between machines; and binding the installed skills
into the project's skill directory inside the sandbox, whose mount points leave empty
directories in the worktree, as the sandbox's empty protected files left 30 F3's empty
local configuration.

## Principles

Stated by the owner in this design, for promotion:

- A setting is local exactly when developers using the workflow on the same
  repository should be able to give it different values; otherwise it is committed
  (D5).
- The workflow, engine included, is managed like any other external tool a
  repository pins: one installed version, each repository declaring the range it
  accepts, the engine refusing outside it (D7).
- The workflow relies on what it needs of a user's engineering guidance, its
  sections, not on how that guidance is organized (D4).
- Users of the workflow bring their own engineering guidance; the workflow does not
  ship it (D3).

## Open Questions

- **The distribution channel.** Until the first public adopter or the coordinator's
  first release, whichever comes first, the wheel is installed from the dev artifact
  repository, its index named only in each developer's own configuration. Revisit
  then: a public index or the public repository's tags serve the public case with no
  change to the artifact.
- **Validating a release against adopters before publishing.** The first release is
  validated by (iii)'s own validation. Revisit at a second adopter, or when a
  published release breaks one: the workflow's release process then checks each known
  adopter's configuration against the candidate.
