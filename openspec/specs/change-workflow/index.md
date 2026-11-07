# Change Workflow — index

Prefix: `CW`

This is the specification's organization: its parts and groups, each requirement by
id with a summary line. [`spec.md`](spec.md) holds the requirements flat, in no
meaningful order; [`README.md`](README.md) is the readable description.

## 1. The process

### Phases and the owner's touchpoints

- [CW-ab9h](spec.md#requirement-cw-ab9h-a-change-moves-through-four-phases-in-order) — design, planning, implementation, closeout, in order; only an owner's direction departs, never across the archive.
- [CW-nfdb](spec.md#requirement-cw-nfdb-a-phase-ends-only-when-its-reviews-triage-advances-it) — design, implementation, and closeout end only when their review's triage names a next-phase exit.
- [CW-hdxi](spec.md#requirement-cw-hdxi-the-merge-brings-in-the-branch-the-change-lands-on) — after pre-closeout, a merge brings in the landing branch and reconciles the change's code with it.
- [CW-a6ow](spec.md#requirement-cw-a6ow-closeout-waits-for-a-validation-of-the-merged-head) — closeout waits for a passed validation of the merged `HEAD`; another review or a waiver needs the owner.
- [CW-9pbk](spec.md#requirement-cw-9pbk-the-owner-is-consulted-at-fixed-touchpoints) — the owner answers design questions, round notes, discussed findings' dispositions, and another round when recommended; advancing is taken without asking.

### Closeout and the archive

- [CW-ksnu](spec.md#requirement-cw-ksnu-closeout-archives-the-change-before-its-review) — closeout archives the change first, so the closeout review reads it and the specifications as archived.
- [CW-trdu](spec.md#requirement-cw-trdu-archive-cleanup-waits-on-the-closeout-reviews-triage) — cleanup waits on the closeout triage advancing, and a passed validation when a path outside the inert paths changed since, unless waived.
- [CW-pkug](spec.md#requirement-cw-pkug-closeout-changes-documentation-only) — closeout edits documentation only; needing a code change returns the change to implementation.
- [CW-1iaz](spec.md#requirement-cw-1iaz-steps-after-the-archive-find-a-change-by-name) — post-archive steps find an archived change by name; design, planning, and implementation refuse it.
- [CW-z83w](spec.md#requirement-cw-z83w-a-design-decision-after-the-design-review-returns-to-design) — a design decision after the design review returns to design; the owner may waive another review.

### The change index

- [CW-uj2q](spec.md#requirement-cw-uj2q-the-step-that-makes-a-transition-writes-it-to-the-index) — each phase or state transition is written to the index row by the step that makes it.
- [CW-jyff](spec.md#requirement-cw-jyff-every-edit-of-the-change-index-is-checked) — every index edit is checked for cell counts, links, statuses, dependencies, and one row per change.

### Discussion steps

- [CW-3tvs](spec.md#requirement-cw-3tvs-design-and-triages-discussed-findings-are-conversations-with-the-owner) — design runs with the owner, and triage brings the owner every finding not accepted by default, one decision or discussed finding per turn, as resumable sessions; a triage with nothing to discuss that advances asks nothing.
- [CW-p1us](spec.md#requirement-cw-p1us-planning-asks-the-owner-nothing) — planning asks nothing; a plan needing an undecided design question returns the change to design.

### A design blocked on a prerequisite

- [CW-dtpz](spec.md#requirement-cw-dtpz-a-design-blocked-on-a-prerequisite-ends-blocked) — design defines the prerequisite with the owner, proposes it from the development branch, and ends blocked.
- [CW-p7xk](spec.md#requirement-cw-p7xk-a-blocked-design-waits-until-its-prerequisite-is-released) — the blocked change stays `in design` until the prerequisite is archived, merged in, and released by the owner.

### The owner's directions

- [CW-jtsl](spec.md#requirement-cw-jtsl-the-owner-may-direct-a-change-to-any-node) — only the owner may direct a change to any graph node, by a logged decision with a reason.
- [CW-zcx8](spec.md#requirement-cw-zcx8-a-directed-step-is-named-until-it-runs) — a directed step is named, unguarded by exit guards, until it runs; it sets its own status.
- [CW-uhdy](spec.md#requirement-cw-uhdy-a-direction-is-held-to-the-unwaivable-entry-guards-it-meets) — a direction is refused at an unmet unwaivable entry guard, never crossing the archive; waivable guards yield.
- [CW-eups](spec.md#requirement-cw-eups-a-direction-to-validation-names-the-validations-target) — a direction to validation nests its target; a pass leads there, a failure goes to the owner.
- [CW-q3dm](spec.md#requirement-cw-q3dm-waivers-are-recommended-and-the-owners-to-take) — a step recommends a waiver only on a written criterion, naming it and its evidence; only the owner waives.

## 2. Implementation and validation

### Sections and sessions

- [CW-5r7l](spec.md#requirement-cw-5r7l-a-section-is-a-verifiable-slice) — each section is a coherent slice ending at a verification point; `tasks.md` prescribes no session distribution.
- [CW-5h8e](spec.md#requirement-cw-5h8e-evidence-only-a-push-produces-is-owed-by-validation) — evidence only a push produces is owed by validation and never gates a task's completion.
- [CW-0ia3](spec.md#requirement-cw-0ia3-an-implementation-session-starts-fresh-unless-the-owner-continues-one) — implementation starts in a fresh session unless the owner names an earlier one to continue.
- [CW-al17](spec.md#requirement-cw-al17-the-implementation-cadence-is-settled-in-design-and-mapped-by-the-plan) — design settles the cadence of sessions and rounds; planning orders sections by it and reports the mapping.
- [CW-v6nj](spec.md#requirement-cw-v6nj-each-round-is-recorded-as-it-starts) — each round is recorded as it starts from the plan's mapping; an unmapped round asks the owner.
- [CW-tc82](spec.md#requirement-cw-tc82-each-section-is-checked-handed-off-and-committed-alone) — each section is handed off, compliance-checked by a fresh-context agent, and committed on its own.
- [CW-1u53](spec.md#requirement-cw-1u53-a-failed-premise-returns-the-change-with-its-work-in-progress) — a plan invalidated by discovered code returns the change, its work committed and pushed as in progress.

### Reading a round

- [CW-aoby](spec.md#requirement-cw-aoby-a-round-is-read-as-one-set-of-changes) — the owner reads a round as one diff from the previous round's commit, no commit rewritten.
- [CW-4svs](spec.md#requirement-cw-4svs-a-clones-round-is-read-in-the-workspace-beside-its-validation-and-review) — a clone's round is read in the workspace beside validation and review; triage waits for the owner's answer.
- [CW-9mrq](spec.md#requirement-cw-9mrq-a-repeat-pass-is-read-as-its-round-was) — a triage fix's repeat pass is read the same way, and its triage waits for a fresh answer.
- [CW-78ul](spec.md#requirement-cw-78ul-a-round-view-in-the-workspace-holds-every-other-step) — while a workspace view moves the branch, no other step starts; no view moves an active run's checkout.
- [CW-n44s](spec.md#requirement-cw-n44s-ending-the-reading-carries-the-owners-commits-onto-the-round) — ending the reading carries the owner's commits onto the round exactly, leaving uncommitted edits uncommitted.
- [CW-uq5q](spec.md#requirement-cw-uq5q-an-owners-commit-is-carried-only-when-it-keeps-the-rounds-changes) — a commit touching a round path is carried only when it keeps the round's changes; merges refuse.
- [CW-gd24](spec.md#requirement-cw-gd24-added-deleted-and-binary-paths-are-carried-only-as-the-round-left-them) — added, deleted, binary, symlink, or mode-changed paths carry only as the round left them.
- [CW-rgws](spec.md#requirement-cw-rgws-a-view-is-not-moved-over-the-owners-work) — a view is not moved to a new head over the owner's commits or uncommitted edits.
- [CW-te38](spec.md#requirement-cw-te38-the-owners-commits-reach-the-clone-only-by-a-fast-forward) — the owner's reading commits reach the clone only through a fast-forward triage makes.

### Validation

- [CW-a7dw](spec.md#requirement-cw-a7dw-validation-describes-one-commit-and-modifies-nothing) — validation describes one commit, fails on a dirty worktree or moved `HEAD`, and regenerates nothing.
- [CW-af15](spec.md#requirement-cw-af15-validation-repairs-nothing) — validation fixes nothing; a repairable condition such as a stale lock fails it back to implementation.
- [CW-zkhs](spec.md#requirement-cw-zkhs-validations-parts-are-the-repositorys) — validation runs the parts the repository's configuration declares but those the owner waived, each part's evidence from the commit under validation alone.
- [CW-g4oz](spec.md#requirement-cw-g4oz-validation-runs-the-parts-the-configuration-declares) — validation learns its plan from `config parts`: preflight first, every started part, then the `run` parts, each in declared order; owed parts once per owed workflow.
- [CW-x9bt](spec.md#requirement-cw-x9bt-the-engine-keeps-a-started-parts-marker-and-closes-each-part) — the engine keeps a `start`'s last line as its collect's `{after}`, keyed by commit, part, and owed workflow, and closes each part with its own line.
- [CW-e7lm](spec.md#requirement-cw-e7lm-validations-result-is-passed-failed-or-inconclusive) — results are `passed`, `failed` (commit-caused or unknown), or `inconclusive` (environmental missing evidence); a part the owner waived is `waived`, counted in no result, a standing waiver read from the log and lapsing at a merge.
- [CW-a1nz](spec.md#requirement-cw-a1nz-an-environmental-failure-goes-to-the-owner-with-its-remedy) — an environmental failure goes to the owner with its remedy, rerun on their word, every attempt kept.
- [CW-av28](spec.md#requirement-cw-av28-a-validation-record-names-the-scenarios-that-exercise-the-change) — the validation record names the end-to-end scenarios exercising the change, with each one's basis.

### The triage of a round

- [CW-qtxb](spec.md#requirement-cw-qtxb-a-rounds-review-validation-and-owners-notes-are-triaged-together) — a round's review, validation, and owner's notes are triaged together, outside the implementing session.
- [CW-514y](spec.md#requirement-cw-514y-records-of-different-commits-form-a-round-only-on-the-owners-waiver) — a review and validation of different commits form one round only on the owner's logged waiver.
- [CW-xg4v](spec.md#requirement-cw-xg4v-a-validation-failure-is-a-finding-and-missing-evidence-is-not) — each commit-caused or unknown validation failure is a finding; an `inconclusive` part is missing evidence.
- [CW-rb5n](spec.md#requirement-cw-rb5n-the-owners-notes-are-triaged-as-a-review) — the owner's notes are saved verbatim and triaged like a review, each point given a position.
- [CW-j1ab](spec.md#requirement-cw-j1ab-a-triages-edits-are-checked-committed-pushed-and-validated) — accepted fixes pass the hooks their commit runs and are revalidated, unless only inert paths change after pre-closeout; every triage commits and pushes its tracked edits.
- [CW-gqav](spec.md#requirement-cw-gqav-a-pre-closeout-review-needs-a-passed-validation-of-head) — a pre-closeout review and its advance need a passed validation of `HEAD` or a records-only ancestor; after its triage, an inert-paths-only one.

## 3. Reviews and triage

### Review records

- [CW-p2b2](spec.md#requirement-cw-p2b2-each-review-is-one-numbered-record) — each review is one never-overwritten numbered file in `reviews/`, the only record of its findings.
- [CW-2nb2](spec.md#requirement-cw-2nb2-a-later-review-reads-earlier-findings-from-the-records) — later reviews read earlier findings and dispositions from the records, even when continuing a reviewer session.
- [CW-ovuj](spec.md#requirement-cw-ovuj-review-records-are-untracked-and-their-durable-content-is-promoted) — `reviews/` is untracked and uncited by permanent documents; durable content is promoted at closeout.
- [CW-5e24](spec.md#requirement-cw-5e24-a-reviews-transcript-is-kept-and-never-read-as-a-record) — a review's raw transcript may be kept, untracked, but no review or triage step reads it.
- [CW-r9d2](spec.md#requirement-cw-r9d2-a-reviewers-output-is-published-only-as-a-review) — reviewer output is published only once format-checked; a run publishing nothing is recorded as stopped.
- [CW-a2lf](spec.md#requirement-cw-a2lf-each-finding-states-its-alternatives) — each finding states its alternatives with their trade-offs, or none and why; a finding without them is not published.

### Lens, basis, and severity

- [CW-5sc1](spec.md#requirement-cw-5sc1-a-findings-lens-and-basis) — a finding carries one of seven lenses and a basis: specification, guidance, evidence, or judgement.
- [CW-7d5f](spec.md#requirement-cw-7d5f-a-findings-severity) — severity is `blocking` (resolved before the next phase), `should` (resolved unless deferred), or `minor` (declinable).

### Triage

- [CW-j1nv](spec.md#requirement-cw-j1nv-triage-states-a-position-on-every-finding-and-presents-every-one-not-accepted-by-default) — the agent states a reasoned position and proposed action on every finding, and presents every one not accepted by default.
- [CW-neua](spec.md#requirement-cw-neua-a-finding-not-accepted-by-default-is-disposed-of-only-by-the-owner) — a finding is disposed of only by the owner's stated disposition, before any is acted on, unless accepted by default.
- [CW-d5ac](spec.md#requirement-cw-d5ac-a-review-finding-the-default-rule-admits-is-accepted-by-default) — an uncontested, non-blocking review finding with one agreed edit or fix and no alternative is accepted by default, its classification recorded.
- [CW-t9bx](spec.md#requirement-cw-t9bx-default-acceptances-are-reported-in-one-table) — default acceptances are reported in one table, with the triage's last question or its final report.
- [CW-r8vz](spec.md#requirement-cw-r8vz-the-owner-revisits-a-default-acceptance) — on the owner's direction, the latest finished triage resumes to amend a default acceptance or its advancing exit.

### Guidance reviews

- [CW-g6ua](spec.md#requirement-cw-g6ua-guidance-reviews) — the owner's interactive guidance review reports the period's figures, lists candidate edits, and records its period.

### The intervention ledger

- [CW-zidp](spec.md#requirement-cw-zidp-a-course-correction-is-logged-to-the-ledger) — each owner course correction is appended to `interventions.jsonl` with its finding's classification and summary.
- [CW-xe8m](spec.md#requirement-cw-xe8m-an-accepted-proposal-is-not-logged-to-the-ledger) — a disposition accepting the agent's proposal unchanged is not logged; the triage record holds it.
- [CW-w22z](spec.md#requirement-cw-w22z-a-design-reversal-is-logged-to-the-ledger) — an owner changing a design recommendation is logged as a `design` entry; an accepted one is not.
- [CW-1jxh](spec.md#requirement-cw-1jxh-the-ledger-is-tracked-and-archived-with-the-change) — the ledger is tracked, stays in the change directory, and is archived with the change.
- [CW-v1rk](spec.md#requirement-cw-v1rk-a-revisited-default-acceptance-is-logged-and-marked) — a corrected default acceptance is logged, its disposition beginning `revisits default acceptance:`.
- [CW-n6wy](spec.md#requirement-cw-n6wy-a-recommended-waiver-is-logged-with-its-criterion) — a recommended waiver is logged with its criterion; one the owner declines is a correction.

## 4. The engine

### The command

- [CW-r3ka](spec.md#requirement-cw-r3ka-the-engine-is-reached-through-one-command) — every engine operation is a `scripts/change-workflow` subcommand acting on the enclosing Git repository; never imported.
- [CW-h8vm](spec.md#requirement-cw-h8vm-make-targets-are-a-convenience-outside-the-surface) — the shipped make fragment is a convenience whose targets and variables carry no compatibility promise.

### Hooks

- [CW-b2xr](spec.md#requirement-cw-b2xr-the-workflows-hooks-are-named-by-when-they-run) — a repository's commands are hooks named by when they run: `after-functional-change`, `pre-commit`, `pre-commit-functional`, `pre-archive`, `pre-push`, `post-clone`.
- [CW-k9vd](spec.md#requirement-cw-k9vd-a-hook-runs-every-command-it-lists) — a hook holds a command or a list; every command runs and is recorded, the hook failing if any failed.
- [CW-u4pc](spec.md#requirement-cw-u4pc-the-engine-holds-which-steps-may-run-each-hook) — the engine's hook table says which step may run each hook; the unattended marker names the step, and `run` refuses others.
- [CW-y6mj](spec.md#requirement-cw-y6mj-a-pre-commit-hook-changes-nothing) — `pre-commit`, its defaults included, reports and changes nothing, so a review may run it.
- [CW-e1sg](spec.md#requirement-cw-e1sg-a-commits-hooks-follow-from-the-paths-it-changes) — a commit touching a path outside the inert paths runs the functional hooks before `pre-commit`; a cleanup's tracked file is committed alone.
- [CW-c8lw](spec.md#requirement-cw-c8lw-a-hooks-default-checks-run-unless-disabled-by-name) — `pre-commit`'s default checks run before its declared commands unless `defaults.disable` names one with a reason.
- [CW-v2dq](spec.md#requirement-cw-v2dq-a-command-receives-its-values-through-placeholders) — a command takes the workflow's values as shell-quoted placeholders, each available only where it is defined; the machine's through the environment.

### The orchestrating session

- [CW-ms3j](spec.md#requirement-cw-ms3j-one-orchestrating-session-advances-one-change-from-its-files) — an orchestrating session advances only its own change, holding no state beyond its files and log.
- [CW-5jlj](spec.md#requirement-cw-5jlj-the-orchestrating-session-runs-what-the-computation-names) — the orchestrating session runs the step the computation names, without the owner where one is named.
- [CW-yvo1](spec.md#requirement-cw-yvo1-the-orchestrating-session-relays-and-takes-no-position) — it relays every step's questions and messages as written, and takes no position on findings or design.
- [CW-mkwj](spec.md#requirement-cw-mkwj-the-orchestrating-session-reads-only-what-routing-needs) — it reads only what routing and recovery need: the computation's inputs, the log, and denials.
- [CW-op72](spec.md#requirement-cw-op72-what-the-orchestrating-session-may-commit) — it may create the clone and commit workflow changes, owner-requested work, and merges; never feature work.
- [CW-bsmk](spec.md#requirement-cw-bsmk-when-the-orchestrating-session-commits-and-merges-nothing) — it commits nothing while a step runs, merges nothing during a round, and leaves leftover work to the owner.
- [CW-tax4](spec.md#requirement-cw-tax4-the-orchestrating-session-resolves-a-merges-conflicts-but-codes) — it resolves merge conflicts in workflow documents itself; code conflicts go to the owner or implementation.
- [CW-6scj](spec.md#requirement-cw-6scj-the-orchestrating-session-may-report-the-toolings-misbehaviour) — it may report the workflow tooling's observed misbehaviour as its own numbered record for the next triage.
- [CW-6fi2](spec.md#requirement-cw-6fi2-a-waived-design-review-after-a-return-is-a-direction-to-planning) — an owner's waiver of another design review after a return is recorded as a direction to planning.
- [CW-k2rv](spec.md#requirement-cw-k2rv-the-owner-stops-a-running-step-through-the-command) — on the owner's word, the command stops the change's running step, naming it when two run; the interrupt resolves no run.
- [CW-h7lq](spec.md#requirement-cw-h7lq-a-stop-signals-only-a-run-that-still-holds-its-record) — a stop checks the run still holds its record at selection and just before the signal, else refuses.
- [CW-w4ne](spec.md#requirement-cw-w4ne-a-stopped-run-is-recovered-as-any-stop-and-a-late-stop-ends-nothing) — a stopped run is recovered as any stop and commits nothing; a stop after the agent exits ends nothing.

### Step runs and outcomes

- [CW-js86](spec.md#requirement-cw-js86-an-unattended-run-ends-with-a-structured-outcome) — an unattended run ends with a schema outcome: finished, question, proposed return, blocked, or stopped.
- [CW-5ldi](spec.md#requirement-cw-5ldi-an-exit-or-a-return-is-named-as-a-target) — exits and returns are targets naming a graph node with any kind or sections; unknown kinds are refused.
- [CW-4vma](spec.md#requirement-cw-4vma-a-triage-outcome-names-the-records-it-triaged) — a triage outcome names its distinct triaged records, at least one review; otherwise it is recorded stopped.
- [CW-1a4d](spec.md#requirement-cw-1a4d-the-wrapper-logs-every-outcome-of-a-run) — the wrapper logs every outcome with session and commit, recording stopped for a run that gives none.
- [CW-4c3e](spec.md#requirement-cw-4c3e-the-files-prevail-over-the-log-on-a-changes-state) — a change's files hold and prevail on its state; the log holds exits and the owner's decisions.
- [CW-k5mk](spec.md#requirement-cw-k5mk-a-runs-denials-come-from-its-own-record) — every unattended outcome carries the run's own recorded denials across all turns, with the harness's reasons.
- [CW-xgq3](spec.md#requirement-cw-xgq3-a-question-resumes-its-session-and-a-return-waits-for-the-owner) — a question resumes its session; a proposed return changes nothing until the owner's logged confirmation.
- [CW-ht4h](spec.md#requirement-cw-ht4h-a-decision-names-the-run-it-resolves-and-a-direction-is-the-owners) — a decision names exactly the run it resolves or reads; a decision directing a step is the owner's.
- [CW-q5fy](spec.md#requirement-cw-q5fy-each-runs-log-line-records-what-it-invoked) — a run's log line records as `invoked` each hook, part, and command run through `run` or the guarded push, with its exit status and timing.

### Interactive runs

- [CW-mzyz](spec.md#requirement-cw-mzyz-an-interactive-run-records-its-outcome-through-the-command) — an interactive run is unrestricted but records its outcome through `record`; an interactive review records nothing.
- [CW-gnqh](spec.md#requirement-cw-gnqh-the-record-command-checks-and-attributes-an-outcome) — `record` schema-checks an outcome and attributes it to session, commit, and interactive; refused without a session id.

### The log and its format

- [CW-x7jd](spec.md#requirement-cw-x7jd-a-changes-record-set-carries-one-format-version) — the log's `format` versions the whole record set; older is read as older, newer is refused.
- [CW-k6qa](spec.md#requirement-cw-k6qa-a-step-started-through-the-command-opens-the-log) — `start` creates the log and marks its format before any step runs; nothing routes on that line.
- [CW-lyr4](spec.md#requirement-cw-lyr4-every-line-appended-to-the-log-carries-its-format) — every appended line carries the format, and appending to a log with a newer line is refused.
- [CW-qj77](spec.md#requirement-cw-qj77-records-of-an-older-format-are-brought-to-the-owner-with-the-conversion) — older-format records, or records without a log, go to the owner with `convert`, never read as current.

### The conversion

- [CW-h12x](spec.md#requirement-cw-h12x-the-conversion-refuses-a-newer-log) — the conversion refuses a newer-format log before anything else, rewriting nothing and never converting backwards.
- [CW-42me](spec.md#requirement-cw-42me-the-conversion-refuses-a-change-with-a-triage-in-progress) — the conversion refuses, naming the review, a change whose triage is in progress by the older reading.
- [CW-o1ca](spec.md#requirement-cw-o1ca-the-conversion-rewrites-the-log-in-place-and-names-every-triaged-review) — lines are rewritten in place keeping seq; one conversion line names every triaged review, owner-confirmed where needed.
- [CW-zniv](spec.md#requirement-cw-zniv-the-conversion-appends-the-owners-direction-to-the-node-the-change-stands-at) — the conversion appends the owner's direction to the change's current node, or writes nothing without one.
- [CW-ajcm](spec.md#requirement-cw-ajcm-what-the-conversion-proposes) — it proposes the node from the latest routing decision after the latest triage, with any guard's remedy.
- [CW-95xp](spec.md#requirement-cw-95xp-the-conversion-replaces-the-log-in-one-step) — it holds the log's lock throughout and replaces the log in one step, so interruption leaves the old log.
- [CW-v8mq](spec.md#requirement-cw-v8mq-a-reader-of-the-log-reopens-a-log-replaced-under-its-lock) — log readers and appenders reopen a log replaced under its lock, so no appended line is lost.

### The next-step computation

- [CW-4rqr](spec.md#requirement-cw-4rqr-the-next-step-is-computed-from-the-files) — the engine computes the next step from the graph over the change's files and log, also as `next`.
- [CW-tel3](spec.md#requirement-cw-tel3-what-the-computation-cannot-classify-is-resolved-or-brought-to-the-owner) — an unclassifiable state is resolved by the orchestrating session when it is routing only, else brought to the owner.
- [CW-m70n](spec.md#requirement-cw-m70n-the-computation-routes-on-exits-and-directions-never-on-the-phase) — routing follows the last outcome's exit and the owner's latest unrun direction, never an exit inferred from phase.
- [CW-l866](spec.md#requirement-cw-l866-a-triages-exit-is-in-its-outcome-and-its-files-prose-is-not-routed-on) — a triage's exit lives in its outcome; `## Next` is unrouted prose; a triage file without one is in progress.
- [CW-0wna](spec.md#requirement-cw-0wna-an-undeclared-exit-or-an-unmet-entry-guard-goes-to-the-owner) — an undeclared exit, a validation's wrong exit, or an unmet entry guard goes to the owner.
- [CW-8tdv](spec.md#requirement-cw-8tdv-an-unmet-exit-guard-names-the-step-that-satisfies-it) — an unmet exit guard names its satisfying step carrying the exit, or goes to the owner when none can.
- [CW-nkys](spec.md#requirement-cw-nkys-validation-is-always-named-with-a-target) — validation is always named with a target, whose guards are checked again on validation's exit.
- [CW-izj1](spec.md#requirement-cw-izj1-a-confirmed-return-starts-its-work-afresh) — a confirmed return releases the returned review, so its work is a fresh round; declined returns go to the owner.
- [CW-tnp6](spec.md#requirement-cw-tnp6-a-round-and-the-merge-advance-only-on-a-passed-validation) — a round and the merge advance only on a passed validation of their commit; a failed merge validation repeats the merge.

### The graph

- [CW-ak1z](spec.md#requirement-cw-ak1z-the-workflow-graph-is-one-table-in-code) — the graph is one table in code of nodes, exits, joins, and guards, changed only by an OpenSpec change.
- [CW-sd34](spec.md#requirement-cw-sd34-exit-guards-bind-steps-and-entry-guards-bind-every-entry) — exit guards bind step exits, not directions; entry guards bind every entry, waivable ones yielding to directions.
- [CW-xo82](spec.md#requirement-cw-xo82-the-archive-guards-both-sides-of-closeout) — the archive's presence or absence guards the steps on each side of closeout; closeout is entered only from the merge.
- [CW-iaeh](spec.md#requirement-cw-iaeh-a-triage-needs-a-record-to-triage-and-a-validation-a-target) — a triage needs an untriaged record of its kind; validation needs a target, checked on its exit.
- [CW-9tzd](spec.md#requirement-cw-9tzd-archive-cleanup-ends-at-the-terminal-node) — archive cleanup exits to the terminal node `done`, which has no exits or step and no direction reaches.
- [CW-66kx](spec.md#requirement-cw-66kx-the-graph-diagram-is-held-to-the-table) — `check graph` holds the diagram's source and embedded copy to the table's structure, whatever its layout.

### Permissions

- [CW-qu42](spec.md#requirement-cw-qu42-an-unattended-run-is-limited-to-its-steps-table) — an unattended run uses only its table's tools, pushes only by the guarded push, never resets or rebases.
- [CW-pehu](spec.md#requirement-cw-pehu-writing-steps-commit-and-push-their-work-and-validation-and-review-commit-nothing) — steps that write tracked work commit and push it through the guarded push; validation and review commit nothing.
- [CW-ajo9](spec.md#requirement-cw-ajo9-a-returning-run-commits-its-work-in-progress-and-a-stopped-run-commits-nothing) — a returning run commits and pushes its work in progress; a stopped run leaves its work uncommitted.
- [CW-4yhk](spec.md#requirement-cw-4yhk-a-denied-run-stops-or-goes-on-only-by-allowed-calls) — a run blocked by a denial stops naming it; going on uses only calls its rules allow.
- [CW-2lvd](spec.md#requirement-cw-2lvd-a-deny-rules-refusal-stands-except-a-write-steering-rules) — a deny rule's refusal is not worked around, except write-steering rules, whose write may use Edit or Write.
- [CW-2h9t](spec.md#requirement-cw-2h9t-a-call-no-rule-allows-may-be-done-by-an-allowed-tool) — a call denied for want of an allow rule may be done by an allowed tool, named in the message.
- [CW-svng](spec.md#requirement-cw-svng-the-orchestrating-session-reads-and-classifies-each-denial) — the orchestrating session reads denials from the run's record and classifies each as a table gap or forbidden.
- [CW-5rmh](spec.md#requirement-cw-5rmh-the-orchestrating-session-checks-a-deny-rules-denial-for-a-workaround) — after a deny rule's denial it checks later calls for a workaround; an Edit-made steered write is a gap.
- [CW-vdqj](spec.md#requirement-cw-vdqj-the-orchestrating-session-proposes-a-rule-for-each-gap-and-records-its-reading) — for each gap it proposes the narrowest rule, as grant or tracked change, and logs its reading.
- [CW-jqi7](spec.md#requirement-cw-jqi7-a-waiting-outcome-is-settled-after-its-denials-are-read) — a waiting outcome is answered only after its denials are read, and the reading does not settle it.
- [CW-drf6](spec.md#requirement-cw-drf6-a-steps-permissions-change-only-on-the-owners-word) — permissions change only by the owner, as a tracked change or a one-run grant; deny rules are never granted.
- [CW-tl5v](spec.md#requirement-cw-tl5v-a-grant-holds-for-one-run) — a grant passes on the run's command line and is logged as `granted`, never added to the table.
- [CW-56zq](spec.md#requirement-cw-56zq-a-file-rule-names-a-path-from-the-checkouts-root) — a file-tool rule's relative path is from the root of the checkout the run started in.

### The guarded push

- [CW-59c7](spec.md#requirement-cw-59c7-the-guarded-push-of-a-change-branch) — an agent may push the change's own branch, none of the configured protected branches, attached and clean, sending exactly `HEAD` to its upstream's remote or one given, never forced.
- [CW-p7kq](spec.md#requirement-cw-p7kq-the-guarded-push-runs-the-repositorys-pre-push-hook) — the guarded push runs the configuration's `pre-push` as Git runs a pre-push hook; failure refuses the push, and none declared skips it.

### Models

- [CW-ebmo](spec.md#requirement-cw-ebmo-each-step-runs-on-its-ordered-models) — the configuration lists each step's ordered models; the wrapper runs the first available, falling back only on unavailability, and logs it.
- [CW-zq4h](spec.md#requirement-cw-zq4h-the-step-models-policy) — a step's models name no two of one vendor, and another harness only where it can enforce the step's limits; the engine refuses violations.
- [CW-1dld](spec.md#requirement-cw-1dld-a-run-with-no-available-model-stops-and-a-waiting-run-resumes-on-its-own) — a run with no available model stops; network errors retry without fallback; waiting runs resume on their model.
- [CW-clhl](spec.md#requirement-cw-clhl-a-review-names-a-reviewer-other-than-its-rows-first) — a review on a fallback model names its reviewer; a reviewer session continues only on the same harness.
- [CW-d1sm](spec.md#requirement-cw-d1sm-the-owner-may-override-one-reviews-model) — the owner may name any model or effort for one hand-run review, marked as an override, without fallback.
- [CW-w2ld](spec.md#requirement-cw-w2ld-the-orchestrating-sessions-model-is-the-configurations) — the orchestrating session starts on the model and effort the configuration's `models.orchestrator` names.

### Cost

- [CW-yzer](spec.md#requirement-cw-yzer-each-unattended-run-records-its-own-cost) — each unattended run logs its own dollars, turns, duration, and tokens, marking dollars partial when inseparable.
- [CW-u7da](spec.md#requirement-cw-u7da-a-resumed-run-records-its-gap-and-cost-is-reported-by-step-and-round) — a resumed run logs its idle gap and cache hit; cost is reportable by step and round with misses.

### Clones and history

- [CW-yib2](spec.md#requirement-cw-yib2-a-change-may-be-worked-in-a-clone-of-its-own) — a change may be worked in its own clone or the workspace; clones never disturb each other.
- [CW-4x66](spec.md#requirement-cw-4x66-the-computation-names-a-changes-clone-or-brings-workspace-records-to-the-owner) — the computation names a missing clone's creation, but brings a change with workspace records to the owner.
- [CW-8jyb](spec.md#requirement-cw-8jyb-creating-a-clone-is-safe-to-repeat) — clone creation is repeatable, finishing an incomplete clone and refusing a foreign or dirty directory, deleting nothing; its remotes come from Git's record in the workspace.
- [CW-s3ju](spec.md#requirement-cw-s3ju-the-branch-a-change-lands-on-is-recorded-where-its-orchestration-began) — the clone records the branch the change lands on, the workspace's or `--from`, printed as `find --json`'s `base`; an argument overrides it.
- [CW-8npg](spec.md#requirement-cw-8npg-a-clones-bootstrap-gates-implementation-and-validation) — implementation and validation wait on the clone's `post-clone` bootstrap succeeding, its state recording its command; a failure goes to the owner.
- [CW-hak6](spec.md#requirement-cw-hak6-archive-cleanup-copies-a-changes-history-into-the-workspace) — archive cleanup last copies the change's records and evidence into the workspace, repeated after its outcome.
- [CW-rf50](spec.md#requirement-cw-rf50-copying-a-changes-history-overwrites-nothing) — the history copy is repeatable, extends prefix files, and refuses to overwrite a differing file.
- [CW-c3he](spec.md#requirement-cw-c3he-a-step-looks-for-records-in-its-checkout-then-in-the-workspace) — a step looks for other changes' records in its own checkout, then in the owner's workspace.
- [CW-xx5f](spec.md#requirement-cw-xx5f-a-clone-is-removed-only-once-its-work-is-safe) — a clone is removed only on the owner's command, once its records are copied and its work is merged into its landing branch on its upstream's remote.
- [CW-ikmm](spec.md#requirement-cw-ikmm-archive-cleanup-removes-a-changes-validation-resources) — archive cleanup runs every part's declared `cleanup` through `run cleanup`, each succeeding when it finds nothing.

### Skills from one source

- [CW-d8de](spec.md#requirement-cw-d8de-each-skill-has-one-source-for-every-harness) — each skill has one source every harness loads; no per-harness copies, and every harness entry resolves.

## 5. The public surface

### The engine's interfaces

- [CW-5qne](spec.md#requirement-cw-5qne-the-engines-interfaces-are-tiered) — interfaces are public, provisional, or internal; subcommands, outputs, and skill names default public; report prose promises nothing.
- [CW-m7fk](spec.md#requirement-cw-m7fk-the-commands-exit-statuses-fall-in-three-categories) — every subcommand exits 0 on success, 1 on refusal or failed check, 2 on usage error.

### Compatibility

- [CW-c2tw](spec.md#requirement-cw-c2tw-compatibility-is-judged-by-semantic-versioning) — public-interface changes are versioned semantically, and a workflow proposal names each public interface it changes.
- [CW-9fbu](spec.md#requirement-cw-9fbu-the-graphs-vocabulary-is-closed) — node names, review kinds, and target shape are closed; unknown ones are reported by name, never routed on.

### A repository's configuration

- [CW-f3qk](spec.md#requirement-cw-f3qk-one-configuration-file-states-what-the-workflow-assumes) — one file, `.agents/workflow.toml`, states the commands, documents, and values the workflow assumes; nothing Git or the invocation supplies.
- [CW-w8ne](spec.md#requirement-cw-w8ne-the-configuration-is-checked-whenever-it-is-read) — every reader checks the whole file, refusing an unknown key, a wrong type, or an unavailable placeholder by name.
- [CW-t5hz](spec.md#requirement-cw-t5hz-a-missing-required-field-refuses-only-the-steps-that-need-it) — a missing required field refuses only the steps needing it, before launch; an explicit empty value is declared.
- [CW-n7ra](spec.md#requirement-cw-n7ra-the-repositorys-inert-paths) — the repository's inert paths name what validation would prove nothing about; the engine holds none of its own.
- [CW-l7hn](spec.md#requirement-cw-l7hn-a-steps-documents-to-load-come-from-the-configuration) — a step loads `load.common` and `load.<step>` through `config load`; the post-compaction hook re-reads `load.common`.
- [CW-i2we](spec.md#requirement-cw-i2we-the-openspec-cli-runs-through-the-configured-command) — the OpenSpec validation and archive run through `openspec.command`, or `openspec` on the path.
- [CW-o6kc](spec.md#requirement-cw-o6kc-the-configurations-resolution-is-listed) — `config` lists how every field resolved, and `config parts` validation's plan, each with `--json`.
- [CW-z5me](spec.md#requirement-cw-z5me-no-step-edits-the-configuration) — no unattended step edits the configuration; it changes only as a tracked edit by the owner, or by the orchestrating session on the owner's word.

### What an adopting repository provides

- [CW-m4ps](spec.md#requirement-cw-m4ps-an-adopting-repository-provides-the-workflows-roles) — the workflow describes each configuration field and each role outside it; a test fails on a named target or path both the statement and the configuration omit.

## Retired ids

None.
