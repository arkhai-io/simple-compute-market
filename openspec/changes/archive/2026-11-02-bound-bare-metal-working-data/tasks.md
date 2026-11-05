# Tasks

Implementation follows design D8's evidence split. Sections 1–2 form the independent helper round and touch no access-role runtime, adapter codec or fulfillment plan. Section 3 waits only for `prove-relay-provisioning` section 9's verified activity-termination implementation; it does not wait for that whole change to close. Section 3 freezes and reviews the integration source before destructive deployed qualification in section 4; section 4 reuses that review unless source changes. The new real-lane observations additionally depend on relay section 12. Independent design review 01 is triaged; its F1 continuity clarification is accepted by the lead under delegated technical authority. The existing task sequence and streamlined cadence are retained for the independent helper handoff; sections 1–2 are implemented and independently reviewed; workflow validation/triage joins remain pending. No deployed implementation is claimed.

Each intermediate section runs its focused suites, comment hygiene and `make check-packaging` before commit. Freeze each round for full local suites (`make test`), independent implementation review and validation of that frozen revision. Reuse unchanged passing evidence instead of rerunning the full suite after every small edit; new code or a relevant unresolved failure requires fresh affected evidence. Record results and unrun prerequisites in the change's handoff/review records. A helper-only round cannot qualify deployed cleanup or close this change.

## 1. Independent identity ledger and test ownership

- [x] 1.1 Add `domains/bare_metal/provisioning/iac/pyproject.toml`, `uv.lock`, `Makefile` and `tests/unit/` / `tests/integration/` as a minimal non-distributable stdlib-helper test project with pytest in dev dependencies and Python selected from the repository declaration. Wire `test-bare-metal-iac` through `domains/Makefile` and root `Makefile` / `make test`; reconcile project discovery in `scripts/uv_project.py` and its tests, and `.github/workflows/tests.yml` only where its derived matrix needs it. Verify the aggregate discovers/runs this project's test target and project-layout, architecture and packaging checks accept its deliberate non-distributable status.
- [x] 1.2 Add `ansible/roles/bare-metal-access/files/tenant_working_data.py` under that IaC project: versioned reserve/clean/remove-home/verify interface, injected host-state boundaries, protected policy/ledger/lock validation, durable UID consumption and idempotent reservation binding (D2–D3). No access-role task, codec or fulfillment plan edits. Verify unit validation/UID-selection cases and integration tests using real temporary ledger files and independent processes: same-reservation retry, competing reservation allocation, failed-create consumption, NSS user/group and consumed UID/GID conflicts, exhaustion, corruption, symlink/hardlink/mode/owner rejection, interrupted replacement and fsync failure. Assert durable state after each failure. For 01-design F1, prove normal calls refuse missing established/corrupt/mismatched history without initializing; preserve the host ledger across simulated service-state restore/redeploy. Do not assert that a structurally valid older ledger detects its own rollback; document that operational quarantine precondition instead.
- [x] 1.3 Specify exact host policy/receipt schema and helper invocation in this change's `design.md`, including all protection checks, finite UID range, ledger lifetime, no implicit account adoption, no recreation of complete reservations and explicit initialization separated from normal calls, and 01-design F1’s host-ledger preservation/self-rollback limit and operator quarantine/recovery boundary. Verify the documented JSON examples parse and pure policy tests reject unknown/unsafe inputs; use invented fixture identities only.
- [x] 1.4 Run `make test-bare-metal-iac`, `make check-comment-hygiene` and `make check-packaging`; record results and keep permanent promotion pending until closeout. Confirm the diff contains no runtime role/adapter activation.

### Section 1 handoff

The new virtual project exercises a stdlib Ansible asset, with real temporary ledger files and independent spawned processes. Host-global NSS is injected; these are unit and library integration tests, not application or deployed evidence. No access-role tasks, codec or fulfillment plan is activated. Existing dynamic lock discovery and non-distributable project handling need no allowlist or CI matrix edit; `domains/Makefile` now reaches this project's tests from the existing bare-metal aggregate.

Initialization exclusively creates the stable lock. A failed initial write requires operator recovery; normal operations never initialize and explicit init cannot recreate a ledger while its established lock remains. Valid older-ledger rollback remains locally undetectable. The exact wire examples and protection rules are recorded in design; permanent promotion remains pending closeout.

