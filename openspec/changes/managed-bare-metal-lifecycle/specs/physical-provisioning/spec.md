## ADDED Requirements

### Requirement: Managed bare-metal tenants enter one confined environment

For the managed bare-metal profile, every tenant access method — interactive shell, remote command, file transfer, and any key the tenant adds — MUST enter one per-lease environment reached through a per-lease SSH endpoint distinct from the host's management endpoint. The tenant MUST NOT have a host account, a privileged group, a container runtime, a raw storage device, a TPM device, or any management credential. The environment MUST expose only a generated minimal runtime view, private network and IPC namespaces, the qualified GPU device nodes, and the lease's encrypted volume.

#### Scenario: Tenant-added key reaches the same environment

- **WHEN** a tenant adds a public key inside its environment and later connects with it
- **THEN** the connection enters the same per-lease environment, and the key does not authenticate to the host's management endpoint

#### Scenario: Tenant name is unknown to the management endpoint

- **WHEN** a connection presents the tenant's user name to the host's management SSH endpoint
- **THEN** authentication fails for every method, because the tenant has no host account

### Requirement: Tenant-written persistent data stays inside the lease volume

While a managed bare-metal lease is active, every location the tenant can write persistently MUST lie inside the lease's encrypted volume. Swap for tenant processes and for provider processes handling tenant plaintext or key material MUST be disabled. Core dumps MUST be prevented from persisting outside the volume. System suspend and hibernation MUST be blocked while any lease volume exists. No persistent kernel-log sink may run while a tenant is exposed. SSH daemon logs MUST be written inside the volume, and persistent provider records MUST carry only fixed-schema event fields, never arbitrary tenant content.

#### Scenario: Host persistent-path control is missing

- **WHEN** prepare finds suspend enabled, a persistent kernel-log sink active, swap control unavailable, or the crash handler unqualified
- **THEN** prepare refuses before exposing access, and the host is not admitted

#### Scenario: Tenant content reaches a daemon log

- **WHEN** a client sends arbitrary text in a protocol field the SSH daemon logs
- **THEN** that text is stored only inside the lease volume and is not copied to persistent provider records

### Requirement: Lease storage is recoverable only for its active generation

A managed bare-metal lease volume MUST survive an unexpected host reboot during its active lease and MUST become unrecoverable to later tenants once the lease is released. The volume's unlock secret MUST be sealed to the host TPM under a policy requiring a monotonic, non-orderly TPM counter to equal the value recorded for that lease generation. The sealed object MUST have a non-empty policy with no alternative branch, `USERWITHAUTH` clear, and `FIXEDTPM` and `FIXEDPARENT` set, under a non-exportable parent whose Name is verified before each unseal. Revocation MUST advance the counter; it MUST NOT rely on deleting data from storage.

Preparation MUST hold the host/index lock while reading or creating the authoritative generation fence and manifest. Another unreleased generation MUST refuse before a counter increment. Object creation, policy evaluation, load, public verification, unseal and cleanup MUST share one ESAPI lifetime, and cleanup MUST be checked and limited to handles returned in that lifetime. Durable sealed public/private blobs, not runtime object or session handles, are the recovery material. An incomplete record from an earlier process lifetime MUST quarantine ordinary retry without flushing a stale handle or advancing the counter again. A prepared retry MUST revalidate the LUKS2 header, its single keyslot and the sealed secret's ability to unlock it before reporting success.

Preparation MUST enter through a content-addressed root-private request and a non-restarting provider oneshot with durable execution state. The unit MUST expose no secret argument, environment or output channel, MUST run in `system.slice`, MUST enforce zero swap and hard and soft core-size limits of zero, and MUST stop its whole control group. Before TPM access or lease-state mutation, the executor MUST verify request identity and ownership, the configured direct TPM device, the fixed cryptsetup path and version, the exact live unit cgroup, zero swap and core limits, and no-new-privileges. It MUST read the effective kernel core pattern from trusted procfs and refuse when that policy is missing, unreadable, malformed or piped. A changed request, incomplete prior execution or uncertain completion MUST refuse or quarantine without automatic redispatch.

A synthetic mapper, filesystem and mount qualification MUST NOT authorize production activation or tenant access. Production activation MUST consume the prepared secret while holding the authoritative host/index lock, durably bind mapping, formatting and mount ownership to the lease generation, and quarantine an interruption whose live-resource state cannot be proved.

#### Scenario: Host reboots during an active lease

- **WHEN** the host restarts before the lease's original end, and no release intent exists
- **THEN** recovery under the per-host lock reopens the same generation's volume without changing the lease end

#### Scenario: Retained sealed copy after release

- **WHEN** a copy of a released generation's sealed object and volume header is used in a fresh TPM session
- **THEN** unsealing fails because the counter no longer matches

#### Scenario: Counter state is ambiguous at prepare

- **WHEN** the counter after a prepare increment cannot be attributed to that attempt through durable exclusive-writer evidence
- **THEN** prepare quarantines the host without sealing a secret

