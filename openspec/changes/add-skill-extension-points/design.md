# Design: add skill extension points

Status: design amended by the triage of its first design review (18 F1 to F5),
awaiting another design review.

## Context

- **What already varies per repository.** `add-workflow-capability-contract` moved
  what runs into `.agents/workflow.toml`: hooks, validation's parts and their
  cleanup, the documents each step loads. `layer-engineering-guidance` divided the
  closeout parts by layer: the workflow's ten in
  `docs/guidance/workflow/closeout.md`, which defines "The repository's own closeout
  parts" as a role whose section the root guidance names, and this repository's two
  in `openspec/README.md`.
- **What is left in the skills.** Instruction text about this repository's tooling,
  nearly all of it about one validation part: its evidence files, its diagnosis (the
  Helm part's memory classification, CI failure classes, warning steps), its record
  section (`## Local`, `## Helm`, `## Pipeline`, `## CI`), what its cleanup writes
  (`helm/validation-capacity.toml`), where scenarios are named (`e2e-tests/`
  markers), and which CI workflows may be owed (`scripts/ci_evidence.py`). It is
  spread over `change-validate`, `change-archive-cleanup`, `change-merge`,
  `change-plan`, `change-implement`, and `change-orchestrate`. Beside it, skills cite
  repository paths and targets where the workflow has a role:
  `openspec/README.md#this-repositorys-closeout-parts` in closeout, plan, and review;
  `make check-comment-hygiene` and `make check-tasks` in closeout; closeout's step 3
  restating this repository's two parts; `docs/development/ROADMAP.md` in design;
  `openspec/config.yaml` in plan; "`origin` in this repository" in merge. CW-m4ps's
  test admits all of it, provided this repository's statement of its roles lists
  each.
- **The contract the material restates.** This repository's validation behaviour is
  specified in `market-change-workflow` (MCW-qeja to MCW-7ts3, MCW-gvqb to MCW-3yqn)
  and explained in its companion; the skills restate it for the agent.
- **What validation does today.** The wrapper checks the guards, waits on the clone's
  bootstrap, and gives the session its target. The skill pushes, runs every part
  that is not waived through `run validation`, which runs the configured command,
  keeps a start's marker, closes each part, and records the invocation, then
  diagnoses, settles environmental failures with the owner, and writes the record,
  whose `Commit:` and `Result:` the guards read. Implementation, triage, and the merge
  run `pre-commit-functional` — here `make dist-clean`, `make check-packaging`, `make
  test` — before a functional commit, the same checks as the `local` part, keeping
  only each command's exit status and timing.
- **The skill check.** `scripts/change-workflow check skills`
  (`scripts/change_workflow/skills.py`), a public subcommand and one of `run
  pre-commit`'s default checks, holds each skill to one source.
- **What has been deployed.** The workflow has no release (`change-workflow`'s
  companion: "Nothing is versioned yet"), and this repository is its only adopter;
  the market's release record versions the market's packages, not the workflow. No
  deployed form of the workflow exists, so no migration path is owed; each changed
  public interface is declared in the proposal (CW-c2tw).

## Decisions

### D1 — An extension attaches to what it extends; the workflow knows evidence, not parts

The workflow and its engine know nothing of a repository's validation parts; they
know evidence. Validation completes the evidence a commit still lacks and assesses
all of it to choose the next step, reusing evidence an earlier step gathered rather
than running every part blindly. What a repository tells the agent attaches to what
it is about: an evidence kind's guide, beside that kind's configuration entry, and
closeout's own parts through their existing role in the root guidance.

Rejected: slots declared per skill and filled through an `[addenda]` table, whose
closed slot vocabulary is public surface, which splits one fact (the capacity
figure) across several slots, and which re-homes the closeout role just built;
shared concern names in an `[addenda]` table, a vocabulary parallel to the
configuration tied to what it describes only by convention; step-scoped guidance
through `load.<step>`, which states nothing about what such a document holds, fails
nothing when it is absent, and blurs guidance with instructions to a step; deferring
to `extract-change-workflow-repository`, which depends on this design.

### D2 — Evidence describes a tree, or a commit where its result depends on history

Evidence describes the Git tree it was gathered against: `git write-tree` of the
worktree as tested, its changes added to a temporary index that honours
`.gitignore`. It is reused for any commit with that tree, so the commit
implementation makes just after its functional checks has its `local` evidence
already. Where the engine computes the tree — through `{tree}` or its own gathering —
the identity is the engine's; evidence written otherwise names its tree on its
writer's word (D3). Inputs outside the tree — the machine's tools, the cluster's
state — are not captured, as validation does not control them today beyond its
preflight.

A kind whose result depends on the commit's history rather than its tree describes
the commit instead: a dispatched run whose head commit is the commit under
validation, or a comparison with a baseline chosen by the commit's ancestry, as
MCW-zk52, MCW-7hr1, and MCW-2lzw require here. Its pattern holds `{commit}`, which
the engine fills with `HEAD`'s full object name, where a tree-keyed kind's holds
`{tree}`; each pattern holds exactly one of them, so the identity is declared by the
pattern and needs no field of its own (18 F3). Such evidence is not reused across
two commits sharing a tree — a message amended, a revert, a squash — which costs
little, since nearly every new commit changes the tree; the reuse this decision is
for, implementation's `local` evidence, keys by tree.

The digest is only as stable as the worktree's untracked files: a workflow file Git
does not ignore would change the tree its own evidence documents. Every file a
change's validation, its gathering, or a step hook writes after implementation is
therefore ignored by Git (CW-g1gn); `.snapshot/*`, `.dist/`, and
`openspec/changes/**/reviews/` are ignored today, and the configuration's check
refuses an evidence pattern whose fixed directory Git does not ignore. Archive
cleanup's capacity figure, a tracked file, is written after the change's last
validation by archive cleanup and committed alone (CW-e1sg), changing a tree no
evidence needs to describe.

Rejected: a commit for every kind, under which implementation's evidence, gathered
before its commit exists, never counts; a tree for every kind, revising MCW-zk52,
MCW-7hr1, and MCW-2lzw, under which a reused run's head and its `dev` comparison may
describe another history; identity as a field of its own beside the pattern, which
the pattern already states; a tree ignoring inert paths, which removes the line
CW-j1ab draws before pre-closeout for documents a test checks for currency;
identity by each kind's declared inputs, deferred (Open Questions); no reuse.

### D3 — Evidence counts by its presence, whoever produced it

Evidence counts when it is present at its kind's pattern for the tree or commit
(D2), whoever wrote
it: a step's hook, the engine's gathering, an agent, or whatever placed it from
beyond the checkout. It is its producer's word; the workflow does not defend against
agents misleading each other, who have no incentive to. Evidence from beyond the
checkout — a run against a topology no checkout holds — is placed in the change's
evidence location by whatever holds it, a layer above the orchestrating session; the
workflow fetches nothing.

Rejected: reusing only what validation gathered, which leaves implementation's
evidence uncounted; reusing only what the engine ran, with the repository declaring
which hook yields which kind, a provenance rule protecting against nothing the
workflow defends; a per-kind `locate` command finding evidence outside the checkout,
which the layer above the orchestrating session already does.

### D4 — The engine reports presence; validation gathers what is missing and assesses everything

`scripts/change-workflow evidence <change> [--json]` lists, for `HEAD`'s tree or
commit as each kind's pattern keys it (D2), each required kind — an owed kind once
for each argument owed (D5) — its pattern, and what matches: present, missing,
waived with the decision's `seq`, or not required. When several files match one
kind and argument — a failed attempt and the rerun after an environmental diagnosis
— it lists them all and marks the last in path order as current; validation
assesses the current one and the record names its path. Writers name their attempts
so that path order is time order — this repository's scripts by a UTC timestamp
directory, as its guides say. Path order rather than modification time, which a copy
from beyond the checkout (D3) may carry from anywhere (18 F1). Validation gathers each missing kind and assesses
every kind's evidence from its guide: passed, failed (the commit or unknown), or
environmental. Present failing evidence is diagnosed, never gathered again for a pass
— only an environmental diagnosis and the owner's word rerun a kind, as today.
Unreadable evidence is gathered again, the record saying why. Evidence is never
gathered again only because another step wrote it or it is old. The record adds
`Tree:` and each kind's source, `present` or `gathered`; the guards keep reading
`Commit:` and `Result:`.

Rejected: the agent matching patterns itself, so each step re-derives presence;
a machine verdict read from a field each guide names, with validation skipped when
everything passes, which couples the engine to each repository's evidence format,
cannot tell environmental from commit-caused, and removes the assessment the guards
and triage read; running every part, as today.

### D5 — A kind is required always or when owed

Each kind's configuration says `required = "always"` or `"owed"`. An owed kind is
required once for each argument a complete section's owed line names, which now
names its kind: `Owed by validation (ci tests.yml): job … — …`. A line naming no
kind reads as the one owed kind, so plans already written read as before, and is
refused where more than one kind is owed. Evidence is present for each argument on
its own: an owed kind's pattern holds `{owed}`, so a `tests.yml` result never makes
`docker.yml` present, and an owed argument is a single path segment holding no glob
character, the owed line refused otherwise, naming its section (18 F1). Waivers are
unchanged, naming kinds where they named parts. Present evidence of a kind not required is listed `not required`
and not assessed. Here `local`, `helm`, and `pipeline` are `always` and `ci` is
`owed`.

Rejected: owing limited to the one CI-shaped kind, leaving another repository's
optional pipeline to a waiver per change; conditions on the paths a change touches,
deferred with D2's declared inputs (Open Questions); conditions in a guide's prose,
which the engine cannot report; a manifest binding each matched file to its owed
argument, a format and a parser for layouts no adopter has asked for.

### D6 — The configuration is the engine's injection, the guide the skill's

A repository injects into the workflow two ways. Its configuration holds every value
the engine reads — what it runs, computes, orders, copies, or checks — and its guides
hold what an agent is told; a value both need lives in the configuration, and a skill
learns it from the engine's structured output, never from the file (CW-d1nj). A guide
restates nothing the configuration holds (CW-g2rs).

So an evidence kind's engine fields stay in `.agents/workflow.toml` and its guide is
prose only:

```toml
[validation]
preflight = ["make check-uv-version"]

[validation.evidence.helm]
required = "always"
evidence = ".snapshot/evidence/{tree}/helm/*/summary.json"
after    = "local"
run      = "make validate-helm CHANGE={change} TREE={tree}"
cleanup  = ["make record-capacity CHANGE={change}", "make -C helm teardown CHANGE={change}"]
guide    = ".agents/evidence/helm.md"
```

`after` stays optional; `guide` is required of every kind, since validation assesses
each kind's evidence from its guide and a kind without one leaves it nothing to
judge by (18 F4). Guides live under `.agents/evidence/`, beside the skills they
extend: they are extensions to steps, not guidance, carry no layer tag, and are not
loaded by `load.common`; after extraction `.agents/` stays the repository's. A part
becomes an *evidence kind* — plain "kind" is the review kind's — and the record's
`Parts:` line becomes `Evidence:`, skills reading either. One file still states every
command (CW-f3qk), and no step edits it (CW-z5me).

Rejected: the guide as the whole declaration, TOML frontmatter holding the engine's
fields above the prose, which puts what the engine reads in the skill's injection;
frontmatter holding only identity and requirement, the agent running commands
written in prose, which gives up the engine's recording, markers, and hook table; an
optional guide with a generic result format and a fallback assessment, a shared
format every writer would produce, bringing back the machine verdict D4 rejects.

### D7 — The engine acts around steps, and a repository hooks each one

Deterministic work belongs to the engine, freeform judgement to the skill. The engine
holds, beside `HOOK_STEPS`, a table of actions before and after each step, with two
built in:

- **Before `validate`:** gather (CW-g6th). Run the preflight, push `HEAD` through
  the guarded push, start every missing `start` kind, run the missing `run` kinds in
  order keeping each `after`, then collect each started kind, keeping evidence and
  closing lines as today. A waived kind is skipped unless a merge since it last ran
  lapses the waiver, which is mechanical; whether a waiver's condition still holds
  is the skill's judgement, which gathers a lapsed kind with `gather --kind <kind>
  --lapsed`. The wait leaves the agent's session.
- **Before `archive-cleanup`:** run every kind's cleanup (CW-ikmm); the skill commits
  a tracked file a cleanup wrote.

A repository hooks each step with `before-<step>` and `after-<step>` (CW-h3ks), for
the nine steps a run is logged as — design, review, triage, plan, implement,
validate, merge, closeout, archive-cleanup — a review's or triage's receiving
`{kind}`. They are the repository's dependency injection onto the workflow. The
built-in action runs first, then the hook. `merge` and `late-merge` run one step and
share its hooks.

A failure before a step informs that step and gates nothing, as a failing test must
reach the triage that fixes it (CW-b7fl): a failing `before-` hook or gathering
starts the session with the failure in its inputs, and the skill says what it means
— validation diagnoses it, implementation whose environment refresh failed stops and
asks. A hook the configuration's check refuses refuses the step.

A failing `after-` hook goes back to the step that can fix it (CW-a4fl). After-hooks
run only after a `finished` outcome, before the outcome is logged as final; on
failure the wrapper resumes the same session once with the failure, and a second
failure ends the run as a question to the owner naming the hook, so routing reads
one outcome. Validation, which cannot act on a failure, explains it in the resumed
turn and the run ends as that question. Interactively the skill runs
`scripts/change-workflow run before|after <step> <change>` itself.

A review runs through its own runner, `review.py`, not the wrapper, and its reviewer
is read-only, so the runner holds the review's hooks (18 F5). It runs `before-review`
before it starts the reviewer, giving the reviewer the run's inputs directory to
read, which is all a read-only reviewer needs: a coordinator, say, hands it what it
knows of another repository there. It runs `after-review` once it has published the
record and before it logs the outcome as final, so a hook may read the record. A
failing `after-review` resumes no reviewer — a resumed reviewer's final message
would be taken for another review, and it can fix nothing — but ends the run as a
question to the owner naming the hook, the published record standing and never
published again. An interactive review is no run: it logs nothing and has no inputs
directory, so it runs no hooks, and says so.

A run's inputs reach its session through a directory under the change's records,
`reviews/runs/<run>/before/` and `…/after/`, given to hooks as `{inputs}` and named
on the run's log line (CW-i9np). The engine writes `status.md` — each hook's or
action's closing line, exit status, and log path — and keeps each hook's printed
output as a log, read only to diagnose a failure. Every top-level Markdown file a hook
writes is a message the skill reads in full as it loads; any other file is data, read
where a message directs, so a large artifact never passes through an argument or the
prompt. The gathering's `status.md` says what was found present or gathered and each
kind's result; the evidence stays at its patterns. The directory is ignored by Git
(D2) and copied by `history`.

Rejected: built-in actions only, with repository hooks a change of their own, since
they are the repository's injection and every repository is expected to fill them;
gathering as a repository's `before-validate` hook, which rewrites in every adopter
what the engine holds; keying hooks by node (twenty a side) or by the name a
target's `step` carries (twelve), deferred to their own change (Open Questions); a
failing `before-` hook stopping the session; a failing `after-` hook carried forward
to the next session, which may not be able to fix it, or brought straight to the
owner or the orchestrating session, which takes no position on the work (CW-yvo1);
the hook's printed output as its message, which makes build noise instructions;
reading every file in the directory, which loads accidental and large files whole;
review excluded from step hooks, which loses the hook that hands a reviewer what a
coordinator knows; resuming the reviewer after a failing `after-review`, which risks
a second published review.

### D8 — Hooks have no defaults

An absent or empty hook runs nothing, and the orchestrating session says in one
sentence that it ran the step without it. The engine does not probe for a make
target: a declared command whose target is missing fails like any command, so a typo
fails loudly. The engine assumes no build tool. The make fragment the workflow ships
documents each hook as a commented target, so adopters meet them where they look.

Rejected: every hook defaulting to a make target the repository must implement or
empty, which starts each adopter with failing hooks and adds `make` to the engine's
assumptions; the same with a missing target probed and skipped, which turns a typo
silent.

### D9 — The base skills name no repository's targets or paths

Every repository path and target in a skill with a role in the workflow is replaced
by that role, by the engine's command, or by a guide: closeout's own parts "in the
section the root guidance names"; "the repository's comment check"; `scripts/
change-workflow check tasks`; the roadmap through `load.design`; closeout's step 3
naming the repository's own parts without restating them; merge's example remote
dropped; triage's worked example rewritten neutrally. Implementation's command forms
the step table's allowlist matches stay, as an exemption owned by
`sandbox-unattended-workflow-steps` and required to go with the allowlist. The
workflow's own paths and targets stay: its guidance, OpenSpec's tree, the change
index, the make fragment's targets, the engine's command. CW-m4ps's test is inverted
for skills (CW-n8tr): a target or path a skill names is the workflow's own or
exempted, or the test fails naming the skill; this repository's statement of its
roles remains for the step table and the make fragment. How a skill cites the
workflow's guidance once it lives outside an adopter's tree is extraction's.

Rejected: only the instruction blocks, leaving extraction an unheld list; neutrality
held by review alone, which let these citations accumulate.

### D10 — The workflow does not defend its obligations against its own repository

A guide or a hook's message is for telling a step about the repository, adding to or
narrowing what the skill says. Nothing enforces that: injected text can always steer
a model, and whoever controls the repository controls the files that would enforce
it — a hook could replace a skill outright. A skill that notices a guide or message
contradicting its own text says so in its report and follows its own text
(CW-c5nt), to surface accidental contradiction such as a guide left stale.

Rejected: removal by a declared deviation keyed by requirement id, ceremony around an
honour system; add-or-narrow with no removal, enforced by nothing; deviations as
rows of the repository's guidance.

### D11 — The check holds structure

The configuration's check (CW-w8ne), run by every reader, refuses, naming the field:
a key or type under `[validation.evidence.<kind>]` it does not define; `required`
outside `always` and `owed`; a kind with neither or both of `run` and `start` with
`collect`; an `after` naming no other kind declared before it, or a started kind's
`after` naming a `run` kind — the shapes the gathering's order, every start before
any run and the runs in declaration order, could not keep, which also rules out
every cycle, as today's check does (18 F2); an `evidence` pattern holding neither or
both of `{tree}` and `{commit}`, or whose fixed directory Git does not ignore; an
owed kind's pattern without `{owed}`, and `{owed}` outside an owed kind; a kind
without a `guide`, or whose guide does not exist or is empty, failing closed as a
`load` directory entry does (18 F4); a hook key other than `before-` or `after-` a
step in `graph.STEPS`; `{kind}` outside review and triage hooks, `{inputs}` outside
step hooks, `{tree}` and `{commit}` outside a kind's commands and pattern and the
functional hooks. A guide restating the configuration is held by review. `check skills` is unchanged; the
inverted test of D9 is the workflow's own.

Rejected: a separate `check guides`, since the configuration is the one place a guide
is named.

### D12 — Reviews read what the reviewed step was given

A review reads the evidence guides wherever it reads a validation record — the
implementation, pre-closeout, and merge reviews — and the inputs directories of the
runs whose work it reviews, found from their log lines; its own `before-review`
messages it reads as any step does. This follows CW-r8cg: a reviewer judging a
validation reads the guide that told the step how to read its evidence.

### D13 — The orchestrating session

The orchestrating session is no step: it has no guide and no hook. It says "a value
of the owner's machine reaches a command through the environment" for
`HELM_ALL_SCENARIOS` (CW-v2dq), writes its waiver example with kinds in general,
reports each skipped hook in one sentence, and relays a second after-hook failure's
question without judging it (CW-yvo1).

### D14 — End-to-end scenarios stay the workflow's

CW-av28 and the plan's `End-to-end:` line stay the workflow's; a repository may say
no scenario exercises a change. Where this repository names scenarios — pytest
markers under `e2e-tests/` — is the pipeline guide's; planning and implementation
name them as the guide of the kind that runs them says. The `tests.yml` and
`azure/setup-helm` example of an owed line moves to the CI guide.

### D15 — The public interfaces changed

Declared in the proposal's "Public interfaces"; none is migrated, the workflow having
no release.

### D16 — This repository's first guides and hooks

`.agents/workflow.toml` declares four kinds — `local` (`always`, `run`), `helm`
(`always`, `run`, after `local`, with the capacity and teardown cleanup), `pipeline`
(`always`, `start` and `collect`), `ci` (`owed`, `start` and `collect`) — `local` and
`helm` with their patterns under `.snapshot/evidence/{tree}/<kind>/`, `pipeline` and
`ci` under `.snapshot/evidence/{commit}/<kind>/` (D2), `ci`'s holding `{owed}` (D5),
each attempt in a UTC timestamp directory, and each kind with its guide under
`.agents/evidence/`, which hold what leaves the skills. The preflight stays. This
repository's validation scripts take the tree and write there, and
`pre-commit-functional` leaves `local` evidence for the tree it tested. No step hook
is declared at first. Closeout's own parts stay in `openspec/README.md`.
`market-change-workflow`'s MCW-r4tx and MCW-5tgp are restated for kinds, and its
validation requirements say "kind" where they named a part.

### D17 — Implementation cadence

One round before its review, so the change keeps moving while the owner is away. The
change alters the tool validating it, so its work goes in this order, each session
leaving the workflow runnable on its own branch: the evidence model — the
configuration's kinds and their check, the tree and the commit, `evidence` and
`gather`, the
record's fields, owed lines naming their kind, `history` by evidence paths, this
repository's configuration and scripts, and `change-validate` and
`change-orchestrate` moved to the new commands; then the actions around steps — the
wrapper's table, the built-in gathering and cleanup, the hooks, the review runner's
hooks, the inputs directory, `run before|after`, the resumption after a failing
after-hook; then the neutral
skills — the four guides, every skill per D9 and D12 to D14 with D10's notice, and
the inverted test.

Rejected: three rounds with a review after each, which would halt for the owner's
reading between them; the neutral skills first, before the guides' final form
exists.

## Open Questions

- **Evidence identity and requirement by declared inputs.** A kind might declare the
  paths it depends on, its evidence identified by their digest and its requirement
  conditioned on a change touching them, so a commit touching only `scripts/` reuses
  the Helm evidence or needs none. A missing declaration would then reuse stale
  evidence or skip a kind silently. Revisit when `test-affected-suite-selection`
  lands, whose mapping from paths to suites carries a check on undeclared reads.
- **Hooks for every node.** Hooks keyed by node — each review and triage kind,
  `late-merge`, `round-view`, `done` — would let a repository act at a node rather
  than a step. Revisit with the first caller needing one; it is an unowned gap of the
  lesser goal.