Focused evidence: `make test-bare-metal-iac` passed 57 unit/library integration tests; four documented JSON examples parsed separately. `make check-packaging` passed (all lock/environment/Python/layout/architecture checks), using repository Python 3.13; `make check-change CHANGE=bound-bare-metal-working-data` passed including comment hygiene. Later code/test/doc fixes did not change dependency, lock or uv-install inputs; passing packaging evidence is reused. The fresh compliance check found protected-root ancestor overlap, filesystem setup in unit tests and premature native-target references; all were fixed with focused tests. Lead corrections also reconciled actual provider account names, supported explicit roots and direct NSS lookups. No finding was declined. User-authorized cadence uses one independent compliance/implementation review for the frozen round; this completed early compliance report is reused without a second section pass. Full `make test` is deferred to the frozen sections 1–2 round by explicit user instruction. No existing `e2e-tests/` marker exercises this inactive helper. Owed by validation: no additional push-only workflow; the existing tests workflow's bare-metal aggregate runs the default helper suite, while native and deployed qualification remain separate unrun prerequisites.

## 2. Independent bounded filesystem and IPC cleanup

- [x] 2.1 Extend the helper with descriptor-relative no-follow traversal and removal, actual mount-identity checks (bind mounts included), protected policy/receipt matching, complete-candidate preflight and revalidation during removal (D4). Verify integration fixtures for home, shared scratch, symlink escape, foreign descendants, directory replacement, unexpected mount identity, hard links, unreadable objects, missing paths and interrupted cleanup. Assert unrelated entries and link targets survive, and no unchecked recursive deletion reaches an external boundary.
- [x] 2.2 Add independent no-UID-process observation without duplicating section 9’s session/schedule/linger barriers, and numeric UID recovery after account absence; add path-backed and System V IPC enumeration, exact owner-and-creator attribution, recheck before removal, final inventory verification and fail-closed unsupported-interface handling (D5–D6). Verify deterministic integration tests with injected kernel/NSS/process observers for all IPC kinds, mixed owner/creator, disappeared/reused object IDs, lingering activity, partial removals and denied observations; assert no termination command is invoked.
- [x] 2.3 Add completion receipts and retry behavior: reserved-but-never-created, account-absent-but-data-present, complete replay, missing attribution and policy drift (D6). Verify complete is committed only after every covered absence check; consumed UIDs survive all states; failures leave resumable protected history. Update the change's design examples and material promotion mapping to match the actual helper interface.
- [x] 2.4 Add `domains/bare_metal/provisioning/iac/scripts/native_cleanup_gate.sh` and isolated native tests in that project's `tests/integration/`, with a dedicated `test-bare-metal-iac-native` root target. Use the built provisioning image for the shipped helper/Ansible and an explicitly disposable isolated account/IPC environment; mount only owned test assets, never operator account state. Verify real System V and path-backed IPC, NSS/account absence, actual bind-mount refusal and no-follow behavior. Missing prerequisites, no tests or skips fail the dedicated gate; ordinary test invocations report any native omissions explicitly.
- [x] 2.5 Run focused default/native checks, `make check-comment-hygiene` and `make check-packaging`. Freeze this independent round, run `make test`, request independent review and record its dispositions through the repository workflow. Record that this round proves helper behavior only and leaves deployed readiness unqualified.

### Section 2 handoff

The helper now binds cleanup-root device/inode/mount identities durably and validates roots before initialization or normal operations. Shared root-owned sticky roots are distinct from protected state/home ancestors. Descriptor traversal preflights all roots/home and IPC before deleting; removal revalidates identity, contents and actual mount IDs (including same-device binds). Only attributable entries are removed, foreign shared-root entries survive, and foreign descendants block selected directories. Linux observation checks every thread's four UID fields without terminating anything. System V uses exact owner/creator attribution and rechecked full inventory fingerprints before libc removal. Completion independently checks all covered absences and retains consumption; reserved/no-account, partial and complete retries are supported.

Corrections to the provisional interface: provider-compatible safe account names replace a fixture-only prefix; `verify-identity` requires the expected account and private group present; reuse of a completed account name requires reverified old absence and a fresh UID/GID. Ledger `roots` and bounded `observations` fields are documented with exact schemas/examples. No role, codec or fulfillment plan is activated, and permanent promotion remains pending closeout.

Focused evidence: `make test-bare-metal-iac` passed 95 unit/library integration tests, with four native tests explicitly deselected and reported. Default filesystem tests use owned disposable files, actual ownership/mount descriptors and injected NSS/kernel/process boundaries; they do not operate on host accounts or IPC. `make test-bare-metal-iac-native` against an available built provisioning runtime passed all four native library integration tests with zero skips: real NSS account absence, System V shm/sem/msg, POSIX shm/sem/mqueue, exact bind-mount refusal, foreign-child refusal/repaired retry, no-follow and fresh identity after same-name completion. The native cases invoke the actual JSON CLI, including explicit initialization and root enforcement. The native container has private PID/IPC/network, an owned tmpfs, and read-only IaC assets; the current helper is mounted source, so rebuilt-image packaging/role execution remains section 3 evidence. No operator-host account or kernel IPC mutation was run. The image's userdel removes an unused same-name private group automatically; the native fixture accepts verified absence, and still fails unexpected account/group deletion errors.

