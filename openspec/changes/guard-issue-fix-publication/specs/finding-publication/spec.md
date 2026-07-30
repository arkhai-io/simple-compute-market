## Purpose

Define portable, recoverable, branch-scoped actions and receipts for publishing
sanitized findings as GitHub issues and separately authorized draft fix pull
requests without granting public code live mutation authority.

## ADDED Requirements

### Requirement: Frozen publication authority
Every issue or draft-PR publication action MUST be a closed, immutable packet
that binds the destination repository, applicable working branch and exact
working SHA, default/upstream branch and pinned upstream SHA, reconciliation
epoch, finding schema and digest, SCM-derived stable fingerprint, exact
`finding_id`, rendered body digest, requested action, and a digest of the
private live authorization. Public validation MUST reproduce those values and
MUST NOT itself grant live mutation authority. Live publication MUST accept
finding schema v2 only; a v1 finding remains historical evidence at its pinned
SCM ref and MUST NOT be adapted or published by this path.

#### Scenario: Frozen action is valid
- **WHEN** a publication packet reproduces the validated finding, occurrence, branch/upstream authority, reconciliation context, rendered bytes, and private authorization digest
- **THEN** SCM can select and validate the deterministic intended action without contacting GitHub

#### Scenario: Authority drift is rejected
- **WHEN** the destination, working ref, upstream ref, applicable PR base/head ref, epoch, finding, occurrence, body, action, or authorization digest differs from the frozen packet
- **THEN** validation fails before external mutation

#### Scenario: Historical finding cannot enter live publication
- **WHEN** a schema-v1 finding or an in-memory v1-to-v2 adaptation is presented
- **THEN** the guarded path rejects it before observation or mutation

### Requirement: Private mutation boundary
SCM MUST own portable publication schemas, deterministic action selection,
rendering, redaction, stable markers, and pre/post validation. Private
infrastructure MUST own GitHub identity and credentials, the current
distributed campaign generation, cleanup and baseline proof, single-writer
branch mutation, guarded push, and credentialed GitHub calls. Every mutating
receipt MUST bind the current private authorization digest. Cleanup MUST NOT
invoke publication, and publication MUST NOT delay, authorize, or substitute
for cleanup. Public execution MUST take a local per-operation lock; the private
executor MUST additionally hold the distributed generation/single-writer
lease. The local lock key MUST be the canonical digest of destination, issue
scope, and operation family, so all issue mutations for one scope serialize.
For every live operation, the same private lease MUST remain valid across
remote-ref observation, GitHub pagination, action selection, journal
persistence, mutation, and post-read. Lease loss before a write fails closed;
lease loss after a step is marked attempted yields `outcome_unknown`.

#### Scenario: Public validation lacks live credentials
- **WHEN** SCM validates a complete issue or draft-PR action without a private credentialed executor
- **THEN** it returns portable validation only and performs no GitHub or branch mutation

#### Scenario: Publication follows cleanup authority
- **WHEN** a finding is queued before cleanup and baseline equivalence
- **THEN** credentialed publication remains unavailable until private generation-fenced cleanup authority supplies the required proof

#### Scenario: Private lease is lost during a live operation
- **WHEN** the distributed generation/single-writer lease is lost after a journal step is durably marked attempted
- **THEN** no later step executes and reconciliation treats the operation as `outcome_unknown`

### Requirement: Branch-scoped issue publication
Only a sanitized finding in `ready_to_file` state MUST be eligible for the
guarded live issue path. That path MUST have no force override and MUST verify
the exact canonical destination repository, explicit repository selection,
exact clean working checkout, expected working HEAD, current remote working
SHA, pinned upstream branch/SHA and ancestry, and default-branch denial. The rendered issue
MUST identify the working branch/SHA, pinned upstream SHA, reconciliation
context, occurrence marker, and the fact that the campaign is not promoting
the working branch to the default/upstream branch. SCM publication MUST map
canonical repository `arkhai-io/simple-compute-market`,
`feat/issue-discovery-harness`, and upstream `dev`; private-infrastructure
publication MUST map canonical repository
`arkhai-io/compute-market-internal-infra`,
`tools/agent-orchestration-scratch`, and upstream `main`. The remote working
SHA MUST equal the finding's working ref and contain its pinned upstream ref.
Every Git and GitHub read/write MUST name the canonical repository explicitly
and MUST ignore or reject conflicting ambient repository/base defaults.

#### Scenario: Ready branch-scoped issue can publish
- **WHEN** a `ready_to_file` finding and frozen action match the clean exact working checkout, current remote authority, supported repository, and non-default working branch
- **THEN** the private executor may perform the selected create, update, reopen, or no-op action

