Skills are written in the order the workflow uses them, and each is proven on a
pilot before the next is written. `capacity-shape-envelope` runs the whole
sequence; `add-full-stack-ci-job` was to prove design and planning from a bare
proposal, and that pilot was withdrawn (3.3).
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
      link resolves to the shared skill of its own name. Amended: no general check
      aggregate exists (`check-packaging` is packaging only), so `change-closeout`
      runs it among closeout's mechanical checks (10.3).
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
      targets); rows the change files contradicted were corrected, among them
      `bare-metal-mock-provisioned-deal` and
      `repair-storefront-alkahest-configuration`. By owner decision every change
      not already implementing is `ready for design`, and external-verification
      waits are `blocked in closeout` (`design.md`). Dependencies inferred from
      proposals were added; contradictions between two changes' own dependency
      claims are left for each change's design review, noted in `Notes`.
      Contradicting index prose and a malformed table were repaired.
- [x] 2.2 Rewrite the index's status definitions to the phase-and-state vocabulary
      and the `Depends on` rule.
- [x] 2.3 Amend part 6 (campaign index currency) of
      `openspec/README.md#plan-closeout-requirements` with the dependency-landing
      step: remove the completing change from every dependent's `Depends on`,
      return each dependent not yet implementing to `ready for design`, and record
      reverification as owed on a `blocked in` dependent rather than overwriting it.
      (Moved to archive cleanup by 10.3a; dependents returned per 10.6a F4.)

## 3. Design discussion

- [x] 3.1 Write the `change-design` skill: the context preload, numbered open
      questions with options, trade-offs, and a recommendation, no file edits until
      the owner settles the design, then decisions recorded in `design.md` and
      `proposal.md` amended when scope moves; it moves the index row to `in design`
      when discussion starts. Written at `.agents/skills/change-design/`; it also
      refuses to start while a dependency gating design is unlanded, checks for
      drift since an earlier design, and leaves `tasks.md` to planning.
- [x] 3.2 Pilot: resolve `capacity-shape-envelope`'s open questions; the owner
      judges depth against a browser session on the same questions.
      The skill matched the browser on every shared point and also raised a
      conceptual error, a guidance violation, and a false claim it missed; the
      browser alone raised a double-claimed call site and separate reporting of
      inadmissible shapes. Amended at the owner's direction: a summary, then
      corrections, then each decision as context, alternatives, and a reasoned
      recommendation; after the owner's review of the session, decision classes
      (judgement, consequence, convention, the latter two batched), no placement
      questions, no caller not alone a reason to omit a capability, example
      documents, every caller walked through a new interface, reopening on a
      corrected premise, ledgered redirections, and a whole-design check before
      recording. The design passed its gate after reviews 03–06.
