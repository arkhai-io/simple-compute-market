# Design: host the change workflow runner

Status: design phase. Not planned. This design waits on the model gateway's
design, so it records direction and questions only. The direction under
"Starting direction" came from the owner's discussion that opened the lesser
goal. Everything under "Open questions" is undecided.

## Context

- **Where a change's state lives today.**
  - **Records** are untracked, in the change's clone and the owner's workspace
    (`scripts/find_change.py`).
  - **The workflow log** is the next-step computation's input.
  - **Session transcripts** sit under the harness's state directory on the
    machine that ran them. Claude Code keys them by the working directory's
    path, so resuming a session needs the same path.
  - **The orchestrating session** is an interactive Claude Code session in the
    owner's terminal (`make orchestrate`).
- **Directions.** The orchestrating session records the owner's decisions as
  `orchestrator` lines in the workflow log (`note_orchestrator` in
  `scripts/change_workflow/log.py`). That function already takes a `by` argument
  naming who recorded the line. Only the owner may direct a step ("The owner
  directs a change's next step" in `openspec/specs/change-workflow/spec.md`).
- **Validation.** Helm validation runs against an explicitly named Kubernetes
  context, isolated in the change's own namespace ("Each Helm validation is
  isolated in its change's namespace").
- **Step runs** are started so that no harness timeout ends them mid-step.

## Starting direction

- **Hosting makes the workflow easier to use, not mandatory.** No merge gate;
  direct patches stay legitimate.
- **Credential isolation comes from separate pods, not from instructions.** Exec
  into a pod is access to every credential in it, so the shared change volume
  holds none. Each user's pod holds only that user's credentials, and access
  control limits exec to one's own pod. This is the runner's first design
  constraint and is to be scrutinized heavily.
- **Takeover is a resume under one's own login.** A session is driven by one
  credential at a time.
- **Directions are attributable and can be standing.** This gives auditability
  rather than prevention. A direction given through a bot is recorded as given
  through the bot.
- **The workflow does not choose a cluster.** It uses the context the environment
  provides.

## Open questions

- **Splitting the change.** The environment contract, the per-user pod and shared
  volume, attributed and standing directions, the pull-request status, and the
  remote entry point could each land separately. Attributed and standing
  directions are useful even on a laptop, and could come first, independent of
  hosting.
- **Isolating credentials in detail.**
  - The threat model: other users, a compromised step, an agent writing its
    environment to the shared volume.
  - Whether harness state directories, which hold sign-in material, are kept per
    user while transcripts are shared.
  - How transcripts are screened for secrets before they reach the shared volume.
  - Who holds cluster-admin, and what that grants.
- **Watching.** Read-only attachment to a terminal session, or a stream of the
  session's events rendered for a viewer. The second avoids giving a viewer any
  access to the pod that holds the driver's credentials.
- **Takeover.** How a session hands over cleanly: the current driver's run stops
  or finishes its turn, and the new driver resumes. What happens to an unattended
  step mid-run when its driver leaves.
- **The environment contract's contents.** Image builds in a container mean a
  daemon, a rootless builder, or a cluster build service. Git access means the
  engine's own credential, scoped per repository. The harness programs are pinned
  at versions.
- **Standing directions.** Their form in the workflow log, how long one holds (the
  next round, or until revoked), and how the next-step computation and the
  orchestrator read one. A standing direction must not let the orchestrator decide
  on the owner's behalf; it records a decision the owner already made.
- **Who counts as the owner.** Several people may drive one change. Whether any of
  them may give the owner's word, or a change names its owner and others relay.
- **The pull-request status.** What it reports (the last step, open findings,
  validation state), when it updates, and which credential publishes it.
- **The remote entry point.** Its transport (commands over the cluster's API, or a
  small service) and how a bot authenticates as itself. A bot's actions are then
  attributed to the bot.
- **Persistence and cost.** Volume lifetime after a change archives: history is
  copied to the owner's workspace today, which on the runner becomes a durable
  store. Idle pods are scaled down, and resumed with their state intact.
