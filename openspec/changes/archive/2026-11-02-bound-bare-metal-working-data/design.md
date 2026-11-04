# Design

## Context

See `proposal.md` for motivation and scope. The access role currently lets the operating system choose a UID, grants an existing named account access, and conditionally deletes its home. The permanent reclaim contract accepts an absent account. `prove-relay-provisioning` section 9 separately adds activity termination and reliable error propagation; this design consumes that prerequisite rather than reimplementing it.

## Goals / Non-Goals

The bounded policy gives a reservation an attributable disposable account and a cleanup receipt covering its home, explicitly configured shared scratch and IPC. It assumes a nonroot tenant with no sudo, no privileged groups or capabilities, and an operator who prevents new tenant execution after the termination barrier. It does not claim complete data isolation against a kernel exploit, data outside those roots, other owners, logs or retained backups. Saving data before teardown is outside this change.

## Decisions

### D1. Add a policy; preserve the existing policies

Use `bounded_working_data` as an explicit operator-selected access/reclaim policy, resolved before grant and retained for reclaim. Existing `remove_lease_key`, `lock_user` and `delete_user` remain available with their current data semantics and the activity termination owed by section 9. Buyer inputs cannot select the policy, UID, cleanup roots, home or ledger. The new policy refuses pre-existing unreceipted accounts; it does not retrofit already granted accounts. This avoids turning an upgrade into unbounded deletion and gives a deliberate rollout boundary.

### D2. The bare-metal role owns a stdlib host-local helper

Add `domains/bare_metal/provisioning/iac/ansible/roles/bare-metal-access/files/tenant_working_data.py`. It has a small versioned JSON request/result interface for protected identity inspection/reservation, fixed-path SSH key installation/revocation, clean, remove-home and verify-complete operations. Inputs carry the capacity reservation ID and derived tenant name; the protected installed policy supplies everything destructive. Commands use argument vectors, never shell-expanded tenant input. It imports only the Python standard library and runs under root on the selected host; it is an Ansible asset, not a new service or importable runtime distribution.

Reserve produces the UID and its expected home for explicit account creation. Clean removes attributable scratch and IPC only after checking the no-process precondition. The role then removes the account without recursive home deletion, invokes the explicit descriptor-safe remove-home operation, and removes its recorded private primary group; verify-complete independently checks every covered absence and durably marks completion. Partial progress is not success. The helper never kills a process or removes scheduled activity; those effects stay with section 9. Alternatives rejected: broad `find / -uid` cleanup, shell pipelines parsing human command output, a new network service, and placing bare-metal host policy in generic fulfillment.

### D3. UID consumption is durable before account creation

Install a root-owned non-writable-by-tenants state directory and policy, with restrictive modes and no symlinked ancestors. A versioned ledger records policy identity, reservation ID, account, UID, private primary GID, derived home, policy/root identity, lifecycle state and bounded cleanup observations; retain its consumed UID/GID sets for the entire policy lifetime. A stable separate lock file serializes operations across processes. Validate owner, regular-file type, modes and link count for policy, ledger and lock; use no-follow opens. A write uses a same-directory restrictive temporary file, flush/fsync, atomic replace and directory fsync while holding the lock. An unreadable, missing established, corrupt or mismatched ledger fails closed; it is never rebuilt from current accounts.

Choose the first eligible unused UID from an operator-configured finite local range and pair it with a private primary group of the same numeric GID. Exclude configured operator/service identities, consumed UID/GID values, and all NSS user/group ID/name conflicts. Persist both identities before creating either group or account; retries reuse both, and a new reservation never inherits either. Group deletion requires the recorded identity and no foreign members/references; ambiguity fails cleanup. This small paired-group boundary prevents ordinary group allocation from inheriting a previous tenant’s group access. Root, system and privileged identities are prohibited even if a range includes them. Persist consumption before `useradd` can run. The same reservation returns its existing identity on retries; conflicting account/policy reuse fails. A completed reservation cannot be granted again. Another reservation never obtains a consumed UID, including after failed creation or deletion. UID allocation exhaustion fails before a host mutation. There is no ledger pruning/reset command in the helper; campaign teardown cannot reset consumption. Policy lifetime extends across service/host restarts and the complete campaign; retiring its ledger requires separate operator decommissioning and removal of every old attribution risk.

