# Design: sandbox unattended workflow steps

Status: design settled 2026-11-19; revised the same day on the triage of design
review 19 (D2, D4, D5, D5a, D6, D8, D10, D13) and of design review 28 (D2, D4, D6,
D7, D8, D12, the cadence); revised again the same day on a return from
implementation, when the sandbox's identity mapping failed the bare-metal ledger
suite (D17–D21; D1, D4, D5, D6, D8, D12 and the cadence restated); revised on the
triage of design review 48 (D6, D13, D19, the cadence); revised on the triage of the
implementation round on 2026-11-20, its review 62, the orchestrator's records 58 and
64, and the sections' handoffs (D2, D4, D5, D5a, D6, D7, D8, D12, D13, D15, D21). Some
decisions are expected to be
reconsidered when `extract-change-workflow-repository` moves the workflow out of this
repository; each stands until then.

## Context

- **The current model.** An unattended run uses Claude Code's `dontAsk` permission
  mode with only the project's settings loaded. Each step's allow and deny rules are
  its own plus `[common]`'s, in `.claude/change-steps.toml`, read by the engine's
  `steps` module, which also holds each step's skill and
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
  replaces a file by rename: a file's inode changes across an edit. The host's `/tmp`
  is a tmpfs.
- **The identity mapping.** Unprivileged bubblewrap's user namespace maps only the
  owner's uid. Every other uid, root's included, shows inside it as the kernel's
  overflow uid, 65534, and no unprivileged tool can map host root. The host's `/tmp`
  shows as `65534`, mode `1777`, so a check trusting only root-owned or the caller's
  ancestors refuses it: the bare-metal working-data helper's (`directory()` in
  `domains/bare_metal/provisioning/iac/ansible/roles/bare-metal-access/files/tenant_working_data.py`)
  failed every ledger test inside a step, and `validate-local` with it, which
  returned this change from implementation (D17).
- **Clones' settings.** `make change-clone` links each clone's
  `.claude/settings.local.json` to the workspace's by an absolute symlink, and
  bubblewrap cannot mount over a symlink (D20).

## Principles

The owner stated these in design; none was recorded before.

- **P1.** Restrictions on unattended steps guard against mistakes, not a malicious
  agent: they give the owner categorical guarantees about what a step can and cannot
  change on their machine, for every run the sandbox confines (D10).
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
environment nor refuses the network. Its one change to the environment is `TMPDIR`,
set to the sandbox's own `/tmp` (D18), which withholds no credential. The guarantee
is about what a step can write on the owner's machine.

