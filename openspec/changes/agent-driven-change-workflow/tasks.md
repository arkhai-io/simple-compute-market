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
      mechanical checks (10.1).
- [x] 1.5 Add `reviews/` directories under `openspec/changes/`, archived ones
      included, to `.gitignore`; confirmed for an active and an archived path.

## 2. Index format

- [x] 2.1 Replace every change table's status cell in `openspec/changes/README.md`
      with `Status`, `Depends on`, and `Notes` columns, checking each row against
      its own change's `proposal.md`, `design.md`, and `tasks.md` rather than
      transcribing its prose, and naming the gated phase of every dependency that
      gates earlier than implementation. List for the owner every row whose
      recorded state the change does not support. 88 rows migrated by a
      fresh-context agent and checked mechanically (vocabulary, dependency
      targets). Rows the change files contradicted were corrected, among them
      `bare-metal-mock-provisioned-deal` (recorded "not planned", 55 tasks done)
      and `repair-storefront-alkahest-configuration` (recorded "implemented",
      tasks open). By owner decision every change not already implementing is
      `ready for design`, and external-verification waits are `blocked in
      closeout` (see `design.md`). Dependencies inferred from proposals were added
      where the old cells omitted them. Contradictions between two changes' own
      dependency claims are left for each change's design review, recorded in
      `Notes` where the migration noticed them. Index prose that contradicted the
      rows was corrected, and a pre-existing malformed table repaired.
- [x] 2.2 Rewrite the index's status definitions to the phase-and-state vocabulary
      and the `Depends on` rule.
- [x] 2.3 Amend part 6 (campaign index currency) of
      `openspec/README.md#plan-closeout-requirements` with the dependency-landing
      step: remove the completing change from every dependent's `Depends on`,
      return each dependent not yet implementing to `ready for design`, and record
      reverification as owed on a `blocked in` dependent rather than overwriting it.

## 3. Design discussion

- [x] 3.1 Write the `change-design` skill: the context preload, numbered open
      questions with options, trade-offs, and a recommendation, no file edits until
      the owner settles the design, then decisions recorded in `design.md` and
      `proposal.md` amended when scope moves; it moves the index row to `in design`
      when discussion starts. Written at `.agents/skills/change-design/`; it also
      refuses to start while a dependency gating design is unlanded, checks for
      drift since an earlier design, and leaves `tasks.md` to planning.
- [ ] 3.2 Pilot: resolve `capacity-shape-envelope`'s open questions; the owner
      judges depth against a browser session on the same questions. First
      response compared: the skill matched the browser session on every shared
      point and raised a conceptual error, a guidance violation, and a false
      claim the browser missed; the browser alone raised a double-claimed call
      site and separate reporting of inadmissible shapes. Amended the skill at
      the owner's direction: open with a summary of the change, then
      corrections, then each decision as context, alternatives, and a
      recommendation with its reason. After the design was recorded, the owner's
      review of the session amended it again: decisions are classified as
      judgement, consequence, or convention, with the latter two batched;
      documentation placement is never asked; absence of a caller is not on its
      own a reason to leave a capability out; representations are shown as
      concrete example documents; every caller is walked through a new
      interface; a corrected premise reopens the decision resting on it; the
      owner's redirections are logged to the ledger; and before recording, the
      rationales, callers, scope growth, and unrecorded principles are checked
      as a whole.
- [ ] 3.3 Pilot: design `add-full-stack-ci-job` from its proposal.

## 4. Change review

- [x] 4.1 Write the `change-review` skill, taking the review kind (`design`,
      `implementation`, `pre-closeout`, `closeout`) and the change: documents to
      read first, the diff to inspect, the questions per kind tagged by lens,
      prompting for the `direction` lens as design discussion and for the
      compliance lenses as exhaustive cited checking, reading earlier reviews and
      triage from `reviews/`, and producing one Markdown review whose findings
      carry lens, basis, severity, and evidence in the fixed field layout.
      Written at `.agents/skills/change-review/`. Beyond the owner's questions,
      the design review also walks every caller through each new interface,
      checks each rationale against the other decisions, and compares scope with
      the original proposal — the gaps the first pilot design discussion left.
- [x] 4.2 Add `make review CHANGE=<change> KIND=<kind>`, running the skill in Codex
      non-interactively with a read-only sandbox and capturing its final message
      as the next numbered file in `reviews/`.
      `scripts/run_change_review.py`, tests in
      `scripts/tests/test_run_change_review.py`. The full session goes to
      `reviews/NN-<kind>.log` beside the review, for the session export. The
      implementation kinds take `REVIEW_BASE` (default `dev`); `MODEL` overrides
      the Codex model. A failed or empty run leaves no review record.
- [x] 4.2a Amended after implementation review 1 (browser): the reviewer's
      session moved to `reviews/transcripts/`, which no review or triage step
      reads, so the Markdown review stays the only record of its findings; the
      reviewer writes to a draft that is published only when it has the review
      format (title, ordered sections, four fields per finding with allowed
      values), and anything else is kept as `NN-<kind>.rejected.md` beside the
      transcript; a failed run keeps its number. `make code-snapshot` now stores
      symlinks as links (`zip -y`), guarded by
      `scripts/tests/test_code_snapshot.py`, which fails without the flag. The
      ledger schema now covers design redirections (`design.md`, the
      `change-workflow` delta).
- [x] 4.2b A re-review continues its reviewer: `make review` resumes the session
      that wrote the latest review of the same kind, read-only through
      configuration (verified to refuse writes), named by a session comment in
      each published record; `FRESH=1` starts a new reviewer. `change-triage`
      amended after its second use: findings that depend on an open decision are
      held from the first pass, review findings are always logged under their
      own review, revised dispositions name what they revise, the count of
      ledger entries written is reported, and a re-review is recommended when
      dispositions changed a central decision. `make review` also streams a
      condensed progress view to the terminal — session header, each command,
      failures, errors, and the agent's messages cut to four lines — while the
      transcript keeps everything.
- [ ] 4.3 Pilot: design review of `capacity-shape-envelope`, also run through the
      browser process. Passes if no `blocking` or `should` browser finding the
      owner accepts is absent from the harness review.
- [ ] 4.4 Pilot: design review of `add-full-stack-ci-job`.

## 5. Review triage and the intervention ledger

- [x] 5.1 Write the `change-triage` skill: a position with evidence on every
      finding, every finding presented ordered by lens then severity, owner
      dispositions recorded in the triage file, one line per disposition appended
      to the change's tracked `interventions.jsonl` naming the `tasks.md` section
      it concerns, and accepted outcomes folded into `design.md` or `tasks.md`.
      It asks the owner whether the review's gate is passed, records the answer in
      the triage file, and, when a phase-closing gate passes, moves the index row
      to the next phase's `ready for` status per the transition table in
      `design.md`.
      Written at `.agents/skills/change-triage/`. It also saves a pasted external
      review as the next numbered record (`NN-<kind>-external.md`) and triages
      it beside the harness review of the same kind, merging duplicate findings;
      classifies each accepted finding's outcome as an edit, a design decision
      (sent to `change-design`, never settled in triage), a task, or none; and
      never dismisses a finding that challenges an owner decision on the
      grounds that the owner made it. Amended after its first use, where the owner could
      not decide from the triage without opening the review: each finding now
      states what the change says now, the reviewer's reasoning, why it matters,
      and the agent's position in prose; findings needing no choice are
      confirmed in one batch, and each finding needing a design choice is
      presented alone with its alternatives, so choosing the option is the
      disposition; one label per issue throughout. `change-design` now triages
      waiting reviews before opening its own discussion.
