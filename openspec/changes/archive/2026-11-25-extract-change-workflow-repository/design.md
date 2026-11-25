# Design: extract the change workflow repository

Status: design settled 2026-11-23 (D1–D24), amended by design review 15's triage
(D4, D5, D6, D8, D14, D18, D21, D22, and D23 added), by the owner's settlement of
planning's question P1 (D24), by the triage of implementation review 30 (D1, D24,
and D25 added), and by the owner's return to design of 2026-11-25 (D2, D5, D6, D9,
D10, D11, D14, D15, D17, D19, and D22 amended, D26 added, and the distribution
channel's open question resolved), once the coordinator had cut the first release
from the workflow's repository, and by the triage of design review 58 (D2, D6, D9,
D14, and D26 amended). The change has two halves in one
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
  - The outcome schema, `change-outcome.schema.json` under `.agents/`.
  - The `change-workflow` capability: its specification, index, companion, and
    diagrams under `openspec/specs/change-workflow/`.
  - The workflow's guidance, `docs/guidance/workflow/`, and the owner's handbook,
    `change-workflow-handbook.md` under `docs/`.
  - The make fragment, `workflow.mk` in `scripts/change_workflow/`, which the root
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
- **Nothing of the workflow had been released when (i) was designed.** The
  repository's tags are the market's. Compatibility is owed only to the format-2
  records in the owner's workspace, which the engine keeps reading. Between the halves
  the coordinator cut the first release, `arkhai-change-workflow` 0.1.0 (D2). It
  differs from (i)'s tree in adding `change-workflow init` (CW-q2vn), which CW-f8yy and
  CW-1rhd exempt from their checks beside `install` and `--version`.
- **This repository names the workflow only by its distribution**, as it names any
  tool it installs: the name, commits, and registry location of the workflow's
  source, and the coordinator's install guide, stay out of this tree.
- **Six open workflow changes moved to the workflow's repository with the release**:
  `add-workflow-harness-adapters`, `add-workflow-model-gateway`,
  `host-change-workflow-runner`, `split-implementation-sessions-automatically`,
  `relay-messages-to-step-sessions`, and `pass-checks-at-every-commit`. Their
  directories and rows are still in this repository's change index.
