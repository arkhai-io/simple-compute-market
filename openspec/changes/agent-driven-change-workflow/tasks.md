Each leaf skill is proven on the pilot, `capacity-shape-envelope`, before a later
section depends on it. Sections 3 onward record the pilot evidence that proves them.

## 1. Shared skill source

- [ ] 1.1 Create `.agents/skills/` as the single skill source, with relative links
      from `.claude/skills/` and `.codex/skills/`.
- [ ] 1.2 Resolve the dangling Stripe skill links: commit their source under
      `.agents/skills/`, or remove them.
- [ ] 1.3 Decide whether the generated OpenSpec skills move behind links, by
      testing whether regeneration overwrites a link.
- [ ] 1.4 Add `make check-agent-skills`: every skill is present for every harness,
      every link resolves, and no harness directory holds a copy of a skill that
      has a shared source. Wire it into the existing check aggregate.
- [ ] 1.5 Add `reviews/` directories under `openspec/changes/`, archived ones
      included, to `.gitignore`.

## 2. Index format and priority

- [ ] 2.1 Replace every change table's status cell in `openspec/changes/README.md`
      with `Status`, `Depends on`, and `Notes` columns, checking each row against
      its own change's `proposal.md`, `design.md`, and `tasks.md` rather than
      transcribing its prose. List for the owner every row whose recorded state
      the change does not support.
- [ ] 2.2 Rewrite the index's status definitions to the phase-and-state vocabulary
      and the `Depends on` rule.
- [ ] 2.3 Add the campaign priority list at the top of the index.
- [ ] 2.4 Amend part 6 (campaign index currency) of
      `openspec/README.md#plan-closeout-requirements`: a completing change removes
      itself from every dependent's `Depends on` and returns each dependent that
      has not begun implementation to `ready for design`.

## 3. Change review

- [ ] 3.1 Write the finding schema: lens, basis, severity, claim, cited evidence,
      suggested action.
- [ ] 3.2 Write the `change-review` skill, taking the review kind (`design`,
      `implementation`, `pre-closeout`, `closeout`) and the change: documents to
      read first, the diff to inspect, the questions per kind tagged by lens,
      prompting for the `direction` lens as design discussion, reading earlier
      reviews and triage from `reviews/`, and writing prose and structured findings.
- [ ] 3.3 Add `make review CHANGE=<change> KIND=<kind>`, running the skill in Codex
      non-interactively with a read-only sandbox and writing the next numbered
      files into `reviews/`.
- [ ] 3.4 Pilot: a design review of `capacity-shape-envelope`, compared against a
      browser-process review of the same design for missed or extra findings.

## 4. Review triage and the intervention ledger

- [ ] 4.1 Write the `change-triage` skill: a position with evidence on every
      finding, every finding presented ordered by lens then severity, owner
      dispositions recorded in the triage file, one line per disposition appended
      to the change's tracked `interventions.jsonl`,
      accepted outcomes folded into `design.md` or `tasks.md`.
- [ ] 4.2 Pilot: triage the 3.4 review.

## 5. Design discussion

- [ ] 5.1 Write the `change-design` skill: the context preload, numbered open
      questions with options, trade-offs, and a recommendation, no file edits until
      the design is settled, then decisions recorded in `design.md` and
      `proposal.md` amended when scope moves.
- [ ] 5.2 Pilot: resolve `capacity-shape-envelope`'s open questions, compared
      against a browser session on the same questions for depth.

## 6. Pre-review validation

- [ ] 6.1 Add a `make` target running `make lock`, `make check-packaging`, and
      `make test`, stopping at the first failure with a summary.
- [ ] 6.2 Make end-to-end log fetching select the run whose head commit is the
      local `HEAD`, waiting with a bound for a just-dispatched run to appear,
      instead of the newest run on the branch.
- [ ] 6.3 Write the `change-validate` skill: the local target; pushing the
      change's own branch, the end-to-end workflow, and its logs; the Helm half
      (`make build-dev`, `helm/` deploy and forward, `e2e-tests/` test-module,
      unforward) when owed; diagnosis of a failing scenario from its logs; and
      `reviews/NN-validation.md`.
- [ ] 6.4 Pilot: validate the first implementation slice of
      `capacity-shape-envelope`, then run an implementation review and triage on it.

## 7. Implementation

- [ ] 7.1 Write the `change-implement` skill: one `tasks.md` section per slice,
      preserving completed tasks, stopping for design when discovered code
      invalidates the plan, comment rules stated locally, ending with
      committing the finished slice unreviewed, then `change-validate`. Decide
      whether it wraps or replaces `openspec-apply-change`.
- [ ] 7.2 Pilot: implement `capacity-shape-envelope` through its remaining
      sections, with a pre-closeout review and triage.

## 8. Closeout and archival

- [ ] 8.1 Write the `change-closeout` skill over the ten parts of
      `openspec/README.md#plan-closeout-requirements`, running each mechanical part
      and reporting the parts that need judgement.
- [ ] 8.2 Write the `change-ship` skill: archival, deleting `reviews/`, and drafting
      the commit message and pull request description from the proposal, the
      promotion record, and the validation evidence.
- [ ] 8.3 Pilot: close out, closeout-review, triage, and archive
      `capacity-shape-envelope`.

## 9. Shared guidance

- [ ] 9.1 Remove the "Generated implementation artifacts" section and the fileset
      wording from `AGENTS.md`, and the tombstone item from the
      `openspec/README.md` completion checklist.
- [ ] 9.2 Document the leaf skills, the review flow, and the ledger in
      `docs/agents/`, linked from `AGENTS.md`'s "Agent skills" section.
- [ ] 9.3 Confirm no committed skill refers to `docs/prompts/`.

## 10. Closeout

- [ ] 10.1 Comment hygiene: `make check-comment-hygiene`.
- [ ] 10.2 Import placement: confirm no Python import was added or touched.
- [ ] 10.3 Documentation compliance: re-check this change's decisions against
      `openspec/README.md`'s placement rules.
- [ ] 10.4 Narrative compression of completed-task notes.
- [ ] 10.5 Roadmap currency: record that no roadmap goal is affected, or update it.
- [ ] 10.6 Campaign index currency: this change's row and the priority list.
- [ ] 10.7 Documentation citations: `make check-doc-citations CHANGE=agent-driven-change-workflow`.
- [ ] 10.8 Packaging: `make check-packaging`.
- [ ] 10.9 End-to-end pipeline: record the run, or record that this change alters
      no pipeline behaviour.
- [ ] 10.10 Promotion: complete the design-promotion record, including the four
      `planning-governance` requirements and the `docs/agents/` documentation.
