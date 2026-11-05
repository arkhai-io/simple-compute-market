# Trace: `change-workflow` rewritten against its outline

This maps every normative clause (MUST, MUST NOT, SHALL, SHOULD, MAY) and every
scenario of `openspec/specs/change-workflow/spec.md` as it stood before this change
to the requirement of the rewritten specification that holds it, or to "dropped"
with the reason. It follows design D10: each existing requirement is REMOVED, and
its rules are held by the ADDED requirements of this change's `change-workflow`
delta, or, for this repository's own part, by `market-change-workflow`'s. Each
section names the existing requirement and the destination D10's table gives it;
every placement below agrees with that table. A clause is quoted short; the
existing specification holds its full text.

A scenario held by an id is a scenario of that requirement, carried with its text,
or reworded only where the rewrite moved a value or a target to the repository
(`dev`, a named CI workflow, a forbidden model, `make lock`), named the command for
a make target, or named the capability's documentation for its companion; each
reworded scenario's row says so. Where a scenario's outcome was the only statement
of a rule, the rewrite also states the rule in its requirement's body (CW-1iaz's
naming of the archived directory, CW-yib2's isolation of two clones, CW-zq4h's
refusal of a table, CW-zniv's writing nothing); the scenario's row names that
requirement. A row naming an MCW id is this repository's part, held by this change's
`market-change-workflow` delta.

No clause or scenario is dropped.

## Phases and owner touchpoints

Destination: split. Moves: the merge's default branch, `dev`. Seam: the merge brings
in the branch the change lands on, the one it was branched from unless the owner
names another, or the repository's default.

