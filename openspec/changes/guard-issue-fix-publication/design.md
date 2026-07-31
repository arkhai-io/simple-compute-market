## Context

See `proposal.md` for motivation. The current issue-discovery implementation
mixes four concerns in one path:

1. validating and rendering a sanitized finding;
2. observing GitHub and selecting create/update/reopen behavior;
3. performing credentialed GitHub calls; and
4. appending local lifecycle state.

It can generate a proposal-only fix packet, but no public schema validates an
actual draft-PR action or receipt. Issue deduplication searches a bounded result
set, `--force` bypasses readiness, repeated occurrences can duplicate comments,
and a process interruption between reopen/comment/local receipt can leave
external truth ahead of local lifecycle truth.

This change consumes finding v2 from
`define-agent-driven-vm-capacity-contracts`. It cannot implement against
finding v1 because upstream/reconciliation authority, evidence hashes, and the
SCM-owned fingerprint are part of every publication idempotency key.
There is no v1-to-v2 live adapter: v1 remains historical at its pinned ref.

The implementation dependency was discharged at public commit
`5ece6f908605f58d7b1143c37316ef4aa9845508`. That immutable commit is the
consumed finding-v2 schema, fingerprint, and g1-v2 contract authority for this
change. Later guarded-publication commits may advance the working branch, but
they do not retarget the consumed finding contract or its scenario/profile
hashes.

## Goals / Non-Goals

**Goals:**

- Make action selection a pure, deterministic, fully validated public
  operation over frozen authority and complete read-only observations.
- Make every credentialed mutation recoverable from a create-once intent and
  verifiable post-state.
- Preserve automatic issue create/update/reopen behavior without duplicate
  occurrence publication.
- Add a safely constrained actual draft fix-PR path while retaining
  proposal-only fallback.
- Keep cleanup and upstream promotion outside publication authority.

**Non-Goals:**

- General-purpose GitHub automation, arbitrary issue editing, non-draft PRs,
  review, merge, or release management.
- Campaign integration PRs to `dev`/`main`.
- Storing GitHub credentials or distributed generation state in public
  artifacts.
- Live canary mutation during implementation; live proof remains a later
  private qualification stage.

## Decisions

### Split observation, action selection, mutation, and reconciliation

The public package defines closed models and validators for:

- publication authority;
- complete issue/PR observations;
- deterministic issue and draft-PR actions;
- mutation intents;
- terminal/no-op/outcome-unknown receipts; and
- lifecycle events.

Action selection accepts only validated values and performs no external call.
A credentialed adapter may live behind the CLI for local compatibility, but its
inputs/outputs must cross these pure models. Private infrastructure invokes the
adapter under the distributed generation and remains the owner of credentials
and live authority.

After mutation, the adapter performs a fresh read and asks the public validator
whether the frozen action is now satisfied. It does not declare success from
the command exit status alone.

**Rejected alternative:** continue letting the GitHub subprocess both decide
and mutate. That makes dry-run parity, partial-failure recovery, and independent
post-validation untestable.

### Bind actions to v2 finding and remote authority

Publication authority contains the finding digest, stable fingerprint,
immutable `finding_id`, canonical destination, remote working branch/SHA,
pinned upstream branch/SHA, reconciliation epoch, both candidate rendered
digests (`issue_body_sha256` and `occurrence_comment_sha256`), requested
operation family, and a private authorization digest. A selected issue action
binds its `rendered_body_sha256` to the applicable frozen candidate digest.
“PR base” is reserved for the working branch targeted by a draft PR; issue
authority calls these values working and upstream refs.

The public validator knows only the digest and allowed branch policy. The
private executor verifies the underlying generation/proofs immediately before
mutation. `arkhai-io/simple-compute-market` actions map
`feat/issue-discovery-harness` to upstream `dev`;
`arkhai-io/compute-market-internal-infra` actions map
`tools/agent-orchestration-scratch` to upstream `main`, and the pinned working
commit must contain the pinned upstream commit. Every command names the
canonical repository and ignores ambient defaults. A public operation locks
the canonical destination/scope/operation-family key; live private execution
holds one distributed generation/single-writer lease continuously from
observation through verified post-read. Lease loss after an attempted step is
an unknown outcome.