#### Scenario: Preparation restarts with an incomplete TPM lifetime

- **WHEN** durable ownership state shows a session or object that was not confirmed closed before its executor lifetime ended
- **THEN** preparation quarantines without flushing its recorded numeric handle or advancing the lease counter again

#### Scenario: Prepared storage was replaced

- **WHEN** a retry finds that the recorded backing file is no longer a matching single-keyslot LUKS2 volume unlockable by the sealed secret
- **THEN** preparation quarantines without formatting or overwriting the existing file

#### Scenario: Supervised execution evidence is incomplete

- **WHEN** the provider oneshot finds changed request content, missing live controls or an earlier running execution without a durable completion
- **THEN** it refuses before TPM access or lease-state mutation and does not automatically restart the request

#### Scenario: Synthetic mapper and mount qualification passes

- **WHEN** a disposable guest completes mapping, formatting, a native mount and checked cleanup for its owned fixture
- **THEN** production activation and tenant access remain refused until the generation-bound activation and recovery owners are integrated

### Requirement: Bare-metal release revokes, resets and verifies before capacity returns

Cancellation, expiry and delivery failure of a managed bare-metal lease MUST use one serialized release that acquires the per-host lock, confirms the generation, verifies host identity, durably records release intent, fences ingress, terminates lease execution, advances the storage counter, invalidates lease-owned TPM sessions, closes the volume, reboots, and verifies — all before capacity returns. Release MUST NOT be reported complete on the counter advance alone: it additionally requires confirmed absence of lease-owned sessions and recovery helpers, a TPM restart qualified to invalidate lease sessions, a failed fresh-session unseal of the retained sealed object, and verified host identity, management reachability, pinned versions and GPU health. The reboot MAY proceed while the lease's own allocation hold remains and MUST be refused while any other allocation exists on any alias of the physical host. Physical release MUST complete without any financial service participating.

#### Scenario: Release retry after revocation

- **WHEN** a release retry finds the counter already above the generation's recorded value, with that release's intent recorded
- **THEN** it treats revocation as done and does not increment again

#### Scenario: Stale release meets a newer lease

- **WHEN** a delayed release for an earlier generation runs after a newer generation is recorded on the host
- **THEN** it changes neither the newer lease's counter, storage, access nor publication

#### Scenario: Boot identity changed but session invalidation unproven

- **WHEN** the host reboots but lease-owned TPM session invalidation cannot be confirmed
- **THEN** release does not complete, and the host is quarantined

### Requirement: Uncertain bare-metal release quarantines the host

A managed bare-metal release step that fails, or whose effect is uncertain, MUST leave the physical host quarantined with its capacity held. After an identity, generation, manifest or lock failure, no further host mutation may occur. After a failure on the generation's own validated objects, only ingress fencing and execution termination may continue, each revalidated. Storage removal and reboot MUST run only after revalidation under the lock. An unreachable host MUST be treated as having unknown physical effects.

#### Scenario: Host identity mismatch during release

- **WHEN** the release target's machine identity or pinned host key differs from the recorded values
- **THEN** no storage or reboot action runs, and quarantine with an operator notification is persisted

#### Scenario: Host unreachable at release

- **WHEN** release cannot reach the host
- **THEN** the host stays quarantined, its capacity stays held, and financial behavior is unchanged

### Requirement: Lease egress denies private and provider destinations

A managed bare-metal lease MAY reach the public internet. Its network namespace MUST deny, for both IPv4 and IPv6: private, carrier-grade NAT, loopback, link-local (including metadata), multicast, reserved and documentation ranges; the host's own addresses; and an operator-supplied provider-endpoint set. Prepare MUST refuse when the lease firewall table is absent or mismatched for either family, or when the provider-endpoint set is empty. No public inbound service endpoint is exposed for the lease.

#### Scenario: Tenant connects to a private address

- **WHEN** a process in the lease connects to a private, link-local, or provider-endpoint address
- **THEN** the connection is refused, while public destinations remain reachable

#### Scenario: Firewall state drifted

- **WHEN** prepare finds the lease firewall table missing or different for either address family
- **THEN** prepare refuses before exposing access

### Requirement: Bare-metal release delegates to durable fulfillment teardown

For managed bare-metal reservations, lease release SHALL initiate teardown through the same narrow fulfillment-teardown port VM release uses, SHALL use the durable `fulfillment_id` as the release tracking identifier, and SHALL NOT submit or poll a provider job directly. Fulfillment convergence SHALL dispatch, retry and recover the bare-metal release steps through the bare-metal fulfillment provider and SHALL re-observe the same aggregate on retry; no second release implementation exists. Lease lifecycle SHALL keep capacity held until that aggregate reports verified release completion or an explicit force-release occurs, and force-release SHALL NOT clear physical quarantine.

#### Scenario: Operator retries a failed bare-metal release

- **WHEN** a bare-metal fulfillment is `teardown_failed` and an operator retries lease release
- **THEN** the retry re-observes the same `fulfillment_id`, no second release operation is created, and capacity stays held