| Clause or scenario | Held by |
|---|---|
| A change MUST move through design, planning, implementation, and closeout, in order, except where the owner directs a step | CW-ab9h |
| No direction crosses the archive | CW-ab9h |
| The design phase MUST end with a design review, the implementation phase with a pre-closeout review, the closeout phase with a closeout review | CW-nfdb |
| A phase ending in a review MUST NOT be treated as finished until its triage names a step of the next phase as its exit; for implementation, the merge | CW-nfdb |
| Once the pre-closeout triage advances the change, a merge step MUST bring in the branch the change lands on, the one it was branched from unless the owner names another | CW-hdxi |
| That branch is `dev` unless the owner names another | CW-hdxi (the repository's default); `dev`: MCW-ca51 |
| The merge MUST resolve its conflicts and reconcile the change's code with what that branch changed, even without a conflict, before closeout starts | CW-hdxi |
| Closeout MUST NOT start until a validation of the merged `HEAD` passed, unless the owner waives it | CW-a6ow |
| The merge MUST judge whether its resolutions merit another pre-closeout review and whether its validation may be waived, and MUST take either only on the owner's confirmation | CW-a6ow |
| Without either, the merge MUST advance to closeout without waiting for the owner | CW-a6ow |
| The owner MUST be consulted for the design discussion's questions, their notes on each round, every finding's disposition, and whether the dispositions merit another round | CW-9pbk |
| Triage MUST ask about another round once every finding is disposed of and before any fix | CW-9pbk |
| A triage with no finding and no point of the owner's notes MAY record that the change advances without the owner | CW-3tvs |
| Every other transition MUST proceed without waiting for the owner, unless a step raises a question only the owner can answer | CW-9pbk |
| Closeout MUST archive the change, merging its deltas, before its closeout review | CW-ksnu |
| The closeout review MUST read the archived change and the permanent documents as archived | CW-ksnu |
| The archive is cleaned up, and the change `archived`, only once the closeout triage advances it and, when `HEAD` differs outside `openspec/` and `docs/`, a validation passed, unless the owner waives it, recorded in the ledger | CW-trdu |
| Closeout MUST change documentation only; a part needing a code change MUST return the change to implementation | CW-pkug |
| The steps after the archive MUST find an archived change by its name | CW-1iaz |
| Design, planning, and implementation MUST refuse an archived change | CW-1iaz |
| Planning MUST NOT begin before the design review's triage records that the change advances | CW-z83w |
| A design decision made after that MUST return the change to design | CW-z83w |
| The owner MAY waive another design review for it; the waiver MUST be recorded in the ledger | CW-z83w |
| Every review MUST stop for the owner's disposition of each finding before any finding is acted on | CW-neua |
| An agent MUST NOT treat its own or another agent's agreement as a disposition | CW-neua |
| Scenario: A reviewer and the implementing agent agree | CW-neua |
| Scenario: Planning exposes an unanswered design question | CW-z83w |
| Scenario: The closeout review reads the synchronized specifications | CW-ksnu |
| Scenario: An archived change is given to implementation | CW-1iaz |
| Scenario: A closeout review finds a code defect | CW-trdu |
| Scenario: The owner waives archive cleanup's validation | CW-trdu |
| Scenario: The owner waives archive cleanup's validation under orchestration | CW-trdu |
| Scenario: Closeout finds a comment that needs rewriting | CW-pkug |
| Scenario: A design review accepts a blocking finding | CW-7d5f |
| Scenario: Another round is decided before the fixes | CW-9pbk |

## Index transitions are written by the step that makes them

Destination: general. Seam: the index's path is a role (D13); the requirements say
"the change index".

| Clause or scenario | Held by |
|---|---|
| Each change of phase or state MUST be written to the change's index row by the skill that makes it, in the same step, at each listed transition | CW-uj2q |
| An implementation review after a section MUST NOT change the status | CW-uj2q |
| Each step that edits the index MUST check it afterwards: cell count, link, status, dependencies, one row per active change | CW-jyff |
| An archived change MAY have no row | CW-jyff |
| Scenario: An edit breaks a row | CW-jyff |
| Scenario: An archived change's row is pruned | CW-jyff |
| Scenario: A closeout review's triage advances the change | CW-uj2q |
| Scenario: A pre-closeout review's triage advances the change | CW-uj2q |

## Review records

Destination: general.

| Clause or scenario | Held by |
|---|---|
| Each review MUST be one Markdown file in the change's `reviews/`, numbered in the order reviews are produced | CW-p2b2 |
| That file MUST be the only record of its findings | CW-p2b2 |
| The records' order MUST be establishable, by number or by file times | CW-p2b2 |
| A record MUST NOT be overwritten | CW-p2b2 |
| Each finding MUST state its lens, basis, severity, and evidence | CW-p2b2 |
| A later review MUST obtain earlier findings and dispositions from the files, not from session memory | CW-2nb2 |
| A review of the same kind MAY continue the reviewer session that wrote the earlier one | CW-2nb2 |
| It MUST still read the triage and dispositions from the records | CW-2nb2 |
| `reviews/` MUST NOT be tracked by version control | CW-ovuj |
| `reviews/` MUST NOT be cited by permanent documentation | CW-ovuj |
| Anything durable in it MUST reach permanent documentation through promotion at closeout | CW-ovuj |
| A review's raw session MAY be kept as a transcript under `reviews/transcripts/`, untracked | CW-5e24 |
| No review or triage step SHALL read a transcript | CW-5e24 |
| A reviewer's output SHALL be published as a record only after it is checked to have the review format | CW-r9d2 |
| Scenario: A pre-closeout review asks whether feedback was addressed | CW-2nb2 |
| Scenario: A later review runs beside a transcript | CW-5e24 |
| Scenario: The reviewer returns an error instead of a review | CW-r9d2 |
| Scenario: A review finding changes the design | CW-ovuj |

## Finding lens, basis, and severity

Destination: general.

| Clause or scenario | Held by |
|---|---|
| A finding's lens MUST be one of the seven lenses | CW-5sc1 |
| Its basis MUST be `specification`, `guidance`, `evidence`, or `judgement`, each citing as stated | CW-5sc1 |
| Its severity MUST be `blocking`, `should`, or `minor`, with their meanings | CW-7d5f |
| Scenario: A finding cites written guidance | CW-5sc1 |

## Triage of every finding

Destination: general.

| Clause or scenario | Held by |
|---|---|
| The implementing agent MUST record its own position on every finding, with evidence and a proposed action | CW-j1nv |
| A position of agreement MUST state its reason as a disagreement does | CW-j1nv |
| Every finding MUST be presented to the owner, none withheld | CW-j1nv |
| A finding MUST be treated as disposed of only when the owner states a disposition | CW-neua |
| Scenario: A minor finding the agent agrees with | CW-j1nv |
| Scenario: The owner discusses one finding and not another | CW-neua |

## Intervention ledger

Destination: general.

| Clause or scenario | Held by |
|---|---|
| Each disposition correcting course MUST be appended as one entry to `interventions.jsonl`, with the fields named | CW-zidp |
| A disposition accepting the agent's proposal as it stands MUST NOT be logged; the triage record holds every disposition | CW-xe8m |
| The ledger MUST be tracked, MUST remain in the change directory, and MUST be archived with the change | CW-1jxh |
| A changed or reversed design recommendation MUST be appended in the same shape, with `review` `design`, lens `direction`, basis `judgement`, null severity | CW-w22z |
| A recommendation the owner accepts MUST NOT be logged | CW-w22z |
| Scenario: The owner accepts a finding as proposed | CW-xe8m |
| Scenario: The owner reverses a design recommendation | CW-w22z |
| Scenario: A reviewed change's archive is cleaned up | CW-1jxh |

## Implementation sections and sessions

Destination: general. Seam: the evidence a section may owe validation is named by
validation's parts; CI is this repository's example, kept in the scenarios without
naming a workflow file.

| Clause or scenario | Held by |
|---|---|
| Each section MUST be a coherent, verifiable slice, sized by what it changes and proves, and MUST end at a verification point | CW-5r7l |
| A section's verification MUST name only evidence an implementation session can produce | CW-5h8e |
| Evidence only a push produces MUST be named as owed by validation: the workflow, the job, and what it must show | CW-5h8e (as the repository's validation part identifies it); the CI part's form, the workflow, the job, and what it must show: MCW-gvqb |
| Such evidence MUST NOT gate a task's completion | CW-5h8e |
| A session finding it in a verification MUST check the task on its own evidence and name it as owed in the section's notes | CW-5h8e |
| The plan MUST NOT prescribe in `tasks.md` how sections are distributed across sessions or rounds | CW-5r7l |
| A session MUST begin with no prior conversation and read the guidance, the change, and its sections, unless the owner directs the work to a named session not waiting on the owner, which continues on its model, reading the files again | CW-0ia3 |
| The cadence MUST be settled in design, the sections ordered by it, and planning's outcome MUST carry its mapping | CW-al17 |
| Each round MUST be recorded as it starts, from the latest mapping, as its first round with a section incomplete | CW-v6nj |
| A change with no mapping for its next incomplete section MUST ask the owner, once per round | CW-v6nj |
| Each section MUST be checked, handed off, and committed on its own | CW-tc82 |
| Anything a later session needs MUST be recorded in the change's files before each section is committed | CW-tc82 |
| A section's diff MUST be checked against the guidance by an agent with no part of the implementing session in its context | CW-tc82 |
| When code invalidates the plan, the session MUST record why, commit its work in progress with no task checked, push it, and return the change | CW-1u53 |
| Scenario: A section is finished | CW-tc82 |
| Scenario: The owner sends the next section to a finished session | CW-0ia3 (the command for the make target) |
| Scenario: A plan maps a two-round cadence | CW-al17 |
| Scenario: The plan's premise fails mid-section | CW-1u53 |
| Scenario: A section owes CI evidence | CW-5h8e (a CI workflow, for `tests.yml`) |
| Scenario: An older plan gates a task on a CI run | CW-5h8e |

## Validation observes a committed slice

Destination: split. Moves: the packages built from the commit; end-to-end evidence
from the commit's pipeline run; the owed CI workflows dispatched from a fixed list;
the named jobs judged and every other failing job compared with `dev`; the images,
the Helm render checks, and the chart-to-loader check; the Helm end-to-end run of a
listed set of scenarios from no persistent state; and their scenarios. Seam:
validation's parts are the repository's, and each part's evidence comes from the
commit under validation (CW-zkhs).

| Clause or scenario | Held by |
|---|---|
| Validation before an implementation review MUST describe one commit and MUST NOT modify the checkout | CW-a7dw |
| It MUST fail if the worktree is not clean at its start or after any step, or if `HEAD` is no longer the validated commit | CW-a7dw |
| It MUST then collect no further evidence, and MAY still stop what it started | CW-a7dw |
| It MUST NOT regenerate lockfiles or any other tracked file, `tasks.md` included | CW-a7dw |
| It MUST build the internal packages it tests from the commit, never from wheels another branch left in the shared wheelhouse | MCW-v3tf |
| A condition validation could repair MUST fail validation and return the slice to implementation | CW-af15 |
| End-to-end evidence MUST come from a pipeline run whose head commit is the commit under validation | MCW-zk52; the general rule, each part's evidence from the commit, CW-zkhs |
| It MUST dispatch, on the change's branch, each workflow a complete section names as owed | MCW-3i99 |
| It MUST dispatch only workflows on a fixed list that holds none that publishes | MCW-3i99 |
| Adding to the list MUST be a tracked change by the owner | MCW-3i99 |
| It MUST judge each named job and what it must show, from a run whose head is the commit | MCW-7hr1 |
| A named job that fails, or an absent observation, MUST be a failure | MCW-7hr1 |
| It MUST compare each failure of every other failing job with the same job in `dev`'s latest completed ancestor run, and MUST name that run and its commit | MCW-2lzw |
| A failure that run shows too MUST be reported as already failing on `dev` and MUST NOT be a failure | MCW-2lzw |
| Any other failure MUST be diagnosed as any failure is | MCW-2lzw |
| With no such run, or failures that cannot be compared, the failure MUST be of unknown cause | MCW-3yqn |
| Validation MUST build the service images, include the Helm render checks with the chart-to-loader check able to run, and a Helm end-to-end run of a listed set of scenarios | MCW-qeja (the images and the render checks); MCW-8h0r (the Helm end-to-end run) |
| A skipped chart-to-loader check MUST fail validation | MCW-qeja |
| Every pipeline scenario not on the list MUST be reported as not run against Helm, never as passed | MCW-8h0r |
| Validation MUST NOT fix what it finds in the commit | CW-af15 |
| Its result MUST be `passed`, `failed`, or `inconclusive`, as defined | CW-e7lm |
| An environmental failure MUST be put to the owner with its remedy before the record is written, and its part rerun on the owner's word | CW-a1nz |
| Every attempt's evidence MUST be kept | CW-a1nz |
| The Helm end-to-end run MUST start from no persistent state left by an earlier deployment | MCW-8h0r |
| The record MUST name the end-to-end scenarios that exercise the change, with the basis for each | CW-av28 |
| Scenario: A deploy fails on volumes left by an earlier install | MCW-8h0r |
| Scenario: A lockfile is stale | CW-af15 |
| Scenario: An earlier pipeline run exists on the branch | MCW-zk52; CW-zkhs's scenario states its general form |
| Scenario: A pipeline scenario the charts do not serve | MCW-8h0r |
| Scenario: Owed CI evidence beside jobs that fail on `dev` | MCW-7hr1 (`test · test-deployment-packaging`, a job `tests.yml` has, for one it does not) |
| Scenario: A job not owed fails only on the branch | MCW-2lzw |
| Scenario: A new failure in a job that already fails on `dev` | MCW-2lzw |
| Scenario: A test that fails on `dev` fails another way on the branch | MCW-2lzw |
| Scenario: No `dev` run of the branch's code | MCW-3yqn |
| Scenario: A plan owes a workflow that publishes | MCW-3i99, with the dispatch list's clause group |
| Scenario: A dispatched run is cancelled | MCW-3i99, with the CI dispatch's clause group; the general rule it applies is CW-a1nz |

## Guarded push of a change branch

Destination: split. Moves: the protected branches, `main` and `dev`, and the refusal
of recognizable private content, which `dev` added to this requirement after the
rewrite began and the merge before closeout brought in; it is this repository's
pre-push check. Seam: the push refuses the repository's protected branches (CW-59c7),
and runs the repository's pre-push check, where it provides one, before it pushes
or reports success, refusing when it fails (CW-p7kq, settled at review 71's
triage, 71 F1 and F2).

| Clause or scenario | Held by |
|---|---|
| An agent MAY push a change's own branch without approval only after the check: `HEAD` attached, worktree clean, branch neither `main` nor `dev`, upstream of the same name | CW-59c7 (the repository's protected branches); `main` and `dev`: MCW-farr |
| The push MUST send exactly `HEAD` and MUST NOT be forced | CW-59c7 |
| A branch with no upstream MAY be pushed to the same name, setting it | CW-59c7 |
| The check MUST report a refused state and MUST NOT repair it | CW-59c7 |
| Before sending commits, the check MUST reject personal home paths, private assistant planning/session paths, and denylisted identifiers from added content, filenames, and commit messages | CW-p7kq (the push runs the repository's pre-push check, and refuses when it fails); the rules: MCW-q8vd |
| It MUST inspect intermediate commits, not only the final tree, and MUST omit matched values from diagnostics | MCW-q8vd |
| An unreadable configured denylist or unavailable comparison refs MUST fail closed | MCW-q8vd |
| Scenario: The worktree is dirty | CW-59c7 |
| Scenario: Private content is removed in a later commit | MCW-q8vd |

## Triage of an implementation round

Destination: general. The round view's mechanics are requirements of their own
(D11).

| Clause or scenario | Held by |
|---|---|
| The implementation review, the validation of the same commit, and the owner's notes MUST be triaged together, in a session not the implementing one | CW-qtxb |
| A published review MUST name the commit it reviewed | CW-qtxb |
| For a pasted review, triage MUST record the commit the owner says its reviewer saw | CW-qtxb |
| A review and a validation of different commits MAY be one round only on the owner's waiver, which MUST be recorded in the ledger | CW-514y |
| Each failure caused by the commit, or of unknown cause, MUST be presented as a finding, its diagnosis checked against the logs | CW-xg4v |
| An `inconclusive` part MUST be read as missing evidence, never as a finding | CW-xg4v |
| The owner's notes MUST be saved verbatim as a review record and triaged like any review | CW-rb5n |
| The triaging agent MUST state its own position on each point rather than carry it out | CW-rb5n |
| Each disposition MUST be logged to the intervention ledger | CW-rb5n |
| Accepted fixes MUST pass a section's checks before they are committed | CW-j1ab |
| The commit MUST be validated again, unless after a pre-closeout review it changes only `openspec/` and `docs/` | CW-j1ab |
| A triage of any kind MUST commit the tracked edits its dispositions made, and push them | CW-j1ab |
| The owner MUST be able to read a round as one set of changes, no commit changed to show it | CW-aoby |
| For a change in its clone, the reading MUST take place in the workspace, on its copy of the branch, and MUST NOT move the clone's branch | CW-4svs |
| Validation and the implementation review MUST start when the round's sections are committed, beside the reading | CW-4svs |
| Triage MUST NOT start until the owner has answered on the round, saved as its owner record | CW-4svs |
| A repeat pass MUST be read the same way, its triage MUST NOT start until the owner answered on it, and an earlier answer covers only the earlier pass | CW-9mrq |
| For a change in the workspace, while its branch is moved, review, validation, triage, and implementation MUST NOT start | CW-78ul |
| Ending the reading MUST return the branch to the round's commit, or to the last carried commit; the round's own commits MUST NOT change | CW-n44s |
| A view MUST NOT move a checkout in which an unattended run is in progress | CW-78ul |
| Ending the reading MUST carry each owner's commit with exactly its paths at its content, and MUST leave uncommitted edits uncommitted | CW-n44s |
| It MUST carry a path the round changed only when the commit keeps every change the round made to it, and MUST refuse without moving otherwise, for a merge, or off the round's base | CW-uq5q |
| A path the round added, deleted, or changed as binary, symlink, or mode MUST be carried only as the round's; an absent path MUST NOT be taken for an empty file | CW-gd24 |
| A view MUST NOT be moved to a new head while such commits or uncommitted edits are present | CW-rgws |
| An owner's commit MUST reach the clone only through a fast-forward triage makes | CW-te38 |
| A pre-closeout review MUST NOT run, nor its triage advance, unless the latest validation passed for `HEAD` or an ancestor differing only in ledgers and records, unless the owner overrides it | CW-gqav |
| Once its triage has run, a commit `HEAD` differs from only in `openspec/` and `docs/` MUST be accepted the same way | CW-gqav |
| Scenario: The owner's note is contradicted by the files | CW-rb5n |
| Scenario: A repeat round's fix is read | CW-9mrq |
| Scenario: A review and a validation describe different commits | CW-514y |
| Scenario: A ledger line is committed after the validation | CW-gqav |
| Scenario: A pre-closeout triage commits only documents | CW-j1ab |
| Scenario: An implementation triage commits only documents | CW-j1ab |
| Scenario: The owner reads a round committed section by section | CW-aoby |
| Scenario: Validation runs while the owner reads | CW-4svs |
| Scenario: The owner has no notes | CW-4svs |
| Scenario: The owner commits an edit while reading | CW-n44s; its fast-forward clause also CW-te38 |
| Scenario: The owner commits part of a file the round changed | CW-uq5q |
| Scenario: The owner commits a whole file the round changed, then edits on | CW-n44s |
| Scenario: The owner edits a file the round added | CW-gd24 |
| Scenario: The owner commits a deletion the round made | CW-gd24 |
| Scenario: The owner commits a binary file the round changed | CW-gd24 |
| Scenario: The owner merges during the view | CW-uq5q |
| Scenario: The view is refreshed over the owner's commit | CW-rgws |
| Scenario: A view would move a checkout with a run in progress | CW-78ul |
| Scenario: Validation fails beside an implementation review | CW-xg4v |

## Harness-neutral agent skills

Destination: general. Seam: the skills' and harnesses' paths are inventory entries
(D13).

| Clause or scenario | Held by |
|---|---|
| Each skill MUST have exactly one source, loadable by every supported harness | CW-d8de |
| A skill MUST NOT be kept as separate copies; every harness entry MUST resolve | CW-d8de |
| Scenario: A skill is edited | CW-d8de |
| Scenario: A harness entry does not resolve | CW-d8de |

## An orchestrating session advances one change

Destination: general. Seam: merges of `dev` become merges of the branch the change
lands on.

| Clause or scenario | Held by |
|---|---|
| The owner MAY advance one change from one orchestrating session | CW-ms3j |
| It MUST hold no state beyond the change's files and workflow log | CW-ms3j |
| It MUST run the next step the computation names | CW-5jlj |
| It MUST advance without the owner wherever the computation names a step | CW-5jlj |
| It MUST bring every question to the owner, showing each message as written | CW-yvo1 |
| It MUST NOT answer a design question, nor decide or state a position on a finding | CW-yvo1 |
| It MUST show the earlier outcomes a run's line keeps beside its last | CW-yvo1 |
| It MUST continue a named implementation session only on the owner's word | CW-0ia3 |
| It MAY create the change's clone and branch | CW-op72 |
| It MAY commit the workflow's own changes, what the owner asks for, and merges of `dev` the owner asks for, in the clone, through the guarded push | CW-op72 (merges of the branch the change lands on) |
| It MUST NOT commit while a step runs | CW-bsmk |
| It MUST NOT merge while a round view is open, or between a round's commit and its triage | CW-bsmk |
| It MUST NOT write feature work of its own accord | CW-op72 |
| It MUST NOT commit a closed step's leftover work unless the owner asks | CW-bsmk |
| It MUST resolve a merge's conflicts in the index, change documents, step table, and skills, and MUST bring a conflict in code to the owner | CW-tax4 |
| One the owner does not rule on MUST go to an implementation run, named the files | CW-tax4 |
| While a merge is in progress the computation MUST name the owner | CW-tax4 |
| It MUST NOT read code, reviews, or change documents to form a view of a finding or design question | CW-mkwj |
| It MAY read what routing and recovery need | CW-mkwj |
| It MAY report the tooling's misbehaviour as a numbered record marked as its own | CW-6scj |
| On the owner's waiver of a design review after a return, it MUST record a decision directing planning, and the computation MUST then name planning | CW-6fi2 |
| It MUST advance only the change it was started for | CW-ms3j |
| Scenario: The orchestrating session restarts | CW-ms3j |
| Scenario: The orchestrating session restarts during a round view | CW-ms3j |
| Scenario: A review's triage has nothing for the owner | CW-5jlj |
| Scenario: The owner waives a design review after a return under orchestration | CW-6fi2 |
| Scenario: A finding is relayed | CW-yvo1 |
| Scenario: The owner asks for a permission fix | CW-op72 |
| Scenario: A merge of `dev` conflicts in a skill and in code | CW-tax4, as "A merge conflicts in a skill and in code" |
| Scenario: A merge is asked for during a round's window | CW-bsmk |
| Scenario: A closed step leaves tracked work uncommitted | CW-bsmk |

## Unattended step runs end with a structured outcome

Destination: general.

| Clause or scenario | Held by |
|---|---|
| A step MAY be run unattended, through one wrapper, as its leaf skill | CW-js86 |
| Every unattended run MUST end with a schema-conforming outcome of the five kinds | CW-js86 |
| An exit or a return MUST be named as a target, by step, kind, and sections as stated | CW-5ldi |
| A review or triage named without its kind, or with an empty or unknown one, MUST be refused | CW-5ldi |
| A validation MUST name the target it was given as its exit, and archive cleanup `done` | CW-5ldi |
| A triage's finished or returned outcome MUST name the records it triaged, as stated | CW-4vma |
| The wrapper MUST record an outcome breaking that rule only as stopped, naming the reference; the record command MUST refuse it | CW-4vma |
| The wrapper MUST append each outcome, with the run's session and commit, to the log | CW-1a4d |
| The wrapper MUST record a stopped outcome for a run that ends without one | CW-1a4d |
| A run with further turns MUST be logged with its last outcome, keeping each earlier one on its line | CW-1a4d |
| The files MUST prevail over the log on the change's state | CW-4c3e |
| Every outcome's denials MUST be taken from the run's own record, over every turn, with the harness's reason | CW-k5mk |
| A review run's outcome MUST name the record it published | CW-r9d2 |
| A review run that published none MUST be recorded as stopped; an earlier record MUST NOT count | CW-r9d2 |
| A question MUST be answered by resuming the same session | CW-xgq3 |
| A proposed return MUST NOT change the status until the owner confirms it | CW-xgq3 |
| The confirmation MUST be recorded as the owner's decision naming the run and the step; that step sets the status | CW-xgq3 |
| A decision resolving a run MUST name it, and MUST NOT resolve any other | CW-ht4h |
| A decision reading a run's denials MUST name that run | CW-ht4h |
| A decision directing a step MUST name its target as an exit is named, and MUST be the owner's | CW-ht4h |
| Scenario: Validation needs an environmental remedy | CW-a1nz |
| Scenario: A run crashes | CW-1a4d |
| Scenario: A wake-up follows a run's report | CW-1a4d |
| Scenario: Implementation finds a design question | CW-1u53 |
| Scenario: A triage names its exit | CW-5ldi |
| Scenario: A triage outcome names no records | CW-4vma |
| Scenario: A triage outcome names an unknown record | CW-4vma |
| Scenario: A triage outcome names no review | CW-4vma |
| Scenario: A triage outcome names a record twice | CW-4vma |
| Scenario: The owner confirms a return | CW-xgq3 |
| Scenario: A confirmation names no run | CW-ht4h |
| Scenario: The owner directs a repeat review | CW-zcx8 |
| Scenario: A directed review names no kind | CW-ht4h |
| Scenario: A directed triage names no kind | CW-ht4h |
| Scenario: The orchestrating session directs a step | CW-jtsl |
| Scenario: A decision about one run leaves another waiting | CW-ht4h |

## The next step is computed from the files

Destination: general. The conversion's rules are requirements of their own (D11).

| Clause or scenario | Held by |
|---|---|
| The next step MUST be computed by interpreting the graph over the index row, reviews, tasks, log, and any open round view | CW-4rqr |
| The same computation MUST be available to the owner by hand | CW-4rqr |
| When it fails or cannot classify, the orchestrating session MUST resolve it or bring it to the owner, as stated | CW-tel3 |
| The orchestrating session MUST record what it decided in the log | CW-tel3 |
| The computation MUST route on the last step's exit, and on the owner's latest direction until its target runs | CW-m70n |
| It MUST NOT infer an exit from the phase | CW-m70n |
| A triage MUST name its exit in its outcome, and MUST keep the target and the owner's words under `## Next` as prose | CW-l866 |
| A review with a triage file and no finished or returned triage outcome, or conversion line, naming it MUST be treated as a triage in progress | CW-l866 |
| An undeclared exit, a validation's exit other than its target, and an exit meeting an unmet entry guard MUST be brought to the owner | CW-0wna |
| An unmet guard on a declared exit MUST name the step that satisfies it, carrying the exit as its target | CW-8tdv |
| A guard no step can satisfy MUST be brought to the owner, naming the target and what is missing | CW-8tdv |
| The computation MUST name validation with a target always | CW-nkys |
| It MUST check the target's guards again on validation's exit | CW-nkys |
| Every line the tooling appends to a log MUST carry the format marker | CW-lyr4 |
| A change with an unmarked line, or numbered records and no log, MUST be brought to the owner with the conversion command | CW-qj77 |
| Its log MUST NOT be read as the new format | CW-qj77 |
| The conversion MUST refuse a change with a triage in progress by the older reading, naming the review | CW-42me |
| It MUST rewrite the log's lines in place, each keeping its seq | CW-o1ca |
| It MUST append one conversion line naming every triaged review and no exit, an unattested one only on the owner's confirmation | CW-o1ca |
| It MUST append the owner's direction to the node the change stands at, which the owner confirms or gives | CW-zniv |
| What it proposes, and when it proposes nothing | CW-ajcm |
| It MUST hold the log's lock from its read through replacing the log in one step | CW-95xp |
| Every reader and appender MUST reopen a log replaced under its lock | CW-v8mq |
| Once the owner confirms a return, the returned review MUST NOT govern what follows | CW-izj1 |
| A declined return, or one recorded at closeout, MUST be brought to the owner | CW-izj1 |
| A round, and the merge before closeout, MUST advance only on a `passed` validation of its final commit or one differing as stated | CW-tnp6 |
| An `inconclusive` validation MUST be brought to the owner | CW-tnp6 |
| A `failed` validation of the merged `HEAD` MUST name the merge again | CW-tnp6 |
| Nothing routes on a triage file's `## Next` | CW-l866 |
| Scenario: Reviews await triage | CW-4rqr |
| Scenario: A status was edited by hand | CW-4c3e |
| Scenario: A status is ahead of the log | CW-4c3e |
| Scenario: Triage records another round | CW-8tdv |
| Scenario: A triage has not finished | CW-l866 |
| Scenario: A step names an exit its node lacks | CW-0wna |
| Scenario: A triage names sections out of the plan's order | CW-m70n |
| Scenario: A triage returns the change | CW-izj1 |
| Scenario: A pre-closeout triage returns the change | CW-izj1 |
| Scenario: The owner declines a return | CW-izj1 |
| Scenario: A return confirmed by anyone but the owner | CW-ht4h |
| Scenario: A new triage file awaits its outcome | CW-l866 |
| Scenario: A triage file predates `## Next` | CW-l866 |
| Scenario: A log not yet converted | CW-qj77 |
| Scenario: An older return awaits confirmation | CW-qj77 |
| Scenario: A change has records and no log | CW-qj77 |
| Scenario: A change is converted | CW-o1ca |
| Scenario: A pending return is converted, then confirmed | CW-zniv |
| Scenario: A confirmed return is converted | CW-o1ca |
| Scenario: A conversion proposes a guard's remedy | CW-ajcm |
| Scenario: A conversion after later runs | CW-zniv |
| Scenario: A conversion follows a later direction | CW-ajcm |
| Scenario: A conversion's triage is not attested | CW-o1ca |
| Scenario: An append waits on the conversion | CW-v8mq |
| Scenario: A conversion is interrupted | CW-95xp |
| Scenario: A change is converted with a triage in progress | CW-42me |
| Scenario: An older wrapper appends after the conversion | CW-qj77 |
| Scenario: A validation before closeout passes | CW-nkys |
| Scenario: A validation of the merged HEAD fails | CW-tnp6 |
| Scenario: The merge proposes another pre-closeout review | CW-a6ow |
| Scenario: The owner waives the merge's validation | CW-a6ow |
| Scenario: A validation names another exit | CW-0wna |
| Scenario: A closeout correction awaits validation | CW-trdu |
| Scenario: A documentation correction at closeout | CW-trdu |
| Scenario: A round's validation is inconclusive | CW-tnp6 |
| Scenario: An implementation round advances | CW-8tdv |
| Scenario: A round is recorded after the fact | CW-v6nj |

## Discussion steps stay conversations with the owner

Destination: general.

| Clause or scenario | Held by |
|---|---|
| Design MUST NOT run without the owner | CW-3tvs |
| Triage MUST bring every finding and point to the owner, and MAY finish without the owner only when there is none | CW-3tvs |
| Orchestrated, each MUST run as its own resumable session, one decision or finding per turn, its messages shown and the owner's reply resuming it | CW-3tvs |
| Planning MUST NOT ask the owner to accept the plan | CW-p1us |
| A plan needing a decision the design does not make MUST return the change to design | CW-p1us |
| Scenario: A triage finding is presented | CW-3tvs |

## Unattended runs are held to their step's permissions

Destination: general. Seam: the rule syntax is provisional (D5, 7); the
requirements name rules by what they allow, the syntax only in examples.

| Clause or scenario | Held by |
|---|---|
| An unattended run MUST be limited to the tools its table allows | CW-qu42 |
| It MUST NOT be granted a push other than the guarded push | CW-qu42 |
| Every step writing tracked work MUST commit and push it through the guarded push | CW-pehu |
| Validation and review MUST commit nothing | CW-pehu |
| A returning run MUST commit its work in progress, check no task, and push it | CW-ajo9 |
| A stopping run MUST leave its work uncommitted; one stopped by a guard or a moved `HEAD` MUST commit nothing | CW-ajo9 |
| A step MUST NOT reset, check out, switch, rebase, stash, or clean | CW-qu42 |
| Every denial a run records MUST be on its outcome, from its record, with the harness's reason | CW-k5mk |
| A run that cannot go on without a denied tool MUST end stopped, naming it, not ask or work around it | CW-4yhk |
| A run that goes on MUST do so only by calls its rules allow | CW-4yhk |
| A call a deny rule refused MUST NOT be done by another tool, except a write-steering rule's shell write, which MAY be made with Edit or Write | CW-2lvd |
| A call denied for want of an allow rule MAY be done by a tool allowed for the same work | CW-2h9t |
| Either way the run MUST name the substitute in its message | CW-2lvd, CW-2h9t |
| The orchestrating session MUST read each denial from the run's record, never from the message | CW-svng |
| It MUST classify each by the harness's reason, by its parts, or with no reason against the deny rules | CW-svng |
| It MUST check the run's later calls after a deny-rule denial for a workaround | CW-5rmh |
| It MUST read a write-steering denial whose write was made with Edit or Write as a gap, needing no ruling | CW-5rmh |
| It MUST propose the narrowest rule for a gap, saying whether a grant or a tracked change | CW-vdqj |
| It MUST record its reading as a decision reading that run, before the next step runs | CW-vdqj |
| A waiting outcome MUST be answered or decided after its denials are read; the reading MUST NOT settle it | CW-jqi7 |
| A deny rule's denial MUST NOT be granted for one run | CW-drf6 |
| A change to a step's permissions MUST be made by the owner, or on their word by the orchestrating session, tracked, or granted for one run | CW-drf6 |
| A grant MUST be passed on the run's command line, recorded as `granted`, and never added to the table | CW-tl5v (through `start`, for the make target) |
| A file rule's relative path MUST name a path from the root of the checkout the run starts in | CW-56zq |
| Interactive runs MUST NOT be restricted by the table | CW-mzyz |
| Scenario: A step changes directory before writing a file its table allows | CW-56zq |
| Scenario: Validation attempts to relock | CW-4yhk (regenerating a lockfile its table denies, for `make lock`) |
| Scenario: A step is denied a command no rule names | CW-vdqj |
| Scenario: The owner grants rules before a fresh run | CW-tl5v (each rule its own `--allow` of `start`, for `ALLOW`) |
| Scenario: A step does the work of a call no rule names with a tool its rules allow | CW-2h9t |
| Scenario: A step's in-place sed is refused and the step uses the Edit tool | CW-2lvd |
| Scenario: A question carries denials | CW-jqi7 |
| Scenario: A step is denied by a deny rule | CW-2lvd |
| Scenario: A step commits its work | CW-qu42 |
| Scenario: A step stops at its session's limit | CW-ajo9 |

## A design blocked on a prerequisite halts

Destination: general.

| Clause or scenario | Held by |
|---|---|
| The design step MUST, with the owner, define the prerequisite's requirements and proposal and end blocked | CW-dtpz |
| The prerequisite's proposal and row MUST be written on a branch from the development branch, never the blocked change's | CW-dtpz |
| They MUST reach the development branch before the prerequisite's workflow starts | CW-dtpz |
| The blocked change's branch MUST receive them only by merging the development branch | CW-dtpz |
| The blocked change MUST remain `in design`, the prerequisite gating its design | CW-p7xk |
| Once the prerequisite is archived and merged, the dependency MUST be released, on the owner's word, before design resumes | CW-p7xk |
| Scenario: A prerequisite has not landed | CW-p7xk |
| Scenario: A prerequisite has landed | CW-p7xk |

## Unattended steps run on their step's ordered models

Destination: split. Moves: the forbidden models, Fable and Astra. Seam: a repository
may forbid models, and the table names none it forbids; the owner's override for one
review stands.

| Clause or scenario | Held by |
|---|---|
| Each row MUST name its models in priority order, each with its harness and effort | CW-ebmo |
| The wrapper MUST run the first available, falling to the next only when one is unavailable | CW-ebmo |
| It MUST record the model and effort that ran on the log line | CW-ebmo |
| The table MUST NOT name a Fable or Astra model | CW-zq4h (the models a repository forbids); Fable and Astra: MCW-y37w |
| A row MUST NOT list two models of one vendor | CW-zq4h |
| Another harness's model MUST appear only on a row whose limits it can enforce | CW-zq4h |
| A run whose models are all unavailable MUST end stopped, naming the reason | CW-1dld |
| A network error MUST be retried and MUST NOT cause a fallback | CW-1dld |
| A waiting run MUST be resumed only on the model it ran on | CW-1dld |
| A review on a model other than its row's first MUST name its reviewer's harness and model | CW-clhl |
| A review MUST continue a previous reviewer's session only on the same harness | CW-clhl |
| The owner MAY name any model or effort for one review by hand; a named model MUST be the only one, the record and line marking the override | CW-d1sm |
| The orchestrating session MUST NOT name one | CW-d1sm |
| Scenario: The owner reviews on a model the table forbids | CW-d1sm (a model the repository forbids, for a Fable model) |
| Scenario: Codex is unavailable for a review | CW-clhl |
| Scenario: A row names a forbidden model | Two models of one vendor: CW-zq4h; a Fable model: MCW-y37w |
| Scenario: A step's only model is at its usage limit | CW-1dld |

## Unattended runs record their cost

Destination: general.

| Clause or scenario | Held by |
|---|---|
| Each run's log line MUST record its own cost, for Claude and for Codex as stated | CW-yzer |
| Dollars that cannot be told from the session's earlier turns MUST be marked partial | CW-yzer |
| A resumed run MUST record the gap since its last turn and whether its first turn read the cache | CW-u7da |
| A change's cost MUST be reportable by step and round, with cache misses and gaps | CW-u7da |
| Scenario: A discussion turn is resumed after a long gap | CW-u7da |

## Each change is worked in its own clone

Destination: general. Moves: the clone's bootstrap command, `make init`. Seam: the
bootstrap is the repository's; the wheelhouse scenario says "environments".

| Clause or scenario | Held by |
|---|---|
| A change MAY be worked in a clone of its own, holding its branch, records, environments, evidence, and sessions, or in the workspace | CW-yib2 |
| The computation MUST name the clone's creation when the branch is checked out in neither, and the orchestrating session MUST create it and the branch | CW-4x66 |
| When the workspace holds the change's records, the computation MUST NOT name the clone and MUST bring the change to the owner, naming both routes | CW-4x66 |
| Creating a clone MUST be safe to repeat, finish an incomplete clone, and refuse, deleting nothing, a directory as stated | CW-8jyb |
| The clone's `origin` MUST be the workspace's, and a remote MUST name the workspace | CW-8jyb |
| The bootstrap MAY run while design proceeds | CW-8npg; the bootstrap command: MCW-uqlq |
| Implementation and validation MUST NOT start before it has succeeded | CW-8npg |
| Its state MUST be recorded so running, succeeded, and failed are told apart | CW-8npg |
| A failed bootstrap MUST be brought to the owner, naming its log, not retried by itself | CW-8npg |
| As its last act, archive cleanup MUST copy the records and the evidence they name into the workspace at the same paths | CW-hak6 |
| The copy MUST be safe to repeat, MUST extend a prefix, and MUST NOT otherwise overwrite, refusing a differing file | CW-rf50 |
| Once archive cleanup's outcome is logged, the orchestrating session MUST repeat the copy | CW-hak6 |
| A step reading another or an earlier change's records MUST look in its checkout, then in the workspace | CW-c3he |
| A clone MUST be removed only on the owner's command, after repeating the copy, and only once its work is safe as stated | CW-xx5f |
| Named evidence the clone does not hold MUST be named in the removal's report | CW-xx5f |
| Scenario: Feature work begins on a change | CW-4x66 |
| Scenario: A change already under way in the workspace | CW-4x66 |
| Scenario: Clone creation was interrupted | CW-8jyb |
| Scenario: The bootstrap failed | CW-8npg |
| Scenario: Two changes are worked at once | CW-yib2 (environments, for the wheelhouse) |
| Scenario: A later session needs a cleaned-up change's history | CW-c3he |
| Scenario: The owner removes a clone too early | CW-xx5f |
| Scenario: Records grow after archive cleanup copied them | CW-hak6 |
| Scenario: A copied record conflicts | CW-rf50 |

## Each Helm validation is isolated in its change's namespace

Destination: market, whole. Seam: archive cleanup runs the repository's removal of a
change's validation resources (CW-ikmm).

| Clause or scenario | Held by |
|---|---|
| The Helm part MUST deploy into its change's own namespace, derived from its name | MCW-fnuh |
| It MUST NOT install, upgrade, remove, or scale a release or volume in another namespace | MCW-fnuh |
| Its images MUST carry a tag fixed per change, and MUST NOT be tagged by commit | MCW-fnuh |
| Before deploying, it MUST remove every volume the previous deployment wrote, the out-of-band ones included | MCW-a0hu |
| It MUST create the namespace's out-of-band Secrets | MCW-a0hu |
| It SHOULD upgrade in place from zero replicas, and MAY uninstall and install when refused, saying so | MCW-a0hu |
| Its scenarios MUST run inside the namespace and MUST NOT depend on a local port | MCW-notv |
| After the scenarios it MUST keep every pod's log and the events, and MUST scale the workloads to zero | MCW-notv |
| A preflight MUST compare the recorded memory times the running releases with what the node can allocate, and MUST treat a misfit as environmental | MCW-7bia |
| With no figure, or no measurement, it MUST warn and go on | MCW-7bia |
| A pod failing for memory after a passed preflight MUST be classified from the evidence named | MCW-epkd |
| Archive cleanup MUST remove the change's namespace and images | MCW-7ts3; archive cleanup running it: CW-ikmm |
| It MUST record the memory the latest validation measured, with when; with none, keep the figure and say so | MCW-7ts3 |
| Conflicting figures at a merge: the one measured later MUST be kept | MCW-7ts3 |
| Scenario: Two changes are validated at once | MCW-fnuh |
| Scenario: A change is validated again | MCW-a0hu |
| Scenario: An earlier run crashed with its workloads up | MCW-a0hu |
| Scenario: Usage cannot be measured | MCW-7bia |
| Scenario: Archive cleanup after a validation that measured nothing | MCW-7ts3 |
| Scenario: No memory figure is recorded yet | MCW-7bia |
| Scenario: Two validations pass the preflight together | MCW-epkd |
| Scenario: A commit's own pod is killed for memory | MCW-epkd |
| Scenario: A change's archive is cleaned up | MCW-7ts3 |

## The workflow graph is declared in code

Destination: general.

| Clause or scenario | Held by |
|---|---|
| Steps and transitions MUST be declared as one table in code: nodes, exits, joins, exit guards, entry guards | CW-ak1z |
| Exit guards MUST apply to steps' exits and MUST NOT be checked against directions | CW-sd34 |
| Entry guards MUST be checked on every entry; an unwaivable one MUST refuse while unmet; a waivable one MUST take a direction as override | CW-sd34 |
| The archive MUST be an unwaivable entry guard of the closeout review, its triage, and archive cleanup, and its absence one of design, planning, implementation, and the merge | CW-xo82 |
| Closeout MUST be reached by a step's exit only from the merge | CW-xo82 |
| A triage node's entry guard MUST be a review of its kind awaiting triage, or a later validation record as stated | CW-iaeh |
| Validation's entry guard MUST be unwaivable: a target; the target's entry guards MUST be checked on its exit | CW-iaeh |
| Archive cleanup's exit MUST be the terminal node `done` | CW-9tzd |
| A change to the table MUST be made as an OpenSpec change | CW-ak1z |
| The diagram's source, and its export's embedded copy, MUST be checked against the table | CW-66kx |
| Scenario: The diagram's departures are reported | CW-66kx (`check graph`, for `make change-graph`) |
| Scenario: The documented diagram drifts | CW-66kx (the capability's documentation, for the `change-workflow` architecture) |
| Scenario: The round's triage waits for its join | CW-ak1z |
| Scenario: A round's validation and review ran before the owner read it | CW-78ul |
| Scenario: A round's validation starts before its review is published | CW-iaeh |
| Scenario: Archive cleanup finishes | CW-9tzd |
| Scenario: The owner directs the triage of a failed fix validation | CW-iaeh |
| Scenario: A step's exit meets an unmet entry guard | CW-xo82 |

## Interactive step runs record their outcome

Destination: general.

| Clause or scenario | Held by |
|---|---|
| An interactive run MUST behave as it does without the wrapper, unrestricted, but MUST end by recording its outcome | CW-mzyz |
| A review MUST record nothing | CW-mzyz |
| The record command MUST check the outcome against the schema | CW-gnqh |
| It MUST record it with the session's id, `HEAD`, and that the run was interactive | CW-gnqh |
| It MUST refuse without a session id, and inside an unattended run | CW-gnqh |
| Every step's permissions MUST allow printing the session's id | CW-gnqh |
| Scenario: An interactive triage finishes | CW-mzyz |
| Scenario: An interactive review is pasted into a triage | CW-mzyz |
| Scenario: An interactive session ends without recording | CW-mzyz |
| Scenario: An interactive plan sets its status and records nothing | CW-mzyz |
| Scenario: The harness exports no session id | CW-gnqh |
| Scenario: An unattended run records its own outcome | CW-gnqh |

## The owner directs a change's next step

Destination: general.

| Clause or scenario | Held by |
|---|---|
| The owner MAY direct a change to any node by a decision naming its target and a reason; it MAY resolve the waiting run | CW-jtsl |
| Only the owner MAY direct a step; the orchestrating session MUST NOT direct one, nor record an exit on a step's behalf | CW-jtsl |
| The computation MUST name the directed step until a later run of it is logged, checking no exit guard | CW-zcx8 |
| The step sets its own status as it starts | CW-zcx8 |
| A direction MUST be refused, naming the guard, while an unwaivable entry guard of a node it names is unmet | CW-uhdy |
| An archived change MUST NOT be directed to design, planning, or implementation, nor one not archived to the closeout review, its triage, or archive cleanup | CW-uhdy |
| A waivable entry guard, and the step's own check, MUST accept the direction as override | CW-uhdy |
| A direction to validation MUST name its target nested, and is refused without one | CW-eups |
| A directed validation that passed MUST lead to its target; one failed or inconclusive MUST be brought to the owner | CW-eups |
| Scenario: The owner directs past a guard | CW-sd34 |
| Scenario: Closeout finds a design defect before the archive | CW-jtsl |
| Scenario: The owner waives archive cleanup's validation by a direction | CW-zcx8 |
| Scenario: An archived change is directed to design | CW-uhdy |
| Scenario: A change not archived is directed to archive cleanup | CW-uhdy |
| Scenario: The owner directs a pre-closeout review over a failed validation | CW-uhdy |
| Scenario: The owner directs a validation before closeout | CW-eups |
| Scenario: A validation is directed without a target | CW-eups |
| Scenario: A directed validation could never reach its target | CW-eups |
| Scenario: A triage is directed with nothing to triage | CW-uhdy |

## The specification's Purpose and Evidence

Not requirements, so no delta carries them. Closeout rewrites them by hand before the
archive (the plan's promotion task): the Purpose drops the Helm validation namespace,
and the Evidence entries for validation's parts, the CI comparison, the namespace,
the capacity record, and the parallel Helm check move to `market-change-workflow`'s
Evidence.