- [ ] 5.2 Pilot: triage the 4.3 and 4.4 reviews, passing each design gate.

## 6. Planning

- [x] 6.1 Write the `change-plan` skill on top of `openspec-update-change`: tasks
      from the design that passed review, completed tasks preserved and amended
      rather than replaced, the files each accepted decision touches, the
      validation each section owes, each decision's permanent destination, and the
      closeout task; each section ending at a verification point and sized to be
      implemented in one fresh session. It moves the index row to `in planning`
      when planning starts and to `ready for implementation` when the owner
      accepts the plan.
      Written at `.agents/skills/change-plan/`. Built to continue the design
      session, at the owner's preference, for its context; to keep the plan
      standing on the record, it first writes into `design.md` anything a task
      relies on that only the discussion holds, and stops for design on any
      question the design did not answer. It settles the provisional
      documentation destinations the design delegated to planning, and logs
      plan redirections to the ledger as `"review": "plan"`. Amended after
      implementation review 2 (browser): a design question planning exposes
      returns the change to design, and planning resumes after another design
      review or the owner's recorded waiver of it (also in the `change-workflow`
      delta); the gate evidence — index row and latest design triage — is read
      from files before planning starts; completed tasks may be amended or
      corrected, never deleted or rewritten; tasks may trace to a cited
      repository obligation as well as a decision or requirement.
      `change-triage`'s gate step now rewrites the index row's notes with its
      status.
- [x] 6.2 Pilot: amend `capacity-shape-envelope`'s existing plan to its reviewed
      design. Run continuing the design session, at the owner's preference.
      The stale 24-task plan was replanned into seven sections and 45 tasks and
      accepted. Planning stopped correctly on one design question the design
      left open (local-table derivation) and the owner decided it; the skill
      then lacked the return-to-design step added afterwards, so the owner's
      waiver of a re-review was recorded after the fact. Section 4 is confined
      to a ~2,100-line module and is the section most likely to outgrow one
      session. `make check-doc-citations` now skips untracked `reviews/`.
- [ ] 6.3 Pilot: plan `add-full-stack-ci-job` from nothing.

## 7. Implementation

- [x] 7.1 Write the `change-implement` skill: one `tasks.md` section per fresh
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
      Written at `.agents/skills/change-implement/`. It replaces
      `openspec-apply-change` for this workflow rather than wrapping it: that
      generated skill implements every remaining task in one session, the
      opposite of a section per session, and `openspec update` would overwrite
      any edit to it; it stays available for changes worked outside this
      workflow. The skill also refuses to start on a branch that does not carry
      the change, since several changes are often in flight in one checkout,
      and stops at a verified point when a section proves larger than planned. Amended at the owner's direction during
      pilot 7.3: a session may continue into later sections, by a range named at
      the start (`make implement SECTIONS=1-3`) or on the owner's word after a
      section is committed, and one implementation review may cover every
      section committed since the last; each section is still checked, handed
      off, and committed on its own. After the first multi-section run (sections
      2–4 in one session, 404k tokens, no compaction, compliance findings
      decreasing per section): every section now runs `make test` before
      commit; task notes and plans name each suite's level as `TESTING.md`
      defines them, and the fresh-context check verifies those claims. The
      pilot's sections were committed to this change's branch at the owner's
      direction; the two changes merge together.
- [x] 7.2 Add a committed Claude Code project hook that, when a session resumes
      after compaction, re-reads the required guidance documents and restates the
      change and section being worked.
      `.claude/settings.json` (now un-ignored; `.claude/settings.local.json`
      stays ignored) runs `scripts/post_compaction_context.py` on `SessionStart`
      with the `compact` matcher, whose output Claude Code adds to context.
      Claude Code caps injected context at 10,000 characters and the required
      documents are about 250 KB, so the hook names them to re-read in full —
      never a digest — with the branch and the changes in progress. Tests in
      `scripts/tests/test_post_compaction_context.py`; the hook's firing is
      proven on the first compaction in a new session.