The current remote working tip must remain byte-exact to the frozen working
ref. The current remote upstream tip is observed separately from the finding's
pinned upstream ref. Upstream movement after the frozen series began is normal:
the Git observation records both refs plus a derived drift bit, while action
selection continues to require that the frozen working ref contains the pinned
upstream ref. It does not silently retarget or reject the frozen series merely
because `dev` or `main` advanced. A live executor compares its before/after
remote-upstream observations and fails closed on movement during one operation.

Remote default authority is a third observation, not an alias for upstream:
the reader requires one symbolic `HEAD` and its exact commit. SCM therefore
records default `main` separately from upstream `dev`; private infrastructure
records both names as `main` and requires their independently read commits to
agree. Neither default nor upstream may become the working branch.

All local Git reads run with a sealed environment that disables system/global
configuration, replacement objects, fsmonitor, untracked-cache shortcuts,
hooks, optional locks, paging, and prompting while fixing file-mode, case, and
symlink interpretation. Each supplied root is converted to a lexical absolute
path without resolving its components; it must then equal its strict canonical
resolution, so final/ancestor symlinks and `..` aliases fail closed. The exact
Git roots reject graft files, replacement refs, URL rewrites, hidden index
flags, dirty/nonignored-untracked/submodule state, and noncanonical origins.
They also enumerate ignored files and reject every ignored artifact under the
tool's source/config/schema roots plus source-like, importable Python-archive, or
executable artifacts elsewhere under `tools/issue-discovery`. The repo-local
`.venv` is the sole explicit exclusion: it is external executor/toolchain
authority, not Git policy authority, and private live execution must supply it
as a separately sealed environment. Configured SSH origins may establish local
repository identity, but remote reads discard those bytes and use only a
constructed `https://github.com/<owner>/<repo>.git`; explicit ports, userinfo,
and local origins are invalid. Remote reads execute outside destination-local
repository config. Private infrastructure may inject a credentialed read-only
transport for that exact canonical URL, but credential material cannot cross
into an observation or action.

When the destination is private, its checkout is not the checkout supplying
SCM schemas, redaction, and publication policy. The reader therefore observes
that SCM policy checkout separately: it must be a clean exact Git root on
`feat/issue-discovery-harness`, its exact HEAD must contain the frozen
`scm_contract_ref`, and its branch, HEAD, cleanliness, and containment proof
are hashed into the Git observation. The selected action binds that entire
observation digest.

The Git observation also binds the canonical SHA-256 of the complete validated
preview, plus the exact nullable inbound-merge ref and its containment result.
The selector requires that preview digest to match before field-level checks,
so a valid Git token cannot be reused with a different preview when a future
authority field is added or accidentally omitted from a comparison.

**Rejected alternative:** bind only local HEAD and destination. A stale remote
base or changed upstream context would let a locally valid packet mutate the
wrong branch epoch.

### Use stable defect, scope, and occurrence markers

Rendered issues use three non-secret machine markers:

- stable SCM-derived defect fingerprint;
- scope digest derived from destination, working branch, canonical scenario ID
  and hash, and stable fingerprint; and
- occurrence marker derived from immutable `finding_id`, canonical finding
  digest, and the sanitized human occurrence payload digest.

The issue identity key is `(destination, stable fingerprint, scope digest)`.
Working SHA and time are occurrence data, so a new commit on the same working
branch updates the existing issue. A different destination or canonical
scenario authority receives a different scope and does not deduplicate.

The occurrence-payload digest covers exact sanitized human payload bytes with
one trailing newline, excluding the marker and separator framing, so it is not
self-referential. The two frozen candidate rendered-body digests cover exact
final issue-body and occurrence-comment bytes after marker insertion. They are
also non-self-referential because the machine markers deliberately omit both
rendered digest fields. The exact occurrence marker is the idempotency key for
comments/updates only when finding and payload digests also match; a reused ID
with either digest changed is an identity conflict. Scope JSON lives in the
initial issue-body marker; the initial occurrence is also in that body, and
later occurrences each use one marked comment. Draft PRs carry their own exact
base/head/SHA/diff marker. The normative spec fixes the namespaces, fields,
canonical encoding, and comment-safety rules; titles and prose are never
identity authority.

The entire case-sensitive `<!-- scm.finding-publication.` namespace is
reserved. Sanitized human payloads containing that prefix anywhere are
rejected before rendering, and the renderer parses its own output back to
exactly one scope plus one initial occurrence (or exactly one comment
occurrence) before it can mint a preview.

**Rejected alternative:** include observed SHA/run/time in issue identity. That
creates a duplicate issue for every reproduction instead of maintaining one
defect record.

