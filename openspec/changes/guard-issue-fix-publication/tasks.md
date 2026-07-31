## 1. Freeze publication models after finding v2

- [x] 1.1 Block implementation until `define-agent-driven-vm-capacity-contracts` has committed, validated, and pushed the final finding-v2 schema and SCM-owned fingerprint derivation; record the exact consumed public commit (`5ece6f908605f58d7b1143c37316ef4aa9845508`).
- [ ] 1.2 Add closed schemas under `tools/issue-discovery/schemas/` for publication authority, complete issue/comment/PR observations, issue actions, proposal-only fix packets, actual draft-PR actions, owner-only operation journals, terminal/no-op/outcome-unknown receipts, and truthful lifecycle events.
- [ ] 1.3 Make every model bind the exact canonical repository, allowed working/upstream branches and SHAs, ancestry, reconciliation epoch, finding-v2 digest, stable fingerprint, immutable `finding_id`, scenario scope, rendered-body digest, action kind, and private authorization digest; reserve PR base/head fields for draft actions and reject finding v1, credentials, private evidence/identifiers, and executor-local paths.
- [ ] 1.4 Add positive fixtures plus negative schema tests for missing authority, extra keys, default/upstream branch selection, unsafe fix refs, auto-closing text, non-draft PRs, changed digests, and secret/private fields.

## 2. Separate observation and deterministic action selection

- [ ] 2.1 Refactor `tools/issue-discovery/src/issue_discovery/issues.py` so finding rendering, complete GitHub observations, pure action selection, credentialed execution, post-state validation, and lifecycle append are distinct seams.
- [ ] 2.2 Implement the exact canonical `scm.finding-publication.scope.v1`, `.occurrence.v1`, and `.fix-pr.v1` HTML-comment JSON markers, field sets, character restrictions, and body/comment placement; define `occurrence_payload_sha256` over the normalized human payload excluding marker/framing and separately freeze the final rendered bytes; keep working SHA/run/time in occurrence authority and never trust titles/prose.
- [ ] 2.3 Implement terminal cursor pagination for all open/closed issues, every comment on every scoped candidate, and every relevant PR; reject repeated cursors/object IDs, malformed/conflicting markers, reused finding IDs with changed digests, and ambiguous matches, then directly reread selected objects/comments/refs before mutation.
- [ ] 2.4 Make dry-run and live mode consume the same current remote-ref and complete GitHub observations and emit the same deterministic action, with dry-run stopping only before credentialed mutation; keep offline packet preview separately labeled and incapable of selecting a live action.
- [x] 2.5 Add fake-observation tests for create, update, reopen, fresh exact-occurrence no-op (open or closed) only when finding/payload digests both match, reused-ID digest conflict, new-SHA same issue, different destination/scenario scope, incomplete search, ambiguous matches, stale local/remote refs, and default-branch denial.

## 3. Make issue publication occurrence-idempotent and recoverable

- [x] 3.1 Remove force bypass and require finding-v2 `ready_to_file`, exact canonical destination, clean working checkout, current remote working authority, pinned upstream context/ancestry, non-promotion issue text, and explicit repository arguments despite ambient defaults.
- [ ] 3.2 Implement the exact owner-only journal state machine: 0700 owned non-symlink directories; 0600 owned regular single-link lock/journal files; no-follow/create-exclusive creation; file/parent fsync; prior-digest CAS; same-directory atomic monotonic replacement; and the canonical destination/scope/operation-family lock key.
- [ ] 3.3 Implement create/update/reopen/no-op execution so the exact `finding_id` plus canonical finding and occurrence-payload digests are recorded once and changed content under a reused ID fails closed; for a closed issue, verify the idempotent occurrence comment before requesting reopen, and require final state to be occurrence-complete and open.
- [ ] 3.4 Read back direct GitHub state after mutation and emit a terminal success/no-op receipt only when it exactly satisfies the frozen action.
- [ ] 3.5 Persist `outcome_unknown` when possible after ambiguity and infer it on startup from attempted-without-observation journals; reconciliation may accept an exact observed effect and continue only a never-attempted step, while a proven-absent attempted effect requires a private retry-authorization digest and ambiguous state remains fenced.
- [ ] 3.6 Require the private generation/single-writer lease across observation, planning, journal, write, and post-read; fail before write on lease loss and mark/infer unknown after attempted-state lease loss.
- [ ] 3.7 Add fake-GitHub/filesystem tests for duplicate retry, lost receipt, every crash boundary, unsafe owner/mode/type/link/symlink/CAS state, comment/reopen partials, ambiguous create, explicit retry authorization, changed authority/lease, successful reconciliation, and fail-closed partial state.

## 4. Validate proposal fallback and actual draft fix PRs