`make check-packaging` and `make check-change CHANGE=bound-bare-metal-working-data` passed, including comment hygiene; unchanged dependency/uv-install inputs reuse that packaging evidence after later helper/test-only fixes. The single `make test` invocation stopped with exit 2 during Rust compilation because the temporary filesystem filled (ENOSPC), after all preceding suites passed, including the newly wired helper's 95 passes. After reversible recovery of temporary disk space, only Rust was resumed: six tests passed. The exact remaining root targets were then run under uv 0.12.19: E2E unit passed 352 tests; release tooling initially passed 1815 and failed one unchanged clone-removal test because the host Git 2.34.1 rejects `merge-tree --write-tree` (`fatal: unknown rev --write-tree`). The unchanged failed fixture's content was captured, and Git 2.49.0 returned the expected identical merge tree. Only its 58-test clone-management module was rerun and passed; the uncompleted Helm render target passed separately. This is composed full-target coverage with an honestly retained interrupted invocation, not a claim that one unchanged `make test` exited zero. No second full invocation was run.

The original full invocation used available uv 0.8.14. The repository minimum gate was checked explicitly, isolated uv 0.12.19 and Git 2.49.0 were prepared without production changes, and scoped `make lock PROJECTS=domains/bare_metal/provisioning/iac` plus final `make check-packaging` passed under the supported tools. The helper project's canonical lock remained byte-identical, so no dependency-driven test repeat was required. All 18 incidental other-project lock edits were preserved privately and compared before restoration: complete package name/version/source sets and actual Linux/Python 3.13.7 default/dev reachable pin sets matched, and all reachable versions were present in their environments. This supports reuse on the tested platform only; no universal cross-platform equivalence is asserted. The final tree retains only this section's scope. The lead coordinates the single frozen-round independent review/compliance and validation join; no separate section-2 review is added. The continuous review identified a blocking mutation-authority race after final descriptor checks; the lead accepted refusal for foreign-owned ancestors and nonsticky group/other-write masks (including POSIX ACL effective masks), with descriptors retained through deletion. A subsequently found initial double-slash alias bypass in pure policy normalization was also accepted and rejected explicitly, with `//tmp`, `//root` and `//` regressions. Both were fixed within the same round. The reviewer confirmed the mutation-authority correction fully addressed with no remaining source blocker; the accepted alias guard remains included in the same final byte/document check. Final affected suites passed: default 95 passed / four native deselected (9.35s), isolated actual-CLI native four passed / zero skips (9.475s). Helper SHA-256: `b21dbdf219bc8af66e82448c29f90eb0976f48735b57a38e74425b224ac57735`. The full repository run overlaps this correction; it is not described as an exact unchanged frozen revision. Unaffected suite evidence is retained and the final helper/native reruns establish the corrected source behavior. The earlier section-1 compliance findings are fixed and retained as evidence, not repeated. Review dispositions remain pending that join.

No existing `e2e-tests/` marker exercises this inactive helper. Owed by validation: no extra push-only workflow; the existing tests workflow's bare-metal aggregate now reaches this default project. Native evidence is separate from deployed lifecycle qualification. Section 3 remains gated on reviewed/verified relay section 9; sections 3–5 were not started. This round proves helper behavior only and does not qualify access revocation, held-capacity lifecycle behavior or deployed cleanup.

## 3. Integrate reservation-bound grant and reclaim after the termination prerequisite

- [x] 3.1 Gate this section on reviewed/verified `prove-relay-provisioning` section 9 code and relevant validation; inspect its actual activity/absent-account interface and reconcile this change's deltas without editing its completed tasks or duplicating termination. Record the prerequisite evidence and integration assumptions in `design.md`; verify section 9 failure propagation remains intact. Until available, keep this section pending while independent work remains usable.
- [x] 3.2 In `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/codec.py` and `services/bare_metal_fulfillment_plan.py`, carry accepted `capacity_reservation_id` and trusted policy selection from grant through stored parameters into reclaim and helper variables. Snapshot policy before grant for bounded jobs, retain compatibility for existing policies, reject missing/conflicting bounded correlation and buyer-selected targets. Verify `test_bare_metal_codec.py` and `test_bare_metal_fulfillment_plan.py` cover grant/reclaim roundtrip, policy changes, legacy inputs and exact reservation mismatch without a physical effect. Preserve existing username derivation from settlement identity/access references; it is not derived from the SSH key.
- [x] 3.3 Integrate `ansible/roles/bare-metal-access/tasks/main.yml`, `ansible/playbooks/node-access.yaml`, and protected helper/policy installation with the host-preparation entrypoint available after the prerequisite. Select bounded policy explicitly; reserve before account creation, create only the recorded nonprivileged UID/private primary GID pair, and refuse existing unreceipted accounts. After section 9's verified termination invoke clean between quiescence and account removal; delete the account without unchecked home recursion, invoke explicit helper remove-home, remove only the recorded unused private primary group, then verify-complete before success. Verify native execution of the shipped tasks for successful grant/reclaim, helper rejection, partial create, account-absent retry, foreign-home child and no account/group resurrection. Every failed helper or removal must yield a failed play.
- [x] 3.4 Confirm `provisioning/compute/service/Dockerfile` packages the helper/policy assets and root native targets run bare-metal assets without borrowing VM ownership. Extend `provisioning/compute/service/tests/unit/test_bare_metal_ansible_assets.py` only for package/task structure; keep behavioral coverage in bare-metal IaC. Verify syntax/native checks in the built image; all asset paths resolve there and source/image imports remain stdlib-only for the helper.
- [x] 3.5 Extend `provisioning/compute/service/tests/integration/test_bare_metal_leases_api.py` and the existing bare-metal fulfillment/mock integration modules through canonical typed clients to prove correlated grant/reclaim, compensation after failed create, cleanup failure → failed teardown/held capacity, and successful retry → ordinary release. Update adapter mock output only for actual diagnostic fields; facts remain diagnostic. Run `make test-bare-metal`, `make test-provisioning`, both relevant native gates, `make check-comment-hygiene` and `make check-packaging`; record unrun prerequisites.