- [x] 3.3 **Withdrawn** 2026-10-14: Pilot: design `add-full-stack-ci-job` from its proposal.
      The `add-full-stack-ci-job` pilot (3.3, 4.4, 6.3, and 5.2's half) is withdrawn
      at the owner's direction: no second full design cycle is run for this change.
      Its gap stays open here — design discussion, design review, and planning from a
      proposal alone, where `capacity-shape-envelope` only amended an existing plan —
      and is verified by `parallel-change-workflows`' pilots instead.

## 4. Change review

- [x] 4.1 Write the `change-review` skill, taking the review kind (`design`,
      `implementation`, `pre-closeout`, `closeout`) and the change: documents to
      read first, the diff to inspect, the questions per kind tagged by lens,
      prompting for the `direction` lens as design discussion and for the
      compliance lenses as exhaustive cited checking, reading earlier reviews and
      triage from `reviews/`, and producing one Markdown review whose findings
      carry lens, basis, severity, and evidence in the fixed field layout.
      Written at `.agents/skills/change-review/`. The design review also walks
      every caller through each new interface, checks each rationale against the
      other decisions, and compares scope with the proposal — gaps the first
      design pilot left.
- [x] 4.2 Add `make review CHANGE=<change> KIND=<kind>`, running the skill in Codex
      non-interactively with a read-only sandbox and capturing its final message
      as the next numbered file in `reviews/`.
      `scripts/run_change_review.py`, tests in
      `scripts/tests/test_run_change_review.py`. The implementation kinds take
      `REVIEW_BASE` (default `dev`); `MODEL` overrides the Codex model. The
      transcript's location and failed-run handling are superseded by 4.2a.
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
      amended after its second use: findings depending on an open decision held
      from the first pass, review findings logged under their own review, revised
      dispositions naming what they revise, the count of ledger entries reported,
      and a re-review recommended when dispositions changed a central decision.
      `make review` streams a condensed progress view; the transcript keeps
      everything.
- [x] 4.3 Pilot: design review of `capacity-shape-envelope`, also run through the
      browser process. Passes if no `blocking` or `should` browser finding the
      owner accepts is absent from the harness review.
      Result: failed. From the records — browser 04 and 05, harness 03 and 06 —
      four accepted browser findings had no harness counterpart: older storefronts
      silently ignoring the new declaration (04 F2, should), the envelope
      constraining stated rather than provisioned dimensions (04 F6, should), and
      a `tasks.md` still describing the earlier design, missed in both rounds
      (04 F7, 05 F6, blocking). The harness raised findings the browser missed too
      (06 matched all four round-2 architecture findings). `change-review`'s
      design questions amended at the owner's direction: consistency checks that a
      promised behaviour acts on what it says it governs, architecture walks each
      interface across versions, and readiness asks whether an existing
      `tasks.md` describes the settled design.
- [x] 4.4 **Withdrawn** 2026-10-14: Pilot: design review of `add-full-stack-ci-job`.
      See 3.3.

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
      review as `NN-<kind>-external.md`, merged with the harness review of its
      kind; classifies accepted outcomes as edit, design decision (sent to
      `change-design`), task, or none; and never dismisses a finding for
      challenging an owner decision. Amended after first use: each finding states,
      in prose, what the change says, the reviewer's reasoning, why it matters,
      and the agent's position. Presentation superseded by 9.8 and 9.10, ledger
      scope by 10.3d. `change-design` triages waiting reviews first.
- [x] 5.2 Pilot: triage the 4.3 and 4.4 reviews, passing each design gate.
      Done for `capacity-shape-envelope`: its design reviews 03–06 were triaged and
      the design gate passed. The `add-full-stack-ci-job` half is withdrawn with 4.4
      (see 3.3).

## 6. Planning

- [x] 6.1 Write the `change-plan` skill on top of `openspec-update-change`: tasks
      from the design that passed review, completed tasks preserved and amended
      rather than replaced, the files each accepted decision touches, the
      validation each section owes, each decision's permanent destination, and the
      closeout task; each section ending at a verification point and sized to be
      implemented in one fresh session. It moves the index row to `in planning`
      when planning starts and to `ready for implementation` when the owner
      accepts the plan.
      Written at `.agents/skills/change-plan/`, continuing the design session
      (`design.md`); it settles destinations the design delegated and logs plan
      redirections as `"review": "plan"`. Amended after implementation review 2
      (browser): an exposed design question returns the change to design, resuming
      after another design review or the owner's recorded waiver; gate evidence is
      read from files; completed tasks are amended, never deleted or rewritten;
      tasks may trace to a cited repository obligation. `change-triage`'s gate
      step rewrites the row's notes.
- [x] 6.2 Pilot: amend `capacity-shape-envelope`'s existing plan to its reviewed
      design. Run continuing the design session, at the owner's preference.
      The stale 24-task plan became seven sections and 45 tasks, accepted.
      Planning stopped correctly on one open design question (local-table
      derivation), which the owner decided; lacking the return-to-design step
      added afterwards, the owner's waiver of a re-review was recorded after the
      fact. Section 4 (a ~2,100-line module) was the likeliest to outgrow one
      session. `make check-doc-citations` now skips untracked `reviews/`.
- [x] 6.3 **Withdrawn** 2026-10-14: Pilot: plan `add-full-stack-ci-job` from nothing.
      See 3.3.

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
      Written at `.agents/skills/change-implement/`, replacing
      `openspec-apply-change` for this workflow (`design.md`); it refuses a branch
      not carrying the change and stops at a verified point when a section
      outgrows its plan. Amended at the owner's direction during 7.3: a session
      may continue into later sections (`make implement SECTIONS=1-3`, or on the
      owner's word), one review covering them, each section still checked, handed
      off, and committed alone. After the first multi-section run (sections 2–4,
      404k tokens, no compaction, compliance findings falling per section): every
      section runs `make test`, and notes name each suite's `TESTING.md` level,
      verified by the fresh-context check. The pilot's sections were committed to
      this branch at the owner's direction; the two changes merge together.
- [x] 7.2 Add a committed Claude Code project hook that, when a session resumes
      after compaction, re-reads the required guidance documents and restates the
      change and section being worked.
      `.claude/settings.json` (now un-ignored; `.claude/settings.local.json`
      stays ignored) runs `scripts/post_compaction_context.py` on `SessionStart`
      with the `compact` matcher. Under the 10,000-character cap (`design.md`) it
      names the documents to re-read in full, with the branch and the changes in
      progress. Tests in `scripts/tests/test_post_compaction_context.py`; the
      hook's firing is proven on the first compaction in a new session.
- [x] 7.3 Pilot: implement the first section of `capacity-shape-envelope` in its
      own session, recording what the fresh-context check caught.
      Done as sections 1–4 (7.1): the check caught a blocking constraint-loss bug
      in section 1, and compliance findings fell per section.

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
      Done; the part starts with `make dist-clean` (`design.md`), logs under
      `.snapshot/validation/<short commit>/local/<n>/` (8.8). Unit (fake runner
      and reader): the step order, the first-failure stop with its tail, a dirty
      tree (the fake answers only `git status --porcelain --untracked-files=all`)
      running nothing, and a step that dirties the tree failing the check after
      it. First run for real in 8.6.
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
      Done in `validate_slice.py`, as corrected by 8.6, 8.10, and 8.11:
      `make dist-clean`, the preflights, `make build-dev`, and a VM storefront
      reinstall before the render checks, so the loader check runs this commit;
      uninstall then `deploy-local`; `HELM_SCENARIOS` (`contracts`,
      `e2e_alkahest_escrow_codecs`, what the default charts serve) run, every
      other pipeline scenario reported not run (replacing `HELM_EXCLUSIONS`);
      `HELM_ALL_SCENARIOS=1` runs all. Scenarios wait, bounded, for the background
      port-forwards; `test-module` quotes `MODULE` for marker expressions. Unit:
      step order, unserved scenarios not run, the context and missing-environment
      refusals running nothing, a render `skip:` failing, unforwarding after a
      failing scenario or unopened ports, a non-`or` marker list refused; one test
      reads the real `e2e-tests/Makefile` variables through `make`. The tests
      prove the flag's effect, not its plumbing. The risk that `build-dev`, which
      regenerates the tracked `alkahest_anvil_addresses.json` and syncs the
      storefront without `--frozen`, would dirty the tree did not occur: every
      Helm part from validation 10 on ended clean.
- [x] 8.3 Add `make check-push-ready` and `make push-branch`
      (`scripts/check_push_ready.py`, tests against temporary Git repositories):
      refuse a detached `HEAD`, a dirty worktree, `main` or `dev`, and an upstream
      named differently from the branch; push a branch with no upstream to the
      same name on `origin` with its upstream set; push exactly `HEAD`, never
      forced; report and never repair.
      Done. `test_check_push_ready.py` drives real Git against a temporary
      repository and bare remote: a new branch pushed tracking its own name,
      exactly `HEAD` pushed, a moved remote rejecting the unforced push, and each
      refusal pushing nothing, detached and dirty leaving the checkout as it was.
- [x] 8.4 Make `scripts/fetch-e2e-logs.py` select the run whose head commit is the
      local `HEAD` (`--commit`, defaulting to `HEAD` when no `--run-id` is given),
      polling with a bound for a just-dispatched run and taking the newest match,
      with tests for both gaps: a finished earlier run on the branch, and a run not
      yet listed. Update the run-selection paragraph of
      `docs/development/TESTING.md`'s system integration section to match.
      Done. Unit (`test_fetch_e2e_logs.py`, fake runner): an earlier commit's run
      never fetched, a late-listed run waited for, the newest match taken,
      `--commit`, `--after-run` for a repeated dispatch, `--run-id` refusing either
      selector, the no-run error. `E2E_COMMIT` and `E2E_AFTER_RUN` reach the
      script through `make` (Makefile text asserted); `TESTING.md` describes it.
- [x] 8.5 Write the `change-validate` skill (`.agents/skills/change-validate/`,
      linked for both harnesses) and `make validate CHANGE=`: check the branch
      carries the change; `make push-branch` and `make run-e2e`; the local and Helm
      parts while the pipeline runs; `make fetch-e2e-logs` for `HEAD` and the
      run's conclusion; a diagnosis of each failing scenario from its logs; and
      `reviews/NN-validation.md`, numbered when written, naming the commit, each
      part's result, the Helm exclusions, the run and its conclusion, and the
      diagnoses. It never edits or fixes. `make check-agent-skills`.
      Done. Failures are `V<n>`; Helm runs after a local failure unless the tree
      was dirty; the newest run ID is recorded before dispatch. Proven only by
      8.6. Section checks: `check-packaging` and `make test` passed after `make
      dist-clean`, no lock rewritten (before it, other branches' wheels rewrote
      six locks and failed `kit/site`); the three new suites, 41 tests, pass;
      comment hygiene and `check-agent-skills` pass; `test-release-tooling` fails
      only `test_settlement_deployment_surfaces.py`'s two tests, as at the
      starting commit. `scripts/tests` is outside `make test`, so
      `validate-local` does not run it.
- [x] 8.6 Pilot: validate `capacity-shape-envelope` at `HEAD`. The Helm part runs
      the whole scenario set once with no exclusions, and the exclusion list is set
      from what fails for a missing service, as distinct from what fails for a real
      reason.
      Attempt 1 (`capacity-shape-envelope`'s `09-validation.md`, `75c121de`):
      local and pipeline passed; Helm gave no scenario evidence (a credential-helper
      timeout, then a volume another commit's migration rewrote) and ran with the
      exclusions, the instruction sitting in this change rather than the one
      validated. The owner's review produced 8.8–8.14. Attempt 2
      (`10-validation.md`, `004e580e`, with `HELM_ALL_SCENARIOS=1`): local passed;
      pipeline run 37917228588 passed (VM 135 passed, 3 skipped — API-credits
      payment cases from the merged `dev`; bare-metal 16 passed). The
      retained-volume preflight stopped the first Helm attempt, as designed; on the
      owner's word the release and its three `keep` PVCs were removed. The second
      ran every scenario: all that create a listing failed, the default chart
      values configuring no settlement mechanism (`design.md`). The owner kept
      chart work in `helm-e2e-pipeline-parity` and narrowed the Helm part (8.2); on
      that scope the record is `passed`. Skill findings: the retained-volume stop
      and owner settlement worked; no outcome covered missing evidence (now
      `inconclusive`, 8.8); one gap blocking every scenario prevented setting the
      exclusion list.
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
      Done. Unit: two attempts write `1/` and `2/`, each `summary.json` carrying
      its `attempt`; the printed path is not asserted. The outcome is the skill's
      (`design.md`); 9.3 names `passed`.
- [x] 8.9 Environmental failures in the session: amend `change-validate` to stop on
      a failure diagnosed as environmental with good confidence, put the evidence
      and remedy to the owner, rerun the part as a new attempt on the owner's word,
      record `inconclusive` when the owner declines, never treat an unknown cause
      as environmental, and report validation-tooling defects in a section of the
      record about the validation. State the full-control premise in the skill.
      Done in the skill (`## Environment`, `## Failures` for commit or unknown
      causes, `## About the validation`, the premise). Skill text; proven only by
      8.6's re-run.
- [x] 8.10 Fresh Helm state: add `persistence.retainOnUninstall` (default `true`)
      to the storefront, provisioning, registry, and bare-metal storefront charts,
      rendering `helm.sh/resource-policy: keep` only when it is true, with render
      tests for both settings; add `helm/local-values.yaml` setting it `false` and
      `make -C helm deploy-local`; the Helm part uninstalls an existing release,
      waits for its PVCs to go, stops on a surviving one, and deploys with
      `deploy-local`. Tests for the sequence and the surviving-PVC stop.
      Done. Render tests (`helm/scripts/test-render.sh`, needs Helm, no cluster):
      five PVCs, each by name, retained by default and not under
      `local-values.yaml`; breaking a template's condition fails exactly its
      check; `--set-string …=false` also disables retention. `deploy` takes
      `EXTRA_VALUES`; `deploy-local` passes the overlay; `undeploy` uninstalls with
      `--wait --ignore-not-found` (`stop` its alias). Unit (fakes modelling
      forwards and volumes as state): before the build, forwards stopped, ports
      free, a `keep` PVC refused; after it, `undeploy`, volumes polled until gone,
      `deploy-local`; a volume left at the deadline stops the deploy. PVCs are
      selected by `app.kubernetes.io/instance=<release>`; only the bare-metal
      storefront schema gains the property. `DEPLOYMENT_AND_CONFIG.md` describes
      the convention. Not run against a cluster when written; first exercised by
      8.6's attempt 2.
- [x] 8.11 Preflights: `gh auth status` before the push (skill); in the Helm part,
      `docker info`, a `Ready` node, `make -C helm check-local-secrets` (a new
      target over the chart's eight out-of-band Secret names, with a test that each
      name appears in `helm/values.yaml`), and the forwarded ports free after
      `unforward`; a credential-helper response check that warns only. Tests for
      each refusal and the warning.
      Done. Default values read six out-of-band Secrets, not eight
      (`arkhai-api-credits-registry-identity` only with `api-credits-registry`;
      `arkhai-e2e-credentials`, `arkhai-buyer-profile-credential`, and the
      `arkhai-buyer-profiles` PVC only by the e2e-tests chart's `helm test` hook,
      which validation does not run); `check-local-secrets` passes on
      `docker-desktop`. Unit (fakes): Docker unreachable, a node not Ready or
      absent, and a missing Secret each stop before `make dist-clean`; a silent
      helper warns and the part passes; a helper timing out, failing, or missing
      is named; `$DOCKER_CONFIG` honoured; each Secret appears in
      `helm/values.yaml`. Node and helper checks also run live; the retention query
      found three `keep` PVCs on the owner's release (settled in 8.6). Port and
      volume checks run after `unforward`, before the build.
- [x] 8.12 Coverage: amend `change-validate` to write the record's coverage section
      (scenario, basis, lane, result; or that none covers the change), reading the
      scenarios from the change's task notes and adding what the diff shows; amend
      `change-plan` to name the end-to-end scenarios each section's verification
      point relies on, and `change-implement` to confirm or correct them in the
      section's notes before committing.
      Done in the three skills; `change-plan`'s covering scenarios replace its
      older Helm-checks rule, and `change-implement` confirms them before the last
      task is checked. Skill text; proven by the next plan and section using them.
- [x] 8.13 `make validate CHANGE=<change> HELM_ALL_SCENARIOS=1` passes the
      instruction into the session's prompt, and `change-validate` runs the Helm
      part with it and records which scenarios fail only for a missing service.
      Done: the session opens as `/change-validate <change> with
      HELM_ALL_SCENARIOS=1` (Makefile text asserted; read by the session in 8.6);
      it runs every pipeline scenario, so the served list can grow.
- [x] 8.14 Record for `capacity-shape-envelope`'s closeout (10.3), to place there:
      a namespace per validation, and chart Secrets made optional with the ordinary
      values overlays as fallback.
      Done: recorded in 10.4, where the owner placed them.

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
- [x] 8A.3 Regenerate locks through `make lock` after a clean wheel build. Run
      focused workflow and shape-admissibility tests and the root unit/integration
      aggregate; run `make check-packaging`, `make check-agent-skills`, comment
      hygiene, scoped documentation citations, and strict OpenSpec validation.
      Check import placement, documentation ownership, completed-note compression,
      roadmap/index currency, and existing promotion destinations. Record failures
      and unrun typing, Docker/Helm end-to-end, or remote pipeline checks; retain
      the corresponding post-review closeout and promotion gates.
      Local merge checks (2026-10-08) passed: every root unit/integration target,
      agent skill links, comment hygiene, strict OpenSpec 1.14.0 validation, the
      index checks, registry-client typing, and `make check-packaging` on the
      final wheelhouse. Core typing reports the inherited `query_dsl.py:487`
      error, identical on both parents; scoped citations reported four inherited
      references to the workflow documents closeout creates; no function-local
      imports added. Not run: Docker and Helm end-to-end (local containers
      running; stack tests replace volumes) and the remote pipeline (no revision
      for the uncommitted merge). The retained gates are section 12's tasks.
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
      Done in `.agents/skills/change-triage/`, amending its steps so the
      presentation and ledger rules keep one copy. Outcome `fix`: in-session code
      changes, checked by `change-implement`'s step 5, committed once with the
      change documents and ledger, never pushed. Environmental entries and
      `inconclusive` parts are missing evidence; observations about other changes
      or the tooling are presented, not triaged. The fresh-context check added
      round recognition, the branch, worktree, and diff-base checks, a lone
      re-validation, and `O<n>` labels. Reworked by implementation review 1 F1, F2
      (after 9.10). Skill text; proven by 9.5.
- [x] 9.2 Add `make triage CHANGE=`, opening a Claude Code session with
      `/change-triage <change>`.
      Done. Its help names the round's inputs.
- [x] 9.3 In `scripts/run_change_review.py`: allocate a record's number when it is
      written rather than when the run starts, so parallel records never share one;
      and make `KIND=pre-closeout` refuse unless the latest validation record names
      `HEAD` and its result is `passed`, overridden by `UNVALIDATED=1`. Tests in
      `scripts/tests/test_run_change_review.py`.
      Done; per implementation review 1 (external) F3 the requirement is an
      establishable order and no overwrite (the exclusive claim), not unique
      numbers. Unit (runner and `HEAD` injected): a record written mid-run moves
      the review to the next number and renames its transcript, also on
      interruption; pre-closeout refuses, starting nothing, with no record,
      another commit's, `inconclusive`, or a later `failed` over `passed`, and runs
      on `passed` or `UNVALIDATED=1`; implementation reviews never check; a short
      commit prefix is accepted and a decorated `Commit:` or `Result:` fails
      closed (warned of in the template). `make -n review … UNVALIDATED=1` emits
      `--unvalidated`.
- [x] 9.4 Amend `change-implement`'s closing report (review and validation in
      parallel, the owner's notes, then `make triage`; the first three were done
      in 8.12, `make triage` remains) and `change-review`'s inputs
      (read the validation record of the reviewed commit when one exists; never
      wait for one).
      Done. `change-review` reads the validation of its commit when one exists,
      never waits, and names the pre-closeout requirement; `change-implement` and
      `change-validate` close with `make triage`.
- [x] 9.5 Pilot: triage `capacity-shape-envelope`'s `07-implementation.md` and
      `08-implementation-external.md` with 8.6's validation record and the owner's
      notes, through `make triage`; compare the two reviews for the pilot record;
      the change stays `in implementation`.
      Round 1 (`07`–`10`; `10-validation.md`, `004e580e`, passed on the narrowed
      Helm scope; `07` read sections 1–4 against `22115762`) was triaged by the
      owner under the first-built skill (`93d5733a`). Round 2 ran the amended
      workflow end to end: `11-validation.md` (`e4bf7a81`, passed after the
      retained-volume preflight stopped Helm attempt 1 on volumes an agent's plain
      `make deploy` left, remedied on the owner's word), `12-implementation.md`
      from `07`'s resumed reviewer, then `make triage`. Unaided, the triage checked
      the records' commits, fixed 12 F1 more broadly than asked with a test that
      fails without the fix, and recorded the gate; the resumed reviewer accounted
      for every finding from `03` to `10`. Gaps, amended in the skills: unrecorded
      fix checks (`change-triage` records them) and a presentation layout kept
      only in session memory (`change-triage` prescribes it). Round 1's reviews:
      the harness (`07`) found both code defects the browser (`08`) missed; the
      browser's accepted `should` (publication loop proven only at derivation
      level) was in `07`'s testing answer but not a finding (`change-review` now
      makes such gaps findings). The stray volumes led `DEPLOYMENT_AND_CONFIG.md`,
      both Makefiles, and the e2e-tests quick start to require `make -C helm
      deploy-local`. The fix round closed with a lone re-validation, as subagents
      at the owner's direction: `13-validation.md` (`22bc1408`, containing
      `6f04fc01`) passed every part first time; its triage wrote only the
      confirming file.

- [x] 9.6 Give the owner the round to read as uncommitted changes:
      `make round-diff CHANGE= [BASE=]` (a worktree script, removed by 9.7) checks out
      the round's base in a worktree beside the checkout and overlays `HEAD`'s
      files, other changes' directories excepted; `change-implement`,
      `change-validate`, and `change-triage` point the owner's notes at it. A
      pasted review's commit is read from the snapshot name and appended as the
      runner's `reviewed-commit` comment (`change-triage`). Spec delta and design
      amended (`design.md`, "An implementation round is triaged in a fresh
      session").
      Done at the owner's direction after pilot round 3, whose sections were
      committed before the owner could read them. Integration, real temporary Git
      repositories (11 passed); `main()` and the Make target untested; run once by
      hand on `capacity-shape-envelope` (base `22bc1408`, 21 files). Removed by
      9.7: the owner found a second editor project each round, without the owner's
      inline test setup, worse than reading in the checkout.

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
      Done at the owner's direction, over an editor comparison against a named
      base and the uncommitted-sections fallback (`design.md`). Two fresh-context
      checks' findings were fixed: branches stranded by a commit during the view
      or a fix after a hand return, views that could not be closed, a recorded run
      never forgotten, a dispatch over the running pipeline, an incomplete guard,
      the round's own commits named as strays, and overstated claims. Integration,
      real temporary Git repositories with push and dispatch through an injected
      runner (`scripts/tests/test_round_view.py`, 26 passed): the view's status and
      branch position; `done` in each case (edit kept, commit during the view,
      hand reset, never reset, fix after a hand return, earlier round commit) and
      its refusals off the branch or base; the base selection; the refusals that
      open no view; `start`'s push, baseline, dispatch order and failures. Not
      exercised: the Make targets and their prerequisite, the rollback when the
      reset itself fails, and the real `gh` and push.
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
      Unit, comparison injected (`scripts/tests/test_run_change_review.py`, 49
      passed): records of any change and an empty diff admit; any other path, one
      outside a change directory, `archive`'s, or a non-ancestor refuses, naming
      the path; `run_review` admits pre-closeout after a ledger commit. Real Git in
      a temporary repository: `_changed_since` lists paths (non-ASCII included,
      renames as both paths) and nothing for a non-ancestor or unknown commit. Not
      exercised: the check on real Git output end to end, and `make review` with a
      real ledger commit. Fresh-context findings (renames, ancestry, overstated
      tests) fixed.
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

Implementation review 1 (external, `reviews/01-implementation-external.md`),
triaged. Script fixes are proven at unit level; skill and spec fixes are text,
proven only when a session follows them:

- F1 — `make review` appends `<!-- reviewed-commit: <HEAD> -->` to each published
  review (one test, `HEAD` injected); `change-triage` compares every record's
  commit and triages a mismatch as one round only on the owner's logged waiver; a
  pasted review's commit is the owner's word, recorded; spec delta and design.
- F2 — `change-triage` presents earlier untriaged validation failures, merged with
  later evidence; only a record with no `V<n>` is marked superseded.
- F3 — record order establishable (number, or file time), nothing overwritten:
  `claim_record` creates the name exclusively and takes the next number if it
  exists (tested with a record written before the proposal and with a colliding
  proposal); an interrupted run leaves no empty record. An agent writing a record
  checks the name is free — a check, not an exclusive claim.
- F4 (section 8) — `Validation.step()` checks after every command that `HEAD` is
  the recorded commit and the tree clean; every caller stops on a failed step,
  `unforward` still running as cleanup. Tested for a dirtied tree in the local
  part and `HEAD` moving in the Helm part; the other stop points by reading.
- F5 — before closeout, `make check-doc-citations` may report only the documents
  the change creates at closeout (`change-implement`, `change-triage`).
- S1, S2 — owner notes saved as pasted, `O<n>` labels only in triage; validation
  and owner-note triage files are "not a gate".
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
      Done: `scripts/find_change.py` (`change_directory`; prints the directory as
      a script), used by `run_review`, `round_view.start`,
      `check_doc_citations.documents`, the `triage` and `validate` targets, and
      `change-validate`'s record path; `make design` and `make implement` refuse an
      archived change (10.3d F7); `validate-local` and `validate-helm` take no
      change. Unit (`test_find_change.py`, temporary tree): active, archived,
      active preferred, missing, twice archived refused naming both, a suffix not
      matched, non-names refused, the command's output and failure. Wiring: an
      archived closeout review recorded in the archive (unit, runner injected); an
      archived change's validation as round-view base (integration, real temporary
      Git repository); scoped citations on archived and unknown changes (unit,
      temporary tree). Make targets run by hand only. Own-path misses of a scoped
      check on an archived change, found on `bare-metal-buyer-domain`, are fixed by
      10.3b.
- [x] 10.2 Amend the guidance to match: `openspec/README.md`'s closeout part 10
      ends with `openspec archive <change> -y` (`--skip-specs` where the specs
      were synchronized by hand), parts 5 and 6 lose "not at archival", and the
      contributor workflow's step 7 says the closeout review reads the archive;
      `openspec/changes/README.md`'s legend drops `ready for archival` and
      `Depends on` names `archived`; `change-triage`'s gate table, `change-review`'s
      closeout kind, and `change-design`'s dependency rule likewise.
      Done: closeout ends by archiving (`--skip-specs`, the lookup); parts 5 and 6
      no longer contrast completion with archival; the legend has `deferred` and
      `archived` outside the grid; `change-review` and `change-triage` use the
      lookup, the closeout review reading the merged specifications and asking
      whether each delta kept its meaning and the change may land; the gate
      table's `closeout` row is `archived`. Part order superseded by 10.3d F3, the
      landing rule's timing by 10.3a, the writer of `archived` by 10.6. Text,
      proven when 10.4 follows it.
- [x] 10.3 Write the `change-closeout` skill over the ten parts of
      `openspec/README.md#plan-closeout-requirements`, running each mechanical part
      and reporting the parts that need judgement, including
      `make check-agent-skills`; it moves the index row to `in closeout` when
      closeout starts, updates the row's link to the archived directory, archives
      the change last, and commits, so that the closeout review reads the archive.
      Done at `.agents/skills/change-closeout/`, linked for both harnesses. It
      checks the pre-closeout gate, puts decisions left to closeout to the owner,
      archives (`--skip-specs` with no deltas), reads each merged `spec.md` diff,
      and repoints the row, in one commit; the row stays `in closeout` until
      archive cleanup (10.6). Part order, citation timing, code moves, and `make
      closeout` superseded by 10.3d. End-to-end coverage for 10.1–10.3: none;
      tooling and skill text, proven by its suites and the pilot. Section checks:
      four focused script suites, 95 passed; `check-packaging`,
      `check-agent-skills`, comment hygiene, and `openspec validate --strict`
      (1.14.0) pass; scoped citations report only the closeout documents the plan
      creates. `make test` passed up to `test-release-tooling`, where three
      compose-rendering tests (`test_bare_metal_compose.py`,
      `test_multi_storefront_compose.py`) failed with Docker unreachable in the
      session's WSL distro (no compose file touched); the Helm render checks did
      not run. The fresh-context check's fixes were made; declined: a ledger line
      for closeout overrides (no closeout kind), and a guard on closeout reviews of
      active changes, later added by 10.3c. Handoff items resolved by 10.3a,
      10.3b, and 10.6 (then called `change-ship`).
- [x] 10.4 Pilot the closeout half: run `change-closeout` on
      `capacity-shape-envelope`, after amending its section 7 to the new closeout —
      the eleven parts in order, comment hygiene and import placement as
      confirmations, 7.10's `spec.md` entries the archive's synchronization, and
      archival a part of its own — then its closeout review and triage.
      At that closeout, decide where two questions from validating this pilot
      belong: a kube namespace per validation, and the chart's out-of-band
      Secrets made optional with the ordinary values overlays as fallback.
      Placed by the owner after the pilot's closeout, which could not see them,
      being recorded here: optional Secrets is an open question of
      `helm-e2e-pipeline-parity`; a namespace per validation belongs to
      `parallel-change-workflows`. Closeout archived the pilot in `f7447b35`,
      documentation only. Closeout review 21's one blocking finding, F1
      (hold-or-close summaries in `ARCHITECTURE.md` and `DEPLOYMENT_AND_CONFIG.md`
      contradicting the spec's base-shape-first rule), was fixed in `f7acf392`;
      external review 22 passed it; the owner passed the gate on both.
- [x] 10.5 Amend every other active change's closeout task the same way,
      preserving completed tasks: its unchecked parts reordered to
      `openspec/README.md`'s eleven, with archival a part of its own; comment
      hygiene and import placement made confirmations, any outstanding work on them
      moved to before the pre-closeout review; any instruction to remove the change from
      other rows' `Depends on` or reset dependents moved out of closeout, since
      archive cleanup releases dependents; unchecked promotion tasks say the archive
      synchronizes the specs and is the last step; a change that already
      synchronized its specs by hand archives with `--skip-specs`, recorded as a
      note on its completed task. List the changes amended and any left as they
      were, with the reason.
      Amended, 46: `add-alkahest-attestation-reference-query`,
      `add-database-migration-commands`, `add-deterministic-regression-contract`,
      `add-future-domain-shape-validation`, `add-harness-buyer-action-slice`,
      `add-harness-findings-projection`, `add-harness-scenario-contract`,
      `add-persistent-buyer-profiles`, `apicredits-end-to-end-lane`,
      `automate-seller-spot`, `bare-metal-and-credits-domain-stacks`,
      `billable-capacity-reservations`, `capacity-reservation-lifecycle-hardening`,
      `contain-embedded-host-key-material`, `deduplicate-dynaconf-bootstrap`,
      `default-no-pre-settlement-capacity-hold`, `disburse-a-settlement-disposition`,
      `fix-golden-image-config`, `fix-resource-pool-provider-at-creation`,
      `kit-owned-capacity-and-publication`, `kit-owned-negotiation-runtime`,
      `kit-storefront-composition-seam`,
      `market-platform-compute-40-multi-domain-proof`,
      `multi-domain-storefront-composition`, `name-unverifiable-responses`,
      `negotiation-capacity-feasibility-probe`, `negotiation-driven-capacity-resize`,
      `negotiation-time-capacity-hold`, `never-strand-the-host-on-passthrough`,
      `pools-6-fair-scheduling-policy`, `pools-7-storefront-fulfillment-cutover`,
      `pools-8-capacity-projection-and-listing-hints`, `publish-wheels-through-a-gate`,
      `refactor-e2e-fulfillment-lifecycle`, `relay-vm-access-without-a-dashboard`,
      `repair-storefront-alkahest-configuration`,
      `replace-polling-with-authenticated-push`, `restore-issue-discovery-thin-runner`,
      `retain-authenticated-request-outcomes`, `separate-marketplace-registry`,
      `service-identity-signing`, `settle-capacity-claim-vocabulary`,
      `shorten-long-requirements`, `sign-multi-language-credits-middleware`,
      `storefront-domain-parameterization`, `type-core-packages`. Sections with no
      checked closeout task were rewritten as the eleven parts; others kept their
      checked tasks, reworded the rest, appended missing parts, and note the
      order. Comment and import work moved to the last implementation section;
      nine hand-synchronized specs noted for `--skip-specs`; implementation tasks
      hand-copying delta-covered specs or archiving withdrawn into closeout, and a
      change without spec deltas records that in place of strict validation
      (`openspec/README.md` part 10, `change-closeout`), both at the owner's
      direction. Left as they were: `bare-metal-mock-provisioned-deal`,
      `pools-9-retire-local-physical-authority`, and
      `remove-dead-storefront-physical-surfaces` (archived on `dev`);
      `unbacked-bare-metal-listings` (rewritten by `dev`, swept in 11.4);
      `redesign-authenticated-replay-state` (unplanned, no closeout task); changes
      with no `tasks.md`. Section 12 here was aligned too.
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
      (`scripts/tests/test_check_doc_citations.py`): an archived change's own-path
      citation resolves, a missing file under that path and a missing citation
      elsewhere are reported, an active change's own-path citation must resolve as
      written. `bare-metal-buyer-domain` drops from six misses to the five
      documents moved after its archive.
- [x] 10.3c `make review KIND=closeout` refuses a change that is not archived,
      with no override: the closeout review reads the archive, and the remedy is
      to finish closeout, which archives. A change closed out before this rule,
      with specs synchronized by hand, archives with `--skip-specs` first. Test it
      beside the pre-closeout validation guard. Done before 10.4.
      Done in `run_review`, before any transcript or record. Unit, runner injected
      (`scripts/tests/test_run_change_review.py`): an active change's closeout
      review is refused with nothing run or written.
- [x] 10.3d Implementation review 2 (external, `reviews/02-implementation-external.md`),
      triaged: F2 and F5 are 10.3a and 10.3c.
      - F1: the `planning-governance` delta modifies "Canonical planning homes":
        the `archived` status, not the directory, marks a completed change.
      - F3: closeout parts reordered to the order the work needs — judgement
        parts, packaging, pipeline evidence, promotion, citations, archival on its
        own — with `AGENTS.md`'s list and `change-plan` following.
      - F4: closeout changes documentation only; comment hygiene and import
        placement are done before pre-closeout, asked about by its review, and
        confirmed at closeout, a needed code edit returning the change to
        implementation; `change-closeout` runs no suites and owes no validation.
      - F6: `change-triage` validates an archived change with `openspec validate
        --specs --strict`.
      - F7: only steps after the archive find an archived change; `make design`
        and `make implement` refuse one (`find_change.py --active`; unit in
        `scripts/tests/test_find_change.py`); the two targets were run by hand,
        and no test covers their wiring.
      - F8: `change-closeout` resolves the change through `find_change.py` and
        resumes after an uncommitted archive.
      - S1: `scripts/harness-review-context.sh`'s lifecycle sentence.
      Spec deltas and design amended; skill text proven by 10.4. From the
      fresh-context check: the legend and `change-plan` no longer have closeout
      release dependents; `change-implement` places imports at module level as
      written; closeout names `check-agent-skills` and `openspec validate`. At the
      owner's direction, a closeout triage stops for the owner on a finding needing
      code, and the ledger records only course corrections (`change-triage`, delta,
      design). `make closeout CHANGE=` opens `change-closeout`, active or
      archived, so an interrupted closeout resumes (`make -n` test).
- [x] 10.6 Write the `change-archive-cleanup` skill (named `change-ship` in the
      notes above), run when the closeout gate is passed:
      `reviews/` kept in place as 12.10 decided,
      dependents released as `openspec/README.md` part 6 states, and the
      commit message and pull request description drafted from the proposal, the
      promotion record, and the validation evidence; it sets the index row to
      `archived`. Pilot it on `capacity-shape-envelope`.
      Written: `.agents/skills/change-archive-cleanup/SKILL.md`, opened by `make
      archive-cleanup CHANGE=` (archived changes only, `find_change.py
      --archived`, unit-tested; the target by `make -n`). It checks the branch, the
      archive, the `in closeout` row, and that every closeout review is triaged
      with the latest gate passed; edits only the index; keeps `reviews/`; commits
      without pushing; writes the merge drafts to the archive's
      `reviews/pull-request.md`. At the owner's direction triage stops at a passed
      closeout gate and names `make archive-cleanup` (gate table, delta scenario,
      design), after the pilot's triage cleaned up the archive itself before the
      skill existed; that unpushed commit was dropped. Pilot in `093dc8f6`: the
      index edits matched the dropped reference (row `archived`,
      `publish-shape-bounds` released and left `ready for design`, graph marked,
      the resize change's notes rewritten), the row's notes more exact; the drafts
      named the other changes the branch carries. Also fixed: strict validation,
      failing since 10.3d because a MODIFIED requirement renamed a scenario, which
      keeps its name.

- [x] 10.6a From implementation review 3 (external, `reviews/03-implementation-external.md`),
      at the owner's dispositions. F1: `reviews/` is kept until an export flow
      exists (delta, design). F2: closeout code fixes stay owner-directed
      in-session, `change-triage` suggesting, never requiring, a review of the
      validated fix. F3: `scripts/check_change_index.py` (`make
      check-change-index`) checks every row's cells, link, status, and
      dependencies and that every change directory has a row, run after index
      edits by gate triage, closeout, and archive cleanup (skills,
      `openspec/README.md` part 6, delta with a scenario, design,
      `docs/agents/change-workflow.md`). F4: archive cleanup returns `ready for
      planning`, `in planning`, and `ready for implementation` dependents to
      `ready for design` and keeps `in implementation`, reading no `tasks.md`
      (part 6, legend, `planning-governance` delta with a scenario, design, skill).
      F5: the proposal describes the current workflow. Checks: `scripts/tests` 648
      passed (unit and `make -n` tooling tests; `test_check_change_index.py` 16,
      unit against a temporary index); comment hygiene, `check-agent-skills`, the
      index check, and strict validation pass; scoped citations report only the
      spec and companion promotion creates. The fresh-context check against
      `7cd6bedd` led to a moved test import, a restated scenario, and three
      completed index-check descriptions; `AGENTS.md`'s "Domain docs" citing the
      nonexistent `docs/adr/` is inherited, left for its own change.
## 11. Shared guidance

- [x] 11.1 Remove the "Generated implementation artifacts" section and the fileset
      wording from `AGENTS.md`, and the tombstone item from the
      `openspec/README.md` completion checklist. Confirm the browser session
      prompts still carry the whole tombstone convention, including that no
      tombstone survives into production code or permanent documentation.
      Done: `AGENTS.md`'s section is gone and its packaging bullet says "before the
      work is committed"; the checklist item is gone. `docs/prompts/implementation.md`
      and `change-grooming.md` carry the whole convention, and nothing cited the
      removed section. The comment rule's ban on tombstone references stays, since
      the browser process still produces them.
- [x] 11.2 Write `docs/agents/change-workflow.md`: invoking each leaf skill and
      `make review`, the review file layout, and the ledger; link it from
      `AGENTS.md`'s "Agent skills" section.
      Done: the skill table (step, skill, how to start it, what it writes), the
      order of steps and their refusals, `make review`'s options and external
      reviews, the round view, the review directory, and the ledger; linked from a
      "Change workflow" subsection of `AGENTS.md`'s "Agent skills". It cites only
      documents that exist; promotion (12.11) adds the links to the
      `change-workflow` spec and architecture companion it creates.
- [x] 11.3 Confirm no committed skill refers to `docs/prompts/`.
      Done: no skill, and nothing under `.claude/` or `.codex/`, names
      `docs/prompts/`.
- [x] 11.4 Merge `dev` into this branch before closeout, so closeout promotes
      against the documents as they are on `dev`. Then sweep, as 10.5 did, the
      closeout section of `unbacked-bare-metal-listings`, whose `dev` version
      rewrote it, and of any change `dev` added.
      Merged in `7cd6bedd`, resolved toward `dev`'s retirement of local-table
      derivation and `home_site`, carrying this branch's admissibility default and
      pricing-hold exclusions and dropping the local-table admissibility tests,
      scenario, and documentation. The index kept this format, `dev`'s rows
      converted and the dependents of the five changes `dev` archived released.
      For `dev`'s architecture check the contracts allowlist named the
      admissibility kit, at the owner's choice (edge removed by 11.5 F4), and that
      kit gained its own allowlist; it joined the three publication lists `dev`'s
      publish-matrix tests check. Swept: `unbacked-bare-metal-listings` and
      `encapsulate-capacity-backing` (placeholders name the eleven parts);
      `deduplicate-dynaconf-bootstrap` and `change-closeout` run `make
      check-architecture-change` in packaging, which `dev` added to part 7.

- [x] 11.5 From implementation review 4 (external, `reviews/04-implementation-external.md`,
      the merge and section 11), at the owner's dispositions. F1: the index check
      requires one row per active change directory and reports duplicates; an
      archived change's row may be pruned (checker, delta with a scenario,
      `openspec/README.md` part 6, the guide, design, the Make help). F2: the
      proposal's non-goal, tooling list, and chart retention line corrected. F3:
      `openspec/README.md`'s contributor steps record destinations during
      implementation and promote at closeout. F4: `kit/resource-pools-contracts`
      no longer declares the shape kit it does not import (`pyproject.toml`, its
      allowlist, `RELEASING.md`, `ARCHITECTURE.md`); relocked after `make
      dist-clean`, a wheel another branch built having been taken as the newest
      contracts version; each lock lost only that edge. Checks: `make
      check-packaging` passes with no architecture warning; `make test-kits` and
      `make test-storefront` (1037 unit, 411 integration) pass; `scripts/tests`
      650 passed (`test_check_change_index.py` 18, unit against a temporary
      index); comment hygiene, `check-agent-skills`, the index check, and strict
      validation pass; scoped citations report only the spec and companion
      promotion creates.


## 12. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

Listed in an earlier order; closeout works the parts in `openspec/README.md`'s order.

- [x] 12.1 Comment hygiene — confirm: `make check-comment-hygiene`, and read the
      comments this change added; anything to rewrite returns it to implementation.
      Confirmed: `make check-comment-hygiene` passes, and the comments the change
      added to `scripts/` describe current behaviour; none names the review or
      migration that introduced it.
- [x] 12.2 Import placement — confirm: check the imports this change added or touched,
      including in `scripts/fetch-e2e-logs.py`, `scripts/validate_slice.py`, and
      `scripts/check_push_ready.py`.
      Confirmed: an AST scan of every script and test this change added or touched
      under `scripts/` finds no function-local import.
- [x] 12.3 Documentation compliance: re-check this change's decisions against
      `openspec/README.md`'s placement rules.
      Done: every decision has a placement-rule destination in the promotion record.
      Corrected in `design.md`: the index is checked by `make check-change-index`
      and the landing rule runs at archive cleanup; concurrent validation and a
      namespace per validation belong to `parallel-change-workflows`, optional chart
      Secrets to `helm-e2e-pipeline-parity`. The `TESTING.md` run-selection and
      `DEPLOYMENT_AND_CONFIG.md` retention paragraphs, written in section 8, match
      the code.
- [x] 12.4 Narrative compression of completed-task notes.
      Done: sections 1–11's notes cut by about a third — final behaviour, evidence
      with test levels, deferrals, destinations, superseded detail replaced by a
      pointer. Moved to `design.md` first: the OpenSpec skills' links, planning's
      default run in the design session, and `change-implement` replacing `openspec-
      apply-change`.
- [x] 12.5 Roadmap currency: record that no roadmap goal is affected, or update it.
      No roadmap goal affected: `docs/development/ROADMAP.md` has no goal covering
      contributor workflow.
- [x] 12.6 Campaign index currency: this change's row and its campaign placement;
      other rows' `Depends on` are left to archive cleanup.
      This change's row is `in closeout`, under independent active changes, with no
      campaign graph; `parallel-change-workflows`' `Depends on` is left for archive
      cleanup. `make check-change-index` passes.
- [x] 12.7 Documentation citations, after promotion (12.11):
      `make check-doc-citations CHANGE=agent-driven-change-workflow`, then
      `openspec validate agent-driven-change-workflow --strict`.
      `make check-doc-citations CHANGE=agent-driven-change-workflow` reports
      nothing; `openspec validate agent-driven-change-workflow --strict` (1.14.0)
      passes. The unscoped check's 11 misses are all elsewhere and predate this
      closeout.
- [x] 12.8 Packaging: `make check-packaging`.
      `make check-packaging` passes with no architecture warning and no lock
      rewritten; `make check-architecture-change CHANGE=agent-driven-change-
      workflow` reports no row; `make check-agent-skills` passes.
- [x] 12.9 End-to-end pipeline: record a passing run and the scenarios it covers,
      or an explicit blocker naming its cause and owner.
      Run 38627126214 passed on `197bff17`, the closeout commit after the dev merge,
      run at the owner's word because the merge changed the VM listings reconciler
      and storefront code after the last run (38460926563, `443f9505`). `e2e-vm`
      134 passed, `e2e-bare-metal` 51 passed, `e2e-apicredits` 1 passed and 3
      skipped: the payment-deal scenarios skip when `PAYMENTS.*` is not
      configured, as on dev's own run 37936939239. The change's own code is
      contributor tooling the pipeline does not run, except that
      `make fetch-e2e-logs E2E_RUN_ID=38627126214` fetched this run's logs.
- [x] 12.10 Resolve the open question on exporting session transcripts and review
      logs: how `change-archive-cleanup` confirms the export ran before `reviews/` is deleted,
      and whether permanent documentation states that they are exported.
      Decided by the owner, ahead of closeout because 10.6 waited on it: archive
      cleanup does not delete `reviews/` until an export flow exists, and then
      exports as part of archive cleanup; permanent documentation states nothing
      about export meanwhile. Recorded in `design.md`'s open question.
- [x] 12.11 Promotion: complete the design-promotion record against the proposal's
      knowledge-to-promote list — `change-workflow` spec and architecture
      companion, the five `planning-governance` requirements (three added, two
      modified), closeout part 6,
      `AGENTS.md`, `docs/agents/change-workflow.md`, the run-selection paragraph of
      `docs/development/TESTING.md`, the PVC-retention paragraph of
      `docs/development/DEPLOYMENT_AND_CONFIG.md` (and whether
      `openspec/specs/deployment-state/architecture.md`'s paragraph on explicit
      volume choices should cite it), and a `change-workflow` row
      linking the spec and architecture companion in `openspec/specs/README.md`.
      The `change-workflow` and `planning-governance` `spec.md` files the deltas
      cover are written by the archive in 12.12, not by hand.
      Done: `openspec/specs/change-workflow/architecture.md` written;
      `openspec/specs/change-workflow/spec.md` created as a skeleton (Purpose,
      Evidence) the archive fills with the delta's requirements, so it is never left
      "Purpose: TBD"; `openspec/specs/README.md` gains the capability row;
      `docs/agents/change-workflow.md` links the spec and companion;
      `openspec/specs/deployment-state/architecture.md` points at the retention
      paragraph; `planning-governance`'s Evidence names closeout part 7 for
      packaging. The design-promotion record is complete. The delta's review-records
      requirement says durable content is promoted at closeout, since `reviews/` is
      no longer deleted.
- [x] 12.12 Archival, last: `openspec archive agent-driven-change-workflow -y`
      merges the deltas and moves the change under `openspec/changes/archive/`;
      point the index row at it, and run `openspec validate --specs --strict`.
      Archived with the deltas merged: neither permanent spec carried them by
      hand. `change-workflow` gains its 11 requirements under the skeleton's
      Purpose; `planning-governance` gains 3 and has 2 modified. The row links the
      archive; `openspec validate --specs --strict` and `make check-change-index`
      pass.