- [ ] 4.1 Correct proposal-only packets so they contain a suggested `fix/<fingerprint>[-suffix]` child branch, exact working-branch base, issue reference, patch/validation plan, and no claim that a branch, commit, or PR exists.
- [ ] 4.2 Add Git authority validation for actual fix branches: exact allowed name, pre-existing remote head at its pinned SHA, remote base equal to the applicable pinned working branch, base-ancestor-of-head proof, nonempty reviewed commit set/diff, clean exact tree, and private guarded one-ref push receipt supplied before public action selection.
- [ ] 4.3 Implement pure draft-PR action selection and receipt validation binding base/head names and SHAs, issue `Refs` reference, reviewed commits, validation summary, diff digest, draft state, and private authorization.
- [ ] 4.4 Keep credentialed fix-branch creation/push and GitHub draft opening behind the private executor seam; public code MUST NOT create or push a ref or grant generation, cleanup, or mutation authority.
- [ ] 4.5 Add temporary local bare-remote and fake-GitHub tests for proposal fallback, valid draft opening, existing exact open draft no-op, exact marker on closed/merged/converted-to-ready PR conflict, wrong base/head SHA, unreviewed commit, changed diff, branch collision, default/upstream target, promotion PR, non-draft request, auto-close keyword, and auto-merge denial.

## 5. Correct lifecycle and CLI parity

- [ ] 5.1 Implement the exact lifecycle event-source table: detected finding, cleanup-ready finding, verified issue receipt, optional proposal, private guarded fix-head/adoption receipt, verified draft receipt, merge/adoption containment receipt, later qualifying verification, and direct closed-issue observation; allow only proposal omission before real fix work.
- [ ] 5.2 Derive replayed lifecycle facts idempotently from operation ID plus immutable receipt digest so a local append failure never repeats external mutation or permits free-form synthesis.
- [ ] 5.3 Update `tools/issue-discovery/src/issue_discovery/cli.py` and `runner.py` with explicit preview, issue-publish dry/live, reconcile, propose-fix, and open-fix-pr typed entry points, preserving proposal-only fallback and removing force from capacity live publication.
- [ ] 5.4 Add CLI/runner tests proving dry-run/live validation parity, exact JSON action/receipt output, correct exit status for no-op/outcome-unknown, and no publication call from cleanup paths.
- [ ] 5.5 Extend redaction/privacy tests so actions, intents, receipts, rendered bodies, and lifecycle events reject credentials, private evidence, private identities, endpoints, and executor-local paths before serialization.

## 6. Promote permanent publication behavior

- [ ] 6.1 Create `openspec/specs/finding-publication/spec.md` with the verified normative contract and `openspec/specs/finding-publication/architecture.md` with the authority, idempotency, observation, intent/recovery, branch/PR, and privacy models.
- [ ] 6.2 Add `finding-publication` to `openspec/specs/README.md`.
- [ ] 6.3 Link the repository-wide public-policy/private-execution relationship from `docs/development/ARCHITECTURE.md#testing-strategy` without duplicating the capability contract.
- [ ] 6.4 Update `docs/development/ISSUE_DISCOVERY.md` and `tools/issue-discovery/README.md` only after behavior passes, documenting exact issue/draft commands, no-force readiness, occurrence markers, outcome reconciliation, proposal fallback, private authority, and non-promotion rules.
- [ ] 6.5 Complete the design-promotion record with final stable headings and verify production code/docs do not depend on or cite `openspec/changes/guard-issue-fix-publication`.

## 7. Validate, synchronize, and archive

- [ ] 7.1 Run focused finding/publication/action/lifecycle/CLI/runner tests and the complete `tools/issue-discovery` package suite.
- [ ] 7.2 Run fake-GitHub recovery and local bare-remote branch/ref tests covering every create/update/reopen/no-op/outcome-unknown and draft-PR negative case.
- [ ] 7.3 Run a capture-only replay that emits redacted issue and proposal/draft actions with an empty live-resource ledger and performs no GitHub or branch mutation.
- [ ] 7.4 Run strict OpenSpec validation for this change and disclose unrelated inherited global validation failures.
- [ ] 7.5 Run staged whitespace, secret/credential signature, artifact-path, symlink/mode, and owner-only personal-host denylist scans; inspect exact staged paths and final diff.
- [ ] 7.6 Synchronize verified behavior into permanent specs, mark only actually completed tasks, archive the change, rerun strict validation, and commit/push bounded outcomes through the guarded one-ref procedure.

## 8. Traditional commit checkpoints

- [x] 8.1 Commit owner-replayed frozen actions, complete paginated observation, hermetic destination/policy-checkout Git authority, separate working/upstream/default refs, dry-run parity, and their tests as `feat(issue-discovery): validate guarded publication actions`.
- [ ] 8.2 Commit versioned markers, owner-only operation journals, comment-before-reopen execution, post-state validation, reconciliation, and fake-GitHub recovery tests as `fix(issue-discovery): make issue publication occurrence-idempotent`.
- [ ] 8.3 Commit proposal truth, private-pre-push/public-post-push remote-head validation, draft-only PR actions, lifecycle projection, and focused tests as `feat(issue-discovery): open guarded draft fix PRs`.
- [ ] 8.4 Commit permanent specs/architecture, operator docs, completed promotion record, archived change, and full-suite evidence as `docs(issue-discovery): promote guarded finding publication`.
- [ ] 8.5 For every checkpoint, stage only exact reviewed paths; use the repository-traditional body sections in this order: `Plain-language summary`, `Architectural summary`, `Change groups`, `Boundary decisions and deferrals`, `Issue tracking` when applicable, `Validation`, and `Result`. Run staged whitespace, secret, artifact-path, symlink/mode, and owner-only host scans plus proportional tests. Then guarded-push only `feat/issue-discovery-harness`, persist the receipt, and prove remote `dev` and private-infra `main`/scratch refs did not move.
