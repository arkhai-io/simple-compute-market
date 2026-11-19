# Design: sandbox unattended workflow steps

Status: design settled 2026-11-19. Some decisions are expected to be reconsidered
when `extract-change-workflow-repository` moves the workflow out of this repository;
each stands until then.

## Context

- **The current model.** An unattended run uses Claude Code's `dontAsk` permission
  mode with only the project's settings loaded. Each step's allow and deny rules are
  its own plus `[common]`'s, in `.claude/change-steps.toml`, read by
  `scripts/change_workflow/steps.py`, which also holds each step's skill and
  `resume_from`. A call no rule allows is denied and recorded in the run's
  `permission_denials`; deny rules encode each skill's "never" lines. The contract is
  CW-qu42, CW-4yhk, CW-2lvd, CW-2h9t, CW-svng, CW-5rmh, CW-vdqj, CW-jqi7, CW-drf6,
  CW-tl5v, CW-56zq, CW-b5cf, CW-z5me and CW-zq4h in
  `openspec/specs/change-workflow/spec.md`; the rationale is its companion's
  "Restrictions bind unattended runs only".
- **Its cost.** The allowlist names this repository's commands in the forms sessions
  type them, so it cannot travel to another repository or harness. In
  `serve-running-rate-deals` 24 of 88 logged runs carry a denial or a grant.
- **The push.** Every writing step pushes in its session through
  `scripts/change-workflow push`, the guarded push (CW-59c7, CW-p7kq); `[common]`
  denies every other `git push`. The credential is ambient: `origin` is an SSH
  remote, and the owner's Git configuration names gh's credential helper.
- **Outcomes.** The wrapper already records an unattended run's outcome outside the
  session (`wrapper.py`); the log is an untracked file under the change's `reviews/`.
  Recording needs no credential.
- **Validation.** Since `add-skill-extension-points` the engine gathers every missing
  evidence kind before validation's session (CW-g6th); the session gathers a new
  attempt itself only for unreadable evidence, a lapsed waiver, or a remedied
  environmental failure. Implementation, triage and the merge run the suites and
  builds in their sessions, through `run pre-commit`.
- **Writes outside the checkout.** Archive cleanup's `history` writes into the
  owner's workspace; design's prerequisite worktree, `../<prerequisite>-proposal`,
  sits beside the checkout.
- **This machine.** Ubuntu 26.04.1 on WSL2, with `bwrap` installed, unprivileged user
  namespaces available, and no AppArmor restriction on them. Claude Code's Edit tool
  replaces a file by rename: a file's inode changes across an edit.

## Principles

The owner stated these in design; none was recorded before.

- **P1.** Restrictions on unattended steps guard against mistakes, not a malicious
  agent: they give the owner categorical guarantees about what a step can and cannot
  change on their machine.
- **P2.** Steps keep their ambient credentials — GitHub, GCP, kube; the workflow
  does not withhold them.
- **P3.** An orchestrator and its sessions may read every change's checkout and write
  only their own change.
- **P5.** The workflow's guarantees are enforced below the harness, at the OS or
  container level, so they hold on any harness.
- **P6.** Coupling to a harness lives only in that harness's adapter, which the owner
  may supply, so a harness the workflow has never heard of can be used.
- **P7.** One container will hold an orchestrator session and every session it
  starts; per-step confinement happens inside it, by the mechanism this change
  designs. `host-change-workflow-runner` designs the image, cuts orchestration over to
  it, and reworks any OS-level function if its OS differs.
- **P8.** What the sandbox does not cheaply prevent, the step's review catches.
- **P9.** No older reader is expected to meet newer records; compatibility is owed
  only by a newer reader to older lines.