**01-design F1 — ledger continuity.** Uninterrupted protected host-ledger continuity is an operator precondition. A valid older copy of the same ledger cannot detect its own rollback: ownership, permissions, schema checks, locking, atomic replacement, fsync and current NSS observations cannot establish that a later consumed identity was omitted. Normal calls detect and refuse missing established, corrupt or mismatched state without initializing it. Service database restore, image redeployment and campaign reset must preserve the host ledger unchanged. A known or suspected restore of structurally valid older host state operationally quarantines the host until its complete consumption history is verified or the host is decommissioned; the helper does not claim to discover that rollback locally. Initial installation and recovery are distinct from normal operations. The lead accepted this clarification under delegated technical authority; it does not record personal owner review or add another review round.

Alternatives rejected: the system's next UID (reuses deleted IDs), username-only receipts (cannot recover UID ownership after account deletion), and an in-memory campaign set (lost on restart). Holding a lock through a long deletion serializes cleanup, but a whole-host policy already admits one tenant and correctness dominates throughput.

### D4. The protected root policy defines the entire deletion boundary

The root-owned policy defines a dedicated home parent, configured scratch roots and path-backed IPC roots, a local UID range/exclusions, and allowed filesystem/mount identities. Home derives from the recorded tenant name under that home parent. Ordinary requests cannot override any path. Validate policy roots before use: absolute normalized paths, no aliases/overlap, no `/`, operator homes, service state, log/backup roots or protected state directory. Record policy identity in the receipt so a later configuration edit cannot silently widen a prior tenant's cleanup. Policy drift refuses until an operator restores the matching policy or repairs the host separately.

Only UID-owned entries inside those roots are cleanup candidates. Traverse with directory file descriptors and no-follow operations, inspecting every component; do not recursively delete through a symlink or mount. Unlink an attributable symlink itself without resolving its target. Refuse unexpected mount points (including bind mounts), unexpected device identities, ownership drift and any selected directory containing a foreign-owned descendant. Preflight a candidate tree before removal, then revalidate identity/type/ownership during descriptor-relative removal; a race or unreadable entry fails rather than guessing. Non-selected foreign entries in a shared root are retained. No recursive `rmtree` or `rm -rf` over unchecked contents. Dedicated home cleanup follows these same rules; the role must not run unchecked recursive `userdel -r` before the helper validates the home. After account removal it removes the verified home through the helper's bounded path operation and verifies absence.

This favors refusal over accidentally deleting another owner. It does not promise deletion of hard-linked copies outside the boundary or files a tenant deliberately transferred to another UID; such data is outside this working-data policy. Detected foreign children still block completion rather than being silently accepted.

### D5. IPC has two explicitly covered forms

Path-backed IPC (including POSIX shared-memory/semaphore objects exposed under configured IPC roots, and sockets/FIFOs in covered roots) follows the filesystem rules. Linux System V shared memory, semaphores and message queues are inventoried from the kernel interface; removal uses the standard library's `ctypes` libc bindings with numeric IDs and a platform capability check. Compare both owner and creator UID immediately before removal, and verify the inventory afterwards. An object with either UID matching the tenant but the other differing is ambiguous and fails cleanup; do not delete it. Refuse unavailable/unreadable IPC inventories and unsupported kernel interfaces. Kernel-owned numeric IDs can be recycled, so an ID alone is never attribution. Tests supply an injected kernel adapter for deterministic errors and exercise real objects in an isolated IPC namespace in native qualification.

### D6. Quiescence is a checked precondition; complete is a verified state