Rejected: withholding the push credential and the route to the Git host, with the
engine doing every remote operation (the agent's first recommendation) — the owner's
steps need GitHub, GCP and kube, and adversarial containment is not the aim;
containing every step in a container on a laptop — that is the runner's;
keeping the guarantee at the rule level — it cannot travel; deferring — it blocks
extraction and the adapters. A Docker socket, reachable by every writing step, is a
way out of any local sandbox; under P1 it is accepted.

### D2 — The push stays in the session; any other `git push` is refused by the sandbox's `git`

Steps keep pushing through `scripts/change-workflow push`. The sandbox binds the
engine's own `git` read-only over both of the system's Git executables (D4),
`/usr/bin/git` and `/usr/lib/git-core/git`, Git's exec path, which Git puts first on
`PATH` for its scripted commands and aliases; the real binary sits at a path only
the engine's `git` names. It refuses a `push` while the unattended-run marker is set
and the guarded push's marker is not, whatever its options — `--no-verify` and `-c
core.hooksPath=…` among them — and otherwise runs the real `git`. The checkout's
hooks and `core.hooksPath` are left as they are, so the guarded push runs the
repository's pre-push as it does today (CW-p7kq), and the owner's pushes, outside
any sandbox, are untouched. An adapter may add its harness's command rules refusing
`git push` (P6). The check after the run (D6, check 6) is the backstop, and in an
unconfined run (D10) the only guard.

The guarantee is about `git push`, the route an agent's mistakes take: a plain push,
then a retry with the hooks skipped. Other routes to the remote — the real binary
called by its own path, the Git host's API with the ambient credential, the wire
protocol directly, or a push spelled so the engine's `git` misreads its subcommand,
as an alias defined on the command line (`-c alias.p=push p`) or an unknown option
taking a separate value before it — are working around the refusal, outside P1
(28 F2): the
orchestrating session looks for them in a run's later calls (CW-5rmh), and check 6
finds one that reached a protected branch. Protection against a bad remote write
belongs at the Git host's authorization, not on the owner's machine: a Git mistake
caught at the time can be undone, and the container `host-change-workflow-runner`
designs will hold narrower API keys than the owner's.

Each push the guarded push attempts is recorded, once Git returns, among the
session's invocations: its branch, its remote, the commit sent, and Git's exit
status. Each push the engine's `git` refuses is recorded there too, with its command
line, and the wrapper carries it into the line's `refusals` (D7) (28 F3).

The guarded push sets no upstream under a run, since `.git/config` is protected:
where the branch has none and a remote is given, it pushes without
`--set-upstream`, and once the session ends the engine sets the branch's upstream,
outside the sandbox, to the remote of the run's last successful guarded push of that
branch, as its record names it. A failed push, or no push, sets none; nor does a
run whose checks found a violation, after which no action runs (D6, CW-f9le).

Rejected: the engine pushing at the run's edge — once the step holds the credential
it buys nothing, and loses the per-section pushes; a command rule alone, or an
adapter's rule made mandatory for every writing step — harness-specific, against P5,
and Codex has none; detection alone — the mistake reaches the remote first. A
pre-push hook the engine wired through `core.hooksPath` was restated (19 F1): Git
skips it on `git push --no-verify`, and a command-line `-c core.hooksPath` overrides
it without writing `.git/config`, so an agent retrying a push its hook refused
reaches the remote; keeping the hook beside the wrapper for unconfined runs — two
mechanisms. Restated on design review 28's F2, which found a second real Git beside
the mounted one: the engine making every remote Git write outside the step — it
reopens D1's ambient credentials and the per-section pushes; restricting remote
access at the OS level — the network and credential controls D1 excludes. For the
upstream: setting a missing one before the run — the engine would choose the remote
for the step; refusing a push without one — it stops the step for the owner. For its
record (28 F3): reading the push from the transcript or the pre-push hook's
invocations — the hook's are kept before Git runs, whatever Git then does, a
repository may declare no hook, and a transcript is the harness's (P6).

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
engine's `git` bound read-only over the system's two (D2), the network shared,
`--die-with-parent`, and `--unshare-pid`, so that bubblewrap's end ends every process
the harness started, a background one included, as the wrapper's end must
(CW-x3pf). A write to a protected file fails as a read-only file system;
replacing one by rename fails busy, so `git config` cannot rewrite `.git/config`. A
Unix socket on a read-only mount stays connectable, so Docker needs no setting. A
protected path absent at launch is created first — a settings file in its harness's
empty form, `{}` for JSON and an empty file otherwise — and bound read-only like any
other, so it cannot be created during the run (19 F3); the placeholder stays. Each
step's `/tmp` is a tmpfs of its own (D17, D18), and each writable and protected path
is mounted where its symlinks lead (D20).

Inside the sandbox only the owner's uid is mapped: root-owned paths show as the
overflow uid. The private `/tmp` answers that for temporary files; `/`, `/home` and
`/usr` still show so, a limit the runner's container remedies (P7).

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
| review | in the checkout, only `.git/change-invocations/` |
| design, plan | `openspec/`, `.git/`; the repository adds `docs/`; design also each registered `../*-proposal` worktree (D5b) |
| implement, triage, merge, validate | the checkout |
| closeout | its inert paths and `.git/` |
| archive cleanup | `openspec/changes/`, `.git/` |

Every step, the review included, also writes a private `/tmp` (D17, D18), its
adapter's state paths, without which its harness cannot run, and `~/.cache`; every
step also writes the repository's additions (D12), the review only those outside its
checkout, so the checks it runs for evidence can write their tools' caches
(implementation round, handoff 11a.8). The review's one path in the
checkout is where `run` keeps what a session invoked, so the checks the review skill
lets it run for evidence (`run pre-commit`) can record themselves; every file it
reviews stays read-only (19 F2). Protected in every scope: `.agents/workflow.toml`,
`.git/config`, the engine's `git`, and the adapter's and the repository's protected
paths. Reads are open everywhere but the host's `/tmp`, which the private one hides
but for the paths under it a scope names (P3, D18).

The change's log is not mount-protected: closeout's archive moves its directory. It
is guarded by D6. Archive cleanup's history copy becomes an engine action after its
session (CW-hak6), so no step writes the owner's workspace.

Rejected: two coarse profiles with each step's finer scope checked after the run
(the agent's recommendation) — the owner wants a step stopped; a narrower validation
— see D5c; one profile for every step — a review could write what it reviews. A
review writing nothing at all was restated (19 F2): its harness keeps its session
state in its adapter's paths, Codex in `~/.codex` and Claude Code, the review's
fallback, in `~/.claude`; rejected for it are a writable checkout held by check 2 —
detection where prevention is cheap — and the harnesses' state redirected outside
the sandbox — redirection each adapter would have to know how to make.

### D5a — A file or pattern entry mounts its directory

A file or pattern entry in a step's scope — closeout's `**/README.md` and
`AGENTS.md` — mounts each match's directory writable. Tools replace files by rename,
so a single file cannot be bound writable. Where that exposes code beside a README,
or, for files at the root, the whole checkout, D6's check 7 stops the run on any path
changed outside what closeout may change (CW-pkug). The closeout review reads only
documentation, so it cannot be relied on to see a code edit: the premise that it
would, on which this decision was first settled, was restated (19 F4).

An adapter's state file whose directory is the home directory — Claude Code's
`~/.claude.json` — is mounted alone instead: its directory would make the whole home
writable, against P3. Such a file can be written in place but not replaced by
rename; Claude Code catches the failed save (implementation round, handoff 6.1).

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

### D6 — Seven checks after every run; a violation stops it

After every unattended session, whatever its outcome, before any action or hook
after it, the wrapper checks against the state it recorded at the start:

1. `HEAD` is on the change's branch and descends from the start commit;
2. for validation and review, `HEAD` and every tracked file are unchanged;
3. the workflow log was only appended to (a review runs beside a validation and
   appends its line meanwhile);
4. each existing review record is unchanged, and the ledger only grew at its end;
5. `refs/stash` is unchanged;
6. the remote's change branch is the last successful guarded push, as its record
   names it (D2), unchanged, or at a commit not made in the run, and no protected
   branch on the remote has a commit made in the run at its tip, read by listing each
   remote at the start and the end; a remote unreadable at either end is not checked
   (48 F4). The owner's round view, opened in their workspace beside a review in the
   change's clone, moves the workspace's change branch to the round's base, and
   closing it can leave the owner's commits there; neither is the run's (64 R1);
7. for closeout, every path changed since the start, committed or not, is one
   closeout may change (CW-pkug): the repository's inert paths, changes' records,
   and the archive's own writes.

A violation logs the run `stopped`, its reason and an `invariants` field naming each,
the step's message kept ahead, as `triage_outcome` and `landed_outcome` do; the
after-hooks do not run; nothing is repaired. The configuration and the harness's
settings need no check: they are mounted read-only. Their names are not guarded, a
limit D19 records.

Rejected: fewer checks — 4 and 5 would rest on a review's luck, and 6 is the one
backstop for a push to a protected branch; check 6 as a guarantee, fetching a moved
protected branch to find a run's commit below its tip and stopping a run whose
remote cannot be read (48 F4) — a run's commit built on by another party within the
run, or a remote lost between a push and the check, is no mistake's route, and an
offline run would stop, though the sandbox never gates the workflow (D10);
protection of the remote is the Git host's authorization (D2); on 64 R1, leaving the
clone's `workspace` remote unchecked — the engine keyed to a clone's convention, and
an unconfined run's push there unseen — and ordering the round view around the runs
— a `round-done` before a review's end trips it again; and given up there, a run
rewinding or deleting a change branch, whose new tip holds no commit of the run, as
the round view's own rewind holds none, and which the sandbox's `git` refuses in a
confined run; recording a violation beside a standing
outcome — a rewritten history would route as if nothing happened; a question — a
resumed session rarely helps. Check 3 as byte-identical was restated: it would fire
on a parallel review's line. Check 7 was added (19 F4): D5a's mounts let closeout
reach code, and neither its review nor any validation reads closeout's own commit.

### D7 — Refusals come from the run's events

The harness's adapter reads the run's event stream for writes the sandbox refused —
"Read-only file system", or "Device or resource busy" for a protected file — and the
wrapper records each on the line as `refusals`: tool, command or path, error. A push
the sandbox's `git` refused is a refusal too, read from the engine's own record of it
(D2), not from the harness's events, so every harness reports it alike (28 F3). The
step's unattended instructions make it recognize such an error as outside its scope,
end stopped when it cannot go on, and say what it did instead when it can. `denials`
remains for harness rule denials, such as an adapter's `git push` rule. The
orchestrating session reads both from the record and classifies each: the step
reached beyond its job, a finding; or its scope is too narrow, a gap answered with
the narrowest path. A denial by the harness's own guard rather than a rule — Claude
Code refusing to write through a link — is a finding where its target makes it one,
and otherwise neither, since no path answers it (58 R3). The next-step computation treats a line with refusals as one
with denials (CW-jqi7).

Rejected: the step's own report alone — refusals would be read from messages; no
special handling — "a run that cannot go on says so" would no longer hold.

### D8 — A grant is a writable path for one run

`start` and `resume` take `--write <path>`, the make targets `WRITE=`; the line
records `writes_granted`; nothing is kept. Each value is split on `;`, each part
trimmed and empty parts dropped, as `--allow`'s are today. Each path resolves as a
`[sandbox]` entry does (D12): relative from the checkout's root, `~` the home
directory. A grant names a path, never a pattern — a value with a glob character is
refused — since a gap is answered with the narrowest path (D7). A file mounts its
directory (D5a); a path absent at launch is created as a directory before it is
mounted. The engine refuses, naming the value, a path that is or lies under a
protected path, as written or where its links lead, since that is where it is
mounted (D20; 62 F1), or is `/tmp` itself, which would hide the step's private `/tmp` with
the host's (D18), before launching anything (19 F7); a directory containing a
protected path is granted, the protected path staying read-only inside it, as in
every scope (D4, D12; 28 F4). `--allow` and `ALLOW=` go.

Rejected: no grants — a round could not be widened without moving `HEAD`; running a
step under another step's scope — broader than any gap. A new key rather than
reusing `granted` keeps a newer reader from mistaking an old line's rules for paths.
Grants for a fresh run only — a stopped session could not be widened as it resumes,
which is the case a refused write produces; patterns, as the configuration takes —
broader than the gap they answer.

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

The guarantees hold for runs logged confined. An unconfined run has no file bound at
all — Claude Code runs with every tool allowed (D13) and the step table is gone — and
no `git` wrapper (D2): only the checks after it. Containerizing the harness (P7)
remedies this; no further control is added for the interval (19 F5).

Rejected: refusing to start, with an owner-only override (the agent's
recommendation) — the owner prefers the workflow never block on the sandbox;
refusing outright; falling back to the allowlist — two systems and the coupling P6
removes. Restated on design review 19's F5, which challenged this decision: refusing
by default with a one-run override, and refusing unless the owner's environment
accepts unconfined runs on that machine (the agent's recommendation) — the container
remedies the gap, and this intermediate state needs no control of its own.

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
writable.common = ["~/.local/share/uv", "~/.kube/cache", "~/.config/gcloud", "~/.docker",
                   "~/.npm"]
writable.design = ["docs/"]
writable.plan   = ["docs/"]
protected = []
```

Relative paths are from the checkout's root, `~` the home directory. `~/.npm` is
npm's cache, which the configured OpenSpec command's `npx` writes (D21).
`writable.common` is every step's, the review taking only its paths outside the
checkout, as written and where their links lead (D5). The check refuses a writable
path that is or lies under a protected one, compared as written and where its links
lead (62 F1), since the sandbox could not honour it, `/tmp` itself (D18), `writable.review`, and an unknown step
(CW-w8ne). A writable
directory containing a protected path is admitted, the protected path mounted
read-only inside it, as the engine's own scopes hold `.agents/workflow.toml` inside
the checkout and Codex's `config.toml` inside `~/.codex` (28 F4). `config` and
`config --json` list each step's resolved scope with each path's source — engine,
adapter, repository — so the orchestrating session can propose the narrowest path
for a gap (CW-o6kc).

Rejected (28 F4): refusing a writable directory that contains a protected path — it
would hold a repository's additions and the owner's grants to a stricter rule than
the engine's own scopes, for no protection the read-only mount does not already
give. Rejected for the review's caches (handoff 11a.8): a `writable.review` key
admitting only paths outside the checkout — a second key carrying what
`writable.common` already declares; leaving the review without them — its `run
pre-commit` fails this repository's OpenSpec check on `~/.npm`, and its line carries
the refusal on every run.

### D13 — Internal adapters for Claude Code and Codex

Each harness gets an internal adapter module stating its unattended launch inside
the sandbox with its prompts off — Claude Code in `dontAsk` with every tool allowed,
its own sandbox off, which keeps its denial records meaningful for the extras — its
writable state (`~/.claude`, `~/.claude.json`; `~/.codex`), its protected paths —
every settings file its harness loads, present or absent at launch (D4): Claude
Code's `.claude/settings.json`, `.claude/settings.local.json` and
`~/.claude/settings.json`, Codex's `~/.codex/config.toml`, inside its writable state
(19 F3) — its reading of refusals and denials from its events, the steps it can run,
and its optional command rules.
The two do not nest: Codex's own sandbox mounts a fresh `/dev`, hiding the system's
Git where the engine's `git` runs it (D2), so every Git command of a reviewer inside
both fails (48 F1). A confined review therefore runs Codex without its own sandbox,
the review's scope (D5) keeping every reviewed file read-only; an unconfined review
(D10), with no engine `git` mounted, keeps `--sandbox read-only` as its only guard.
Codex names no session in its commands' environment, so the engine gives each Codex
review attempt a run key of its own, distinct from the starting session's and from
Codex's, under which the engine's `git` keeps a refused push and `run` keeps the
checks the reviewer runs, and from which the review's line reads them (D2, D5, D7;
48 F3). Two limits are recorded, not guarded. Claude Code's writable `~/.claude` holds what
the owner's own sessions load beside its protected `settings.json` — `CLAUDE.md`,
skills, agents, commands and hook scripts — and a step writing them has already
broken its skill's rule, as one writing settings has (D15, D19; P1, P8); protecting
each, placeholders created where absent, was rejected (handoff 6.6). Codex refuses to
run in a directory its configuration does not trust, so a review of a clone outside
those directories ends with Codex's error rather than as unavailable, and does not
fall back to Claude; detecting it is `add-workflow-harness-adapters`' (handoff
11a.4).
CW-zq4h's harness clause becomes "only for steps its adapter can
run", so Codex stays review-only until `add-workflow-harness-adapters`, which makes
the interface public and owner-supplied (P6).