### Section 3 handoff

The reviewed activity-termination prerequisite is present, including the explicit
`--trusted-uid` interface for protected receipt identities after NSS absence.
The integration retains early buyer-proxy removal and key revocation before that
barrier. `inspect` supplies an existing identity without allocation or ledger
mutation; bounded grants freeze policy and policy ID before host effects, and
reclaim refuses missing/conflicting reservation correlation or legacy adoption.
The codec always emits policy authority, including the legacy default, so
inventory cannot silently activate bounded behavior. Username derivation remains
the existing settlement/access-reference derivation.

The operator-only `bare-metal-working-data` host-preparation role installs the
protected helper/policy and runs one-time initialization only when explicitly
requested. Policy roots and state directories must already exist safely in the
target mount namespace. It refuses policy replacement and ledger reinitialization;
normal grant/reclaim cannot initialize or adopt history. The existing Dockerfile
already copies the entire owned IaC tree, so no new distribution or dependency
was required. Runtime composition, settings documentation and test composition
now supply the trusted policy ID.

A native reproduction found that the inherited `authorized_key` implementation
follows an intermediate tenant `.ssh` symlink despite `follow=false`. Bounded
jobs now use receipt-bound no-follow `install-key`/`revoke-key` operations, with
fixed targets and descriptor-only writes/permissions. They skip pathname-based
key/permission tasks and do not modify an existing receipted account on grant
retry. Legacy key-path behavior is not claimed as corrected. See the design's
bounded SSH key authority rationale and closeout promotion mapping.

Focused evidence: the adapter suite passed 137 unit/library integration tests;
the bare-metal IaC default suite passed 123 unit/library integration tests, with
nine native cases explicitly deselected. Focused provisioning service coverage
passed 38 unit, library integration and application integration tests, including five new typed-client
bounded cases: correlated transient failure/same-job retry/ordinary release,
terminal failure/held capacity, partial-create compensation, and two rejected
buyer authority overrides before dispatch. Existing relay, legacy policy,
migration and release behavior remains covered. The structural asset module's
five tests supplement behavior rather than proving it.

The dedicated bare-metal native gate passed all nine library integration cases,
zero skips, using the actual packaged role/helper and disposable NSS accounts,
files, kernel IPC and process activity. It covers ordinary grant/reclaim, complete
replay, a fresh UID for a second reservation, failed create after private-group
creation, account-absent retry, unsafe-home refusal/repaired retry, explicit init
and refusal to reset/replace state, and home/intermediate/final-key symlink
sentinels. The disposable controller image has no systemd/procps target stack:
systemd/scheduler commands are explicit fixtures, while process adapters observe
real private procfs and send real signals. A fixture aliases the image's Python
to the conventional target interpreter path. Docker's owned `/work` tmpfs remains
noexec; executable boundary fixtures live in the disposable container's own layer.
These are not claims of deployed systemd, host isolation or purchase readiness.
Initial missing callback/interpreter and noexec-fixture failures were diagnosed
and retained rather than counted as passes.

The final provisioning image passed VM native (three cases), family native
(13 cases), and both domains' own/shared-configuration syntax checks with zero
native skips. A single corrected legacy barrier fixture then passed separately,
ensuring its direct command-failure test supplies the policy fact set by the full
role and fails for the intended command rather than an undefined condition.
Bare-metal native host-operation evidence is reused after an adapter-only policy
correction; production Ansible/helper behavior remains unchanged, and final image
imports confirm the corrected policy emission. A later account-absence comment
clarification changes no YAML task semantics. Helper SHA-256:
`c470e93ae1ffc79be77697287f6cd74efb2dca977d6484c357e375525cf7f646`.