#### Scenario: Force cannot bypass readiness
- **WHEN** a finding is not `ready_to_file` or a caller requests a force override
- **THEN** the guarded live path rejects publication

#### Scenario: Default branch is denied
- **WHEN** the action selects `dev`, `main`, or another repository default/upstream branch as the campaign issue/fix working base
- **THEN** validation fails before mutation

### Requirement: Occurrence-idempotent deduplication
Issue discovery MUST search the complete eligible destination issue set or fail
closed, including every page of open and closed issues and every comment needed
to establish occurrence state. The issue scope MUST be derived from stable
fingerprint, destination, working branch, scenario ID, and scenario SHA-256.
Within that scope, a new immutable `finding_id` MUST update or reopen exactly
once. The same `finding_id` MUST select no-op only when both its canonical
finding SHA-256 and occurrence-payload SHA-256 are identical to the recorded
values; either digest changing under that identity MUST fail closed as an
identity conflict. A different destination,
working branch, scenario ID, or scenario hash MUST NOT deduplicate with the
existing issue. A new working SHA for the same working branch and scenario MUST
remain a new occurrence of the existing scoped defect rather than create a
duplicate issue.

The issue body MUST contain exactly one compact canonical marker of this form:

`<!-- scm.finding-publication.scope.v1 {JSON} -->`

The JSON object MUST contain exactly destination, fingerprint, working branch,
scenario ID, and scenario SHA-256. The initial issue body MUST additionally
contain exactly one occurrence marker, and every later occurrence MUST appear
in its own issue comment, of this form:

`<!-- scm.finding-publication.occurrence.v1 {JSON} -->`

The occurrence JSON MUST contain exactly `finding_id`, `finding_sha256`, and
`occurrence_payload_sha256`. The last value is SHA-256 over the exact UTF-8
bytes of the sanitized human occurrence payload, normalized to exactly one
trailing newline, excluding the machine marker, its HTML-comment framing, and
any separator blank lines. It therefore is not self-referential. The frozen
rendered-body digest separately covers the complete final issue-body or comment
bytes after marker insertion. Marker JSON uses the public canonical JSON
algorithm without its trailing newline inside the comment; values MUST reject
`--`, `<`, and `>` so the comment cannot terminate early. Titles and human
prose MUST NOT be identity authority.

Discovery MUST terminally paginate every comment on every candidate carrying
the exact scope marker, reject duplicate object IDs/cursors and non-terminating
cursor chains, and directly reread the selected issue plus all its comments
immediately before mutation. Body/comment disagreement, conflicting digests
for one `finding_id`, duplicate scope/occurrence claims, malformed markers,
concurrent reread drift, incomplete pagination, or unreadable comments MUST
fail closed.

#### Scenario: New occurrence updates an open issue
- **WHEN** an open scoped issue has the same stable fingerprint, working branch, and scenario authority but lacks the new `finding_id` marker
- **THEN** action selection appends the new occurrence exactly once

#### Scenario: New occurrence reopens a closed issue
- **WHEN** a closed scoped issue has the same stable fingerprint and scenario authority but lacks the new `finding_id` marker
- **THEN** action selection reopens it and records the occurrence exactly once

#### Scenario: Exact occurrence is a no-op
- **WHEN** the matching issue already contains the exact `finding_id`, canonical finding digest, and occurrence-payload digest
- **THEN** action selection is no-op and creates no duplicate comment or issue

#### Scenario: Finding identity is reused with changed content
- **WHEN** an observed `finding_id` is paired with a canonical finding digest or occurrence-payload digest different from the immutable occurrence already recorded
- **THEN** validation reports an identity conflict and performs no mutation

#### Scenario: Incomplete search fails closed
- **WHEN** the executor cannot prove it searched the complete eligible issue set
- **THEN** it MUST NOT assume absence or create a new issue

#### Scenario: Matching title lacks machine authority
- **WHEN** an issue title or prose appears to match but its versioned JSON markers do not establish the exact scope
- **THEN** the selector ignores the title claim and fails closed if the remaining observation is ambiguous

### Requirement: Recoverable mutation receipts
Before an external mutation, the executor MUST persist an owner-only operation
journal under the current run directory. Every traversed run/operation
directory MUST be owned by the current user, mode 0700, non-symlink, and a real
directory. Journal and lock files MUST be owner-owned, regular, non-symlink,
single-link files with mode 0600. Initial journal creation MUST use
create-exclusive/no-follow semantics, then fsync the file and its parent.

Under the scope lock, the journal MUST move by canonical prior-digest
compare-and-swap through `planned`, per-step `attempted`, per-step
`observed_applied`/`observed_absent`/`ambiguous`, and terminal `succeeded`,
`no_op`, or `outcome_unknown` states. A monotonic update MUST write a
same-directory create-exclusive 0600 temporary file, fsync it, atomically
replace the prior journal, and fsync the parent. The complete frozen action,
before-observation digest, attempt identity, and all per-step states remain in
every revision. Changed bytes at an existing operation/attempt identity,
symlinks, unsafe modes/owners/links, nonmonotonic transitions, or a stale prior
digest MUST fail closed.

