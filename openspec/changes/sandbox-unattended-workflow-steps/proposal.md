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
  open models may offer neither, and an owner may bring a harness the workflow
  has never heard of.
- **The allowlist leaks at its edges and grows to patch them.** Its own comments
  show the cost. `find` is allowed, so `-delete`, `-exec`, `-ok`, `-fprint`, and
  `-fls` are each denied. The `git diff` family is allowed, so `--output` is
  denied. A chained command needs every part allowed, so `cd` is allowed as a
  no-op. In `serve-running-rate-deals`, 24 of 88 logged runs carry a denial or a
  grant.
- **It bounds commands, not files.** A step's Read tool reaches any file the
  owner can read, and a listed command may write outside the checkout.

## What Changes

The threat model stays what it is: the restrictions guard against a step's
mistakes, not a malicious agent, and steps keep their ambient credentials. What
changes is how the guarantees are enforced: by the operating system, below any
harness, as categorical bounds on what a step can change on the owner's machine.

- **The engine launches each unattended step inside an OS sandbox it owns**
  (bubblewrap on Linux), confining the harness's file tools, shell, and subagents
  alike. Inside it, a step may run any command; the network, the environment, and
  reads are left as they are.
- **Each step writes only its scope.** Review writes nothing; design and planning
  `openspec/`, `.git/`, and what the repository adds (`docs/` here); closeout its
  inert paths; archive cleanup `openspec/changes/`; implementation, triage, the
  merge, and validation the checkout. A file or pattern entry mounts its directory.
- **Protected paths no step writes:** the workflow's configuration, `.git/config`,
  the engine's hook directory, and the harness's settings.
- **Only the guarded push leaves a checkout during an unattended run,** refused
  otherwise by an engine pre-push hook the protected paths keep wired.
- **Six checks after every run** — history only extended, validation and review
  changing nothing, the log and ledger only appended to, review records
  unchanged, no stash, the remote moved only by the guarded push. A violation
  stops the run.
- **Refusals are recorded** from the run's events, and grants become writable
  paths for one run.
- **Repositories extend the baseline** in `[sandbox]` of the workflow's
  configuration; protected paths can only be added.
- **Each harness has an adapter** stating its launch, state, protected paths, and
  refusal reading. This change builds internal adapters for Claude Code and Codex.
- **The engine creates a prerequisite's worktree** (`propose`), and copies archive
  cleanup's history into the workspace, so no step writes outside its change.
- **Where the sandbox cannot run, a step runs unconfined and says so.**
- **The step table and every deny rule go.** Each step's skill, `resume_from`,
  and baseline scope live in the engine beside the graph.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `change-workflow`: the unattended-run requirements (CW-qu42, CW-4yhk, CW-k5mk,
  CW-svng, CW-5rmh, CW-vdqj, CW-jqi7, CW-drf6, CW-tl5v, CW-b5cf, CW-z5me, CW-zq4h),
  history's copy (CW-hak6), a blocked design (CW-dtpz), and the configuration's
  listing (CW-o6kc) change; CW-2lvd, CW-2h9t, and CW-56zq are removed; the sandbox,
  scopes, protected paths, extension, fallback, pre-push hook, checks, refusals,
  `propose`, adapters, interactive runs, and the round view's refusal are added.
- `market-change-workflow`: MCW-5tgp no longer reads targets from a step table, and
  this repository's `[sandbox]` declaration is added.

## Non-Goals

- **Do not restrict credentials or the network.** Steps keep the owner's GitHub,
  GCP, and kube access.
- **Do not contain a malicious agent.** A step can still escape through the Docker
  socket or by deliberately unsetting the unattended marker; the checks and reviews
  catch what that does to the change.
- **Do not build a public adapter interface or add harnesses.**
  `add-workflow-harness-adapters` does that; this change's adapters are internal.
- **Do not build the container or the hosted runner.** `host-change-workflow-runner`
  designs the image, cuts orchestration over to it, and reworks any OS-level
  function its OS needs.
- **Do not support other operating systems.** Ubuntu is canonical.
- **Do not confine interactive runs.** The owner's own settings apply.
- **Do not ship permission packs.**

## Impact

- `.claude/change-steps.toml` and `scripts/change_workflow/steps.py`, removed; each
  step's definition moves into the engine beside `graph.py`.