The role first revokes access and invokes section 9's verified termination of sessions, lingering and scheduled activity. Those detailed barriers and their checks stay with section 9. The helper independently verifies only that no remaining process references the UID (real, effective, saved or filesystem UID); denied/unreadable process observations fail. It does not duplicate section 9’s schedule, session or lingering observers. Quiescence checks and cleanup occur while new grants are excluded; recheck before completion. A caller-provided `quiescent=true` is not evidence. If the account already vanished, the ledger still gives the numeric UID for these checks; absent account must not skip them.

The codec emits the accepted policy explicitly even for a legacy grant, so inventory cannot enable bounded behavior outside the stored selection. Receipts survive partial cleanup and account deletion. A retry re-reads protected identity and policy, removes only remaining attributed objects, and verifies account/NSS name and UID, private primary group, home, UID-owned covered scratch and IPC all absent, with no UID process and section 9’s activity barrier satisfied before committing `complete`. Missing receipt plus absent account fails closed for this policy: there is no safe UID to clean. A reserved receipt whose account was never created can complete after the same bounded absence checks, without creating the account. A complete retry re-verifies absence rather than trusting stale success. Cleanup never resurrects an account. Consumed UID history survives all terminal states.

### D7. Integrate only after verified activity termination

Independent helper/test work changes no role runtime, codec or fulfillment plan. Later integration first verifies section 9's accepted code and evidence, rebases on that interface, and reconciles absent-account handling without rewriting its history. Carry `capacity_reservation_id` from accepted grant through stored job parameters and teardown preparation, rendering a local `reservation_id`; never substitute a deal/escrow identity. Refuse bounded cleanup on a legacy job lacking correlation instead of guessing. Choose policy from trusted host configuration before grant and snapshot its identifier into accepted inputs; host policy still controls paths and verifies the identifier at execution.

The ordering is revoke access → section 9 termination → verified quiescence → helper clean of scratch/IPC and home validation → account and bounded home removal → helper verification/receipt completion → successful job. The helper has an explicit remove-home operation, performed after nonrecursive account deletion and before verify-complete, to keep descriptor-safe home handling in one implementation. The role never uses recursive account-tool home deletion. It then removes only the ledger-bound unused private group before completion verification. Reclaim facts may report policy, UID, receipt state and bounded counts, but remain diagnostic. Nonzero helper or role status must fail the job; no success flag in output may override it. Existing fulfillment/lease state machines retain capacity until proven teardown, and an operator force-release keeps its distinct audit meaning.

### D8. Test at the owning boundary and qualify actual execution

Create a minimal `package = false` uv project at `domains/bare_metal/provisioning/iac/`, patterned on VM IaC without transferring ownership to VM. Pure policy parsing and identity selection get unit tests. Real temporary filesystem traversal, ledger persistence, interrupted writes and competing processes belong in that project's integration tests; injected NSS/kernel/process adapters isolate only host-global effects. A temporary-tree test still uses the real helper filesystem boundary. Native Linux tests exercise real disposable accounts and IPC only in an isolated disposable environment, with no operator account targets; missing prerequisites are an explicit failure in its dedicated gate, not a counted pass.

Wire the default project tests into the domains/root Make aggregates and their dynamically derived CI matrix; update lock/project discovery and packaging checks. Add a bare-metal native gate using the built provisioning image and an isolated disposable host environment for account/kernel behavior. Ordinary static asset checks only supplement these tests. Service integration through typed clients proves parameter correlation, helper failure propagation, compensation and held capacity. The deployed protected purchase path must seed covered data, obtain a real grant, reclaim normally, verify absence through operator observations and successfully grant a second reservation with a different UID. It must also show a deliberately refused cleanup keeps capacity unavailable before repairing the disposable fixture and retrying. Neither a mock deal nor helper tests qualify deployed cleanup. Freeze, validate and independently review the integration source before destructive deployed qualification. The real-lane additions depend on relay section 12 providing the bare-metal module; retain the verified section 9 termination prerequisite. Reuse the source review when qualification changes no code.

## Risks / Trade-offs