The executor MUST durably set the relevant step to `attempted` before its
external write and persist its observation before the next step. A process
that remains alive MAY persist `outcome_unknown` after an ambiguous call. If it
is interrupted, the next opener MUST interpret any `attempted` step without a
conclusive observation as `outcome_unknown`; the interrupted process is not
assumed to have written that state.

A terminal success or no-op receipt MUST bind the issue number and URL,
selected action, `finding_id` marker, rendered body digest, authorization
digest, and before/after observations. Reconciliation MUST repeat complete
read-only ref/GitHub observation. If it proves an attempted effect already
exists, the journal marks that step applied and MAY continue only a never-
attempted next step under unchanged authority and the same valid private lease.
If it proves the attempted effect absent, a new attempt still requires an
explicit private retry-authorization digest. Ambiguous, conflicting, or
incomplete state remains `outcome_unknown` and permits no write.

For a closed matching issue, the executor MUST publish and verify the
idempotent occurrence comment before requesting reopen. A reopen without the
required occurrence update MUST NOT be reported as successful publication.

#### Scenario: Mutation succeeds
- **WHEN** the observed post-mutation issue state exactly matches the frozen action after a create, update, reopen, or no-op
- **THEN** a terminal receipt records the verified action and before/after state

#### Scenario: Reopen comment fails
- **WHEN** recording the occurrence on a closed issue fails or is ambiguous
- **THEN** the receipt is `outcome_unknown` and cannot satisfy publication success

#### Scenario: Comment succeeds and reopen is ambiguous
- **WHEN** the exact occurrence comment is verified but the later reopen call has an unknown outcome
- **THEN** the journal records the completed comment step and `outcome_unknown`, and reconciliation never repeats that comment

#### Scenario: Retry reconciles first
- **WHEN** an earlier intent has no conclusive terminal receipt
- **THEN** the executor performs complete read-only reconciliation, records a proven effect, continues only a never-attempted next step, or requires explicit private retry authorization for a proven-absent attempted effect

#### Scenario: Process dies after attempted persistence
- **WHEN** recovery opens a valid journal whose current step is `attempted` with no conclusive observation
- **THEN** recovery derives `outcome_unknown` before any remote write and does not assume the interrupted process recorded the result

### Requirement: Guarded draft fix pull requests
Proposal-only fix packets MUST remain a valid fallback that mutates no branch or
GitHub state. Actual draft-PR opening MUST require a separately authorized,
reviewed fix branch named `fix/<fingerprint>[-suffix]`, plus the verified
terminal issue-publication receipt for this exact finding occurrence. The fix
head MUST not be a default/upstream or working branch and its base MUST be
exactly the applicable working branch. Before action selection, the private
executor MUST first review/authorize the branch and guarded-push exactly that
one ref, producing a private push receipt. Public post-push action selection
MUST then prove the head exists remotely at its pinned SHA, the remote working
base exists at its pinned SHA, the base is an ancestor of the head, and the
reviewed diff is nonempty. Public SCM code validates those observations but
MUST NOT create or push the fix branch.

The frozen action MUST bind base/head names and SHAs, issue reference, reviewed
commit set, validation summary, tree/diff digest, and private authorization.
The PR MUST be draft, MUST use `Refs` rather than an auto-closing keyword, MUST
NOT auto-merge, close, retarget, or mutate the issue, and MUST NOT be a
harness-to-`dev` or private-branch-to-`main` promotion. Existing pull requests
MUST be completely paginated, directly reread before mutation, and selected by
exact head/base/SHA plus one compact canonical marker:

`<!-- scm.finding-publication.fix-pr.v1 {JSON} -->`

The JSON MUST contain exactly finding ID/SHA, issue number, base branch/SHA,
head branch/SHA, and tree/diff digest. The same marker character restrictions
apply. Title matching MUST NOT be authoritative. Only one exact open draft PR
with the matching marker, head/base names and SHAs, and diff digest may select
no-op. A matching marker on a closed, merged, converted-to-ready, or otherwise
conflicting PR MUST fail closed for operator disposition; the executor MUST NOT
reopen, convert, retarget, mutate, or create a duplicate PR.

#### Scenario: Proposal fallback is emitted
- **WHEN** no authorized fix branch or live PR authority exists
- **THEN** the harness emits a validated proposal-only packet and performs no branch or GitHub mutation