### Require a complete fail-closed GitHub observation

The credentialed reader paginates through every eligible open/closed issue,
every comment of every scoped candidate, and every relevant PR. Cursor chains
must terminate without repeated cursors or object IDs. The public observation
schema records query authority, page/total information, and content digests.
The selected object, comments, and refs are directly reread immediately before
mutation. Incomplete, concurrent-drifted, truncated, unreadable,
malformed/conflicting-marker, ambiguous, or duplicate matches fail closed.

For PRs, the reader verifies both branch refs and any existing head/base match
before selecting open/no-op. Only one exact open draft can be a no-op. An exact
marker on a closed, merged, converted-to-ready, or otherwise conflicting PR is
a fail-closed operator conflict; automation does not reopen, convert, retarget,
or duplicate it. Search limits are never interpreted as proof of absence.

**Rejected alternative:** increase a fixed `--limit`. Any fixed value silently
reintroduces the same correctness bug when the repository grows.

### Persist intent before mutation and reconcile ambiguous outcomes

A create-once owner-only operation journal is atomically written under the
current run directory before the first mutating call. Directory/file
owner/mode/type/link checks, no-follow/create-exclusive creation, file and
parent fsync, and same-directory atomic replacement are normative. Under the
scope lock, canonical prior-digest compare-and-swap permits only the exact
`planned -> attempted -> observed_* -> terminal` state machine while retaining
the full action, authority, attempt, and prior observations in every revision.
An interrupted `attempted` state is interpreted as unknown on recovery; the
dead process is not expected to write its own outcome.

Issue create is one external operation followed by read verification. For a
closed matching issue with a new occurrence, the adapter records the occurrence
comment before requesting reopen. Any timeout,
non-parseable response, process interruption, or partial state yields
`outcome_unknown`.

A fresh selection for an exact occurrence is a no-op even if the issue is now
closed. The selector cannot safely infer whether a human closed an already
terminal occurrence or a prior operation stopped after commenting. The
mandatory journal makes those cases distinguishable: recovery of a persisted
`comment_then_reopen` action may verify its attempted comment and continue its
never-attempted reopen step, while missing or corrupt intent fails closed
instead of synthesizing a reopen from GitHub state alone.

A recovery first repeats complete ref/GitHub reads:

- if an attempted effect exists exactly, it marks it applied and may continue
  only a never-attempted next step under unchanged authority/lease;
- if the attempted effect is conclusively absent, another attempt requires an
  explicit private retry-authorization digest; and
- if state is partial, ambiguous, incomplete, or authority changed, it remains
  outcome-unknown and allows no write.

**Rejected alternative:** rerun the mutating command after a nonzero exit. The
remote may have committed the first request despite the local failure.

### Make readiness and dry-run non-bypassable

The guarded capacity-publication path accepts only finding-v2
`ready_to_file`. It exposes no `--force` flag. Any legacy non-capacity command
that retains a force option is a separate interface and cannot accept a
capacity publication packet.

Dry-run constructs the same remote-ref and completely paginated GitHub
observation and passes through the same action selector and validators. Its
sole difference is that it serializes the selected action instead of handing
it to the mutating adapter. Offline packet preview is a different command and
is labeled preview-only because it cannot claim a live action. Rendering an
arbitrary mapping produces only this non-capability value. The validated
preview required by Git observation and action selection is minted only after
owner-authenticated replay of the immutable finding-v2 ingest artifacts.
Neither dry-run nor preview creates a journal/lifecycle event or claims a
distributed write lease.

**Rejected alternative:** skip remote/ref/dedup checks in dry-run. That makes
the preview materially different from the action the campaign later performs.

### Treat fix proposals and actual draft PRs as different actions

A proposal packet contains suggested branch/base, issue reference, validation
expectations, and a patch plan but proves no branch or work exists. It advances
the lifecycle only to `fix_proposed`.

An actual draft-PR action requires:

- a `fix/<fingerprint>[-suffix]` child branch;
- an existing remote reviewed head SHA distinct from working/default/upstream
  refs;
- the applicable remote working branch and current pinned base SHA;
- proof that base is an ancestor of head and the reviewed diff is nonempty;
- the reviewed commit set and diff digest;
- validation evidence;
- a non-closing `Refs #...` issue link; and
- private authorization for guarded one-ref push and PR mutation.

