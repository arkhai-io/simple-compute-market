# Pass the checks at every commit

## Why

Every commit a step makes runs `scripts/change-workflow run pre-commit <change>`:
the workflow's default checks, then the repository's closing checks. The owner
prefers a change planned so that those checks pass at every commit. In practice a
step often commits while some of them fail, and only design says anything about it:
a citation of a file the change itself will create is expected
(`.agents/skills/change-design/SKILL.md`). Planning's own completion check admits
the same failure and no other. No other step has a rule, so each decides for itself
whether a failure may be committed through.

`add-skill-extension-points` met every kind of such failure:

- **A failure the change's stage makes expected.** The change's deltas added sixteen
  requirements to `change-workflow`. The index check
  (`scripts/check_spec_index.py`, run among the closing checks) counts a named
  change's deltas as the archive will leave them, so an id the deltas add must
  already be listed in the capability's `index.md`. Closeout's promotion writes
  those entries, so the check failed at the design commit, at both design triages'
  commits, and at planning's. Planning then moved writing the entries forward into
  the change's first task, so that implementation's commits could pass. Citations
  of files the change would create failed the citation check alongside it.
- **A failure inherited from the base.** A comment in
  `scripts/tests/test_change_workflow_log.py`, from a commit the change never
  touched, failed the comment check at every commit until the change's first
  section fixed it as a defect found.
- **A failure a step caused or knowingly left.** The owner lifted the step table's
  deny rules on the configuration and on `.claude/` so the implementation session
  could edit both. Two step-table tests that hold those rules failed in every
  `make test` that session ran, and it committed through them until the
  orchestrating session restored the rules.

## What Changes

- **The index check stops failing on requirement ids the change's own deltas add,
  until closeout.** While the named change has not reached closeout, an id its
  deltas add or rename to that the capability's `index.md` does not list is not a
  failure. From closeout on, which writes the entries, it is, as today. How the
  check learns the change's phase — its status in the change index, or an argument
  the closing checks pass — is settled in design.

## Open questions

Each is for design to settle with the owner, or to leave to a change of its own:

- **Planning for passing checks.** Should the workflow require a plan whose every
  commit can pass the checks, and what does planning do when a section cannot —
  such as an edit to a file every step is denied, which the owner grants for one
  session?
- **Citations of files the change will create.** Is this failure still expected,
  should the citation check learn the change's own planned files as the index check
  learns its deltas, or should design and planning avoid citing what does not yet
  exist?
- **A failure inherited from the base.** May a step commit through it, naming it in
  its report and recording it as a defect found — fixed in the change's next
  section, or given a row in the change index — or must the change fix it before
  its first commit?
- **A failure a step caused or knowingly left.** Is it ever committed, for example
  when the owner approved it for one run, and how does the step's report and the log
  record that approval?
- **Where the rule lives.** The workflow's guidance read by every step
  (`docs/guidance/workflow/changes.md`), each step's skill, or the engine, which
  could refuse a commit whose pre-commit failed outside what the rule admits.

## Public interfaces

Each is named here as `docs/guidance/workflow/changes.md` requires; whether each
change is compatible is settled in design:

- the index check's behaviour, `make check-spec-index CHANGE=<change>` and the
  closing checks that run it;
- `scripts/change-workflow run pre-commit`, if the engine comes to hold the rule;
- the skills of the steps that commit.

## Capabilities

### New Capabilities

- None expected.

### Modified Capabilities

- `market-change-workflow`: the repository's closing checks, among them the index
  check.
- `change-workflow`: if the rule on committing through a failing check becomes the
  workflow's.

## Non-Goals

- **Do not weaken a check at closeout.** Every check passes from closeout on, as
  today.
- **Do not decide the open questions here.** The proposal records them; design
  settles them with the owner.

## Impact

- `scripts/check_spec_index.py` and its tests.
- The steps' skills and the workflow's guidance, depending on the open questions.
- `openspec/README.md`, "The index check".

## Dependencies and Related Changes

- **Independent:** nothing must land first.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `market-change-workflow`, and
  `change-workflow` if the rule becomes the workflow's
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion.