(P4, a coordinator above the orchestrators for cross-repository work, is direction
recorded beside P3: no workflow writes into another repository's checkout.)

## Decisions

### D1 — The threat model: mistakes, with ambient credentials

The profiles guard against a step's mistakes, not against an agent working around
them (P1). Steps keep their ambient credentials (P2): the sandbox neither scrubs the
environment nor refuses the network. The guarantee is about what a step can write on
the owner's machine.

Rejected: withholding the push credential and the route to the Git host, with the
engine doing every remote operation (the agent's first recommendation) — the owner's
steps need GitHub, GCP and kube, and adversarial containment is not the aim;
containing every step in a container on a laptop — that is the runner's;
keeping the guarantee at the rule level — it cannot travel; deferring — it blocks
extraction and the adapters. A Docker socket, reachable by every writing step, is a
way out of any local sandbox; under P1 it is accepted.

### D2 — The push stays in the session, refused otherwise by a Git hook

Steps keep pushing through `scripts/change-workflow push`. Before each unattended
run the engine points the checkout's `core.hooksPath` at its own hook directory under
`.git/`, which the sandbox protects (D4, D5). Its pre-push hook refuses a push while
the unattended-run marker is set and the guarded push's marker is not; otherwise it
runs the repository's own hooks, so the owner's pushes are untouched. An adapter may
add its harness's command rules refusing `git push` and `--no-verify` (P6). The check
after the run (D6, check 6) is the backstop.

Rejected: the engine pushing at the run's edge — once the step holds the credential
it buys nothing, and loses the per-section pushes; a command rule alone —
harness-specific; detection alone — the mistake reaches the remote first. The hook
installed only in clones and refusing unconditionally was restated: it would refuse
the owner's own pushes wherever installed.

### D3 — Enforcement below the harness

The engine starts every unattended step's harness process inside an OS sandbox it
owns (P5), so the harness's file tools, shell and subagents are confined alike. One
Linux implementation sits behind the wrapper's existing launch seam; there is no
backend interface. Ubuntu, this machine's OS, is canonical (P7).

Rejected: mapping profiles onto each harness's own sandbox (the agent's first
recommendation) — the workflow would be opinionated about harnesses, and a harness's
sandbox confines only its shell; a container per run — the whole orchestrator will
run in one container (P7); a backend interface for a container backend later — under
P7 no second backend is anticipated, and extracting one later is a refactor with a
real case; deferring.

### D4 — bubblewrap

The engine launches `bwrap` with the root filesystem read-only, the step's writable
paths bound read-write over it, each protected path bound read-only over those, the
network shared, and `--die-with-parent`. A write to a protected file fails as a
read-only file system; replacing one by rename fails busy, so `git config
core.hooksPath …` cannot rewire D2's hook. A Unix socket on a read-only mount stays
connectable, so Docker needs no setting. A protected path absent at launch is
created first or left to the checks.

Rejected: Landlock — its rights only add up per tree, so `.git/config` cannot be
protected while Git creates its lock files in `.git/`, and D2 would rest on
detection; both mechanisms — two implementations; a separate Unix user — breaks P2.
On native Ubuntu 24.04 and later, AppArmor's restriction on unprivileged user
namespaces may need an allowance for `bwrap`; inside a container, the runner allows
it or reworks (P7).

### D5 — A scope per step, enforced by the sandbox

Each step writes only its scope, stopped rather than caught:

| Step | Writable |
|---|---|
| review | nothing |
| design, plan | `openspec/`, `.git/`; the repository adds `docs/`; design also each registered `../*-proposal` worktree (D5b) |
| implement, triage, merge, validate | the checkout |
| closeout | its inert paths and `.git/` |
| archive cleanup | `openspec/changes/`, `.git/` |

Every step but the review also writes a temporary directory, `~/.cache`, its
adapter's state paths, and the repository's additions (D12). Protected in every
scope: `.agents/workflow.toml`, `.git/config`, the engine's hook directory, and the
adapter's and the repository's protected paths. Reads are open everywhere (P3).

The change's log is not mount-protected: closeout's archive moves its directory. It
is guarded by D6. Archive cleanup's history copy becomes an engine action after its
session (CW-hak6), so no step writes the owner's workspace.

Rejected: two coarse profiles with each step's finer scope checked after the run
(the agent's recommendation) — the owner wants a step stopped; a narrower validation
— see D5c; one profile for every step — a review could write what it reviews.

### D5a — A file or pattern entry mounts its directory

A file or pattern entry in a step's scope — closeout's `**/README.md` and
`AGENTS.md` — mounts each match's directory writable. Tools replace files by rename,
so a single file cannot be bound writable. Where that exposes code beside a README,
or, for files at the root, the whole checkout, closeout's review sees any code edit
and it is handled there (P8).

Rejected: binding every other entry of such a directory read-only, with a check for
new files (the agent's recommendation) — complexity and a thousand mounts for what
the review already sees; the whole checkout for closeout with a check — the same
reach, less honest; moving README edits to implementation; staged writes the engine
applies.

### D5b — The engine creates a prerequisite's worktree

A design needing a prerequisite ends with a question naming it. On the owner's word
the orchestrating session runs `scripts/change-workflow propose <change>
<prerequisite>`, which creates `../<prerequisite>-proposal` on `propose-<prerequisite>`
from the remote's landing branch without tracking (tracking would write the
protected `.git/config`). The resumed design session's sandbox mounts every
worktree registered in its checkout's `.git/worktrees/` whose path matches
`../*-proposal`; design writes and checks the proposal there and ends blocked.
Creating a worktree is mechanical, so the engine does it.

Rejected: mounting the checkout's parent writable — design could write every
sibling clone (P3 grants reads only); a worktree inside `.git/`; staging the files
for the engine to place; leaving the worktree to the owner.

### D5c — Validation writes the checkout, and the check holds it

Validation's scope is the checkout, since a new attempt builds environments in
directories that do not exist at launch. That it changes nothing is held by D6's
check 2: `HEAD` and every tracked file unchanged.

Rejected: a narrow list — here it collapses to the checkout through the package
directories; moving new attempts out of the session through an outcome field —
prevention at the cost of the outcome contract and the skill's loop; read-only
validation.

### D6 — Six checks after every run; a violation stops it

After every unattended session, whatever its outcome, before any action or hook
after it, the wrapper checks against the state it recorded at the start:

1. `HEAD` is on the change's branch and descends from the start commit;
2. for validation and review, `HEAD` and every tracked file are unchanged;
3. the workflow log was only appended to (a review runs beside a validation and
   appends its line meanwhile);
4. each existing review record is unchanged, and the ledger only grew at its end;
5. `refs/stash` is unchanged;
6. the remote's change branch is the last guarded push or unchanged, and no
   protected branch on the remote gained a commit made in the run (one fetch).

A violation logs the run `stopped`, its reason and an `invariants` field naming each,
the step's message kept ahead, as `triage_outcome` and `landed_outcome` do; the
after-hooks do not run; nothing is repaired. The configuration needs no check: it is
mounted read-only.

Rejected: fewer checks — 4 and 5 would rest on a review's luck, and 6 is the one
backstop for a push to a protected branch; recording a violation beside a standing
outcome — a rewritten history would route as if nothing happened; a question — a
resumed session rarely helps. Check 3 as byte-identical was restated: it would fire
on a parallel review's line.

### D7 — Refusals come from the run's events

The harness's adapter reads the run's event stream for writes the sandbox refused —
"Read-only file system", or "Device or resource busy" for a protected file — and the
wrapper records each on the line as `refusals`: tool, command or path, error. The
step's unattended instructions make it recognize such an error as outside its scope,
end stopped when it cannot go on, and say what it did instead when it can. `denials`
remains for harness rule denials, such as an adapter's `git push` rule. The
orchestrating session reads both from the record and classifies each: the step
reached beyond its job, a finding; or its scope is too narrow, a gap answered with
the narrowest path. The next-step computation treats a line with refusals as one
with denials (CW-jqi7).

Rejected: the step's own report alone — refusals would be read from messages; no
special handling — "a run that cannot go on says so" would no longer hold.

### D8 — A grant is a writable path for one run

`start` and `resume` take `--write <path>`, the make targets `WRITE=` (`;`-separated);
the line records `writes_granted`; nothing is kept. The engine refuses a path under a
protected path. `--allow` and `ALLOW=` go.

Rejected: no grants — a round could not be widened without moving `HEAD`; running a
step under another step's scope — broader than any gap. A new key rather than
reusing `granted` keeps a newer reader from mistaking an old line's rules for paths.

### D9 — Interactive runs stay unconfined

An interactive run is not launched in a sandbox, and its invariants are not checked:
the owner's settings and prompts apply, as the proposal's non-goal says, and P7 will
put every session inside the container anyway.

Rejected: checks at `record`; sandboxing make-target launches; an opt-in flag.

### D10 — Without the sandbox, a step runs unconfined and says so

Before launch the engine probes the sandbox. Where it cannot run — no `bwrap`, user
namespaces refused — the step runs unconfined, with a warning and `unconfined: true`
on its line, which the orchestrating session relays to the owner. The checks after
the session run either way. The sandbox guards against mistakes; it never gates the
workflow (P1).

Rejected: refusing to start, with an owner-only override (the agent's
recommendation) — the owner prefers the workflow never block on the sandbox;
refusing outright; falling back to the allowlist — two systems and the coupling P6
removes.

### D11 — Each step's definition lives in the engine

Each step's skill, `resume_from`, and baseline scope, in the workflow's own terms
only (CW-n8tr), live in the engine beside the graph, as the hook table does
(CW-u4pc). `.claude/change-steps.toml`, `steps.py`'s loader and the
`steps.STEP_TABLE` assumption are removed.

Rejected: a harness-neutral table under `.agents/` — a second configuration file
against CW-f3qk, and a repository could rename a step's skill; all of it in
`.agents/workflow.toml` — a repository could loosen a baseline.

### D12 — Repository extension in `[sandbox]`

Following `[load]` (CW-l7hn):

```toml
[sandbox]
writable.common = ["~/.local/share/uv", "~/.kube/cache", "~/.config/gcloud", "~/.docker"]
writable.design = ["docs/"]
writable.plan   = ["docs/"]
protected = []
```

Relative paths are from the checkout's root, `~` the home directory. The check
refuses a writable path under a protected one, `writable.review`, and an unknown step
(CW-w8ne). `config` and `config --json` list each step's resolved scope with each
path's source — engine, adapter, repository — so the orchestrating session can
propose the narrowest path for a gap (CW-o6kc).

### D13 — Internal adapters for Claude Code and Codex

Each harness gets an internal adapter module stating its unattended launch inside
the sandbox with its prompts off — Claude Code in `dontAsk` with every tool allowed,
its own sandbox off, which keeps its denial records meaningful for the extras — its
writable state (`~/.claude`, `~/.claude.json`; `~/.codex`), its protected paths
(`.claude/settings.json`, `~/.claude/settings.json`), its reading of refusals and
denials from its events, the steps it can run, and its optional command rules.
Codex keeps `--sandbox read-only` inside the engine's sandbox, dropping it if the
two cannot nest. CW-zq4h's harness clause becomes "only for steps its adapter can
run", so Codex stays review-only until `add-workflow-harness-adapters`, which makes
the interface public and owner-supplied (P6).

### D14 — No deny rules survive

History, branch and stash rules give way to checks 1 and 5; validation's relock and
commit to check 2; edits of `.claude/` and the configuration to the protected
mounts; `git push` to D2's hook and an adapter's rule; the write-steering rules
vanish. `tail -f` remains skill text: waiting through `wait` avoids a hang
(CW-b5cf). `round-view` and `round-done` refuse under the unattended marker
(CW-p3vz). `git clean`, `gh pr create`, `make run-e2e`, `validate-parallel`, `git
merge --abort` and `--quit`, `docker push` and `helm push` remain skill or guide text,
with the review as backstop (P8). The hook table stays as a mistake guard; a forged
marker is outside P1, and check 2 is what holds validation.

### D15 — The skills

Every skill's "Running unattended" denial paragraphs and the wrapper's `UNATTENDED`
prompt — one command per call, write-steering, "don't ask mode", never `git -C` or
`make -C`, no `..` after `cd` — become one harness-neutral paragraph: the step runs
in a sandbox scoped to it; a write refused as a read-only file system or busy is
outside its scope; stop naming the path if it cannot go on, else say what it did;
wait on background commands with `wait`. The three exemptions this change owns go:
implementation names project tests and bring-up by role, and a plan gives an edit
of the harness's settings to the orchestrator because no step writes them. Archive
cleanup stops running `history`; design's section 4 uses `propose`.

### D16 — The specification

`change-workflow` removes CW-2lvd, CW-2h9t and CW-56zq; renames and modifies CW-qu42,
CW-4yhk, CW-k5mk, CW-svng, CW-5rmh, CW-vdqj, CW-jqi7, CW-drf6, CW-b5cf and CW-hak6;
modifies CW-tl5v, CW-z5me, CW-zq4h, CW-dtpz and CW-o6kc; and adds CW-x3pf, CW-m8wq,
CW-r6kd, CW-h2zt, CW-v5ny, CW-j4cs, CW-q7ub, CW-f9le, CW-w3oa, CW-k8dn, CW-t6mb,
CW-g5ry and CW-p3vz. `market-change-workflow` modifies MCW-5tgp (the step table no
longer names targets) and adds MCW-s4bx (this repository's `[sandbox]`). The new
log fields — `invariants`, `refusals`, `writes_granted`, `unconfined` — are additive
and need no format version (P9, CW-x7jd). Both companions and indexes follow at
closeout.

### Implementation cadence

One round, three sessions, then closeout:

1. **The engine's sandbox.** Each step's definition in the engine replacing the step
   table; `[sandbox]` and its checks; scope resolution and its listing in `config`;
   the bubblewrap launcher with protected mounts, the probe, and the unconfined
   fallback.
2. **Adapters and wiring.** The Claude Code and Codex adapters (launch, state,
   protected paths, refusals, optional rules); the wrapper's and review's launch
   through them; grants as `--write`; refusals recorded and routed; the step table
   and `steps.py` removed; the skills' unattended paragraph and the three exemptions.
3. **The guarantees around it.** The six checks and the stopped outcome; the
   pre-push hook with its marker condition; `propose` and design's section 4; the
   history copy as an engine action and archive cleanup's skill; `round-view` and
   `round-done` refused under the marker; MCW-s4bx's declaration.

This change rewires the engine it runs on: after its round lands, its own triage and
closeout run under the new sandbox, the unconfined fallback limiting the risk.

## Open Questions

- **Native Ubuntu's AppArmor and `bwrap`.** Whether Ubuntu 24.04 and later admit
  `bwrap`'s user namespaces without an administrator's profile is verified in
  implementation on a native install; D10's fallback covers a refusal meanwhile.
  Revisit when the owner or a coworker runs unattended steps on native Ubuntu.
- **The read grant inside the runner's container.** P3 is met locally by open
  reads; `host-change-workflow-runner` mounts the parent of the checkouts read-only.
  Revisit in that change's design.
