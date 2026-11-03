## Why

The workflow runs every step that writes on Claude Code. A review runs in Codex's
read-only sandbox first and falls back to Claude. Each step's models are listed in
the step table with their harness, and the wrapper runs the first available.
Nothing else is supported. The architecture companion gives the reason: "Codex
appears only where its sandbox can hold a step to its limits, which is the review
alone". The step's limits are Claude Code permission rules, and only a read-only
review maps onto a Codex sandbox mode.

That leaves three needs unmet:

- **Balancing plan limits.** A step whose one model hits its usage limit stops
  until the limit resets. Running implementation on Codex would let the owner
  spread work across plans.
- **A wider range of reviewers.** The owner intends to bring review feedback from
  more models over time, including open models served by a provider such as
  Venice. Reading the work with several different models finds more than one
  model reading it twice.
- **A harness boundary that can take another harness.** Today each harness's
  launch, resume, event stream, transcript location, limit detection, and cost
  are handled in modules written for that harness: `harness`, `stream`,
  `subagents`, and `cost`. Adding a third harness means touching all of them.

`sandbox-unattended-workflow-steps` removes the blocker. It replaces Claude
Code's rules with harness-neutral profiles, so any harness that can enforce a
profile can run a step under it.

## What Changes

- **A harness adapter interface.** Each harness is one adapter. It covers:
  - launching a step and resuming a waiting run;
  - mapping the step's sandbox profile onto the harness's own mechanism;
  - reading the harness's event stream into progress and refusals;
  - locating its transcripts;
  - recognizing an unavailable model or a usage limit;
  - reporting what the run cost.

  The wrapper, the review runner, the watcher, and cost reporting go through the
  interface, not through harness-specific code.
- **Adapters for three harnesses:**
  - **Claude Code,** for every step, as today.
  - **Codex,** for every step whose profile it can enforce, including
    implementation, no longer only the review.
  - **One skills-capable harness serving open models** through a provider such as
    Venice. Which harness is chosen in design.
- **Model policy extends to the new harnesses.** A step's models stay a priority
  list, each naming its harness. The rule against a second model of one vendor as
  a fallback carries over, with the vendor of an open model defined in design.
- **Skills stay native.** Every supported harness loads the skills natively. The
  workflow does not support harnesses without skill loading, and it does not
  compose prompts for them.

## Capabilities

### New Capabilities

- None expected.

### Modified Capabilities

- `change-workflow`, or the engine capability if `specify-change-workflow-and-engine`
  creates one. Affected: harness support, the model policy ("Unattended steps run
  on their step's ordered models"), cost recording ("Unattended runs record their
  cost"), and the requirement that a waiting run resumes on the model it ran on.

## Non-Goals

- **Do not support harnesses without skill loading.** Deferred for the
  foreseeable future.
- **Do not build the model gateway.** Each harness authenticates as it does today.
  A common credential path is the gateway change's.
- **Do not change which model any step runs on.** Adding Codex or an open model to
  a step's list is a policy decision for the owner, taken when the adapters exist.
- **Do not change interactive sessions.** These are started in the owner's own
  harness.

## Impact

- `scripts/change_workflow/harness.py`, `stream.py`, `subagents.py`, `cost.py`,
  `wrapper.py`, `review.py`, and `watch.py`, reorganized around the adapter
  interface.
- The step table's model rows and their validation in
  `scripts/change_workflow/steps.py`.
- The skill installation for the new harness: links in this repository, or the
  installer once `extract-change-workflow-repository` provides one.
- `scripts/change_cost.py`, for cost across harnesses.
- The workflow's specification and architecture companion, where "Models are
  policy, with no same-vendor fallback" explains the current rule.
- The workflow's tests under `scripts/tests/`.

## Dependencies and Related Changes

- **`sandbox-unattended-workflow-steps` (design).** Adapters map the profiles that
  change defines, and whether a harness can run a step depends on whether it can
  enforce that step's profile.
- **`specify-change-workflow-and-engine` (design).** The adapter interface becomes
  part of the engine's documented structure, and its public surface if adapters
  can be supplied from outside.
- **`extract-change-workflow-repository`** is independent of this change in either
  order. Whichever lands second extends the installer, or this repository's skill
  links, to the new harness.
- **The model gateway change, still to be opened,** gives every adapter one
  credential path.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow`, or the engine
      capability `specify-change-workflow-and-engine` creates, specification and
      architecture companion
- [ ] New subsystem specification
- [ ] No permanent documentation change

`docs/agents/change-workflow.md` changes with it.

The lesser goal's gap "Writing steps run only on Claude Code" in
`openspec/changes/README.md` is owned by this change and closes with it.

### Knowledge to promote

To be determined at design completion.