`make check-packaging` passed, including lock, project, interpreter, wheelhouse and
architecture checks. `make check-change CHANGE=bound-bare-metal-working-data`
passed before this handoff and is rerun with the final task/index edits. At that
handoff, broad aggregates were still owed at the frozen combined source round;
the later frozen runtime review and validation now passed with the scopes
recorded in section 4.3. Focused evidence remains separately recorded above.
A fresh-context section-check spawn hit the agent thread limit. The lead explicitly
consolidated that check into the one independent frozen-round source review;
no passing fresh review, personal owner reading, prior-round triage completion or
formal round advance is claimed. Source-only completion is recorded as an
orchestrator note, leaving the combined review/validation join with the lead.

Ordinary refusal/recovery qualification must repair the fixture while the actual
executor job still has retry budget. Real runner `AnsibleError("Playbook failed")`
classification is retryable under the default bare-metal codec; terminal failures
remain immutable and hold capacity, with the existing separately audited operator
override boundary. No synthetic terminal-job success or new recovery API was added.
The dedicated `e2e_bare_metal_bounded_cleanup` marker remains unrun. The accepted
physical observations and the frozen runtime review/validation now satisfy the
technical prerequisites recorded in section 4.3; the formal pre-closeout/source
joins remain. Existing `e2e_bare_metal_mock_deal` proves the ordinary mock
journey only. Native helper, deployed cleanup, and pipeline evidence remain
separately scoped. Permanent promotion remains closeout work.

### Whole-change implementation review 02 F1 fix (after archive)

Review 02 F1: the helper's grant operations refused only a `complete`
receipt, so after reclaim's `clean` (state `cleaned`, account possibly already
deleted) a stale or replayed grant could recreate the account and reinstall the
buyer's key while teardown was unproven, against the spec's "New execution
SHALL remain excluded through cleanup". `reserve` on an existing receipt,
`verify-identity` and `install-key` now accept only `reserved`; reclaim's
`inspect`, `revoke-key`, `clean`, `remove-home` and `verify-complete` are
unchanged, as is a grant from `reserved`, which the deployed 4.1–4.2 cycles
ran. A grant arriving after reclaim starts but before `clean` still sees
`reserved`; the activity barrier and the no-UID-process checks of `clean`,
`remove-home` and `verify-complete` keep that interval failing closed. The
permanent spec gained the scenario "A grant arrives after cleanup started"
under the quiescence requirement, and
`openspec/specs/physical-provisioning/architecture.md#bounded-bare-metal-working-data`
states the rule and the per-call lock limit.

Evidence: `make test-bare-metal-iac` (unit and library integration) passed 126
with 10 native cases deselected, including the new library integration case for
each grant operation after `clean` with the account still present, ledger
bytes unchanged, then clean/remove-home/verify-complete retries. `make test`
exited 0. `make check-packaging` and `make check-change` passed. The native gate
`make test-bare-metal-iac-native` ran against the existing local provisioning
image: its four helper cases (mounted fixed source) passed; the role cases,
including the new `test_grant_after_cleanup_started_restores_no_account_or_key`
regression, could not run because that image predates the shipped helper and
rebuilding it was not permitted in the triage session — the native role
regression remains unrun. The fresh-context compliance check found the library
test did not register the account (so it proved the refusal only through its
message), an inaccurate code comment, and an architecture sentence overstating
coverage across the role's multi-step grant; all three were fixed, and an
inline helper invocation was folded into the new native test helper. Nothing
was declined.

## 4. Deployed cleanup qualification of the reviewed integration round

### Accepted Arkhai proof method on this branch

The owner selected Arkhai-only TEST qualification. The alternative method in
`openspec/changes/archive/2026-11-02-qualify-arkhai-real-provisioning/design.md#accepted-method-mapping`
is accepted for the unfinished live observations below. It drives the shipped
buyer CLI and independent typed operator observations, reusing neutral SSH and
bounded-data helpers without importing complete chain-specific pytest drivers.
The named original markers remain available; an unrun marker is never reported
passed. Completed source tasks and original implementation history are preserved.

The accepted Arkhai method completed 4.1–4.2 using the shipped buyer and
independent typed/operator observations. The first ordinary bare-metal GPU rental
was cleaned and independently observed; a fresh-UID successor could not access
predecessor data. Its nonce-scoped foreign descendant caused a real cleanup
refusal, held capacity and automatic notification; fixture-only repair let the
same ordinary job retry once and complete. Final inventory, sentinels and
management remained sound. The literal
`e2e_bare_metal_bounded_cleanup` marker was not run. Frozen runtime review,
CI, E2E, composed local validation and Helm validation passed on the reviewed
candidate; this source revision changes workflow and Markdown only and passed
147 focused tests, packaging/change checks and all 23 CI jobs. Delegated
technical triage now reconciles those exact inputs and scopes under task 4.3;
independent pre-closeout review remains the next phase. No identity ledger reset, force release or policy bypass was
used.