- Finite UID pool → expose exhaustion clearly; size it for the campaign and never recycle under pressure.
- Missing/corrupt/mismatched ledger state → normal calls refuse without initializing. Known or suspected valid older-state restore → operator quarantines the host; local self-rollback detection is not promised. Verify every consumption or decommission; never automatically reconstruct from current NSS state (01-design F1).
- Filesystem/IPC ambiguity or namespace mismatch → fail closed; require one explicitly supported host/kernel policy and native tests of it before rollout.
- Nonroot tenants can retain data outside declared roots or transfer ownership → state the limited guarantee; no forensic or whole-host erasure claim.
- Section 9 can evolve independently → independent helper work proceeds; integration waits and adapts after its interface and validation are available.

## Migration Plan

Implement and review the independent helper first without activating it. After section 9 is available and verified, integrate the policy, run focused/native checks and freeze, validate and review the integration source. After relay section 12 supplies the real lane, qualify the reviewed policy on an empty disposable host. Drain existing leases; verify no historical accounts are being adopted, initialize protected policy/ledger explicitly, and deploy the reviewed assets/configuration together while capacity remains disabled. Complete deployed qualification before enabling new tenants. Existing policies need no migration. Rolling back code must disable new bounded grants and keep the ledger intact; do not resume a prior policy over unverified tenant residue or restore an older consumed-UID set. Service database restore, image redeployment and campaign resets preserve the host ledger independently and unchanged; none restores host identity history from a service backup. A known or suspected valid older-ledger restore keeps the host disabled until its history is verified or it is decommissioned. Recover forward or quarantine/decommission the host.

## Lead review points

The selected finite UID policy, Linux-only IPC adapter and strict refusal on foreign descendants intentionally narrow availability to keep attribution defensible. Review the helper's reserve/clean/verify boundary and the additive policy selection/snapshot seam before runtime integration. No owner decision is deferred while tasks prescribe a competing answer.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1, D3–D6: bounded policy, identity consumption, attribution and completion | `openspec/specs/physical-provisioning/spec.md#requirement-bounded-working-data-cleanup-is-an-explicit-bare-metal-policy`; `#requirement-tenant-uids-remain-consumed-for-the-policy-lifetime`; `#requirement-cleanup-targets-are-protected-and-bounded`; `#requirement-tenant-ipc-cleanup-requires-unambiguous-ownership`; `#requirement-bounded-cleanup-checks-quiescence-without-owning-termination`; `#requirement-bounded-cleanup-completes-only-after-verified-absence`; `#requirement-a-bare-metal-reclaim-tolerates-an-account-its-grant-never-created` (delta merged at archive) |
| D2–D7 and 01-design F1: helper ownership, host-ledger continuity/rollback limits, bounded filesystem and IPC cleanup, retries and integration sequencing | `openspec/specs/physical-provisioning/architecture.md#bounded-bare-metal-working-data` |
| D1, D3–D6 and 01-design F1: operator setup, exclusions, exhaustion, refusal recovery and ledger preservation/quarantine | `docs/bare-metal-seller-quickstart.md`; `docs/development/VALIDATION_RUNBOOK.md#22-prepare-the-host`; `docs/development/VALIDATION_RUNBOOK.md#26-restore-and-cleanup` |
| D8: IaC test ownership, native gate and deployed qualification boundary | `docs/development/TESTING.md#ansible-syntax-and-native-checks` |
| Readiness, actual deployed observation and remaining gaps | `docs/development/ROADMAP.md#payment-qualification-boundaries`; `openspec/changes/README.md` (Reach hosts and VMs campaign) |
| Repository-wide authority/dependency boundary | `docs/development/ARCHITECTURE.md#authority-boundaries`; no new architecture rule was needed |

## Helper wire contract (version 1)

The root-only entrypoint is `python3 tenant_working_data.py --policy /etc/arkhai-working-data/policy.json`; it reads one JSON request from stdin and emits one JSON result. Initialization is the separate explicit `--init` invocation and creates the stable lock exclusively: an existing lock, even with a missing ledger, refuses initialization. Installation must create the protected policy/state directories first. There is no reset, prune, restore or adoption operation. A failed initial write requires operator recovery; it does not silently repeat initialization. Normal operations cannot create either missing lock or ledger. Removal of both is a continuity loss to quarantine, never a reason to reinstall fresh state.

