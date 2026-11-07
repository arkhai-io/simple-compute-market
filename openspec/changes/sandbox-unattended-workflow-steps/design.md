# Design: sandbox unattended workflow steps

Status: design phase. Not planned. The direction under "Starting direction" came
from the owner's discussion that opened the lesser goal, and design confirms or
revises it. Everything under "Open questions" is undecided.

## Context

- **The current model.** An unattended run uses Claude Code's `dontAsk`
  permission mode, with only the project's settings loaded. A tool call no allow
  rule names is denied and recorded in the run's `permission_denials`. Each
  step's rules are its own plus `[common]`'s, from `.claude/change-steps.toml`.
  Deny rules win, and they encode each skill's "never" lines. The rationale is in
  `openspec/specs/change-workflow/architecture.md`, "Restrictions bind unattended
  runs only". The contract is the requirement "Unattended runs are held to their
  step's permissions" in `openspec/specs/change-workflow/spec.md`.
- **Guarded push.** Every committing step pushes through `make push-branch`, the
  only push allowed. Every other `git push` is denied in `[common]`.
- **Grants.** The owner can grant rules for one run on its command line (`ALLOW=`).
  The grant is noted on the run's log line and never written into the table.
- **Protection of the table.** Every step is denied `Edit(.claude/**)` and
  `Write(.claude/**)`.
- **Reviews.** A review runs first in Codex's read-only sandbox (`codex exec
  --sandbox read-only`), which is already a profile in all but name.
- **Interactive runs.** These are not held to the table; the owner's own settings
  and prompts apply.
- **Harness-imposed refusals.** Claude Code refuses some shapes whatever the rules
  allow: a `find` over `/` or `/etc`, and a path that climbs with `..` after a
  `cd`. Each costs a denial on the run's line.

## Starting direction

- **Restrict the environment instead of listing commands.** A step may run
  anything inside its profile.
- **Three starting profiles:** read-only, workspace-write, and workspace-write with
  network or cluster access.
- **Privileged actions are engine operations.** The step holds no credential for
  them.
- **Detection where prevention is impractical.** Post-step invariant checks catch
  what a sandbox cannot stop. With every step's work committed and pushed, a
  reset or stash is detected and recoverable, not silently lost.
- **Repositories extend, and may tighten freely.** They may loosen only a
  profile's settings, never an engine guarantee. Permission packs may come later.

## Open questions

- **Removing the push credential on a developer's machine.** In a container, the
  engine can hold the only Git credential. On a laptop, credentials are ambient:
  an SSH agent, a credential helper, a token in the environment. A sandbox can
  block network access to the Git host, but a workspace-write step that needs the
  network, such as validation, then needs a host list precise enough to admit
  what it needs and refuse the push. Whether the local guarantee is "no
  credential" or "no route to the Git host" is open.
- **What each profile allows exactly.** Which paths are writable: the checkout,
  the change's records, a temporary directory, and the harness's own state. Which
  network hosts are reachable. Whether validation's cluster access is a profile
  of its own or a setting on workspace-write.
- **How refusals are recorded.** Today a denial is a structured record from
  Claude Code. A sandbox refusal often appears as a command failing with a
  permission error, and a step may misread it as an ordinary failure. Whether the
  engine can attribute such failures to the sandbox, and how they reach the
  outcome, decides whether "a run that cannot go on without a denied tool ends
  saying so" still holds.
- **The full set of invariants.** The starting set:
  - `HEAD` descends from the step's starting commit;
  - the records are not rewritten;
  - the configuration is unchanged;
  - no stash, reset, or clean happened.

  Candidates to add: tracked files outside the change's expected scope, and the
  workflow log only appended to. Each check needs a cheap, deterministic test.
- **What survives of deny rules.** Some "never" lines are about intent, not
  capability. Validation must not change the commit; a review must not edit
  files. Profiles cover some of these: a read-only review cannot edit. Others need
  an invariant check: validation's `HEAD` and tree are unchanged. Whether any deny
  rules remain once profiles and invariants exist is open.
- **Owner grants.** Today a grant adds a rule for one run. Under profiles, a grant
  might widen a profile setting for one run, such as a writable path or a network
  host. Whether grants survive in that form, and how they stay recorded, is open.
- **Interactive runs.** Whether an interactive step runs under its profile, which
  would make interactive and unattended behaviour match, or keeps the owner's own
  settings as today.
- **Where profiles are declared.** Today the table lives under `.claude/` because
  it is Claude Code's syntax. Profiles are harness-neutral, so their natural home
  is the workflow's own configuration and step definitions, with each harness's
  syntax generated from them.