- [x] 4.1 Complete the accepted equivalent normal-cycle observation: the shipped bare-metal buyer completed a real GPU rental and ordinary bounded reclaim; independent operator observations confirmed the tenant session/process/activity, account/home and covered working data/IPC were absent. The successor received a fresh UID and usable access but could not read predecessor data. The literal `e2e_bare_metal_bounded_cleanup` module was not run; raw host evidence and environment identifiers remain private.
- [x] 4.2 Complete the accepted equivalent refusal/retry observation: a nonce-scoped foreign descendant caused actual cleanup refusal, held capacity and automatic notification. Repairing only that fixture allowed the same ordinary job to retry once and complete; sentinels, management and final inventory were verified. This is deployed observation, not helper/mock inference or force-release.
- [x] 4.3 Reconcile the completed frozen-candidate review and validation evidence with the source and deployed observations before pre-closeout: CI's 23 jobs, all three E2E lanes, composed local validation and Helm validation passed with their recorded scopes; the current workflow/Markdown-only revision passed 147 focused tests and packaging/change checks. The deployed 4.1–4.2 observations use the accepted method and are recorded above. Preserve that evidence binding and obtain the remaining formal pre-closeout/source joins per workflow. Resolve accepted findings and rerun affected checks; freeze a new source round if code changes. Do not describe the composed local results as one successful `make test` invocation or treat helper checks as physical evidence. **Done:** the component implementation reviews, current-candidate validation bindings and separate deployed observations are now reconciled by delegated technical triage. Component commits and historical failures remain distinct; the current candidate passed all 23 CI jobs. Independent pre-closeout review remains the required next phase and is not claimed complete by this record.
- [x] 4.4 Before pre-closeout review, fix comments/docstrings to describe current invariants and inspect every added/touched local import, moving it to module level unless a verified reason justifies it. Run real affected suites after moves, comment hygiene and packaging. Complete the classification/promotion map in `design.md`; current-state permanent prose is written in closeout only. **Done:** the independent helper and combined integration reviews found no remaining source blocker; helper imports are module-level, and frozen cleanup implementation inputs are unchanged since review. Current `make check-comment-hygiene` passes. The design promotion record maps D1–D8 to the owning specs, architecture, operator documentation, testing guidance and readiness index. No import move or affected-suite rerun was needed. The implementation evidence join is complete; independent pre-closeout review and closeout remain.

### Section 4 source preparation

Source preparation extends the real bare-metal module supplied by the relay
work. Additional owned modules are
`e2e-tests/tests/e2e/roles/scenarios/bare_metal/working_data_qualification.py`,
`e2e-tests/tests/e2e/roles/scenarios/bare_metal/working_data_probe.py` and
`e2e-tests/tests/unit/test_working_data_qualification.py`. The typed target in
`e2e-tests/src/e2e_harness/real_provisioning_target.py` gains an optional explicit
operator-observation connection, whose key path is local to the harness rather
than the provisioning service. The shared SSH helper remains the sole command
builder and pins the physical host key. The protected installed policy supplies
cleanup roots; the observer does not invoke the cleanup helper as evidence.

Configured qualification runs two complete ordinary lifecycles, retaining the
first observed UID to require a fresh successor. The second introduces one
nonce-scoped foreign-owned fixture child, requires actual retry metadata and
held capacity, then removes only that child before the ordinary job retries.
A dedicated bounded-cleanup marker requires explicit configuration. The shared setup-plan guard in
`e2e-tests/tests/unit/test_scenario_cleanup_order.py` normalizes pytest
parameter labels to the underlying fixture name; a direct regression preserves
its early-finalizer detection. The bare-metal real driver declares the new
seed-observed state flag. Baseline
real-lane execution without it remains a single lifecycle. At the source handoff,
source checks were distinct from deployed qualification. The accepted equivalent
deployed observations now complete 4.1 and 4.2; the literal marker remains unrun.
Frozen runtime review and validation passed, and the delegated implementation
join is recorded in 4.3. The independent pre-closeout review and triage are now recorded; promotion and archive remain this closeout.

### Section 4 source handoff

The source extension adds marker `e2e_bare_metal_bounded_cleanup` to the real
bare-metal module. Invoke `make -C e2e-tests test-module
MODULE=e2e_bare_metal_bounded_cleanup
ACTIVE_PROFILES=local,real-provisioning-target` against an existing controlled
stack, with the external operator configuration selected through
`CONFIG_DIRECTORY` as needed. This command requires explicit
`cleanup_qualification` in the bare-metal target; missing input is an error,
not a baseline pass. The committed example shows only commented deterministic
placeholder metadata and a harness-local key reference. Marketplace identities
and TEST-chain wallet remain independent profile inputs.

