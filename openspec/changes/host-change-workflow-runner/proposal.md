## Why

A change's live state is tied to the machine running it. Its records are
untracked, in its clone and the owner's workspace. Its sessions' transcripts are
in the harness's state directory on that machine. Its orchestrating session runs
in that machine's terminal. Three consequences follow:

- **Sharing a change in progress is expensive.** Handing a change to someone
  else, or showing them where it stands, means passing around hundreds of
  megabytes of records and transcripts. Context is lost in the transfer.
- **Nobody else can watch or step in.** A colleague cannot follow a running step,
  answer a question it is waiting on, or take the change over without
  reconstructing it on their own machine.
- **Bypassing the workflow is easier than using it.** For a person or a bot
  driving work, running the implementation directly takes less effort than
  setting up the workflow. So work skips design, review, and validation. The
  workflow deliberately does not gate merges: a patch made directly to `dev`
  stays legitimate. Its remedy is to be the easiest path, not the only one.

A hosted runner keeps each change's state in one place that anyone working on it
can reach, and gives people and bots the same small set of verbs to drive it.

## What Changes

- **An environment contract.** The runner and a developer's machine both meet one
  written contract:
  - a Kubernetes context configured in advance, which validation uses as it is
    (Docker Desktop's, on a laptop);
  - a way to build images;
  - Git access through the engine;
  - the supported harness programs.

  The workflow assumes the contract and does not choose a cluster.
- **A pod per user per change, holding only that user's credentials.**
  - **The volume is shared, the credentials are not.** A shared volume holds the
    change's clone, records, and session transcripts, and never a credential.
  - **Access is per user.** Kubernetes access control lets each user exec only
    into their own pod, because exec into a pod is access to every credential in
    it.
  - **Credentials stay with their owner.** API keys never enter the cluster: they
    come through the model gateway. A subscription is signed in by its user inside
    their own pod, through the provider's flow.
- **Watching and taking over.**
  - **Watching is read-only.** Other users watch a running session read-only.
  - **Taking over is a resume.** You resume the session from the shared
    transcripts in your own pod, under your own credentials, so nobody drives a
    session on someone else's subscription.
  - **Session paths stay stable,** so a resume finds its transcript.
- **Directions attributed to who gave them.** The orchestrator's record of a
  direction or a waiver names the person who gave it. A standing direction, such
  as waiving the next round's validation because only comments changed, is
  recorded when it is given, not held only in a session's memory. It then
  survives the session, and the next round reads it from the records.
- **An advisory status on the change's pull request.** It shows whether the change
  went through the workflow and where it stands. It is visible, not enforced:
  nothing blocks a merge.
- **One entry point for people and bots.** A small set of remote commands lets a
  developer and a bot drive a change the same way: start, status, attach
  read-only, and say, which sends a reply or a direction.

## Capabilities

### New Capabilities

- Possibly a capability for the runner and its environment contract, decided in
  design.

### Modified Capabilities

- `change-workflow`, or the engine capability, for:
  - attributed and standing directions ("The owner directs a change's next step",
    "An orchestrating session advances one change");
  - the pull-request status;
  - the remote entry point.

## Non-Goals

- **Do not gate merges on the workflow.**
- **Do not serve parties outside the team.** Running for parties that are not
  trusted with one another's material raises access questions this change does
  not answer: who may read transcripts, and what content may leave.
- **Do not build the model gateway.** This change consumes it.
- **Do not prevent a person from giving a direction through someone else's
  session.** The runner cannot verify intent held in a conversation. It makes the
  direction attributable and visible.

## Impact

- A runner image, its deployment, and the environment contract's document. The
  locations of their source are decided in design. Deployment configuration that
  names private infrastructure stays out of this repository.
- `scripts/change_workflow/log.py` and the orchestrator skill, for attributed and
  standing directions.
- A pull-request status published by the engine.
- The remote entry point.
- The workflow's specification, architecture companion, and
  `docs/agents/change-workflow.md`.

## Dependencies and Related Changes

- **`add-workflow-model-gateway` (design).** No API key may enter the cluster, and
  the runner's credential isolation is designed against the gateway's tokens and
  relay.
- **`extract-change-workflow-repository`.** The runner image is built from the
  extracted workflow at a version. Gates implementation.
- **`sandbox-unattended-workflow-steps`.** The engine holds the push credential
  and checks invariants. In a container, this is where "the step holds no
  credential" becomes fully true. Gates implementation.
- **`add-workflow-harness-adapters`** is related, not required. Each harness the
  runner offers must have an adapter.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `change-workflow`, or the engine
      capability `specify-change-workflow-and-engine` creates
- [ ] New subsystem specification, if the runner becomes a capability of its own
- [ ] No permanent documentation change

The lesser goal's gap "A change's live state and transcripts are tied to the
machine running it" in `openspec/changes/README.md` is owned by this change. If
design splits it, the resulting changes share the gap.

### Knowledge to promote

To be determined at design completion.
