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
- [ ] 7.3 Pilot: implement the first section of `capacity-shape-envelope` in its
      own session, recording what the fresh-context check caught.

## 8. Pre-review validation

Validation observes one commit and edits nothing (`design.md`, "Validation observes
a committed slice and never alters it"). Every script below is tested in
`scripts/tests/` with an injected command runner, at unit level, except where a
real repository is the lowest level that proves the behaviour, and except
`fetch-e2e-logs.py`, whose existing tests patch `subprocess.run` and were extended
in that form rather than converted. No end-to-end scenario covers this section: it
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
      fixes are diffed against, superseded validation records, a validation naming
      another commit than the reviews (ask the owner), a lone re-validation, and
      owner-note labels `O<n>`. Skill text; proven by 9.5.
- [x] 9.2 Add `make triage CHANGE=`, opening a Claude Code session with
      `/change-triage <change>`.
      Done. Its help names the round's inputs.
- [x] 9.3 In `scripts/run_change_review.py`: allocate a record's number when it is
      written rather than when the run starts, so parallel records never share one;
      and make `KIND=pre-closeout` refuse unless the latest validation record names
      `HEAD` and its result is `passed`, overridden by `UNVALIDATED=1`. Tests in
      `scripts/tests/test_run_change_review.py`.
      Done. Unit (`test_run_change_review.py`, the runner and `HEAD` injected): a
      record written while the reviewer runs makes the review take the next
      number, and its transcript is renamed from its provisional name, also when
      the run is interrupted; a
      pre-closeout review refuses, and starts no reviewer, with no validation
      record, one naming another commit, an `inconclusive` result, or a later
      `failed` record over an earlier `passed` one; it runs on a passing record or
      `UNVALIDATED=1`; an implementation review never checks; a short commit
      prefix is accepted and a decorated `Commit:` or `Result:` line fails closed,
      which `change-validate`'s template now warns about. `make -n review …
      UNVALIDATED=1` emits `--unvalidated`. The existing test of the reviewer's
      command now passes the override, since it runs with no repository.
- [x] 9.4 Amend `change-implement`'s closing report (review and validation in
      parallel, the owner's notes, then `make triage`; the first three were done
      in 8.12, `make triage` remains) and `change-review`'s inputs
      (read the validation record of the reviewed commit when one exists; never
      wait for one).
      Done. `change-review` reads the validation of the commit it reviews when one
      exists, never waits, and names the pre-closeout requirement;
      `change-implement` and `change-validate` close with `make triage`.
- [ ] 9.5 Pilot: triage `capacity-shape-envelope`'s `07-implementation.md` and
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

## 10. Closeout and archival

- [ ] 10.1 Write the `change-closeout` skill over the ten parts of
      `openspec/README.md#plan-closeout-requirements`, running each mechanical part
      and reporting the parts that need judgement, including
      `make check-agent-skills`; it moves the index row to
      `in closeout` when closeout starts.
- [ ] 10.2 Write the `change-ship` skill: archival with the intervention ledger kept
      and `reviews/` deleted, and drafting the commit message and pull request
      description from the proposal, the promotion record, and the validation
      evidence; it moves the index row to `archived`.
- [ ] 10.3 Pilot: implement `capacity-shape-envelope`'s remaining sections, one
      session each, then
      pre-closeout review and triage, closeout, closeout review and triage, and
      archival.
      At that closeout, decide where two questions from validating this pilot
      belong: a kube namespace per validation, and the chart's out-of-band
      Secrets made optional with the ordinary values overlays as fallback.

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
      logs: how `change-ship` confirms the export ran before `reviews/` is deleted,
      and whether permanent documentation states that they are exported.
- [ ] 12.11 Promotion: complete the design-promotion record against the proposal's
      knowledge-to-promote list — `change-workflow` spec and architecture
      companion, the three `planning-governance` requirements, closeout part 6,
      `AGENTS.md`, `docs/agents/change-workflow.md`, the run-selection paragraph of
      `docs/development/TESTING.md`, the PVC-retention paragraph of
      `docs/development/DEPLOYMENT_AND_CONFIG.md` (and whether
      `openspec/specs/deployment-state/architecture.md`'s paragraph on explicit
      volume choices should cite it), and a `change-workflow` row
      linking the spec and architecture companion in `openspec/specs/README.md`.