#### Scenario: Authorized draft fix PR opens
- **WHEN** a reviewed remote `fix/<fingerprint>[-suffix]` head, exact remote working-branch base, ancestor relation, nonempty commit/diff set, validation, issue reference, and private authority all match the frozen action
- **THEN** the executor may open one draft PR targeting the working branch

#### Scenario: Exact open draft is a no-op
- **WHEN** complete observation finds one open draft PR whose marker, head/base names and SHAs, and reviewed diff digest exactly match the frozen action
- **THEN** action selection is no-op and does not mutate or duplicate the PR

#### Scenario: Exact marker is on a terminal or ready PR
- **WHEN** the exact fix-PR marker is found on a closed, merged, converted-to-ready, or otherwise conflicting PR
- **THEN** validation fails closed for operator disposition and performs no PR mutation

#### Scenario: Promotion or unsafe branch is rejected
- **WHEN** a PR targets a default/upstream branch, uses the working branch as its head, proposes harness-to-`dev` promotion, contains an unreviewed commit/diff, requests a non-draft PR, or uses an auto-closing issue reference
- **THEN** validation fails before PR mutation

#### Scenario: Public planner is asked to create a fix ref
- **WHEN** an action lacks a pre-existing remote fix head at the pinned SHA
- **THEN** public validation rejects the draft-PR action and leaves branch creation/push to separately authorized private infrastructure

### Requirement: Truthful finding lifecycle
Lifecycle MUST be an idempotent projection from the following exact event
sources:

| State/event | Required authority |
| --- | --- |
| `detected` | validated immutable finding v2 |
| `issue_ready` | the same finding is `ready_to_file` with cleanup and baseline-equivalence proof |
| `issue_published` | verified terminal create/update/reopen/no-op issue receipt |
| `fix_proposed` | validated proposal-only packet bound to the issue receipt; no branch/PR identity |
| `fix_in_progress` | verified private guarded-push or adoption receipt for a reviewed nonempty fix diff rooted at the working ref |
| `draft_pr_open` | verified public draft-PR receipt plus the exact private fix-head receipt |
| `fixed_unverified` | verified merge/adoption receipt proving the reviewed fix commit/diff is contained in a new authorized working ref |
| `verified` | later qualifying scenario/result on a ref containing that fix proves the normalized defect absent and cleanup complete |
| `closed` | prior `verified` plus direct read-only proof that GitHub now reports the issue closed |

`fix_proposed` is optional: a separately reviewed fix branch MAY move from
`issue_published` to `fix_in_progress` without a proposal packet. No other
claimed fact may be skipped or synthesized by a free-form transition.
Operation IDs and receipt digests MUST make projection idempotent. A proposal,
issue, branch, PR, or merge MUST never by itself close or verify the finding,
and campaign automation MUST NOT auto-close the issue.

#### Scenario: Proposal does not claim active work
- **WHEN** the harness generates only a proposal packet
- **THEN** lifecycle records `fix_proposed` and no branch or PR identity

#### Scenario: Draft PR is recorded separately
- **WHEN** an authorized fix branch exists and its draft PR opens
- **THEN** lifecycle projects `fix_in_progress` from the private fix-head receipt and `draft_pr_open` from the verified PR receipt while the issue remains open

#### Scenario: Verification controls closure
- **WHEN** a fix is adopted but no qualifying rerun verifies the original finding
- **THEN** the lifecycle cannot advance from `fixed_unverified` to `verified` or `closed`

### Requirement: Dry-run parity and redaction
Dry-run and live publication MUST execute the same schema, pinned-authority,
readiness, redaction, complete-search, deduplication, lifecycle, and
action-selection validation. Dry-run MUST stop only before the external
mutation and MUST emit the action that live mode would attempt from the same
observed state. Consequently, dry-run MUST perform the same read-only remote
ref and completely paginated GitHub observations as live mode. A separate
offline packet-preview command MAY render and validate frozen bytes, but MUST
label its output `preview_only` and MUST NOT claim which live action would be
selected. Dry-run MUST NOT create an operation journal, append a lifecycle
event, mutate a local/remote ref, or claim a distributed write lease. No
credential, private evidence content, private identifier, or executor-local
path MAY enter a public action or receipt.

#### Scenario: Dry-run selects the live action
- **WHEN** dry-run and live mode receive identical frozen authority and read-only GitHub observations
- **THEN** they select byte-equivalent publication actions and dry-run stops before mutation

#### Scenario: Sensitive action is rejected in both modes
- **WHEN** an action or receipt contains a credential, private evidence, private identifier, or executor-local path
- **THEN** dry-run and live validation both fail before output or mutation

#### Scenario: Offline preview has no remote observation
- **WHEN** the operator renders a packet without current remote refs and complete GitHub observations
- **THEN** output is explicitly preview-only and cannot be used as a dry-run or live mutation action