Policy schema (all fields required; unknown/duplicate fields rejected):

```json
{"version":1,"policy_id":"example-policy-v1","state_dir":"/srv/example-working-state","home_parent":"/srv/example-tenant-homes","scratch_roots":["/srv/example-scratch"],"ipc_roots":["/dev/shm"],"uid_min":41000,"uid_max":41999,"exclude_ids":[41001],"mount_ids":[123,124]}
```

These are invented fixture identities and illustrative mount IDs, not deployable host configuration. Mount IDs must be obtained on the selected host in its actual mount namespace. The finite range is inclusive, starts at least at 1000 (the conventional Linux non-system boundary) and excludes every current NSS UID/GID/primary-GID plus every consumed or explicitly excluded value. The account name must match `[a-z_][a-z0-9_-]{0,31}` and cannot be root, nobody or daemon. This preserves existing `arkhai-...` settlement/access-reference-derived names; it does not introduce a fixture-only runtime namespace. Existing NSS name conflicts and any unreceipted home refuse allocation. Home derives by appending it to `home_parent`. All paths are absolute and normalized, including rejection of initial double-slash aliases; roots cannot overlap each other or protected state/service/log/backup roots. `/dev/shm` and `/dev/mqueue` are permitted as exact path-backed IPC roots only. Within `/var/lib`, only an explicit dedicated state directory or exact `/var/lib/BrlAPI` scratch root is accepted; all other service state is refused. Targeted NSS name/UID/GID lookups supplement enumeration, including backends whose enumeration omits entries. Policy, lock and ledger are regular single-link files owned by root with no group/other permissions; directories and ancestors have no group/other write or symlink components (root's sticky `/tmp` is the sole ancestor exception for disposable test environments). The state directory itself must have the protected owner. Policy bytes normalize to a SHA-256 digest of canonical sorted compact JSON; a changed value refuses every existing receipt.

Every request has these common fields; only `install-key` additionally requires `ssh_public_key`, one OpenSSH public-key line. No other operation accepts that field:

```json
{"version":1,"operation":"reserve","reservation_id":"example-reservation-a","account":"tenant_example_a","policy_id":"example-policy-v1"}
```

Operations are `reserve`, `inspect`, `verify-identity`, `install-key`, `revoke-key`, `clean`, `remove-home` and `verify-complete`. Neither paths nor numeric identities nor quiescence assertions are caller inputs. `reserve` consumes UID/private-GID durably before returning; an exact retry reuses it, a completed reservation refuses grant, and a new reservation may reuse its account name only after every prior same-name receipt is complete and its absence is independently reverified; it still consumes a fresh numeric pair. `verify-identity` requires both the exactly matching receipted account and private group to exist, and rejects supplementary membership or foreign primary-group references. It performs no account creation.

Ledger schema and successful reservation result:

```json
{"version":1,"policy_digest":"illustrative-sha256","roots":{"/srv/example-tenant-homes":{"device":1,"inode":100,"mount_id":123},"/srv/example-scratch":{"device":1,"inode":101,"mount_id":123},"/dev/shm":{"device":2,"inode":1,"mount_id":124}},"consumed":[41000],"receipts":{"example-reservation-a":{"reservation_id":"example-reservation-a","account":"tenant_example_a","uid":41000,"gid":41000,"home":"/srv/example-tenant-homes/tenant_example_a","state":"reserved","policy_digest":"illustrative-sha256","observations":{}}}}
```

```json
{"version":1,"operation":"reserve","reservation_id":"example-reservation-a","account":"tenant_example_a","uid":41000,"gid":41000,"home":"/srv/example-tenant-homes/tenant_example_a","state":"reserved","policy_digest":"illustrative-sha256","observations":{}}
```

The real digest is a 64-character SHA-256 hex string. Ledger version is exactly 1; every consumed identity has exactly one receipt with the same UID/GID, derived home and matching policy digest. Receipt states are `reserved`, `cleaned`, `complete`; consumption and receipts are retained in all states for the entire policy lifetime. Writes fsync the restrictive same-directory temporary file, replace atomically and fsync the directory under the stable exclusive lock. A failed write is reported as failure even when replacement already happened; retry inspects the actual ledger rather than inferring success from a previous response. Errors emit version/error/message JSON on stderr and exit nonzero. Success output is diagnostic and never an alternative release authority.

The helper cannot identify a valid older copy as rolled back. Service-state restoration and image redeployment leave this ledger untouched; suspected host-ledger rollback keeps the host disabled until the operator verifies all consumed history or decommissions it. These schemas and continuity rules promote with D2–D7 at closeout; helper-only checks establish no deployed qualification.


### Bounded operations and native gate

The ledger binds each cleanup root's device, inode and actual Linux mount ID at explicit initialization. Every normal operation revalidates those protected roots and their identities before proceeding; replacement or policy drift refuses. Shared data roots may be root-owned sticky directories such as mode 1777 `/tmp`, `/dev/shm` and `/dev/mqueue`; that exception never applies to policy, ledger, lock, home parent or state directory. Directory ancestors remain protected and are opened component by component without following links. Linux fdinfo mount IDs, rather than `st_dev` alone, refuse bind mounts within a covered root.

`clean` verifies no task in any process references the UID in its real/effective/saved/filesystem UID fields, checks protected account/private-group identity, inventories all covered roots and System V IPC, preflights the complete candidate set, then removes owned scratch/path-backed IPC and exact owner-and-creator System V objects. It validates home topology without deleting the home. No process kill, session/schedule/linger observer or termination command exists here. IPC header/row interfaces must be supported and readable; an empty inventory is valid, an unavailable inventory is an error. Object fingerprints are rechecked immediately before `IPC_RMID`; mixed creator/owner identity refuses before any deletion. Foreign entries in shared directories survive; a selected directory with any foreign descendant refuses. Symlinks themselves may be unlinked when attributable; their targets are never traversed. External hardlinks survive. Roots, children, mount identity and directory contents are revalidated during removal and all relevant inventories afterwards.

`remove-home` requires the account's name and numeric UID absent and removes only its descriptor-validated home. It verifies IPC and activity but does not remove a private group; the role owns account/group removal. `verify-complete` independently verifies account/name/UID, private GID/name and foreign references, home, attributable scratch/path-backed and System V IPC, and process absence before fsyncing `complete`. All failures retain consumed history; partial filesystem effects are recovered by inventory on retry. Repeating completion rechecks actual absence. A repeated old receipt cannot act on a newly reused same-name identity: identity/home mismatch refuses. The `observations` object contains only bounded nonnegative entry/object counts: `scratch_removed` includes scratch and path-backed IPC entries, `ipc_removed` counts System V objects, and `home_removed` counts home entries. Results describe the current operation; the ledger persists observations on clean/completion, while remove-home returns its diagnostic count without adding a new durable state transition. Verification-only completion records zero removal counts. These fields are diagnostic and never release capacity.

`make test-bare-metal-iac` runs pure unit plus library integration tests against actual owned temporary files, injecting only NSS/kernel/process observations and deterministic race callbacks. It explicitly excludes native tests. `make test-bare-metal-iac-native PROVISIONING_IMAGE=<built-provisioning-image>` starts a disposable root container with private PID/IPC and no network, an owned `/work` tmpfs, and only this IaC source tree mounted read-only. The empty Docker PID mode explicitly selects its default private namespace. CAP_SYS_ADMIN and an unconfined container AppArmor profile permit bind mounts inside that owned scratch only; it does not use privileged mode, host namespaces or operator account mounts. The script checks its disposable-container contract and tmpfs before account operations. It uses the built image's Python/Ansible and the current shipped helper source asset, exercises real temporary NSS accounts, System V and POSIX shared memory/semaphores/message queues, actual same-device bind-mount refusal, foreign-child refusal/repaired retry and no-follow behavior. Missing image, unsupported capabilities, zero tests or skips fail the gate. This independent gate does not claim rebuilt-image asset packaging, Ansible role activation, lifecycle integration or deployed readiness; those remain the later sections' evidence.


### Destructive-entry mutation authority

An owned entry beneath a foreign-owned directory cannot be safely removed by checking ownership and then unlinking its name: that directory owner can chmod and replace a child even when its current mode is 0555. Similarly, a tenant-owned nonsticky directory with effective foreign write authority permits replacement while the tenant UID is quiescent. Cleanup therefore refuses the entire preflight if any selected entry's containing directory or ancestor is controlled by a UID other than trusted root or the quiesced tenant, or is group/other writable without the sticky bit. Linux POSIX ACL effective class masks are reflected in group mode bits, so the refusal covers named-user/group ACL writers as well. Root-owned sticky shared roots remain supported; the sticky rule prevents foreign UIDs from replacing root/tenant-owned candidates. The helper retains the checked entry descriptor across unlink/rmdir and rechecks parent authority during removal. No silently skipped tenant residue or new staging subsystem is introduced. Native regressions exercise foreign-owner 0555, tenant 0777 and named ACL write masks with preserved operator sentinels, followed by explicit fixture repair and ordinary retry. This is the accepted frozen-round review correction and promotes with D4's attribution/race rationale at closeout.


## Integration interface and prerequisite verification

The integration consumes the activity helper's protected numeric interface,
`--trusted-uid <account> <uid>`, including when NSS no longer contains the account.
That interface does not authenticate receipts: only the bounded helper may supply
its numeric identity. The reviewed relay implementation preserves legacy absent-
account success, fails on an unverified termination barrier and requires relay
removal before reporting success. Its focused activity tests and packaged native
barrier checks establish this source prerequisite; no deployed cleanup is implied.

The lead accepted one necessary integration amendment under delegated technical
authority: `inspect` reads an existing protected receipt with the normal exclusive
lock, exact policy/reservation/account matching and current identity-conflict
checks. It does not allocate, initialize, reset, adopt, clean, terminate or write
the ledger. It permits absent accounts and complete receipts, requiring current
identity absence for a complete receipt. Missing attribution refuses. Reclaim uses
this read before the numeric activity barrier; using `reserve` here would allocate
during teardown and refuse completed retries, while using `clean` would violate
the termination-before-deletion invariant. Tests cover read-only behavior, missing
and mismatched attribution, identity conflict and completed replay.

The deployment chooses `bare_metal_reclaim_policy` and, for the bounded policy,
`bare_metal_working_data_policy_id` before grant. Accepted bounded parameters
retain both values and their capacity reservation into reclaim even if deployment
configuration changes. Existing grants cannot be adopted into the bounded policy.
The protected host policy remains the sole owner of paths and numeric identities.
The operator-only `bare-metal-working-data` host-preparation role installs the
helper and a previously absent protected policy, refuses policy replacement, and
initializes only when `bare_metal_working_data_initialize` is explicitly true.
Policy roots and the state directory must already exist with protected ancestry
in the actual target mount namespace. An existing initialization lock refuses a
second initialization. Normal grant/reclaim never runs the installer or init.

Ordinary retry qualification must repair the unsafe fixture while the same job
still has retry budget. The real runner raises `AnsibleError("Playbook failed")`
on a helper's nonzero play; that message is retryable through the bare-metal
codec unless it matches an explicit transport/operator nonretryable rule. The
queue retains capacity while that failed attempt awaits a scheduler retry.
A terminal failed teardown is immutable under the current lifecycle contract:
retry-release adopts proven completed teardown, it does not reexecute a failed
job. Such a failure retains capacity and needs the existing separately audited
operator verification/force-release procedure. Neither injected aggregate state
nor a force-release may be reported as ordinary successful retry. Native role
refusal/repair checks prove host idempotency, and typed application checks prove
transient same-job retry and terminal failed/held behavior separately; deployed
qualification must still prove the actual ordinary lifecycle on the target.


### Bounded SSH key authority

The packaged `ansible.posix.authorized_key` implementation's `follow=false` does
not prevent traversal of an intermediate `.ssh` symlink: its pathname-based
`chown` and `chmod` follow that link. A disposable native reproduction confirmed
an outside root-owned sentinel directory was changed and an outside key file
created. The bounded path therefore does not use the inherited key or permission
modules. Its protected receipt helper owns two fixed-path operations:
`install-key` (only this operation additionally requires `ssh_public_key`) and
`revoke-key`. Neither accepts a target path, UID or group. Both pin the protected
home parent, receipted home and `.ssh` with no-follow directory descriptors,
verify current owner/private GID, permissions, mount and entry identity, and
refuse symlinks or ambiguous existing key files. Installation writes one validated
public key through a new restrictive descriptor and replaces only that private
key entry, with descriptor-only permission changes. Revocation unlinks only the
validated fixed entry; missing home/directory/key is benign and creates nothing.
Neither operation initializes or changes consumption history. Completed receipts
cannot install a key. Bounded account/group creation skips existing matching
receipted identities instead of applying pathname-based account mutations on a
retry. The normal assumption that the operator excludes new execution during
reclaim still applies; these operations do not claim to replace activity control.

Buyer relay removal precedes receipt inspection, so an attribution refusal does
not leave a reachable buyer proxy behind. Receipt-bound key revocation still
precedes the activity barrier and all working-data deletion. A refusal fails the
job and retains capacity. Native tests cover intermediate `.ssh`, final key and
home symlinks on both grant retry and reclaim, preserving outside sentinels and
then using ordinary repaired retry. This correction is bounded-policy-only;
legacy key-path behavior is not represented as corrected by these tests. The
current-state authority rationale and operator limits promote with D2–D7.


## Deployed observation seam

The real bare-metal target may explicitly opt into bounded-cleanup qualification
with a separate operator observation connection and the expected policy identity.
Its harness-local private key is referenced by path; the existing physical host
public key pins both operator and buyer SSH. The preflight authenticates that
route, verifies the protected established policy/ledger, and requires the Linux
observation utilities before any service hold or supply/purchase write. The
observer reads independent NSS, procfs, kernel IPC, scheduler/session and covered
filesystem state; it never calls the cleanup helper to establish absence.

The dedicated `e2e_bare_metal_bounded_cleanup` marker refuses missing explicit
configuration. A configured run executes a normal lifecycle followed by a second
full lifecycle with another UID. Both seed synthetic home/scratch/path-backed
IPC, three System V IPC families, cron activity, a detached process and one open
SSH session. The refusal fixture is a root-owned child inside a tenant-owned
nonce-scoped scratch directory: that selected tree must fail the helper's foreign
descendant invariant. A foreign top-level file would be preserved and would not
exercise refusal. Recovery requires that exact refusal in job logs, a queued
failed attempt with a scheduled remaining retry, a releasing lease and capacity
still consumed through the canonical site view. It removes only the unchanged
nonce/inode/content-bound foreign child, then observes the normal job scheduler.
No job is resubmitted and no terminal failure is rewritten. Distinct synthetic
operator/service sentinels must survive unchanged; only after successful independent
observations does the observer remove its own sentinel files. Missing utilities,
unknown output and inaccessible state fail qualification rather than imply absence.
This source seam does not establish live readiness without actual deployed runs.

## Arkhai qualification method amendment

The accepted method in `openspec/changes/archive/2026-11-02-qualify-arkhai-real-provisioning/design.md#accepted-method-mapping`
applies to unfinished deployed tasks 4.1–4.3 on this branch. Existing probe and
independent observation semantics remain unchanged. A normal Arkhai rental and
fresh-UID successor/refusal rental provide the ordinary teardown, held-capacity,
same-job retry and notification proof. Do not claim unrun original pytest markers
passed or replace reviewed physical evidence with helper/native results.