### D14 — No deny rules survive

History, branch and stash rules give way to checks 1 and 5; validation's relock and
commit to check 2; edits of `.claude/` and the configuration to the protected
mounts; `git push` to D2's `git` and an adapter's rule; the write-steering rules
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
cleanup stops running `history`; design's section 4 uses `propose`. A merge whose
landing branch changed a protected path cannot be made inside the merge's sandbox:
the merge step stops before merging, naming the paths, and the orchestrating
session, on the owner's word, starts the merge outside any sandbox and resumes the
step to conclude it (implementation round, handoff 10.5); recording it as a limit,
with the merge failing partway, was rejected.

### D16 — The specification

`change-workflow` removes CW-2lvd, CW-2h9t and CW-56zq; renames and modifies CW-qu42,
CW-4yhk, CW-k5mk, CW-svng, CW-5rmh, CW-vdqj, CW-jqi7, CW-drf6, CW-b5cf and CW-hak6;
modifies CW-tl5v, CW-z5me, CW-zq4h, CW-dtpz, CW-o6kc, CW-59c7 and CW-m4ps; and adds CW-x3pf,
CW-m8wq, CW-r6kd, CW-h2zt, CW-v5ny, CW-j4cs, CW-q7ub, CW-f9le, CW-w3oa, CW-k8dn,
CW-t6mb, CW-g5ry and CW-p3vz. `market-change-workflow` modifies MCW-5tgp (the step table no
longer names targets) and adds MCW-s4bx (this repository's `[sandbox]`). The new
log fields — `invariants`, `refusals`, `writes_granted`, `unconfined` — are additive
and need no format version (P9, CW-x7jd). Both companions and indexes follow at
closeout.

CW-m4ps, like MCW-5tgp, names the step table among what its test reads; with D11
removing the table it names only the make fragment. Planning recorded that delta as
a consequence of D11, with no choice in it.

### D17 — Every step gets a private `/tmp` of its own

The sandbox gives every step, the review included, a `/tmp` of its own, owned by the
owner with mode `0700`, in place of the host's bound at its own path. Inside the
user namespace the host's `/tmp` shows as the overflow uid's and world-writable
(Context, "The identity mapping"), so a suite whose checks trust only root-owned or
the caller's ancestors refuses it; the private one passes them, and the bare-metal
ledger suite runs in full in every step (126 passed in a nested sandbox under it).
The fix sits in the sandbox that caused the failure; no other domain changes.

Rejected: a seam in the working-data helper trusting the overflow uid when root is
unmapped — production security code in a second domain would change for the
workflow, and a reviewer of the helper would have to rule out trusting
`nobody`-owned ancestors in production; skipping the ledger tests under an unmapped
root — no step would run them, and a bare-metal change would meet them first in the
pipeline's evidence; running the suite in a container — `validate-local` would need
Docker and an image for one suite, and the cause would stay for the next suite;
running the suites outside the sandbox — the step's own code would run unconfined,
against P1 and P5; mapping host root — no unprivileged tool can; deferring with a
waiver — the change caused the failure and resolves it.

### D18 — The private `/tmp` is a tmpfs; `TMPDIR` points at it; named paths are bound inside

The sandbox mounts `--perms 0700 --tmpfs /tmp` before every bind, and sets `TMPDIR`
to `/tmp`, so a `TMPDIR` the owner set elsewhere, outside the scope and under
root-owned ancestors, does not bring the failure back. A path under the host's
`/tmp` that the scope names — the review's drafts directory, a grant — is bound at
its own path inside the tmpfs, so it means the same file on both sides: the engine
keeps making the review's drafts directory in the host's temporary directory, adds
it to the review's scope as an engine path, and Codex's final message and the
engine's move after the run work unchanged. `config` lists the temporary entry as
the private `/tmp`. The tmpfs ends with the sandbox; nothing is left on the host.
The host's `/tmp` is hidden from reads inside the step but for the paths bound in, an
exception to P3's local fulfilment; sessions outside the sandbox are unaffected.

Rejected: a per-run host directory bound at `/tmp`, removed after the session — a
mount whose source and destination differ, paths translated across the boundary in
both directions, and a directory left behind when the engine is killed, for a
stopped run's `/tmp` no record has needed; the tmpfs with the review's draft moved
into `.git/change-invocations/` — a second purpose for the invocation record; the
private directory mounted at `tempfile.gettempdir()` — fails D17 whenever `TMPDIR`
lies under `/home`; leaving `TMPDIR` alone — a set one points outside the scope.

### D19 — The protected mounts' names are not guarded

A read-only bind protects the file it binds, not its name in the directory around
it. Three routes around a protected mount are recorded as limits of the threat model
(P1), with the step's review as backstop (P8), and nothing checks them:

- renaming a writable directory holding a protected mount and creating a new file
  at the old name — the configuration, a checkout's `.claude/settings*.json`, and
  `~/.claude/settings.json` inside the adapter's writable `~/.claude`;
- removing or replacing a link to a protected file inside a writable directory, as
  every clone's `.claude/settings.local.json` is (D20);
- a repository's `protected` naming a directory holding an engine or adapter
  writable path, `protected = ["~"]`, which `[sandbox]`'s check admits while the
  inner path stays writable.

None is a route a step's ordinary edits take: the harness's edit tools refuse to
write through a link, and its target is read-only. A shell rewrite — `sed -i`, or a
write to a temporary file renamed over the link — replaces a link without meeting a
refusal, but only after a step has already broken its skill's rule that no step
writes the harness's settings (D15); the owner holds that a further mistake, not one
the sandbox guards (48 F2). CW-r6kd promises that
no step writes a protected file, not that a protected path's name stays bound.

Rejected (the agent's recommendation, made again on design review 48's F2): an eighth check after every run comparing each
protected path's kind, link target and content with the start, a difference stopping
the run, with `[sandbox]`'s check refusing a protected directory holding a baseline
path — the owner holds these routes to be workarounds outside P1; mounting each
protected path's parent read-only — it would stop every legitimate write beside
them, in `.agents/`, `.claude/` and `~/.claude`.

### D20 — Paths are mounted where their symlinks lead

Each writable and protected path is mounted where its symlinks lead, and an absent
target is created there before launch. A link whose target lies outside every
writable path needs no mount: the target is read-only under the root. A clone's
linked `.claude/settings.local.json` therefore launches, and a write through it fails
read-only; the link itself is one of D19's limits.

Rejected: `change-clone` copying the settings rather than linking them — the owner's
settings would diverge across clones, and a linked writable path such as `~/.cache`
would still need this; refusing to launch on a symlinked scope path — every clone
would stop.

### D21 — `~/.npm` is a repository addition for every step

The configured OpenSpec command runs `npx`, which writes npm's cache at `~/.npm`;
this repository's `writable.common` names it (D12, MCW-s4bx), which gives it the
review too, since it lies outside the checkout (D5).

Rejected: redirecting npm's cache under `~/.cache` in the configured command —
repository plumbing in a command for a narrower declaration, and a second cache for
the owner's interactive runs.

### Implementation cadence

One round, three sessions, then closeout:

1. **The engine's sandbox.** Each step's definition in the engine replacing the step
   table; `[sandbox]` and its checks; scope resolution and its listing in `config`;
   the bubblewrap launcher with protected mounts, the probe, and the unconfined
   fallback.
2. **The guarantees.** The seven checks and the stopped outcome; the sandbox's
   `git` with its marker condition, bound by session 1's launcher, and its record of
   refused pushes; the guarded push's record of each push, and the upstream set
   after the run from it.
3. **Adapters and wiring.** The Claude Code and Codex adapters (launch, state,
   protected paths, refusals, optional rules); the wrapper's and review's launch
   through them; grants as `--write`; refusals recorded and routed; the skills'
   unattended paragraph and the three exemptions; `propose` and design's section 4;
   the history copy as an engine action and archive cleanup's skill; `round-view`
   and `round-done` refused under the marker; MCW-s4bx's declaration; the step table
   and `steps.py` removed last.

This change rewires the engine it runs on, and each session of its round runs on the
engine the sessions before it committed. No step runs between the old restraint's
removal and its replacement's installation (28 F1): session 2 runs under the step
table; session 3 under the step table and the checks, which run whether or not a run
is confined (D10); and every run after it, the round's own triage and closeout among
them, under the whole sandbox. The session removing `.claude/change-steps.toml` runs
under rules that deny edits under `.claude/`, so the plan gives that removal to the
orchestrating session or the owner.

After the return from implementation (D17–D21), the round gains one session: it
implements D18 — the tmpfs `/tmp`, `TMPDIR`, the review's drafts directory in its
scope, the `config` listing, the refusal of `/tmp` as a grant or `[sandbox]` entry,
and the nested sandbox tests adjusted — and, from design review 48, Codex's launch
without its own sandbox in a confined review and the Codex review's run key (D13) —
then completes section 11's verification
point with `validate-local` passing inside its own sandbox. The round's review and
triage then read every section together, before closeout.

That session runs, as every session of the round does, on the engine the sessions
before it committed, so the sandbox the engine launched it in still binds the host's
`/tmp`, and its own `run pre-commit` meets the ledger suite's failure D17 answers.
Its evidence for `validate-local` is therefore the change's sandbox launched from
inside its own, through the launcher it has just changed, with implementation's
resolved scope, as the suite's nested bubblewrap tests already launch one; the
round's triage, the first step the engine launches with the private `/tmp`, runs
`run pre-commit` in its own sandbox. Likewise the implementing session's scope does
not write `~/.codex`, so a real Codex review under the engine's sandbox (D13) runs
where the owner grants it that path for the session, and otherwise first as the
round's own review, on Codex, whose line the triage reads. D19, D20 (already built)
and D21 (already declared) change the specification and design only.

Rejected (28 F1): keeping the command rules until a final atomic switch — two
restraint systems at once, which D10 rejects as a fallback; one session for every
launch and guard change — a review slice much larger than the others. After the
return: a second round for the private `/tmp`, reviewed apart — a slice smaller than
its review, which the first round's verification point cannot pass without.

## Open Questions

- **Native Ubuntu's AppArmor and `bwrap`.** Whether Ubuntu 24.04 and later admit
  `bwrap`'s user namespaces without an administrator's profile is verified in
  implementation on a native install; D10's fallback covers a refusal meanwhile.
  Revisit when the owner or a coworker runs unattended steps on native Ubuntu.
- **The read grant inside the runner's container.** P3 is met locally by open
  reads; `host-change-workflow-runner` mounts the parent of the checkouts read-only.
  Revisit in that change's design.
