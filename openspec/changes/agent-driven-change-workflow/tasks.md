Skills are written in the order the workflow uses them, and each is proven on a
pilot before the next is written. `capacity-shape-envelope` runs the whole
sequence; `add-full-stack-ci-job` proves design and planning from a bare proposal.
A pilot task records what the skill produced and what, if anything, the owner had
to repair by hand.

## 1. Shared skill source

- [x] 1.1 Create `.agents/skills/` as the single skill source, with relative links
      from `.claude/skills/` and `.codex/skills/`. `debug-attended-lane`, until now
      Claude Code's alone, is linked for Codex too. Both harnesses were confirmed
      to load all seven skills through the links.
- [x] 1.2 Resolve the dangling Stripe skill links: removed. The eight links
      (`stripe-*`, `upgrade-stripe`, `connect-*`) were committed incidentally,
      pointing at a skill installation that never entered the repository, so they
      resolved for no one.
- [x] 1.3 Decide whether the generated OpenSpec skills move behind links: they do.
      In a scratch clone, `openspec update` (1.6.0) wrote through the links,
      leaving them in place and the content byte-identical, and wrote nothing else.
- [x] 1.4 Add `make check-agent-skills` (`scripts/check_agent_skills.py`, tests in
      `scripts/tests/test_check_agent_skills.py`): every shared skill has a
      `SKILL.md` and a link in every harness, no harness holds a copy, and every
      link resolves to the shared skill of its own name. Amended: there is no
      general check aggregate to wire it into — `check-packaging` aggregates
      packaging checks only — so `change-closeout` runs it among closeout's
      mechanical checks (9.1).
- [x] 1.5 Add `reviews/` directories under `openspec/changes/`, archived ones
      included, to `.gitignore`; confirmed for an active and an archived path.

## 2. Index format

- [ ] 2.1 Replace every change table's status cell in `openspec/changes/README.md`
      with `Status`, `Depends on`, and `Notes` columns, checking each row against
      its own change's `proposal.md`, `design.md`, and `tasks.md` rather than
      transcribing its prose, and naming the gated phase of every dependency that
      gates earlier than implementation. List for the owner every row whose
      recorded state the change does not support.
- [ ] 2.2 Rewrite the index's status definitions to the phase-and-state vocabulary
      and the `Depends on` rule.
- [x] 2.3 Amend part 6 (campaign index currency) of
      `openspec/README.md#plan-closeout-requirements` with the dependency-landing
      step: remove the completing change from every dependent's `Depends on`,
      return each dependent not yet implementing to `ready for design`, and record
      reverification as owed on a `blocked in` dependent rather than overwriting it.

## 3. Design discussion

- [ ] 3.1 Write the `change-design` skill: the context preload, numbered open
      questions with options, trade-offs, and a recommendation, no file edits until
      the owner settles the design, then decisions recorded in `design.md` and
      `proposal.md` amended when scope moves; it moves the index row to `in design`
      when discussion starts.
- [ ] 3.2 Pilot: resolve `capacity-shape-envelope`'s open questions; the owner
      judges depth against a browser session on the same questions.
- [ ] 3.3 Pilot: design `add-full-stack-ci-job` from its proposal.

## 4. Change review

- [ ] 4.1 Write the `change-review` skill, taking the review kind (`design`,
      `implementation`, `pre-closeout`, `closeout`) and the change: documents to
      read first, the diff to inspect, the questions per kind tagged by lens,
      prompting for the `direction` lens as design discussion and for the
      compliance lenses as exhaustive cited checking, reading earlier reviews and
      triage from `reviews/`, and producing one Markdown review whose findings
      carry lens, basis, severity, and evidence in the fixed field layout.
- [ ] 4.2 Add `make review CHANGE=<change> KIND=<kind>`, running the skill in Codex
      non-interactively with a read-only sandbox and capturing its final message
      as the next numbered file in `reviews/`.
- [ ] 4.3 Pilot: design review of `capacity-shape-envelope`, also run through the
      browser process. Passes if no `blocking` or `should` browser finding the
      owner accepts is absent from the harness review.
- [ ] 4.4 Pilot: design review of `add-full-stack-ci-job`.

## 5. Review triage and the intervention ledger

- [ ] 5.1 Write the `change-triage` skill: a position with evidence on every
      finding, every finding presented ordered by lens then severity, owner
      dispositions recorded in the triage file, one line per disposition appended
      to the change's tracked `interventions.jsonl` naming the `tasks.md` section
      it concerns, and accepted outcomes folded into `design.md` or `tasks.md`.
      It asks the owner whether the review's gate is passed, records the answer in
      the triage file, and, when a phase-closing gate passes, moves the index row
      to the next phase's `ready for` status per the transition table in
      `design.md`.
- [ ] 5.2 Pilot: triage the 4.3 and 4.4 reviews, passing each design gate.

## 6. Planning

- [ ] 6.1 Write the `change-plan` skill on top of `openspec-update-change`: tasks
      from the design that passed review, completed tasks preserved and amended
      rather than replaced, the files each accepted decision touches, the
      validation each section owes, each decision's permanent destination, and the
      closeout task; each section ending at a verification point and sized to be
      implemented in one fresh session. It moves the index row to `in planning`
      when planning starts and to `ready for implementation` when the owner
      accepts the plan.
- [ ] 6.2 Pilot: amend `capacity-shape-envelope`'s existing plan to its reviewed
      design.