- **This repository's CI runs `make` with no workflow installed** once (iii) lands
  (D26), and today's `code-snapshot`, `review-diff`, `last-diff`, `validate-local`,
  `validate-ci`, `validate-helm`, `run-ci`, and `run-e2e` depend on the fragment's
  `round-view-closed`.
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
the change named, failing only on the `market-change-workflow` delta's added ids
until 10.2 writes their entries, as every change's does until its entries are written
(the subject of the workflow repository's `pass-checks-at-every-commit`) — and no
citation half-rewritten (30 F1).

Rejected: a follow-up change for (iii), which costs a second design and closeout for
what is mostly deletion and citation rewriting; (i) as a prerequisite, which would
halt this design; finer splits; and deferring the move, which leaves the workflow
unadoptable while the hosted runner depends on it.

### D2 — The gate between the halves

The orchestrating session holds the round after (i), which is the candidate for the
preliminary merge, until the coordinator reports. This repository names the workflow
only by its distribution, and the evidence names the release the same way: (iii)'s first
section opens with a decision-gate task whose note records

1. the distribution and its version, `arkhai-change-workflow` 0.1.0, and the
   release's tag, `v0.1.0`;
2. the release's artifact, named by its wheel's file name and SHA-256 digest —
   `arkhai_change_workflow-0.1.0-py3-none-any.whl`,
   `3434aceddbb56ac9763ac32a17c9fd25ce37e8e588beeaee242e5d328eb2d71f` — published on
   the release page of the workflow's repository and in the dev artifact repository,
   a manual build standing in for a CI pipeline;
3. the coordinator's confirmation that the two unowned rows this change found about
   the workflow's own engine and specification were carried to the workflow's
   repository (D19).

No URL or link to the workflow's repository, its name, the tag's commit, the
registry's host, project, or path, or the coordinator's install guide enters the
tree. A wheel's file name may, as this repository's lock files and attachments name
the `arkhai-payments` kit's wheels.

Before the section's session, the orchestrator, on the owner's word, downloads the
wheel from the release page, checks its digest, installs it from that file with `uv
tool install --force <file>`, and runs `change-workflow install`. The session checks
the evidence itself before writing anything: `change-workflow --version` prints the
recorded version, within the committed range; uv's receipt for the tool names a
wheel file, not this tree's wheel project, of the recorded file name and whose
SHA-256 is the recorded digest, the session reading that file's path and writing it
nowhere; and `change-workflow check skills` passes. It ends `stopped`, naming what is
missing, when any of the evidence is absent or any check fails. The version alone
proves nothing, since (i)'s tree builds the same version. The artifact's copy in the
dev artifact repository is the same artifact by its digest; the session does not
fetch it, which would need the registry's location. Whether the release serves this
repository is proven by (iii)'s own validation.

Rejected: widening `blocked` to an external condition, or a new record kind the
computation reads, each a public interface changed for one change's needs; an
informal wait alone, which records nothing and lets an early session proceed; the
moved files' tree equality as evidence, too strict and immaterial to this repository;
checking only that the installed tool is not this tree's build, which proves the tree
is not installed rather than that the release is; recording the evidence as given,
which lets an early or wrong install through to validation; and the session fetching
from the release page itself, which puts the workflow's source location in its
commands and the credentials to reach it in its sandbox.

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
reports missing local fields without refusing, so a CI with no local file, such as
the workflow repository's, checks everything else.

`config --json` succeeds without the local file too, exiting 0, so a fresh clone and
the workflow repository's own CI read structured output with none. It reports the file beside the committed one, and each required local field
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
does not exist in it. This repository's documents cite the workflow in prose by its
distribution's name, `arkhai-change-workflow`, requirement id, and section, with no
link to or address of the workflow's repository; an id and a
section mean the same in every version the range admits, where a link pinned to a tag
would be rewritten at every range bump. Review holds the documents to it: a check
would have to hold the address it looks for.

In (i), the workflow's documents stop linking out of their own set — the companion's
four links to `market-change-workflow` become neutral text — and stay where they are,
the specification under `openspec/specs/change-workflow/` so workflow changes during
the pause keep their OpenSpec deltas; the distribution packages them from there.
This repository's inbound citations stay relative paths through (i) and are rewritten
in (iii).

Rejected: a pointer for the workflow's own documents, which versions them apart from
the skills citing them; copies installed into each repository; links pinned to a
release; a link to the workflow's repository, which this repository does not name;
links to the
installed copy, a machine path; and a `workflow.documents`
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

The wheel is `arkhai-change-workflow` and the command `change-workflow`; the import
package stays `change_workflow` and the capability `change-workflow`. This repository
names the workflow by the distribution alone, never by its repository. The
licence is MIT, as this repository's and the moved history's already are.

Rejected: the plain name for the wheel too, which risks a collision on a public
index; a new product name; and Apache-2.0, a licence other than the moved history's.

### D10 — Two more default checks

The specification index check and the decision destinations check become the
engine's default checks, `spec-index` and `decisions`, run by `pre-commit` and `check
change` and turned off only by name; `make check-repository` stops running them, so
each runs once. `check spec-index --json` reports the paths a change's deltas create,
which this repository's citation check reads in place of importing a delta reader,
in its run scoped to a change, which only the workflow's `pre-commit` makes; its
unscoped run needs no workflow (D26).
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
fixed; the first release exempts `init` as well. This repository's range at (iii) is
the coordinator's first release line, `>=0.1, <0.2`, which `.agents/workflow.toml`
already declares, so installing the release changes no committed file.

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

### D14 — How `market-change-workflow` cites the workflow, and who verifies its adoption

`config --json` gains `roles`: each role the workflow leaves to a repository, by name,
with the configuration fields that provide it, and the distribution's own test holds
the companion's roles table to it. The MCW requirements and companion cite CW
requirements in prose by id. `market-change-workflow` stays here as this repository's
capability.

This repository keeps no test of its configuration or wiring of the workflow: (iii)
deletes `test_change_workflow_assumptions.py` and `test_market_change_workflow.py`.
What they proved goes as follows:

- that the skills name no adopting repository's make target or path: the workflow
  repository's to verify, in a test it rewrites as its skills move from make targets
  to calling its command (CW-n8tr);
- that the fragment's targets and paths are provided, which follows the same move;
- that each role has a provision in this repository's statement: no test verifies it
  once (iii) lands, by choice. The workflow's own test holds its companion's roles
  table to `roles`, which keeps the workflow consistent with itself but reads no
  adopter's statement (58 F2). Review holds the statement complete when a change edits
  `[workflow] version`, `.agents/workflow.toml`, the statement, or a make target it
  names; a provision broken between those shows when the step running it fails;
- what `.agents/workflow.toml` and its template hold, which the engine checks
  whenever it reads them and which a change in the file's structure must not hold up
  a change here behind.

MCW-5tgp keeps what this repository declares and states, without a test reading
`config --json`. The released companion's "What an adopting repository provides"
still says a test fails when a role has no provision in the adopter's statement,
describing the test (iii) deletes; the request that the workflow's repository reword
it as a check an adopter may keep goes to it with the rewritten skills test through
the coordinator, delivered by the orchestrator before (iii)'s gate-and-switch section
and recorded in the change's log: the handbook's procedure for the move, which
carried D24's `force-include` condition and D5's test, was lifted with the first
release before these requests were settled, and its copy here leaves in (iii).
Checking a candidate release against its adopters stays an open question.

Rejected: parsing the installed companion's table, which makes its layout an
interface by accident; keeping both files in a target of their own outside `make
test`, run before each commit, which keeps tests to update whenever the workflow's
configuration changes; skipping them where no workflow is installed, a deliberate skip
in CI; running them against a stand-in command, which checks a snapshot; and keeping
only the roles and fragment completeness as a check, which keeps a test of the
workflow's surface in this repository.

### D15 — The make fragment's installed path

`change-workflow fragment` prints the path of the installed `workflow.mk`, and an
adopting `Makefile` includes it from there. The fragment's default is
`CHANGE_WORKFLOW ?= change-workflow`; it stays outside the compatibility promise, and
`fragment` is public. This repository includes the in-tree fragment through (i) and
switches in (iii) to including the installed one only when `change-workflow` is on
the path: without it every target of this repository's own works, and the workflow's
targets do not exist, so asking for one gets make's own "no rule" error. Nothing is
printed at each parse, so CI's logs carry no note (D26); `AGENTS.md` says to install
the workflow to drive a change.

Rejected: a copy of the fragment in each repository, which goes stale; each adopter
writing its own targets, which lets the steps' targets diverge; an unconditional
include, which fails every `make` on a machine without the workflow; and a note at
each parse when the command is missing, printed in every CI job.

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
guidance check (D10). Its own CI validates the workflow, what this repository's
deleted tests proved among it (D14), and this repository's CI does not install it
(D26). Validating a release against adopters before publishing is deferred (Open
Questions).

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

The six open workflow changes moved to the workflow's repository with the first
release. (iii)'s gate-and-switch section, with the workflow's copy, deletes their
directories under `openspec/changes/`, their rows, the lesser goal's gap rows they
own, and the two unowned rows this change found about the workflow's own engine and
specification, once the gate records that the coordinator carried those two (D2).
`host-change-workflow-runner`'s dependency on this change goes with its row.

At (iii)'s closeout, with nothing in it left open — this change closes the gaps of
the distribution and of the diagrams — the lesser goal is retired: its current state
says this repository adopts the workflow, as `arkhai-change-workflow`, within its
declared range, and that the goal's open changes and gaps moved to the workflow's
repository in 2026-11; its entry leaves the goal index, and its archived rows join
"Archived and superseded", so each change still appears once.

Rejected: a note on each moved change's row, which leaves the same changes in two
repositories to be worked in either; their removal on `dev` by the orchestrator now,
a second pull request outside this change's review; keeping the goal with archived
rows only, a campaign with nothing open among the active ones; and leaving the
section as it is, whose current state this repository no longer holds.

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
coordinator's evidence: the gate section; the installed release; the in-tree copy
removed, with the two tests of this repository's adoption (D14), the six moved
changes and their rows (D19), CI's install of the workflow, and the fragment's
round-view prerequisite of this repository's targets (D26); this repository's
workflow citations rewritten; `market-change-workflow`, its delta applied by hand
(D23), and `AGENTS.md`; and, at closeout, the lesser goal retired. Round 1 is
expected to take three sessions (the engine and installer; the skills and the
configuration split; the checks, documents, and this repository's installed
operation) and round 2 two (the gate and switch, with everything the switch removes
and the `Makefile`'s and CI's operation without the workflow; the citation rewrite
and `market-change-workflow`); planning maps them onto sections. Then closeout, which
archives with `--skip-specs` (D23).

The install target, the skills' switch to `change-workflow`, and the removal of the
workflow's project skill links sit in one section, since this change's later sessions
run whatever is installed from the tree, and a developer reinstalls after each engine
edit.

### D23 — The `change-workflow` delta reaches the permanent specification in (i)

(i)'s last section applies this change's `change-workflow` delta to its
permanent `spec.md` under `openspec/specs/change-workflow/`, and writes its `index.md` entries as
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

### D26 — This repository builds, tests, and releases without the workflow

The workflow is how this repository is changed, not part of how it is validated:
once (iii) lands, a machine without `change-workflow` builds, tests, and releases it.

- **CI.** `tests.yml` installs no workflow. (iii) removes its step installing the
  workflow from the tree, the bubblewrap step and `SANDBOX_REQUIRED`, which only the
  workflow's sandbox tests needed, and their assertions in `test_tests_workflow.py`.
  No suite `make test` runs needs the workflow; the two that did are deleted (D14).
- **The `Makefile`.** It includes the fragment only when the command is on the path
  (D15). This repository's own targets that refuse while a round view is open today —
  `validate-local`, `validate-ci`, `validate-helm`, `run-ci`, `run-e2e`,
  `review-diff`, and `last-diff` — lose that guard, the fragment's
  `round-view-closed`, and refuse nothing on its account. Their help text, and
  `market-change-workflow`'s companion, ask the developer not to run them while a
  round view is open, when the branch points at the round's base rather than its
  commit. `code-snapshot` loses the guard too, and needs no such caution: a snapshot
  is made from any worktree.
- **Its scripts.** The citation check's unscoped run, `make check-doc-citations`
  with no change, and the release targets call no `change-workflow`; the scripts the
  workflow's steps run — `check_change.py` as the `pre-commit` hook, the citation
  check scoped to a change, local and parallel validation — reach the installed
  command on the path.

The guard is dropped rather than replaced (58 F1). No public interface of the
workflow's tells a tool-free check that a view is open: its round-view state is
internal, so reading the marker file would pass silently once a release renamed it.

Rejected: installing the release in CI, which makes the product's validation depend
on a tool it does not use; keeping the fragment's `round-view-closed` prerequisite
unconditionally, which leaves this repository's own targets unusable without the
workflow; reading the engine's round-view marker from Git's metadata, internal state
a compatible release may rename; asking the workflow's repository to publish an
open-view signal before (iii), which holds this change behind another release; and
taking `round-view-closed` as a prerequisite only where the fragment is included,
which the owner judged not worth its machinery beside an instruction; and guarding
`code-snapshot` by any means, which refuses a snapshot of a worktree in use.

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
- This repository is releasable from a machine without the workflow: the workflow is
  how it is changed, not part of its validation (D26).
- The workflow's repository verifies what adopting the workflow requires of every
  adopter; this repository keeps no test of its configuration or wiring of the
  workflow, and review holds its own statement of the roles complete (D14).
- This repository names the workflow only as its distribution,
  `arkhai-change-workflow`, as it names any tool it installs (D2, D6, D9).

## Open Questions

- **A public distribution channel.** Releases go to the release page of the
  workflow's repository and to the dev artifact repository, each named by
  distribution, version, and digest, and this repository installs from the release
  page (D2). Revisit at the first public adopter: a public index serves the public
  case with no change to the artifact.
- **Validating a release against adopters before publishing.** The first release is
  validated by (iii)'s own validation. Revisit at a second adopter, or when a
  published release breaks one: the workflow's release process then checks each known
  adopter's configuration against the candidate.

## Implementation record

Rationale from the implementation, kept here when closeout compressed the task notes:

- **The temporary wheel's form (section 1, D24).** Hatchling's `only-include` and
  `sources` refuse a path outside the project directory ("must be relative"), so the
  wheel took `bypass-selection = true` with a `force-include` table: the reason D24's
  table had that shape.
- **Only an installed engine checks the installed skills (section 3, 30 F3).** The
  engine run from its source tree had the tree's sources for skills, which nothing
  stamps; checking there would have refused every command in a checkout, and every
  in-process test, until the owner installed. The triage amended CW-1rhd and CW-d8de
  to say "of an installed engine", and CW-sv3u to treat an empty local file, the
  sandbox's form of an absent protected file, as absent.
- **The tool environment's root left unprotected (section 3, D13).** Protecting it,
  against a `.pth` file or a replaced entry script beside the protected package, was
  declined because it would also protect a shared environment the engine is installed
  into; it is recorded instead as a current limit of `change-workflow`'s companion.
- **The install target during the pause (section 4).** It reinstalled with
  `--reinstall`, since an edit of the engine or a skill keeps the version and uv would
  otherwise keep the build it had; calling `$(CHANGE_WORKFLOW) install` in its recipe
  was declined, since it would run the command just installed whatever
  `CHANGE_WORKFLOW` names. The target left with the in-tree engine.
- **The CI observation of skipped tests (section 4, 44 F1).** The owed observation "no
  sandbox test skipped" had been inferred from a `-q` summary that names no skip, and
  was false: the Codex sandbox test skips on a runner with no Codex. `-rfEs` was chosen
  over `-rs` because `-r` replaces pytest's default `fE`, whose failure lines the CI
  evidence reads.
- **What `check config` reads (section 5).** It reads the engineering sections the
  workflow's own guidance cites as well as those the shipped skills cite, beyond
  CW-7x0z's letter, since that guidance ships with the skills and cites them in the
  same form; no review raised it.
- **The orchestrating skill's citations (section 5).** It cites its own routing
  sections rather than the engine's next-step module for the computation's result,
  because no requirement words the result's shape, and making that shape a public
  interface would need a requirement of its own.
- **The diagrams' redraw (section 8, D20).** The step's sandbox had no draw.io, so the
  redrawn diagrams were emitted, source and SVG, from one layout by a script kept
  outside the repository, their edges fixed points rather than connections; a later
  redraw edits the `.drawio` source in draw.io and exports its SVG.

## Design promotion record

The `change-workflow` capability, its handbook, and its guidance left this repository
with the workflow, so their destinations are in the released `arkhai-change-workflow`
0.1.0, which carried them from this tree (sections 7 and 8, D23); they are named here
by section and requirement id, with no link, as this repository cites the workflow
(D6).

| Accepted decision | Permanent location |
|---|---|
| D1 One change in two halves | `arkhai-change-workflow`'s companion, "The public surface"; the staging itself is this change's history |
| D2 The gate between the halves | No permanent destination: the gate governed this change's own pause, recorded in 9.2's note |
| D3 Engineering guidance through a pointer | `arkhai-change-workflow`'s companion, "The repository's guidance is layered"; CW-hu0z |
| D4 The pointer's form, citations by section name | `arkhai-change-workflow`'s companion, "A repository's configuration" and "Interfaces are tiered"; CW-hu0z, CW-7x0z, CW-d2rw, CW-n8tr; this repository's unique engineering headings (section 5) |
| D5 Committed configuration and one local file | `arkhai-change-workflow`'s companion, "A repository's configuration"; CW-4pm4, CW-f3qk; here, `MCW-iqh1` (`openspec/specs/market-change-workflow/spec.md#requirement-mcw-iqh1-this-repositorys-local-configuration-template-points-at-its-engineering-guidance`) and `.agents/workflow.local.template.toml` (`.agents/workflow.local.template.toml`) |
| D6 The workflow's documents ship with the engine; this repository cites them in prose | `arkhai-change-workflow`'s companion, "Leaf skills from one source" and "A repository's configuration"; CW-lm42, CW-l7hn, CW-n8tr; here, `MCW-9k0c` (`openspec/specs/market-change-workflow/spec.md#requirement-mcw-9k0c-this-repository-runs-the-installed-workflow-within-its-declared-range`), `market-change-workflow`'s companion (`openspec/specs/market-change-workflow/README.md#this-repository-is-the-workflows-first-adopter`), and `AGENTS.md`, "The change workflow" (`AGENTS.md#the-change-workflow`) |
| D7 One installed version per machine, checked against each repository's range | `arkhai-change-workflow`'s companion, "The public surface", and its handbook; CW-f8yy; here, `ARCHITECTURE.md`, "The change workflow" (`docs/development/ARCHITECTURE.md#the-change-workflow`) |
| D8 A wheel, an installer, the command on the path | `arkhai-change-workflow`'s companion, "The command and its tiers" and "Its parts"; CW-5kl9, CW-1rhd, CW-sv3u, CW-r3ka; its handbook, "Installing the workflow" |
| D9 Names and licence | `arkhai-change-workflow`'s companion, "The command and its tiers"; the licence is the workflow repository's; here, `ARCHITECTURE.md`, "The change workflow" (`docs/development/ARCHITECTURE.md#the-change-workflow`) names it only as its distribution |
| D10 Two more default checks | `arkhai-change-workflow`'s companion, "A repository's configuration"; CW-368t, CW-c8lw; here, `market-change-workflow`'s companion, "What each check enforces" (`openspec/specs/market-change-workflow/README.md#what-each-check-enforces`) and `openspec/README.md`, "The index check" (`openspec/README.md#the-index-check`) |
| D11 The version range | `arkhai-change-workflow`'s companion, "A repository's configuration"; CW-f8yy; here, `.agents/workflow.toml`'s `[workflow] version` and `MCW-9k0c` (`openspec/specs/market-change-workflow/spec.md#requirement-mcw-9k0c-this-repository-runs-the-installed-workflow-within-its-declared-range`) |
| D12 Each log line records the workflow version | `arkhai-change-workflow`'s companion, "A change's records carry one format version"; CW-d867 |
| D13 What is installed is protected | `arkhai-change-workflow`'s companion, "Restrictions bind unattended runs only" and "Current limits"; CW-r6kd |
| D14 How `market-change-workflow` cites the workflow, and who verifies its adoption | `arkhai-change-workflow`'s companion, "What an adopting repository provides"; CW-ora1; here, `MCW-5tgp` (`openspec/specs/market-change-workflow/spec.md#requirement-mcw-5tgp-this-repository-provides-the-workflows-roles`), `market-change-workflow`'s companion, "How this repository provides the workflow's roles" (`openspec/specs/market-change-workflow/README.md#how-this-repository-provides-the-workflows-roles`), and the owner's principle in `ARCHITECTURE.md`, "The change workflow" (`docs/development/ARCHITECTURE.md#the-change-workflow`); the requests to the workflow's repository (its skills' test, and its companion's sentence on an adopter's test) delivered through the coordinator before section 9 (9.1, log seq 92) |
| D15 The make fragment's installed path | `arkhai-change-workflow`'s companion, "The command and its tiers"; CW-dvz5; here, the `Makefile`'s conditional include and its comment, and `MCW-w7nb` (`openspec/specs/market-change-workflow/spec.md#requirement-mcw-w7nb-this-repository-builds-tests-and-releases-without-the-workflow`) |
| D16 The history is lifted by path | `arkhai-change-workflow`'s handbook, "Moving the workflow to its own repository" (section 7) |
| D17 The workflow's repository works through the workflow | No permanent destination here: the workflow repository's own process is its bootstrap's |
| D18 In-flight changes cross at their merge of `dev` | `arkhai-change-workflow`'s handbook, "When an open change crosses to the installed workflow" |
| D19 The lesser goal's section after extraction | `openspec/changes/README.md`, "Retired lesser goal — Make the change workflow a tool any repository can adopt" (`openspec/changes/README.md#retired-lesser-goal--make-the-change-workflow-a-tool-any-repository-can-adopt`), under "Archived and superseded"; its open guidance-loading gap moved to "Unowned work with no campaign" |
| D20 The engine's diagrams redrawn | `arkhai-change-workflow`'s companion diagrams of the engine's parts and of a step run's life (section 8) |
| D21 What the skills check holds | CW-d8de; `arkhai-change-workflow`'s companion, "Leaf skills from one source" |
| D22 Implementation cadence | No permanent destination: the cadence was this change's plan |
| D23 The `change-workflow` delta reaches the permanent specification in (i) | No permanent destination: recorded in this plan and its archival with `--skip-specs` (11.12); the `change-workflow` delta was applied by hand in section 8 and left with the specification, and the `market-change-workflow` delta by hand in 10.2 |
| D24 A temporary exception for the workflow's wheel | No permanent destination: the exception row and `make check-project-layout`'s admission stood through the pause and left with the wheel (9.6); the condition that no `force-include` table remain went to the workflow's repository with the handbook's procedure for the move |
| D25 Unattended Claude Code runs load the installed skills, and stop without them | CW-d8de, its unattended stop and scenario; `arkhai-change-workflow`'s companion, "Restrictions bind unattended runs only" |
| D26 This repository builds, tests, and releases without the workflow | `MCW-w7nb` (`openspec/specs/market-change-workflow/spec.md#requirement-mcw-w7nb-this-repository-builds-tests-and-releases-without-the-workflow`); `market-change-workflow`'s companion, "This repository is the workflow's first adopter" (`openspec/specs/market-change-workflow/README.md#this-repository-is-the-workflows-first-adopter`); `ARCHITECTURE.md`, "The change workflow" (`docs/development/ARCHITECTURE.md#the-change-workflow`); the round-view caution in the `Makefile`'s help text of the seven validation and diff targets |
| The owner's principles (Principles above) | `ARCHITECTURE.md`, "The change workflow" (`docs/development/ARCHITECTURE.md#the-change-workflow`) for D7, D14, D26, and naming the workflow only as its distribution; `arkhai-change-workflow`'s companion for D3, D4, and D5 |
| `market-change-workflow`'s requirements | MCW-9k0c, MCW-iqh1, and MCW-w7nb added and MCW-5tgp and MCW-s4bx modified in its `spec.md` (`openspec/specs/market-change-workflow/spec.md`) by hand (10.2), indexed in its `index.md` (`openspec/specs/market-change-workflow/index.md`) |
| Roadmap currency | No roadmap goal holds the change workflow; `ROADMAP.md` (`docs/development/ROADMAP.md`) is unchanged |
| Campaign index currency | The lesser goal retired (D19); the two gap rows this change owned — the distribution and the diagrams' redraw — closed; this change's row moved with the goal's archived rows, `in closeout` until archive cleanup |
