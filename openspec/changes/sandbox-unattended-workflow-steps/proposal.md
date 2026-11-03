## Why

An unattended step is held to an allowlist of commands. The allowlist lives in
`.claude/change-steps.toml`, in Claude Code's permission rule syntax: one table
of shared rules and one per step, with deny rules for the "never" lines of each
skill. That model served this repository, but it cannot carry the workflow to
other repositories or other harnesses:

- **Different repositories run different commands.** An allowlist names
  commands. Once each repository supplies its own capabilities and an
  implementer reaches for whatever its language needs (`cargo test`, `go vet`, a
  debug script), the list cannot be written in advance.
- **Different harnesses enforce differently.** The rules are Claude Code's
  syntax. Codex enforces sandbox modes, not command rules. A harness serving
  open models may offer neither.
- **The allowlist leaks at its edges and grows to patch them.** Its own comments
  show the cost. `find` is allowed, so `-delete`, `-exec`, `-ok`, `-fprint`, and
  `-fls` are each denied. The `git diff` family is allowed, so `--output` is
  denied. A chained command needs every part allowed, so `cd` is allowed as a
  no-op. Steps that need a command nobody listed are given it by an owner's
  grant for one run.
- **The guarded push is a rule, not a fact.** A step cannot push because a deny
  rule matches `git push`. The step still holds the credential that would let
  it push.

## What Changes

- **Per-step sandbox profiles replace command allowlists.** Each step runs under
  a profile:
  - **read-only:** a review, and reading for triage;
  - **workspace-write:** design, planning, implementation, and triage fixes;
  - **workspace-write with network or cluster access:** validation.

  Inside its profile, a step may run any command.
- **The engine performs privileged actions with credentials the step never
  holds.** These are the guarded push and recording a step's outcome. A step
  asks the engine to act; it does not act itself.
- **Invariant checks after each step.** The engine checks what a sandbox cannot
  prevent: `HEAD` descends from the commit the step started at, the change's
  records were not rewritten, the workflow's configuration is unchanged, and no
  reset, stash, or clean discarded work. A violation fails the step, the way an
  outcome naming no node in the graph is refused today.
- **Repositories extend the baseline.** A repository adds allow and deny rules,
  and adjusts a profile's settings such as extra writable paths or network hosts,
  in the workflow's configuration file. It may tighten anything. It may not
  loosen what the engine guarantees: no push credential in the sandbox, and the
  integrity of the records.
- **Each harness maps a profile onto its own mechanism.** Claude Code uses its
  Bash sandbox and permission settings. Codex uses its sandbox modes. A
  containerized run uses mounts. This change maps the profiles for the harnesses
  the workflow runs on today: Claude Code for every step, and Codex for reviews.
- **Refusals stay visible.** A sandbox refusal is recorded on the run's outcome,
  as a denial is today, so a step that needed more than its profile allows still
  ends saying so.

## Capabilities

### New Capabilities

- None expected.

### Modified Capabilities

- `change-workflow`, or the engine capability if `specify-change-workflow-and-engine`
  creates one. The requirement "Unattended runs are held to their step's
  permissions" is replaced by profiles, engine-performed privileged actions,
  invariant checks, and repository extension.

## Non-Goals

- **Do not add harnesses.** The harness adapter change does that. This change
  defines the profile each adapter maps.
- **Do not build the hosted runner or the model gateway.** Both are their own
  changes.
- **Do not ship permission packs.** Named sets of rules a repository selects may
  follow once the baseline and repository extension exist.
- **Do not change the owner's interactive sessions.** Whether an interactive run
  adopts a step's profile is a design question, but this change does not take
  away the owner's own permission settings.

## Impact

- `.claude/change-steps.toml`, which is replaced or reduced to profiles, and
  `scripts/change_workflow/steps.py`, which reads it.
- `scripts/change_workflow/harness.py` and `wrapper.py`, for mapping profiles and
  for the engine-performed push and the post-step checks.
- The workflow's configuration file, for repository extensions.
- The skills' "never" lines and their instructions to push through `make
  push-branch`.
- The workflow's specification and architecture companion, where "Restrictions
  bind unattended runs only" explains the current model.
- The workflow's tests under `scripts/tests/`.

## Dependencies and Related Changes

- **`add-workflow-capability-contract`.** This change builds on that change's
  configuration file and per-step capability lists. It gates implementation only,
  so the two designs may proceed side by side.
- **`specify-change-workflow-and-engine` (design).** This change designs against
  that change's description of the step table and the guarded push.
- **The harness adapter change, still to be opened,** consumes the profiles this
  change defines.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow`, or the engine
      capability `specify-change-workflow-and-engine` creates, specification and
      architecture companion
- [ ] New subsystem specification
- [ ] No permanent documentation change

The lesser goal's gap "Unattended permissions are allowlists of this repository's
commands" in `openspec/changes/README.md` is owned by this change and closes with
it.

### Knowledge to promote

To be determined at design completion.