Normal qualification and refusal/successor qualification are module-scoped pytest
parameters. Each uses a fresh generated buyer SSH key and fresh deal state; the
UID history spans both. The successor preflight refuses until the first
independent cleanup observation passed, before any successor purchase. It also
requires only its one remaining unused UID/GID pair; the first preflight requires
two. The bare-metal publisher reopens its reconciliation-closed listing through
the ordinary publication stage; no database or host consumption history resets.

Both cycles seed home and selected scratch/path-backed roots, FIFOs, three real
System V IPC families, a detached process, a crontab and an open heartbeat SSH
session. Normal reclaim remains the only cleanup authority. Independent root
observations check NSS/account/private-group/home absence, every covered root,
all four process UID fields, owner/creator IPC attribution, login sessions/user
manager/lingering, cron and at state, plus unchanged inode/content-bound synthetic
operator/service sentinels. The deliberate unsafe child sits inside the selected
tenant-owned scratch directory. Recovery requires its actual foreign-descendant
refusal in the job logs and queued retry metadata, with the lease releasing and
capacity still consumed through the existing site view; only the exact fixture
child is removed before the normal scheduler retries. Exhausted/terminal jobs
are failures and remain held. No policy/ledger reset, helper bypass or force
release occurs. Public buyer admission must remain gated during these failure
drills; an observation failure is not readiness.

Source verification: the focused E2E unit suite passed 496 tests, including
configuration/marker guards, private-key reference refusal, missing predecessor
refusal, retry/capacity gating and real temporary-filesystem/procfs-format/IPC
inventory parsing. A configured `pytest --setup-plan` selected both complete
normal/refusal cycles and preserved recovery-before-hold-release ordering; it
executed no services. The generic setup-plan parser now normalizes pytest's
parameter suffix before resolving a fixture's finalizer; a direct regression
preserves its original early-cleanup check.

A disposable private-container component check used the retained provisioning
image, actual packaged access/cleanup roles and the new observer. It passed real
NSS/account/grant, actual UID-owned files/FIFOs, all three real System V IPC
families, a detached process killed/reaped by reclaim, unsafe-child refusal,
fixture-only repair, ordinary role replay, independent absence and surviving
sentinels. Systemd/loginctl and cron/at command boundaries were explicit standins;
this proves component behavior, not a real scheduler, SSH server, deployed retry
scheduler or hardware qualification. Initial diagnostics correctly refused a
writable fixture ancestor and a container lacking the existing native gate's IPC
removal capability. The corrected container used that gate's protected tmpfs and
private IPC/capability boundary. A later nonmutating UID-count preflight correction
is checked separately against actual protected policy/ledger files rather than
repeating the unchanged destructive component check. Packaging and owned change,
comment-hygiene and privacy checks are recorded before commit. The accepted
cadence leaves one combined source review/full validation with the lead; no extra
broad section review, personal owner reading or formal join is claimed.

At this earlier source handoff, tasks 4.1–4.3 were unchecked; the mock and
component evidence alone did not qualify a physical target. Since then, the
accepted method completed deployed observations 4.1–4.2, while the dedicated
marker remains unrun; subsequent delegated source/validation reconciliation is
recorded in 4.3, with independent pre-closeout review still required.
Owed by validation: `tests.yml`'s `test · test-e2e-unit` job must run the harness
unit suite; pipeline and physical evidence remain separately scoped. Permanent
policy/qualification promotion remains closeout work.

### Shared lane lease-correlation correction

The combined reviewer identified an existing real bare-metal stage reading
`provisioning_job_id` from `DealLease.refresh()`, whose normalized contract instead
returns `create_job_id`. The lead accepted correction to that canonical key;
the provider-job correlation assertion remains required. A regression constructs
the actual typed family `LeaseView`, passes it through the real `DealLease`
normalization, then invokes the real stage: matching grant identity passes and
another grant identity fails. No API or normalization change is made. The same continuous review found that the two configured cycles shared the
module SSH session but reused the unrelated-key filename, which the helper
correctly refuses through exclusive creation. The unrelated-key stage now uses
the cycle in its key name. A regression invokes the actual stage twice with one
actual `SshSession` and a controlled refusing SSH process, verifies distinct keys,
and confirms duplicate-name creation still fails. No SSH key protection is
weakened. These are separate source corrections before the frozen combined
candidate, not deployed qualification or formal review advancement.

## 5. Closeout (eleven parts, in this order)