#### Scenario: Bare-metal release status is read from the aggregate

- **WHEN** lease lifecycle resolves release status for a bare-metal reservation
- **THEN** it reads the fulfillment aggregate's teardown state rather than an executor job

## MODIFIED Requirements

### Requirement: Site-backed release lifecycle
Compute lease lifecycle MUST use an injected site-authority port and MUST NOT report capacity released until the selected executor release succeeds or an operator performs an explicit force-release action.

#### Scenario: Executor release succeeds
- **WHEN** a lease expires and its registered executor completes teardown or reclaim
- **THEN** compute lifecycle records successful allocation release through the site-authority port and capacity becomes available

#### Scenario: Executor release fails
- **WHEN** VM teardown or bare-metal reclaim returns a failure
- **THEN** the allocation remains unavailable, the lease exposes `release_failed`, and retry and force-release controls retain the failure evidence

#### Scenario: Operator force-releases allocation
- **WHEN** an authorized operator force-releases after an unrecoverable executor failure
- **THEN** the audit state distinguishes the operator override from successful physical teardown

Release submission and release-completion reads are separate, independently kind-routed seams. For VM and bare-metal reservations alike, release submission begins teardown of the reservation's durable fulfillment aggregate through a narrow fulfillment-teardown port and returns its `fulfillment_id` as the release tracking identifier. Fulfillment convergence (see the Fulfillment specification's "Fulfillment convergence worker") owns teardown dispatch, retry and recovery through each mode's fulfillment provider, running independently of the lease watchdog's own poll cadence, and the release-completion read observes that aggregate's teardown state. What "teardown complete" means still differs by offering mode — a VM teardown is its multi-step provider teardown, while a bare-metal teardown completes only under "Bare-metal release revokes, resets and verifies before capacity returns" — so completion semantics stay with each mode's provider rather than in the lease lifecycle. Compute lease lifecycle stays kind-agnostic on both sides: a release-job port is resolved by the reservation's offering mode the same way release submission already resolves an executor delegate by mode, so adding or changing one mode's completion semantics does not touch the generic watchdog or any other mode's path. The delegation shape — the narrow fulfillment-teardown port, the durable `fulfillment_id` as release tracking identifier, and the failure-propagation contract for unexpected submission errors — is the formal subject of "VM release delegates to durable fulfillment teardown", "Bare-metal release delegates to durable fulfillment teardown" and "Lease release and fulfillment teardown have separate retry ownership" (`## Relationship to fulfillment`); this section states only the kind-routing rationale.

#### Scenario: VM lease release begins durable fulfillment teardown

- **WHEN** a VM lease is due for release, whether by watchdog-detected expiry or an explicit early-termination request
- **THEN** the executor delegate begins the fulfillment aggregate's teardown and returns its fulfillment identifier as the job the lease lifecycle polls, rather than submitting provider work directly

#### Scenario: Bare-metal lease release begins durable fulfillment teardown

- **WHEN** a bare-metal lease is due for release, whether by expiry, authorized cancellation or delivery failure
- **THEN** the executor delegate begins the bare-metal fulfillment aggregate's teardown and returns its fulfillment identifier as the job the lease lifecycle polls, and the lease lifecycle neither submits nor polls a reclaim job on the shared job queue

#### Scenario: Executor release delegate has nothing to poll

- **WHEN** an executor's release delegate reports no pollable job for a submitted release (e.g. no release mechanism configured for that kind), and that offering mode's release contract does not require physical revocation
- **THEN** the lease lifecycle treats it as immediately complete, independent of whether any other offering mode has a release-job port configured

#### Scenario: Bare-metal release mechanism is missing

- **WHEN** a bare-metal lease is due for release and no release delegate or release job is available for it
- **THEN** the lease lifecycle records a release failure, keeps the allocation unavailable, and does not treat the absence as completion

### Requirement: VM release delegates to durable fulfillment teardown

For VM reservations, lease release SHALL initiate teardown through a narrow fulfillment-teardown port. The VM release adapter SHALL use the durable `fulfillment_id` as the release tracking identifier and SHALL NOT submit or poll a provider job directly. Release-status lookup SHALL be selected by the reservation's `offering_mode`, the same value the capacity claim carries and the Resource Pool declares; VM lookup SHALL read fulfillment aggregate state, and bare-metal lookup SHALL likewise read fulfillment aggregate state (see "Bare-metal release delegates to durable fulfillment teardown").

#### Scenario: Release status is selected by the offering mode

- **WHEN** lease lifecycle resolves a release-status lookup for a reservation
- **THEN** the lookup is selected by the reservation's recorded `offering_mode`
- **AND** a reservation carrying the retired selector key is treated as carrying no offering mode rather than defaulting to one

#### Scenario: Unexpected teardown submission failure remains diagnosable

- **WHEN** composition, persistence, or an unexpected implementation failure prevents VM teardown submission
- **THEN** the failure SHALL propagate to lease lifecycle handling and be recorded as `release_submit_error` rather than being converted to an absent job identifier