- [ ] 6.3 Pilot: plan `add-full-stack-ci-job` from nothing.

## 7. Implementation

- [ ] 7.1 Write the `change-implement` skill: one `tasks.md` section per fresh
      session, starting from the guidance documents, the change, and that section;
      preserving completed tasks; comment rules stated locally; a clean stop that
      records why and commits nothing partial when discovered code invalidates the
      plan; a handoff in the section's task notes; and, before committing the
      finished slice unreviewed, `make lock`, `make check-packaging`,
      `make check-comment-hygiene`, the scoped `make check-doc-citations`, and a
      fresh-context subagent checking the section's diff against `AGENTS.md`,
      `docs/development/ARCHITECTURE.md`, `docs/development/TESTING.md`,
      `docs/development/DEPLOYMENT_AND_CONFIG.md`, `openspec/README.md`, and the
      permanent specification and architecture companion of every capability the
      section touches. It moves the index row to `in implementation` when the
      first section starts. Decide whether it wraps or replaces
      `openspec-apply-change`.
- [ ] 7.2 Add a committed Claude Code project hook that, when a session resumes
      after compaction, re-reads the required guidance documents and restates the
      change and section being worked.
- [ ] 7.3 Pilot: implement the first section of `capacity-shape-envelope` in its
      own session, recording what the fresh-context check caught.

## 8. Pre-review validation

- [ ] 8.1 Add a `make` target running `make check-packaging` and `make test`,
      failing if the worktree is not clean before or after, and stopping at the
      first failure with a summary.
- [ ] 8.2 Add `make check-push-ready`: refuse a detached `HEAD`, a dirty worktree,
      `main` or `dev`, and an upstream named differently from the local branch;
      report and never repair.
- [ ] 8.3 Make end-to-end log fetching select the run whose head commit is the
      local `HEAD`, waiting with a bound for a just-dispatched run to appear,
      instead of the newest run on the branch, with tests for both gaps.
- [ ] 8.4 Write the `change-validate` skill: the local target; when owed, the Helm
      part (`make -C helm test-render` with the VM storefront environment present,
      `make build-dev`, `helm/` deploy and forward, `e2e-tests/` test-module,
      unforward); `make check-push-ready`, pushing exactly `HEAD` unforced, the
      end-to-end workflow, and its logs; diagnosis of a failing scenario from its
      logs; and `reviews/NN-validation.md`.
- [ ] 8.5 Pilot: validate the 7.3 slice, then run an implementation review and
      triage on it with the section 4 and 5 skills; the change stays
      `in implementation`.

## 9. Closeout and archival

- [ ] 9.1 Write the `change-closeout` skill over the ten parts of
      `openspec/README.md#plan-closeout-requirements`, running each mechanical part
      and reporting the parts that need judgement, including
      `make check-agent-skills`; it moves the index row to
      `in closeout` when closeout starts.
- [ ] 9.2 Write the `change-ship` skill: archival with the intervention ledger kept
      and `reviews/` deleted, and drafting the commit message and pull request
      description from the proposal, the promotion record, and the validation
      evidence; it moves the index row to `archived`.
- [ ] 9.3 Pilot: implement `capacity-shape-envelope`'s remaining sections, one
      session each, then
      pre-closeout review and triage, closeout, closeout review and triage, and
      archival.

## 10. Shared guidance

- [ ] 10.1 Remove the "Generated implementation artifacts" section and the fileset
      wording from `AGENTS.md`, and the tombstone item from the
      `openspec/README.md` completion checklist. Confirm the browser session
      prompts still carry the whole tombstone convention, including that no
      tombstone survives into production code or permanent documentation.
- [ ] 10.2 Write `docs/agents/change-workflow.md`: invoking each leaf skill and
      `make review`, the review file layout, and the ledger; link it from
      `AGENTS.md`'s "Agent skills" section.
- [ ] 10.3 Confirm no committed skill refers to `docs/prompts/`.

## 11. Closeout

- [ ] 11.1 Comment hygiene: `make check-comment-hygiene`.
- [ ] 11.2 Import placement: review the imports this change added or touched,
      including in `scripts/fetch-e2e-logs.py`.
- [ ] 11.3 Documentation compliance: re-check this change's decisions against
      `openspec/README.md`'s placement rules.
- [ ] 11.4 Narrative compression of completed-task notes.
- [ ] 11.5 Roadmap currency: record that no roadmap goal is affected, or update it.
- [ ] 11.6 Campaign index currency: this change's row, including the
      dependency-landing step for any dependent.
- [ ] 11.7 Documentation citations: `make check-doc-citations CHANGE=agent-driven-change-workflow`.
- [ ] 11.8 Packaging: `make check-packaging`.
- [ ] 11.9 End-to-end pipeline: record a passing run and the scenarios it covers,
      or an explicit blocker naming its cause and owner.
- [ ] 11.10 Resolve the open question on exporting session transcripts and review
      logs: how `change-ship` confirms the export ran before `reviews/` is deleted,
      and whether permanent documentation states that they are exported.
- [ ] 11.11 Promotion: complete the design-promotion record against the proposal's
      knowledge-to-promote list — `change-workflow` spec and architecture
      companion, the three `planning-governance` requirements, closeout part 6,
      `AGENTS.md`, `docs/agents/change-workflow.md`, and a `change-workflow` row
      linking the spec and architecture companion in `openspec/specs/README.md`.