The public validator validates already-observed remote branch authority and the
receipt after GitHub observation. Public SCM never creates or pushes the
branch; private infra performs that separately authorized guarded one-ref push
before action selection and then performs credentialed draft creation. The
action cannot represent a harness-to-`dev` or private-to-`main` promotion, and
later automation cannot retarget, merge, or close it.

**Rejected alternative:** let the proposal packet trigger lifecycle
`fix_in_progress` or PR creation. A suggestion is not reviewed code or live
work.

### Derive lifecycle from verified external facts

Lifecycle is a pure, monotonic projection from the exact event-source table in
the normative spec. Finding/cleanup, terminal issue receipt, proposal packet,
private guarded fix-head/adoption receipt, terminal draft-PR receipt,
merge/adoption containment receipt, later qualifying result, and direct closed
issue observation each authorize only their named fact. `fix_proposed` is the
one optional intermediate: a reviewed fix head can enter `fix_in_progress`
without a prior proposal. No other fact can be skipped or synthesized, and no
issue/PR text uses auto-closing keywords.

Local lifecycle append occurs after the corresponding terminal receipt. If
local append fails, replay derives the missing event from the immutable receipt
rather than repeating external mutation. Operation ID plus receipt digest makes
that projection idempotent.

### Keep publication privacy closed by construction

Action and receipt schemas allow only public repository/branch identities,
logical scenario/finding authority, content hashes, GitHub public issue/PR
identifiers, and sanitized text. They reject credentials, private evidence,
cloud/host/wallet/GPU identities, private endpoints, and executor-local paths.
Redaction runs before body hashing and is rechecked during action and receipt
validation.

## Risks / Trade-offs

- **[More reads and pagination increase publication latency]** → Publication is
  outside the measured interval and must prefer correctness; cache only within
  one frozen observation.
- **[GitHub search/index lag can hide a just-created issue]** → Verify by the
  returned object identity and direct read when available; otherwise emit
  `outcome_unknown` rather than create again.
- **[Multi-step reopen/update can remain partially complete]** → Persist intent,
  make occurrence markers idempotent, and reconcile direct issue state before
  retry.
- **[Strict branch rules can reject legitimate developer workflows]** → The
  campaign path remains intentionally narrow; developers can use ordinary
  workflows outside campaign credentials.
- **[Public schemas expose repository/issue metadata]** → Those are already
  public for SCM; private-repository receipts remain private infra evidence and
  are sanitized before any public export.
- **[Dependency on finding v2 delays implementation]** → Planning remains
  apply-ready, but tasks explicitly block behavior changes until the first
  change's final schema is committed and pushed.

## Migration Plan

1. Land this apply-ready plan while leaving current runtime behavior unchanged.
2. Complete and archive `define-agent-driven-vm-capacity-contracts`; pin its
   final finding-v2 schema and fingerprint behavior.
3. Add public action/observation/intent/receipt schemas and pure validators,
   then place the existing issue CLI behind them.
4. Implement complete occurrence-idempotent issue behavior and outcome
   reconciliation with fake GitHub/local remote tests.
5. Implement proposal and guarded actual-draft PR actions, then correct
   lifecycle transitions.
6. Promote permanent specs/architecture and operational docs, synchronize,
   archive, and let private infra adopt the final public SHA.

Rollback before private adoption reverts the bounded public commits and leaves
proposal-only behavior. After a private runner pins the new publication
contract, rollback abandons that run epoch and requires a new exact public/
private ref pair; it never falls back mid-run to force-enabled publication.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Frozen publication authority and public/private mutation split | `openspec/specs/finding-publication/spec.md` and `architecture.md` — authority model |
| Stable defect/scope/occurrence identity and complete observation | `openspec/specs/finding-publication/spec.md` and `architecture.md` — idempotency model |
| Intent-before-mutation and outcome reconciliation | `openspec/specs/finding-publication/spec.md` and `architecture.md` — recovery model |
| Guarded branch-scoped issue publication | `openspec/specs/finding-publication/spec.md` — issue behavior |
| Proposal fallback and actual draft fix PR constraints | `openspec/specs/finding-publication/spec.md` — fix publication |
| Truthful lifecycle and dry-run/live parity | `openspec/specs/finding-publication/spec.md` — lifecycle and validation |
| Repository-wide public-policy/private-execution boundary | `docs/development/ARCHITECTURE.md` — testing strategy |
| Capability ownership and navigation | `openspec/specs/README.md` |
| Operator commands and limitations | `docs/development/ISSUE_DISCOVERY.md` and `tools/issue-discovery/README.md` |
