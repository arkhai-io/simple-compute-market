# Design: take a change in from outside the workflow

Status: design phase. Not planned. "Settled with the owner" came from the discussion
that opened the change, after the owner took over pull requests #349, #350, #351 and
#354. Design confirms it and settles the proposed decisions and open questions.

## Context

- **What the four takeovers needed.** Each pull request was an OpenSpec change
  implemented outside the workflow, stacked on the one before. None had a design
  review, and none had workflow records here. For each change, the owner:
  - created a clone on a `review/<change>` branch cut at the pull request's head,
    recording the parent pull request's branch, or `dev` for the bottom one, as the
    branch it lands on;
  - held a design discussion in the clone over the decisions taken during
    implementation;
  - recorded the round after the fact (`note <change> round --after 0`), the owner's
    direction waiving the design review, and the discussion as the round's owner
    record;
  - started `make orchestrate` in a fresh session.
  Once a change below landed, the next one was rebased onto the landing branch and
  its clone's recorded base changed to it. Each session got its instructions from a
  message written by hand.
- **Mechanisms that already carried it.** A round recorded after the fact, the owner
  record triage reads with the review and the validation, the owner's directions,
  and a clone's recorded landing branch. No graph change was needed.
- **What the engine lacked.** Changing a clone's recorded landing branch meant
  editing `change-clone.json` by hand.
- **What went wrong along the way, and was handled by hand:**
  - the workspace's engine was older than the stack's and refused its configuration;
  - the author rebased and force-pushed mid-review, so review branches cut earlier
    were stale;
  - the author built follow-on pull requests on an old head, which were replayed into
    the review branch;
  - a squash merge of the change below stranded the next change on a commit the
    landing branch never received;
  - telling a failure the change caused from one it inherited needed the failing test
    run at the parent's commit;
  - an implementation review waits for the change it depends on to be archived, so
    reviews ran bottom-up while design discussions ran in parallel.

## Settled with the owner

- **D1. Two skills.** `change-intake` runs in the owner's workspace, outside any
  change's steps, as `guidance-review` does. It surveys, sets up, and restacks.
  `change-intake-design` runs in the change's clone, one session per change. They are
  separate because the design discussion forms views on decisions while the
  orchestrator must not, and because each session does one job and stops. The name
  "coordinator" is not used: it names the agent above orchestrators that coordinates
  dependent changes across repositories.
- **D2. The intake prepares; the owner orchestrates.** The intake determines where the
  previous owner left the change and restores only what the workflow needs to
  continue the change from that point. That covers a contributor's pull request and a
  change whose records were lost. It ends with the change ready for `make orchestrate`,
  which the owner runs separately.
- **D3. The intake design reviews decisions after the fact and edits nothing.** It
  takes stock of the decisions taken without a design review and discusses each one
  with the owner. It records the round after the fact, the owner's waiver of the
  design review, and the discussion as the round's owner record. It checks that the
  next-step computation names validation and the implementation review, and it stops.
  Triage carries out the outcomes. The intake calls for it only when it finds such
  decisions.
- **D4. One engine addition.** A supported command changes a clone's recorded landing
  branch. The survey and the restack's Git work stay in the skill's prose, because
  they are judgement.
- **D5. Generic.** The skills are written to the workflow's abstractions: the
  configured hooks (the pre-commit with its functional checks, validation's parts),
  the record set and the engine's commands. They name no target of this repository.
  The forge, GitHub through `gh`, is their one named external assumption.
- **D6. The landing policy is asked at intake.** The default is to push the reviewed
  work to a review branch, which the owner merges onto the pull request's branch
  before merging that to the landing branch. The alternative is to push onto the pull
  request's branch directly. The owner chooses per intake.
- **D7. Working instructions live in the skills and the guidance.** A session started
  in a clone reads no personal memory. So everything the skills need, including how a
  decision is presented and when it counts as settled, comes from the skills and the
  workflow's guidance, as it does for the skills orchestration calls. Colleagues get
  the same behaviour. A rule the skills need that the guidance lacks is added to the
  guidance.
- **D8. Delivered as this change,** through the workflow's design review.

## Proposed decisions

- **P1. Stacks.** The intake maps a stack of pull requests to their changes and sets
  up one clone per change, each recording its parent's branch as the branch it lands
  on. Its restack mode runs once a parent lands:
  - rebase onto the landing branch from the parent's old commit;
  - change the clone's recorded landing branch;
  - run the configured functional checks;
  - tell an inherited failure from the change's own by running it at the parent's
    landed commit;
  - push as D6 chose.
- **P2. Drift.** At setup and at each restack, the intake compares each pull request's
  head with the review branch cut from it. A review branch with no work of the
  owner's is reset to the new head. Follow-on pull requests built on an old head are
  found and replayed, keeping their authorship, on the owner's word.
- **P3. Engine compatibility first.** Before creating any clone, the intake checks that
  the workspace's engine accepts the change's workflow configuration. A mismatch
  stops the intake with the branch to check out.
- **P4. Context from below.** The intake design reads the owner records of the changes
  below it in the stack. Points that depend on a lower change still in triage are
  marked as depending on it. Contradictions with the owner's other plans go into the
  owner record as notes for triage.
- **P5. What orchestration needs travels in files.** The orchestrator recovers from
  files, so anything orchestration needs travels as points of the owner record or as
  the owner's directions in the log, never as a pasted opener. An example is the rule
  to check a finding against the top of the stack and defer it when a later change
  rewrote the code.

## Open questions

- **Does the intake write a record of its own?** For example `reviews/NN-intake.md`,
  holding the survey, what was restored, and why. Recommendation: yes, so later
  reviewers and the orchestrator can see what the intake found and did. That makes it
  a new kind in the record set, judged against `CW-c2tw`.
- **Serial reviews of a stack.** An implementation review waits for the change it
  depends on to be archived. Should the intake be able to start a review early, over
  code the lower change's triage may still change? Recommendation: no. Keep reviews
  serial and run design discussions in parallel, as the four takeovers did.
- **Which state a change is in.** The intake must tell apart a change left in design,
  one designed but not reviewed, one implemented without records, and one with
  partial records. Which signals decide each, and which of them the engine should
  compute rather than the skill infer, is for design.