- `scripts/change_workflow/harness.py`, reorganized into internal adapters, and a
  new sandbox launcher; `wrapper.py` and `review.py`, which launch through them;
  `config.py` for `[sandbox]` and the scope listing; `push.py` and `clone.py` for the
  pre-push hook; `log.py` and `next_step.py` for `refusals`, `invariants`,
  `writes_granted`, and `unconfined`; `around.py` for the history action; a new
  `propose` subcommand; `round_view.py` for its refusal; `cli.py` and `workflow.mk`
  for `--write` and `WRITE=`.
- `.agents/workflow.toml`, gaining `[sandbox]`.
- Every skill's "Running unattended" section, and `change-design`'s section 4,
  `change-archive-cleanup`, `change-implement`, `change-plan`, and
  `change-orchestrate`.
- The workflow's specification, index, and companion, and `market-change-workflow`'s.
- The workflow's tests under `scripts/tests/`.
- `docs/change-workflow-handbook.md`, for grants, running unconfined, and
  `propose`.

The step table's file and its deny rules stop existing, so a change in flight that
still runs the old engine keeps its own copy until it merges the landing branch.

## Dependencies and Related Changes

- **`add-workflow-capability-contract`** and **`specify-change-workflow-and-engine`**
  are archived; this change builds on the configuration file and the engine's hook
  table they left.
- **`add-workflow-harness-adapters`** depends on this design: it makes the adapter
  interface public and owner-supplied, and adds harnesses whose adapters can run
  writing steps.
- **`extract-change-workflow-repository`** depends on this design; some of these
  decisions are expected to be reconsidered there.
- **`host-change-workflow-runner`** builds on this change's sandbox inside its
  container. Its proposal's note that "the engine holds the push credential" no
  longer describes this change: credentials stay ambient.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow` and
      `market-change-workflow`, specification, index, and companion
- [ ] New subsystem specification
- [ ] No permanent documentation change

`docs/change-workflow-handbook.md` changes with it. The lesser goal's gap
"Unattended permissions are allowlists of this repository's commands" in
`openspec/changes/README.md` is owned by this change and closes with it, as do three
of `change-workflow`'s Current limits: the forgeable marker and the unchecked
configuration, the step table's place and syntax, and Read reaching any file.

### Knowledge to promote

- D1: `change-workflow`'s companion, "Restrictions bind unattended runs only",
  rewritten with P1 and P2 as its threat model; CW-x3pf.
- D2: CW-j4cs and CW-59c7; `change-workflow`'s companion, "Pushing is guarded,
  never repaired".
- D3: CW-x3pf and CW-t6mb; `change-workflow`'s companion, the restrictions section
  with P5 and P7.
- D4: CW-x3pf and CW-r6kd; `change-workflow`'s companion, the restrictions section
  and "The engine's own assumptions" (`bwrap` among the tools).
- D5: CW-m8wq, CW-r6kd, and CW-hak6; `change-workflow`'s companion, the restrictions
  section's scope table, with P3.
- D5a: CW-m8wq; `change-workflow`'s companion, with P8.
- D5b: CW-k8dn and CW-dtpz; `change-workflow`'s companion, "A prerequisite is
  proposed apart and halts its dependent"; the design skill.
- D5c: CW-m8wq and CW-q7ub; `change-workflow`'s companion, "Validation observes a
  committed slice".
- D6: CW-q7ub and CW-f9le; `change-workflow`'s companion, "A step run's life".
- D7: CW-w3oa, CW-k5mk, CW-svng, CW-5rmh, CW-vdqj, and CW-jqi7; `change-workflow`'s
  companion, the restrictions section; the orchestrating skill.
- D8: CW-tl5v and CW-drf6; `change-workflow`'s companion; the owner's handbook.
- D9: CW-g5ry; `change-workflow`'s companion, "Interactive runs record their own
  outcome".
- D10: CW-v5ny; `change-workflow`'s companion; the owner's handbook.
- D11: `change-workflow`'s companion, "Its parts" and "The engine's own assumptions"
  (the step table's row removed).
- D12: CW-h2zt and CW-o6kc; `change-workflow`'s companion, "A repository's
  configuration"; MCW-s4bx and `market-change-workflow`'s companion.
- D13: CW-t6mb and CW-zq4h; `change-workflow`'s companion, "Models are policy, with
  no same-vendor fallback" and the restrictions section, with P6.
- D14: CW-p3vz and CW-z5me; `change-workflow`'s companion, the restrictions section
  and its hook table.
- D15: the skills; MCW-5tgp's exemption table in `market-change-workflow`'s
  companion, its three rows removed.
- D16: no permanent destination beyond the requirements it lists — the log's new
  fields are recorded in their requirements, and P9 in `change-workflow`'s
  companion, "A change's records carry one format version".
