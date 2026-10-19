## Why

The change workflow assumes one change is worked at a time on one machine. Each
step runs in the checkout it is started from and describes that checkout's
`HEAD`, and validation states outright that one change is validated at a time,
taking full control of the Docker daemon, the kube context, the release in it, and
the port-forwards. Working two changes in parallel — one in implementation while
another is reviewed, validated, or closed out — collides on every shared resource:

- **The branch.** A checkout holds one branch, and every skill checks that the
  checked-out branch carries the change it works on. Two changes in flight mean
  switching branches between sessions, or a second checkout. A second checkout as a
  sibling worktree was tried for the round view and rejected: each one has to be
  added to the editor's workspace as another project, which is worse than reading
  and testing changes in the existing project.
- **Reading a round after it is committed.** `make round-view` shows a round as
  uncommitted changes by resetting the checked-out branch to the round's base.
  Reading one change's round while another change's branch is checked out has no
  path today, and the reset itself moves whatever branch is checked out.
- **Helm validation.** `make validate-helm` deploys one release
  (`arkhai-node-operator`) to one namespace (`default`) in the allowed kube context,
  uninstalls whatever release it finds there, requires that no release volume is
  retained, and forwards fixed local ports (8545, 8080, 8001, 8081). Two validations
  at once uninstall each other's release and contend for the same ports.
- **Other static resources.** The wheelhouse in `.dist`, which every validation
  part rebuilds with `make dist-clean`; in-tree project environments (`.venv`);
  locally built image tags; the storefront environment validation reinstalls; the
  Docker daemon and CPU the local and Helm parts already run one after the other to
  share; and the evidence directories under `.snapshot/`, keyed by commit.

The end-to-end pipeline itself is per branch: its concurrency group cancels an
earlier run of the same ref, not of another branch.

## What Changes

- Let more than one change be worked at once, each on its own branch, with every
  workflow step — design, planning, implementation, review, round reading,
  validation, triage, closeout — able to run for one change while another change's
  branch is in use, without one step's state, evidence, or deployment disturbing
  the other's.
- Let the owner read a change's committed round, and run its tests in place, while
  another change is being worked, in a way the owner finds no worse than the
  current in-checkout round view.
- Give each Helm validation its own namespace — and with it its own release,
  volumes, and port-forwards — so two validations run side by side, and clean up
  only what that validation created.
- Inventory every other resource two parallel changes would share, and make each
  per change, safely shared, or explicitly serialized with a refusal that names the
  holder.
- Its pilots also verify what `agent-driven-change-workflow`'s could not: design
  discussion, design review, and planning (`change-plan`) from a proposal alone,
  since this change starts from one.

## Capabilities

### Modified Capabilities

- `change-workflow`: the workflow steps run per change rather than per checkout,
  and validation runs in its own namespace. The capability's permanent spec is
  created by `agent-driven-change-workflow`'s closeout.

## Non-Goals

- An orchestrating skill that schedules several changes; that is the later change
  `agent-driven-change-workflow` names.
- Running two changes' end-to-end pipelines on one branch.

## Open questions

- Whether parallel changes use separate worktrees, a checkout that switches
  branches between sessions, or another arrangement, given that a worktree per
  change means another editor project per change.
- How the owner reads a committed round for a change whose branch is not checked
  out.
- Whether a round's validation and implementation review can run while the owner
  reads it. Both describe the checkout's `HEAD`, which the round view moves to the
  round's base, so today they start only at `make round-done`, and only the
  end-to-end pipeline overlaps the reading. Running them against the round's head
  somewhere the owner never opens, such as a worktree, raises the same questions
  as a second change: the ignored `reviews/` directory the reviewer reads and
  validation writes, the environments a fresh checkout must build, and which
  resources the two share.
- Which resources must be per change and which may be shared with a lock: the
  wheelhouse, project environments, image tags, the storefront environment, the
  Docker daemon, and the kube context.
- Whether a namespace per validation needs the chart's out-of-band Secrets in each
  namespace, which `helm-e2e-pipeline-parity` may make optional.

## Dependencies and Related Changes

- Depends on `agent-driven-change-workflow`, whose skills, Make targets, round
  view, and validation scripts this change makes parallel.
- Related to `helm-e2e-pipeline-parity`, which owns the charts and values a
  per-namespace validation deploys, and the open question of making the chart's
  out-of-band Secrets optional.

## Impact

`.agents/skills/change-*`, the workflow Make targets, `scripts/round_view.py`,
`scripts/validate_slice.py`, `helm/Makefile`'s release, namespace, and forwarding
targets, and the `change-workflow` specification. No service code changes.