- [x] 7.3 Pilot: implement the first section of `capacity-shape-envelope` in its
      own session, recording what the fresh-context check caught.
      Done as sections 1–4 of `capacity-shape-envelope` (7.1's notes): the check
      caught a blocking constraint-loss bug in section 1, and compliance findings
      fell per section across the multi-section run.

## 8. Pre-review validation

Validation observes one commit and edits nothing (`design.md`, "Validation observes
a committed slice and never alters it"). Every script below is tested in
`scripts/tests/` with an injected command runner, at unit level, except where a
real repository is the lowest level that proves the behaviour. No end-to-end scenario covers this section: it
is the tooling that runs them, proven by its own suites and by 8.6.

- [x] 8.1 Add `make validate-local` (`scripts/validate_slice.py`, tests in
      `scripts/tests/test_validate_slice.py`): `make check-packaging`, then
      `make test`; a clean worktree, untracked files included, asserted before and
      after; stopping at the first failure; each step's log under
      `.snapshot/validation/<commit>/`; and a summary of each step's result,
      duration, and a failing step's output tail.
      Done; the part starts with `make dist-clean` (`design.md`), and logs go
      under `.snapshot/validation/<short commit>/local/` (corrected by 8.8: one
      numbered directory per attempt beneath it). Unit
      (`test_validate_slice.py`, fake runner and reader injected): the step order
      against fakes, the first-failure stop with its output tail, a dirty tree
      (the fake answers only `git status --porcelain --untracked-files=all`)
      running nothing, and a step that dirties the tree failing the check after it.
      Not yet run for real: `make validate-local` is first exercised by 8.6.
- [x] 8.2 Add `make validate-helm` to the same script: refuse a kube context other
      than `HELM_CONTEXT` (default `docker-desktop`); fail before running anything
      when the VM storefront environment is absent, naming `make init-storefront`;
      `make -C helm test-render`, failing on a loader-check skip; `make build-dev`;
      `make deploy` and `make forward` in `helm/`; the pipeline's scenarios, read
      from `e2e-tests/Makefile`'s `E2E_MODULE` and `E2E_BARE_METAL_MODULE`, minus
      an explicit exclusion list naming each excluded scenario's missing service,
      run with `make test-module` and reported as not run; `make unforward`
      whatever failed; a clean worktree afterwards. The list starts from the
      services the default chart values do not deploy and is confirmed by 8.6.
      Corrected after 8.6: the exclusion list became `HELM_SCENARIOS`, the scenarios
      the default charts serve (`contracts`, `e2e_alkahest_escrow_codecs`); every
      other pipeline scenario is reported as not run against Helm.
      Corrected by 8.10 and 8.11: preflights now include Docker, the node, the
      Secrets, freed ports, and retained volumes, and `make deploy` became the
      uninstall-then-`deploy-local` sequence.
      Done, in `validate_slice.py`, also starting with `make dist-clean`, then
      `make build-dev` and a reinstall of the VM storefront environment before the
      render checks, so the loader check runs this commit's code. Unit: the step order, the exclusions reported as
      not run, the context refusal and the missing storefront environment running
      nothing, a render `skip:` line failing, a failing scenario and ports that never
      open both still unforwarding, and a marker list that is not a plain `or` list
      refused. One test reads the real `e2e-tests/Makefile` variables through
      `make`, so a renamed or reshaped variable fails it. Beyond the plan:
      `e2e-tests/Makefile`'s `test-module` now quotes `MODULE`, so a marker
      expression passes through; and the scenarios wait, with a bound, for
      the forwarded ports to accept connections, because `make forward` starts its
      port-forwards in the background. The exclusion list is
      `HELM_EXCLUSIONS`: `multi_registry`, `e2e_credits_deal`,
      `e2e_vm_introduction` (Mailpit is deployed but not forwarded), and both
      bare-metal scenarios, each with what is missing. `HELM_ALL_SCENARIOS=1`
      (`--all-scenarios`) ignores the list, for 8.6; the tests prove the empty
      list's effect, not the flag's plumbing. 8.6 risk: `build-dev` regenerates
      the tracked `alkahest_anvil_addresses.json` and syncs the storefront without
      `--frozen`, so the clean check afterwards fails unless both are
      reproducible. Not yet run against a cluster; 8.6 should expect
      `e2e_deal_buyer_cli` and `e2e_buy` may also fail for topology, since the
      pipeline runs them inside the compose network and this run reaches the
      storefront through port-forwards.
- [x] 8.3 Add `make check-push-ready` and `make push-branch`
      (`scripts/check_push_ready.py`, tests against temporary Git repositories):
      refuse a detached `HEAD`, a dirty worktree, `main` or `dev`, and an upstream
      named differently from the branch; push a branch with no upstream to the
      same name on `origin` with its upstream set; push exactly `HEAD`, never
      forced; report and never repair.
      Done. `test_check_push_ready.py` drives real Git against a temporary
      repository and bare remote: a new branch pushed and tracking its own name,
      exactly `HEAD` pushed, a remote that moved on rejecting the unforced push,
      and each refusal (detached, protected, dirty, another upstream) pushing
      nothing; the detached and dirty cases also leave the checkout as it was.
- [x] 8.4 Make `scripts/fetch-e2e-logs.py` select the run whose head commit is the
      local `HEAD` (`--commit`, defaulting to `HEAD` when no `--run-id` is given),
      polling with a bound for a just-dispatched run and taking the newest match,
      with tests for both gaps: a finished earlier run on the branch, and a run not
      yet listed. Update the run-selection paragraph of
      `docs/development/TESTING.md`'s system integration section to match.
      Done. Unit (`test_fetch_e2e_logs.py`, existing fake runner extended): a
      finished run of an earlier commit never fetched, a run listed only on the third
      poll waited for, the newest of several runs of one commit taken, `--commit`
      replacing `HEAD` (the script asks Git to resolve it; the fake answers), a
      repeated dispatch of one commit waiting for a run newer than `--after-run`,
      `--run-id` refusing either selector, and the error when no run appears,
      tested with a zero wait. `E2E_COMMIT` and `E2E_AFTER_RUN` reach the script
      through `make` (asserted on the Makefile text); `TESTING.md` describes the
      selection.
- [x] 8.5 Write the `change-validate` skill (`.agents/skills/change-validate/`,
      linked for both harnesses) and `make validate CHANGE=`: check the branch
      carries the change; `make push-branch` and `make run-e2e`; the local and Helm
      parts while the pipeline runs; `make fetch-e2e-logs` for `HEAD` and the
      run's conclusion; a diagnosis of each failing scenario from its logs; and
      `reviews/NN-validation.md`, numbered when written, naming the commit, each
      part's result, the Helm exclusions, the run and its conclusion, and the
      diagnoses. It never edits or fixes. `make check-agent-skills`.
      Done. The skill writes failures as `V<n>` so triage carries them beside review
      findings; it runs the Helm part even after a local failure, unless the
      worktree was dirty, so one triage sees every failure. It records the newest
      run ID before dispatching and fetches only a later run. Proven only by 8.6.
      Section checks: `make check-packaging` and `make test` passed after
      `make dist-clean`, with no lock rewritten (before the clean, other
      branches' wheels in `.dist` made `make test` rewrite six locks and fail
      `kit/site`); the three new suites, 41 tests, pass; `make
      check-comment-hygiene` and `make check-agent-skills` pass;
      `test-release-tooling` fails only
      `test_settlement_deployment_surfaces.py`'s two tests, as at the section's
      starting commit. `scripts/tests` is not part of `make test`, so
      `validate-local` does not run it.
- [x] 8.6 Pilot: validate `capacity-shape-envelope` at `HEAD`. The Helm part runs
      the whole scenario set once with no exclusions, and the exclusion list is set
      from what fails for a missing service, as distinct from what fails for a real
      reason.
      Handoff: run `make validate CHANGE=capacity-shape-envelope` and tell the
      session to run the Helm part as `make validate-helm HELM_ALL_SCENARIOS=1`;
      afterwards set `HELM_EXCLUSIONS` in `scripts/validate_slice.py` to what the
      run shows, as a commit of this change. Both parts run `make dist-clean`, so
      no other session should be building in the checkout meanwhile.
      Attempt 1 (`capacity-shape-envelope`'s `09-validation.md`, commit
      `75c121de`): local and pipeline passed; Helm produced no scenario evidence —
      a Docker credential-helper timeout, then provisioning crash-looping on a
      volume another commit's migration had rewritten. The skill ran with the
      exclusions, because the instruction sat in this change, not the one validated.
      The owner's review of that record produced 8.8–8.14; re-run after them, as
      `make validate CHANGE=capacity-shape-envelope HELM_ALL_SCENARIOS=1`.
      Attempt 2 (`capacity-shape-envelope`'s `10-validation.md`, commit
      `004e580e`): local passed; pipeline run 37917228588 passed (VM lane 135
      passed and 3 skipped — the API-credits payment cases, which skip as
      `blocked: PAYMENTS… not configured` and arrived with the merged `dev`;
      bare-metal 16 passed). The Helm part's first attempt stopped at the
      retained-volume preflight before any build, as designed; on the owner's word
      the release was uninstalled and its three `keep` PVCs deleted. The second
      deployed fresh and ran every pipeline scenario: all that create a listing
      failed, because the default chart values configure no settlement mechanism
      (`Settlement.priority: []`, no chain) — unchanged since before this branch
      merged `dev`, and never exercised before, since earlier Helm runs ran the
      contract checks only. Only the codec cases and setup stages passed. The owner
      chose to keep chart work in `helm-e2e-pipeline-parity` and narrow the Helm
      part to the scenarios the charts serve (8.2's correction); on that scope the
      record is `passed`. What the pilot showed about the skill: the
      retained-volume stop and the settle-with-the-owner step worked as written;
      the three outcomes have no case for "the tooling produced no evidence"; the
      exclusion list could not be established while one gap blocked every
      scenario.
- [x] 8.7 Propose a change bringing the Helm charts and `make forward` to the
      pipeline's compose topology, using the compose configuration the pipeline
      runs, so the exclusion list empties; add its row to
      `openspec/changes/README.md`. Proposal only.
      Done: `openspec/changes/helm-e2e-pipeline-parity/proposal.md`, in the local
      end-to-end stack campaign, with `skip_specs` set as `add-full-stack-ci-job`
      has; like it, `openspec validate --strict` reports the missing delta until
      design either adds one or confirms none is owed.
- [x] 8.8 Validation outcomes and attempts: the record's result, overall and per
      part, is `passed`, `failed`, or `inconclusive` (`design.md`, "Validation
      controls the environment and settles environmental failures");
      `validate_slice.py` writes each attempt to
      `.snapshot/validation/<short commit>/<part>/<n>/` and prints its path; tests
      for attempt numbering. Amend `change-validate`'s record template and
      `run_change_review.py`'s pre-closeout check (9.3) to accept only `passed`.
      Done. Unit: two attempts of one part write `1/` and `2/`, each with its own
      `summary.json` carrying its `attempt`; the printed path is not asserted. The
      outcome is the skill's, in the record template, since only the diagnosis
      tells an environmental fault from a broken build; 9.3 now names the
      `passed` result.
- [x] 8.9 Environmental failures in the session: amend `change-validate` to stop on
      a failure diagnosed as environmental with good confidence, put the evidence
      and remedy to the owner, rerun the part as a new attempt on the owner's word,
      record `inconclusive` when the owner declines, never treat an unknown cause
      as environmental, and report validation-tooling defects in a section of the
      record about the validation. State the full-control premise in the skill.
      Done in the skill: settle-with-the-owner step, an `## Environment` section
      for environmental failures, `## Failures` only for commit or unknown causes,
      `## About the validation` for tooling defects, and the full-control premise.
      Skill text; proven only by 8.6's re-run.
- [x] 8.10 Fresh Helm state: add `persistence.retainOnUninstall` (default `true`)
      to the storefront, provisioning, registry, and bare-metal storefront charts,
      rendering `helm.sh/resource-policy: keep` only when it is true, with render
      tests for both settings; add `helm/local-values.yaml` setting it `false` and
      `make -C helm deploy-local`; the Helm part uninstalls an existing release,
      waits for its PVCs to go, stops on a surviving one, and deploys with
      `deploy-local`. Tests for the sequence and the surviving-PVC stop.
      Done. Chart render tests (`helm/scripts/test-render.sh`, needs Helm, no
      cluster): every persistent chart enabled renders five PVCs, all retained by
      default and none under `local-values.yaml`; breaking the registry template's
      condition made the overlay check fail, then restored. `deploy` takes
      `EXTRA_VALUES`, `deploy-local` passes the overlay, `undeploy` uninstalls with
      `--wait --ignore-not-found`, and `stop` is now its alias. The condition reads
      the value as a string, so `--set-string …=false` turns retention off too.
      Each PVC is checked by name in both renders; breaking the storefront
      template's condition failed exactly its check. Unit (fakes that record the
      cluster queries and port probes with the commands, and model the forwards
      and volumes as state): before the build, the forwards stopped, their ports
      polled until free, and a PVC carrying `keep` refused; after it, `undeploy`,
      the volumes polled until gone (one removed on the second poll), then
      `deploy-local`; a volume still present at the deadline stops the deploy. The PVC query
      selects `app.kubernetes.io/instance=<release>`, which every release PVC
      carries; release and namespace are read from `helm/Makefile`. The bare-metal
      storefront schema gains the property; the other charts' schemas do not
      constrain `persistence`. `DEPLOYMENT_AND_CONFIG.md` describes the
      convention. Not yet run against a cluster.
- [x] 8.11 Preflights: `gh auth status` before the push (skill); in the Helm part,
      `docker info`, a `Ready` node, `make -C helm check-local-secrets` (a new
      target over the chart's eight out-of-band Secret names, with a test that each
      name appears in `helm/values.yaml`), and the forwarded ports free after
      `unforward`; a credential-helper response check that warns only. Tests for
      each refusal and the warning.
      Done. With the default values a deploy reads six out-of-band Secrets, not
      eight (`arkhai-api-credits-registry-identity` joins them when
      `api-credits-registry` is enabled):
      `arkhai-e2e-credentials` and `arkhai-buyer-profile-credential` (and the
      `arkhai-buyer-profiles` PVC) are read only by the e2e-tests chart's
      `helm test` hook, which validation does not run. `check-local-secrets`
      passes on `docker-desktop`. Unit (fakes): Docker unreachable, a node not
      Ready, no node, and a missing Secret each stop before `make dist-clean`; a
      silent credential helper warns and the part still passes; a helper that times
      out, exits non-zero, or cannot run is each named, and `$DOCKER_CONFIG` is
      honoured; each listed Secret appears in
      `helm/values.yaml`. The node query and the helper check were also run
      against the live machine; the retention query found three `keep` PVCs on the
      owner's current `docker-desktop` release, so a validation started now stops
      there and asks. `gh auth status` is a skill step. The ports and retained-volume
      checks run before the build, after `unforward`, since validation owns the
      forwards.
- [x] 8.12 Coverage: amend `change-validate` to write the record's coverage section
      (scenario, basis, lane, result; or that none covers the change), reading the
      scenarios from the change's task notes and adding what the diff shows; amend
      `change-plan` to name the end-to-end scenarios each section's verification
      point relies on, and `change-implement` to confirm or correct them in the
      section's notes before committing.
      Done in the three skills. `change-plan`'s verification point now names the
      covering scenarios, replacing its rule on when a section owes the Helm
      checks, which predated validation running them on every commit;
      `change-implement` confirms them before the last task is checked, and its
      closing report now describes the round (part of 9.4). Skill text; proven by
      the next plan and section that use them.
- [x] 8.13 `make validate CHANGE=<change> HELM_ALL_SCENARIOS=1` passes the
      instruction into the session's prompt, and `change-validate` runs the Helm
      part with it and records which scenarios fail only for a missing service.
      Done. `make validate … HELM_ALL_SCENARIOS=1` opens the session as
      `/change-validate <change> with HELM_ALL_SCENARIOS=1`; the skill's first step
      reads it. The Makefile text is asserted; the session read it in 8.6. After 8.6
      it runs every pipeline scenario instead of the served list, so the list can
      grow.
- [x] 8.14 Record for `capacity-shape-envelope`'s closeout (10.3), to place there:
      a namespace per validation, and chart Secrets made optional with the ordinary
      values overlays as fallback.
      Done: added to 10.3.

## 8A. Reconcile the development-branch merge

- [x] 8A.1 Reconcile root, kit, and E2E `Makefile` targets, `.gitignore`,
      `domains/vms/listings/pyproject.toml`, and the API-credit distribution-wheel
      fixture: preserve workflow and admissibility tooling alongside development's
      package boundaries and payments cutover. Remove the retired shared hosted
      debugging skill and both harness links together. Move the admissibility
      dependency to `kit/resource-pools-contracts/pyproject.toml`, which now owns
      hint validation, and update its moved tests' imports and build prerequisite.
      Adapt the pilot's added pool API tests to `ProvisioningClients.pools` and
      `ComputeProvisioningError` in the provisioning-service integration suite.
- [x] 8A.2 Reconcile the campaign index and completed task history, retaining its
      phase/state columns while applying development's archive, scope, and progress
      updates. Record the merge rationale in `design.md`; leave unfinished pilots,
      validation gates, and feature sections open.
- [ ] 8A.3 Regenerate locks through `make lock` after a clean wheel build. Run
      focused workflow and shape-admissibility tests and the root unit/integration
      aggregate; run `make check-packaging`, `make check-agent-skills`, comment
      hygiene, scoped documentation citations, and strict OpenSpec validation.
      Check import placement, documentation ownership, completed-note compression,
      roadmap/index currency, and existing promotion destinations. Record failures
      and unrun typing, Docker/Helm end-to-end, or remote pipeline checks; retain
      the corresponding post-review closeout and promotion gates.
      Local merge checks (2026-10-08): every root unit/integration target passed
      across the aggregate and resumed run, including the migrated pool-contract
      and pool API tests, shape-admissibility integration, workflow tooling, all
      three middleware implementations, E2E unit tests, and Helm render checks.
      Agent skill links, comment hygiene, strict OpenSpec 1.14.0 validation, and
      the index's row schema, statuses, link targets, and citations passed.
      Registry-client typing passed. Core typing still reports its inherited
      `query_dsl.py:487` assignment error; that file is identical on both parents.
      The scoped citation check reports four inherited references to the planned
      workflow specification, architecture companion, and contributor guide,
      which remain absent until closeout; no missing permanent document is added
      by this merge. Import placement adds no function-local imports, and roadmap
      gaps and feature gates remain applicable. Docker and Helm end-to-end and
      the remote pipeline remain unrun: local containers are already running and
      the standard stack tests replace volumes; this uncommitted merge has no
      corresponding pipeline revision. Section 12's promotion and closeout remain
      open. `make check-packaging` passed against the final rebuilt wheelhouse.

## 9. Implementation-round triage

The review, validation, and the owner's notes on one commit are triaged together in
a fresh session (`design.md`, "An implementation round is triaged in a fresh
session").

- [x] 9.1 Extend `change-triage` for an implementation round: its inputs are the
      untriaged implementation reviews, the validation record of their commit, and
      the owner's notes, pasted and saved verbatim as
      `NN-implementation-owner.md`; each validation failure is a finding (lens
      `testing`, basis `evidence`, severity `blocking`) whose diagnosis is checked
      against the logs; each of the owner's points gets a position like any
      finding and a ledger entry; after the dispositions, accepted fixes are made
      in the session, pass `change-implement`'s checks including the fresh-context
      check, are committed as one commit, and the owner is told to validate it
      again; the pre-closeout gate does not pass without a passing validation of
      `HEAD`.
      Done in `.agents/skills/change-triage/`, amending its steps rather than adding
      a parallel procedure, so the presentation and ledger rules keep one copy. A
      new outcome, `fix`, covers code changes made in the session; the
      implementation round runs `change-implement`'s checks (its step 5) before
      one commit — fixes, edited change documents, and `interventions.jsonl` — and
      never pushes. Environmental entries and `inconclusive` parts are missing
      evidence; observations about other changes or the tooling are presented, not
      triaged against the change. After the fresh-context check, it also states:
      how a round is recognized, the branch and worktree check and the base the
      fixes are diffed against, a lone re-validation, and owner-note labels `O<n>`.
      Superseded records and differing commits were later reworked by
      implementation review 1 (F2, F1; see the notes after 9.5). Skill text;
      proven by 9.5.
- [x] 9.2 Add `make triage CHANGE=`, opening a Claude Code session with
      `/change-triage <change>`.
      Done. Its help names the round's inputs.
- [x] 9.3 In `scripts/run_change_review.py`: allocate a record's number when it is
      written rather than when the run starts, so parallel records never share one;
      and make `KIND=pre-closeout` refuse unless the latest validation record names
      `HEAD` and its result is `passed`, overridden by `UNVALIDATED=1`. Tests in
      `scripts/tests/test_run_change_review.py`.
      Done. Corrected by implementation review 1 (external) F3: the note's earlier
      claim that parallel records "never share" a number was wrong; the
      requirement is now an establishable order and no overwrite, which the
      exclusive claim below provides.
      Unit (`test_run_change_review.py`, the runner and `HEAD` injected): a
      record written while the reviewer runs makes the review take the next
      number, and its transcript is renamed from its provisional name, also when
      the run is interrupted; a
      pre-closeout review refuses, and starts no reviewer, with no validation
      record, one naming another commit, an `inconclusive` result, or a later
      `failed` record over an earlier `passed` one; it runs on a passing record or
      `UNVALIDATED=1`; an implementation review never checks; a short commit
      prefix is accepted and a decorated `Commit:` or `Result:` line fails closed,
      which `change-validate`'s template now warns about. `make -n review …
      UNVALIDATED=1` emits `--unvalidated`. The test of the reviewer's command
      passes the override, since it is about the command, not the gate.
- [x] 9.4 Amend `change-implement`'s closing report (review and validation in
      parallel, the owner's notes, then `make triage`; the first three were done
      in 8.12, `make triage` remains) and `change-review`'s inputs
      (read the validation record of the reviewed commit when one exists; never
      wait for one).
      Done. `change-review` reads the validation of the commit it reviews when one
      exists, never waits, and names the pre-closeout requirement;
      `change-implement` and `change-validate` close with `make triage`.
- [x] 9.5 Pilot: triage `capacity-shape-envelope`'s `07-implementation.md` and
      `08-implementation-external.md` with 8.6's validation record and the owner's
      notes, through `make triage`; compare the two reviews for the pilot record;
      the change stays `in implementation`.
      Handoff: the owner runs `make triage CHANGE=capacity-shape-envelope` in a
      fresh session and pastes their notes when asked. The record is
      `10-validation.md` (commit `004e580e`, `passed` on the narrowed Helm scope,
      no `V<n>` findings; it notes the API-credits payment skips from the merged
      `dev`). `07` reviewed sections 1–4 against base `22115762`, so the triage
      should say how far the validated commit has moved past what the reviews
      read. Record here what the skill could not handle unaided.
      Round 1 (`07`, `08`, `09`, `10`) was triaged by the owner under the skill as
      first built (`93d5733a`). Round 2 ran the amended workflow end to end:
      `make validate` (`11-validation.md`, `e4bf7a81`, passed; the retained-volume
      preflight stopped Helm attempt 1 on volumes an agent's plain `make deploy`
      had left, remedied on the owner's word) and `make review` resuming `07`'s
      reviewer (`12-implementation.md`, same commit), then `make triage`. Unaided:
      the triage compared the two records' commits first and found them equal,
      wrote no notes record since the owner had none, marked the validation's
      triage file "not a gate", fixed 12 F1 more broadly than the review asked (all
      rationals, with a test that fails without the fix), logged both findings,
      and recorded the gate; the resumed reviewer accounted for every earlier
      finding from `03` to `10` in one table. Gaps, amended in the skills: the fix
      note did not record the checks it ran (`change-triage` now records them as
      `change-implement` does); the session presented findings in the labelled
      layout the owner had replaced in an earlier session, since that layout lived
      only in session memory (`change-triage` now prescribes the agreed layout).
      Comparing round 1's reviews: the harness (`07`) found both code defects,
      which the browser (`08`) missed; the browser's accepted `should` (the
      publication loop proven only at derivation level) appears in `07`'s testing
      answer but was never raised as a finding (`change-review` now makes such a
      gap a finding). An agent's plain `make deploy` caused the retained volumes:
      `DEPLOYMENT_AND_CONFIG.md`, both Makefiles, and the e2e-tests quick start now
      say a local cluster is deployed with `make -C helm deploy-local`, and why.
      The fix commit's round closed with a lone re-validation, both steps run as
      subagents at the owner's direction: `13-validation.md` (`22bc1408`, which
      contains `6f04fc01`) passed on every part's first attempt, its
      retained-volume preflight passing; its triage checked the record against
      the step summaries and the pipeline log and wrote only the confirming
      triage file, as the skill's lone re-validation rule says.

- [x] 9.6 Give the owner the round to read as uncommitted changes:
      `make round-diff CHANGE= [BASE=]` (a worktree script, removed by 9.7) checks out
      the round's base in a worktree beside the checkout and overlays `HEAD`'s
      files, other changes' directories excepted; `change-implement`,
      `change-validate`, and `change-triage` point the owner's notes at it. A
      pasted review's commit is read from the snapshot name and appended as the
      runner's `reviewed-commit` comment (`change-triage`). Spec delta and design
      amended (`design.md`, "An implementation round is triaged in a fresh
      session").
      Done at the owner's direction after round 3 of the pilot, whose sections
      were committed before the owner could read them; leaving sections
      uncommitted is the recorded fallback if the worktree does not serve.
      Integration against real temporary Git repositories
      (its tests, 11 passed): the worktree's status is
      the round — modified, deleted, and new files, the change's own documents and
      `openspec/changes/README.md` included, another change's directory at its
      base; new files Git would quote and new tracked files `.gitignore` matches
      appear; the change's directory removed in the round shows as deleted; the
      base is the latest triaged validation; with none, the base must be given; a
      second run replaces the worktree, also after its directory was deleted by
      hand; a path that is not a worktree is never removed; an empty change name
      and `archive` are refused; the checkout's `HEAD` and status are untouched.
      `main()`'s output and the Make target are untested.
      Run once by hand on `capacity-shape-envelope`: base `22bc1408` from
      `13-validation`, 21 files.
      Corrected by 9.7: the owner tried the worktree and found a second editor
      project each round, without the owner's inline test setup, worse than reading
      in the checkout; `round-diff`, its script, and its tests were removed.

- [x] 9.7 Show the round in the owner's own checkout instead:
      `make round-view CHANGE= [BASE=] [NO_E2E=1]` (`scripts/round_view.py`)
      pushes `HEAD`, dispatches the pipeline, and records the run before it, then
      mixed-resets the branch to the round's base, so the round shows as
      uncommitted changes with the files unchanged; `make round-done` resets the
      branch to the recorded commit, leaving the owner's edits uncommitted, and
      also returns when something committed on the base during the view, leaving
      that commit's own changes uncommitted and naming the commits taken off the
      branch, and closes without moving the branch when it is already at or past
      the round's commit.
      While a view is open, every target that describes or publishes a commit —
      `review`, `implement`, `triage`, `validate` and its parts, the push, the
      dispatch, the snapshot and diff targets — fails through the shared
      prerequisite `round-view-closed`, which `change-implement` and
      `change-triage` also check at their start. `change-validate` reads the
      recorded run once (`make round-e2e-baseline`) before any dispatch, since a
      second dispatch cancels the run in progress; `change-implement` and
      `change-triage` put the owner's reading before validation and review. Spec
      requirement and scenario, and design, amended.
      Done at the owner's direction, choosing this over an editor comparison
      against a named base and over leaving sections uncommitted (the fallback).
      A fresh-context check found that a commit during the view stranded the
      branch, that an interrupted run or a view left by hand could not be closed,
      that the recorded run was never forgotten, that the skill's order would
      dispatch over the running pipeline, that the guard missed the push,
      dispatch, snapshot, and diff targets, that the error's docstring claimed
      nothing changed after a push, and that the note overstated its tests; all
      fixed here. A second check found that a fix committed after returning by
      hand was reset off the branch, and that the stray commits listed included
      the round's own; fixed too.
      Integration against real temporary Git repositories, with the push and the
      dispatch through an injected runner (`scripts/tests/test_round_view.py`,
      26 passed): the round shows as modified, deleted, and intent-to-add new
      files with the branch at the base (file contents checked for the new file);
      `done` restores the commit and keeps an edit, or leaves a clean tree; a
      commit made during the view leaves only its own change uncommitted on the
      round's commit and is reported; a view reset back by hand, or recorded but
      never reset, is closed; a fix committed after returning by hand stays on the
      branch; a branch reset to an earlier round commit returns with no strays
      named; `done` on another branch, or with the branch moved
      off the base, refuses and keeps the view, naming the way back; the base is
      the latest triaged validation, or must be given; `check` and a second
      `start` refuse while a view is open; a dirty or untracked tree, a
      non-ancestor base, a detached `HEAD`, a base equal to `HEAD`, and an unknown
      change or `archive` are refused with the branch unmoved and no view open;
      `start` pushes while `HEAD` is still the round's commit, reads the baseline,
      then dispatches, and records the baseline for `HEAD` only; a refused push or
      a failed baseline read or dispatch opens no view and records no baseline;
      the baseline is read once; the command line's `check` fails while a view is
      open and `e2e-baseline` prints once. Not exercised: the Make targets and
      their prerequisite, the rollback when the reset itself fails, and the real
      `gh` and push.
- [x] 9.8 Present a triage one finding per message (`change-triage` step 3): the
      first message opens with an agenda of labels only; a finding is disposed of
      only when the owner names a disposition for it, and any left undisposed is
      raised before the gate; findings follow any decision that could change them,
      then severity. `AGENTS.md` asks every session to put questions to the owner
      in prose and never through a multiple-choice selector, overriding the stock
      OpenSpec skills that name one, which are regenerated and so not edited. Spec
      requirement "Triage of every finding" and design amended. At the owner's
      direction, after the triage of `capacity-shape-envelope`'s third round.
      Text only, proven when a session follows it.
- [x] 9.9 Let a validation of an ancestor clear `HEAD` for a pre-closeout review
      when the two commits differ only in changes' ledgers and reviews
      (`scripts/run_change_review.py`, `validation_problem` and `_changed_since`);
      `change-review`, `change-triage`'s gate table, spec requirement and scenario,
      and design amended. At the owner's direction: `capacity-shape-envelope`'s
      validation 18 triage left a ledger line that could not be committed before its
      pre-closeout review without revalidating.
      Unit, with the comparison injected (`scripts/tests/test_run_change_review.py`,
      49 passed): records of this change or another admit; an empty diff admits;
      any other path, a path outside a change directory, or `archive`'s refuses
      and names the path; a validated commit that is not an ancestor refuses;
      `run_review` admits a pre-closeout review after a ledger commit. Against the
      real Git command in a temporary repository: `_changed_since` lists the
      paths, a non-ASCII one included, lists a rename as both paths, and returns
      nothing for a non-ancestor or an unknown commit. Not exercised: the check
      on real Git output end to end, and the `make review` invocation with a real
      ledger commit. The fresh-context check found that a rename into a change's
      reviews was listed only at its new path, letting a code deletion through,
      that the texts did not require ancestry, and that the note overstated its
      tests; all fixed.
- [x] 9.10 Show the triage presentation instead of describing it (`change-triage`
      step 3): the five parts of a finding are one sentence of guidance rather
      than a list of bold names, the placeholder template is a complete worked
      finding written as plain paragraphs, run-in bold labels and per-part
      headings are named as what not to write, and the italic line under a
      heading carries only the lens, severity being in the emoji. At the owner's
      direction, after the pre-closeout triage of `capacity-shape-envelope`
      presented every finding with the list's names as bold run-in labels, the
      third time the owner had asked for prose. Text only, proven when a session
      follows it.

Implementation review 1 (external, `reviews/01-implementation-external.md`)
triaged. Script fixes are proven at unit level; skill and spec fixes are text,
proven only when a session follows them:

- F1 — `make review` appends `<!-- reviewed-commit: <HEAD> -->` to each published
  review (one test asserts it, `HEAD` injected); `change-triage` names every
  record's commit, compares them, and treats a mismatch as one round only on the
  owner's waiver, logged; a pasted review's commit is the owner's word, recorded;
  spec delta and design amended.
- F2 — `change-triage` presents earlier untriaged validation failures, merged
  with later evidence; only a record with no `V<n>` is marked superseded.
- F3 — the record order must be establishable (number, or file time) and nothing
  overwritten: `claim_record` creates the name exclusively and takes the next
  number if it exists (tested both with a record written before the proposal and
  with a proposal that collides); an interrupted run leaves no empty record. An
  agent writing a record checks the name is free and takes the next number — a
  check, not an exclusive claim.
- F4 (section 8) — `Validation.step()` checks after every command that `HEAD` is
  the recorded commit and the tree is clean, failing the step otherwise; every
  caller stops on a step that did not pass, though `unforward` still runs as
  cleanup. Tests cover a dirtied tree in the local part and `HEAD` moving in the
  Helm part; the other stop points are by reading the code.
- F5 — before closeout, `make check-doc-citations` may report only the documents
  the change creates at closeout (`change-implement`, `change-triage`).
- S1, S2 — owner notes saved exactly as pasted with `O<n>` labels only in triage;
  validation and owner-note triage files are "not a gate".
- S3 — the spec scenario lets the owner continue a session into the next section.
- S4 (section 8) — `fetch-e2e-logs.py` takes its command runner as a parameter;
  its tests pass a fake instead of patching `subprocess.run`.

## 10. Closeout and archival

Closeout and archival are one phase (`design.md`, "Closeout archives the change,
and its review reads the archive"). One session implements 10.1–10.4 and stops;
10.5 is a session of its own; 10.6 waits for the pilot's closeout review and for
12.10.

- [x] 10.1 Find a change by name in the archive: one lookup in `scripts/` that
      resolves `<change>` to `openspec/changes/<change>/` or, failing that, the one
      `openspec/changes/archive/<date>-<change>/`, refusing an ambiguous match.
      Use it wherever a change is taken by name — `make review`, `make triage`,
      `make validate` and its parts, `make round-view`, and
      `make check-doc-citations CHANGE=` — and test it against a temporary tree
      with an active, an archived, a missing, and a twice-archived name.
      Done: `scripts/find_change.py` (`change_directory`; run as a script it
      prints the directory). `run_change_review.run_review`, `round_view.start`,
      `check_doc_citations.documents`, the `design`, `implement`, `triage`, and
      `validate` targets, and `change-validate`'s record path use it; an
      archived change reaching design or implementation is refused by those
      skills' status check. `validate-local` and `validate-helm` take no change. Unit (`test_find_change.py`, temporary
      tree): active, archived, active preferred over archived, missing,
      archived twice refused naming both, a name that only ends an archived
      one not matched, non-names refused, and the command's output and failure.
      Wiring: a closeout review of an archived change is recorded in the
      archive's `reviews/` (unit, runner injected); an archived change's
      triaged validation is the round view's base (integration, real temporary
      Git repository); the citation check scopes to an archived change and
      refuses an unknown one (unit, temporary tree). The Make targets were run
      by hand only (`make triage CHANGE=nope` names both locations).
      Found on the real tree: `make check-doc-citations CHANGE=bare-metal-buyer-domain`,
      an archived change, reports six unresolved citations — one of the
      change's own unarchived path, five of documents since moved or removed.
      A scoped run on an archived change therefore fails on citations the
      unscoped run deliberately lets move on. Closeout runs the check before
      archiving, so closeout is unaffected; a fix made after the closeout
      review, if it runs the check, would meet it. Left for the owner.
- [x] 10.2 Amend the guidance to match: `openspec/README.md`'s closeout part 10
      ends with `openspec archive <change> -y` (`--skip-specs` where the specs
      were synchronized by hand), parts 5 and 6 lose "not at archival", and the
      contributor workflow's step 7 says the closeout review reads the archive;
      `openspec/changes/README.md`'s legend drops `ready for archival` and
      `Depends on` names `archived`; `change-triage`'s gate table, `change-review`'s
      closeout kind, and `change-design`'s dependency rule likewise.
      Done. `openspec/README.md`: the closeout task ends by archiving; part 10
      is "Promotion and archival", naming `--skip-specs` and the lookup; parts
      5 and 6 no longer contrast completion with archival, and part 6 moves the
      row's link to the archive. The index legend has `deferred` and `archived`
      outside the grid, and the landing rule fires when a dependency is closed
      out. `change-review` and `change-triage` find the change through the
      lookup; the closeout review reads the merged specifications and asks
      whether the merge kept each delta's meaning and whether the change may
      ship; the triage gate table's `closeout` row is `archived`, written by
      `change-ship`. Text, proven when 10.4 follows it.
- [x] 10.3 Write the `change-closeout` skill over the ten parts of
      `openspec/README.md#plan-closeout-requirements`, running each mechanical part
      and reporting the parts that need judgement, including
      `make check-agent-skills`; it moves the index row to `in closeout` when
      closeout starts, updates the row's link to the archived directory, archives
      the change last, and commits, so that the closeout review reads the archive.
      Done at `.agents/skills/change-closeout/`, linked for both harnesses
      (`make check-agent-skills` passes). It checks the pre-closeout gate in its
      triage file, runs the citation check before archiving, puts any decision
      the change left to closeout to the owner, and after the archive reads each
      merged `spec.md` diff, then repoints the index row, all in one commit.
      Beyond the plan: a change with no deltas archives with `--skip-specs`;
      the row stays `in closeout` until shipping writes `archived`; when
      closeout moves code, the report says the pipeline run no longer describes
      `HEAD` and a validation is owed before shipping. No `make closeout`
      target: none was planned. Text, proven by 10.4.
      End-to-end coverage for 10.1–10.3: none. This is workflow tooling and
      skill text, proven by its own suites and by the pilot.
      Section checks: the four focused script suites, 95 passed;
      `make check-packaging` passed; `make check-agent-skills`,
      `make check-comment-hygiene`, and `openspec validate --strict` (1.14.0)
      pass; the scoped citation check reports only the four closeout documents
      the plan creates (the `change-workflow` spec and companion,
      `docs/agents/change-workflow.md`). `make test`: every suite passed up to
      `test-release-tooling`, where three compose-rendering tests
      (`test_bare_metal_compose.py`, `test_multi_storefront_compose.py`) failed
      because Docker was unreachable in the session's WSL distro; the section
      touches no compose file. The aggregate stopped there, so the Helm render
      checks did not run.
      Fresh-context check: fixed a weakened test match, the overstated
      citation count, `change-validate`'s record path, `make design` and
      `make implement` against the spec's "every step", part 6 moving the
      row's link before the archive exists (now in part 10), and the
      checklist's "active change". Declined: a guard refusing a closeout
      review of an active change (not asked for), and a ledger line for owner
      overrides during closeout (the ledger's shape has no closeout kind;
      design's to decide). Left for the owner, recorded below.
      Handoff: (1) Closeout now releases dependents (part 6) before the
      closeout gate, while `Depends on` gates until `archived`, written at
      shipping; a failed closeout review leaves dependents released. Either
      the release moves to `change-ship` or the gate becomes closeout.
      (2) The permanent `planning-governance` spec's "Roadmap currency at
      change closeout" still contrasts completion with archival and has a
      "complete but not yet archived" scenario; the delta needs a MODIFIED
      requirement, a spec change no task names. (3) The scoped citation check
      on an archived change, above. (4) `change-triage`'s closeout row names
      `change-ship`, written by 10.6.
- [ ] 10.4 Pilot the closeout half: run `change-closeout` on
      `capacity-shape-envelope`, after amending its section 7 to the new closeout —
      the eleven parts in order, comment hygiene and import placement as
      confirmations, 7.10's `spec.md` entries the archive's synchronization, and
      archival a part of its own — then its closeout review and triage.
      At that closeout, decide where two questions from validating this pilot
      belong: a kube namespace per validation, and the chart's out-of-band
      Secrets made optional with the ordinary values overlays as fallback.
- [ ] 10.5 Amend every other active change's closeout task the same way,
      preserving completed tasks: its unchecked parts reordered to
      `openspec/README.md`'s eleven, with archival a part of its own; comment
      hygiene and import placement made confirmations, any outstanding work on them
      moved to before the pre-closeout review; unchecked promotion tasks say the archive
      synchronizes the specs and is the last step; a change that already
      synchronized its specs by hand archives with `--skip-specs`, recorded as a
      note on its completed task. List the changes amended and any left as they
      were, with the reason.
- [x] 10.3a From the 10.1–10.3 handoff, at the owner's direction: dependents are
      released at archive cleanup, after the closeout gate, not at closeout, since a dependency lands
      at `archived` and closeout runs before its review (`openspec/README.md`
      part 6, `change-closeout`, the `planning-governance` delta's reverification
      requirement and a scenario for a closeout review that sends the change
      back, and design); and the delta modifies "Roadmap currency at change
      closeout" to drop its contrast between completion and archival, which now
      happen in one phase. Text only.
- [x] 10.3b Resolve an archived change's citations of its own unarchived path
      against its archive directory when `make check-doc-citations CHANGE=` is
      scoped to it, so a check rerun after the closeout review does not report
      the archive move; citations of anything else still must resolve. Test it
      against a temporary tree. Done before 10.4.
      Done in `scripts/check_doc_citations.py`. Unit, real temporary tree
      (`scripts/tests/test_check_doc_citations.py`): an archived change citing its
      own unarchived path resolves while a missing file under that path, and a
      missing citation elsewhere, are still reported; an active change's own-path citation must resolve as written.
      Against the repository, `bare-metal-buyer-domain` drops from six misses to
      the five documents that moved after it was archived.
- [x] 10.3c `make review KIND=closeout` refuses a change that is not archived,
      with no override: the closeout review reads the archive, and the remedy is
      to finish closeout, which archives. A change closed out before this rule,
      with specs synchronized by hand, archives with `--skip-specs` first. Test it
      beside the pre-closeout validation guard. Done before 10.4.
      Done in `run_review`, before any transcript or record is created. Unit, with
      the reviewer runner injected (`scripts/tests/test_run_change_review.py`): a
      closeout review of an active change is refused with nothing run or written;
      the existing case shows an archived change's closeout review recorded in the
      archive.
- [x] 10.3d Implementation review 2 (external, `reviews/02-implementation-external.md`),
      triaged: F2 and F5 are 10.3a and 10.3c.
      - F1: the `planning-governance` delta modifies "Canonical planning homes" — the
        `archived` status, not the directory's place, marks a completed change.
      - F3: `openspec/README.md`'s closeout parts are reordered to the order the
        work needs — judgement parts, packaging, pipeline evidence, promotion,
        citations, archival — eleven parts, archival on its own; `change-closeout`
        checks citations and the change's specs after promotion and before the
        archive; `AGENTS.md`'s list and `change-plan` follow.
      - F4: closeout changes documentation only. Comment hygiene and import
        placement are confirmed at closeout, done before pre-closeout, and asked
        about by the pre-closeout review (`change-review`); a needed code edit
        returns the change to implementation. `change-closeout` runs no suites and
        owes no validation.
      - F6: `change-triage` validates an archived change with `openspec validate
        --specs --strict`.
      - F7: only the steps after the archive find an archived change by name;
        `make design` and `make implement` refuse one (`scripts/find_change.py
        --active`; there is no plan target). Unit for the script's flag
        (`scripts/tests/test_find_change.py`); the two Make targets were run by
        hand against an archived change, and no test covers their wiring.
      - F8: `change-closeout` resolves the change through `find_change.py` and
        resumes after an archive that was not committed.
      - S1: `scripts/harness-review-context.sh`'s lifecycle sentence.
      Spec deltas (`change-workflow`, `planning-governance`) and design amended.
      Skill text is proven when a session follows it; 10.4 is that session.
      From the fresh-context check: the index legend and `change-plan` no longer
      have closeout release dependents; `change-implement` places imports at
      module level as it writes them, since closeout only confirms; closeout's
      packaging and citation parts name `check-agent-skills` and the change's
      `openspec validate`; a closeout triage stops for the owner on a finding
      that needs code, at the owner's direction (`change-triage`, delta scenario,
      design). The ledger records only course corrections: a disposition that
      accepts the agent's proposal writes no entry (`change-triage`, the ledger
      requirement and a scenario, design), at the owner's direction.
- [ ] 10.6 Write the `change-archive-cleanup` skill (named `change-ship` in the
      notes above), run when the closeout gate is passed:
      the export 12.10 settles, `reviews/` deleted with the ledger kept,
      dependents released as `openspec/README.md` part 6 states, and the
      commit message and pull request description drafted from the proposal, the
      promotion record, and the validation evidence; it sets the index row to
      `archived`. Pilot it on `capacity-shape-envelope`.

## 11. Shared guidance

- [ ] 11.1 Remove the "Generated implementation artifacts" section and the fileset
      wording from `AGENTS.md`, and the tombstone item from the
      `openspec/README.md` completion checklist. Confirm the browser session
      prompts still carry the whole tombstone convention, including that no
      tombstone survives into production code or permanent documentation.
- [ ] 11.2 Write `docs/agents/change-workflow.md`: invoking each leaf skill and
      `make review`, the review file layout, and the ledger; link it from
      `AGENTS.md`'s "Agent skills" section.
- [ ] 11.3 Confirm no committed skill refers to `docs/prompts/`.

## 12. Closeout

- [ ] 12.1 Comment hygiene: `make check-comment-hygiene`.
- [ ] 12.2 Import placement: review the imports this change added or touched,
      including in `scripts/fetch-e2e-logs.py`, `scripts/validate_slice.py`, and
      `scripts/check_push_ready.py`.
- [ ] 12.3 Documentation compliance: re-check this change's decisions against
      `openspec/README.md`'s placement rules.
- [ ] 12.4 Narrative compression of completed-task notes.
- [ ] 12.5 Roadmap currency: record that no roadmap goal is affected, or update it.
- [ ] 12.6 Campaign index currency: this change's row, including the
      dependency-landing step for any dependent.
- [ ] 12.7 Documentation citations: `make check-doc-citations CHANGE=agent-driven-change-workflow`.
- [ ] 12.8 Packaging: `make check-packaging`.
- [ ] 12.9 End-to-end pipeline: record a passing run and the scenarios it covers,
      or an explicit blocker naming its cause and owner.
- [ ] 12.10 Resolve the open question on exporting session transcripts and review
      logs: how `change-archive-cleanup` confirms the export ran before `reviews/` is deleted,
      and whether permanent documentation states that they are exported.
- [ ] 12.11 Promotion: complete the design-promotion record against the proposal's
      knowledge-to-promote list — `change-workflow` spec and architecture
      companion, the five `planning-governance` requirements (three added, two
      modified), closeout part 6,
      `AGENTS.md`, `docs/agents/change-workflow.md`, the run-selection paragraph of
      `docs/development/TESTING.md`, the PVC-retention paragraph of
      `docs/development/DEPLOYMENT_AND_CONFIG.md` (and whether
      `openspec/specs/deployment-state/architecture.md`'s paragraph on explicit
      volume choices should cite it), and a `change-workflow` row
      linking the spec and architecture companion in `openspec/specs/README.md`.