**Closeout record (2026-11-02).** 5.1 `make check-comment-hygiene` passed; reviewed comments state current invariants. 5.2 The independent source review found no new function-local imports. 5.3 D1–D8 and the accepted continuity limitation are placed by documentation ownership; deployed claims remain bounded to observed policy and lifecycle behavior. 5.4 Stale source-handoff status was corrected; detailed test history and valid-rollback limitations remain in tasks/design rather than being erased. 5.5 Goal 1 has no additional bare-metal cleanup gap row to remove; payment qualification now records the deployed observations and retains API-credit, exhausted-retry, and shared-listing-pause limits. 5.6 The Reach-hosts row is in closeout; graph and dependents remain unchanged until archive cleanup. `make check-change-index` passed. 5.7 The b253 current-source record reports packaging and all five architecture checks passed; no exception belongs to this change and agent-skill checks are inapplicable. Final combined-document `make check-packaging`, comment hygiene and all five owning architecture checks also passed before commit; the initial sandbox cache-write failure was preserved and the unchanged-source run completed with writable cache access. 5.8 Current-source CI 41534499721 passed all 23 jobs and public-content CI 41534499619 passed. Reused frozen runtime evidence remains CI 41402761003 (23 jobs), E2E 41402755345 (145 VM, 65 bare-metal, 1 API-credit pass with six payment-prerequisite skips), composed local coverage for 20 prerequisites after the original aggregate environment failure, and four Helm workloads/14 served scenarios with recorded exclusions. Deployed cleanup/refusal/retry and successor observations are separate; the dedicated bounded-cleanup marker remains unrun. 5.9 Permanent architecture, quickstart, runbook and testing destinations are promoted below; the normative delta merged at archive. 5.10 `make check-doc-citations` and pinned strict validation passed. 5.11 Pinned archive merged six additions and one modified requirement into `physical-provisioning`; post-archive checks passed.


- [x] 5.1 **Comment hygiene:** confirm `make check-comment-hygiene` and review touched comments for current-state rationale. Any code correction returns the change to implementation; closeout edits documentation only.
- [x] 5.2 **Import placement:** confirm all touched imports against the reviewed diff and real suite evidence; an import needing correction returns to implementation.
- [x] 5.3 **Documentation compliance:** reconcile every accepted material decision with `openspec/README.md` placement rules and the promotion map; verify exclusions and actual deployed evidence support the claimed boundary.
- [x] 5.4 **Narrative compression:** retain final behavior, material validation, unresolved work and permanent destinations in task notes; preserve necessary alternatives in design and remove duplicated narrative.
- [x] 5.5 **Roadmap currency:** update the affected readiness/gap mapping in `docs/development/ROADMAP.md`, or explicitly record no applicable change, and name the disposition in the promotion record.
- [x] 5.6 **Campaign index currency:** update this change's row and partial dependency graph in `openspec/changes/README.md`, preserve other changes' ownership/status, run `make check-change-index`, and record the result.
- [x] 5.7 **Packaging:** run `make check-packaging` and `make check-architecture-change CHANGE=bound-bare-metal-working-data`; resolve owned exceptions before archival. Run `make check-agent-skills` only if agent guidance was touched; any code fix returns to implementation.
- [x] 5.8 **End-to-end pipeline:** confirm the frozen revision's successful full pipeline and named bare-metal scenarios, and the separate real deployed cleanup/refusal/retry/second-UID evidence. Record run/result/revision; missing evidence is a blocker, never a pass.
- [x] 5.9 **Promotion:** promote bounded policy/UID/attribution/retry rationale to `openspec/specs/physical-provisioning/architecture.md`; let archive merge this delta into its `spec.md`. Update `docs/bare-metal-seller-quickstart.md`, `docs/development/VALIDATION_RUNBOOK.md` and `docs/development/TESTING.md` for policy installation, lifetime/exclusions, refusal recovery, exact native/deployed commands and evidence limits, including 01-design F1: service restore/redeploy preserves the host ledger, valid older-ledger rollback is not locally detectable, and known/suspected rollback requires operational quarantine until verified or decommissioned. Confirm `openspec/specs/README.md` still indexes the companion and record unchanged disposition if so. Confirm no repository-wide authority rule changed in `docs/development/ARCHITECTURE.md`, or promote a reviewed material rule there if required; finish every design-promotion row.
- [x] 5.10 **Documentation citations:** run `make check-doc-citations CHANGE=bound-bare-metal-working-data`, resolve every unresolvable/tombstoned citation, then `bunx @fission-ai/openspec@1.14.0 validate bound-bare-metal-working-data --strict` immediately before archival.
- [x] 5.11 **Archival:** pinned archive merged six additions and one modified requirement into `physical-provisioning`; the index link targets the dated archive. `make check-change CHANGE=bound-bare-metal-working-data` passed after archival. The row remains `in closeout` for the closeout review and triage.
