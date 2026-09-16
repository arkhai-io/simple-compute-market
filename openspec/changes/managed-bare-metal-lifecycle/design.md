## Context

The bare-metal whole-host path already reserves capacity at the site authority, schedules a Settlement Resource, grants SSH access through the bare-metal provisioning adapter and the `bare-metal-access` Ansible role, and releases through the lease lifecycle. The release half does not yet produce a host safe for an unrelated tenant; `proposal.md` lists the defects. This document records the accepted design for the managed host profile, storage and key custody, release, verification and quarantine, together with the qualification gates that separate implemented behavior from physically qualified behavior.

Ownership does not change:

| Concern | Owner |
|---|---|
| Physical exclusivity and capacity return eligibility | Site authority |
| Release decision and final capacity return | Provisioning lease lifecycle |
| Teardown dispatch, requeue and recovery | Fulfillment convergence |
| Managed host preparation, reclaim steps and their verification | Bare-metal provisioning adapter and access role |
| Close, reopen and confirmed relisting | Capacity publication kit |

No second release worker, storefront expiry loop or storefront-only availability flag is introduced.

## Goals

- One managed host profile whose tenant cannot write persistent data outside a per-lease encrypted boundary.
- Lease data survives an unexpected host reboot during an active lease, and becomes unrecoverable to later tenants once the lease is released.
- One serialized, generation-fenced release path for cancellation, expiry and delivery failure. It completes independently of any financial state and fails closed.
- Relisting only after verified release and confirmed remote publication.

## Non-goals

See `proposal.md#non-goals`. In particular: no payment changes, no general sandbox or key-management platform, and no public inbound service in the initial profile.

## Decisions

### D1. One managed host profile

The profile supports one host type:

- Linux with systemd and the unified cgroup hierarchy with per-slice swap control;
- OpenSSH;
- `cryptsetup` and TPM 2.0 user-space tools;
- a TPM 2.0 device;
- one NVIDIA GPU whose kernel driver matches the running kernel and user-space version;
- a Resource Pool whose deliverable modes do not allow a conflicting allocation on the same physical host while a lease is held.

Qualification pins the exact kernel, driver and systemd versions. Any drift sends the host to quarantine.

Alternatives rejected:

- **Plain unprivileged account with an encrypted home.** World-writable paths, scheduled jobs, user service managers, logging sockets and host loopback services all persist data outside the home.
- **`ChrootDirectory` on a second SSH daemon.** Shares the host network namespace, so host loopback services and abstract sockets stay reachable.
- **A container runtime with its own SSH daemon.** Adds a runtime, a base image and host network rewiring. It remains the fallback if GPU access fails inside the chosen sandbox.
- **A passthrough VM.** That is the VM product.

### D2. Managed tenant boundary

Every tenant access method enters the same per-lease environment.

**Units.** Each lease generation `G` gets runtime units, which do not survive a reboot:

- `arkhai-lease-<G>.socket` on the buyer port;
- an accept-per-connection `sshd -i` service template;
- one slice holding every tenant process.

Socket activation allocates the listening socket in the host network namespace. Each service instance joins the lease's named network and IPC namespaces, so only the passed connection crosses into the host.

**Runtime view.**

- Root is a read-only tmpfs with `/usr` bound read-only and `/usr/local` masked.
- `/etc` is a generated per-lease directory holding only what the SSH daemon and user-space tools need:
  - `passwd`, `group` and `shadow` with root, the privilege-separation user and the tenant;
  - `nsswitch.conf` set to files;
  - the dynamic-linker cache;
  - `hosts`, the time zone and alternatives links;
  - the lease SSH daemon configuration and buyer host key;
  - resolver and CA configuration for egress.
- Nothing else from the host is mapped: no other home directory, `/root`, `/var/lib`, `/var/log`, host `/tmp`, logging or bus sockets, or TPM device.
- `/proc` hides other users' processes.
- `/dev` is private, plus the qualified GPU device nodes allowed through the device policy.

**Account.** The tenant account exists only inside the generated view, not in host NSS. The management SSH daemon therefore sees an unknown user for every authentication method.

**Lease SSH daemon.**

- PAM is disabled, so no login session or user service manager exists.
- Password and keyboard-interactive authentication are disabled.
- The authorized-keys file lives inside the lease volume, so keys the tenant adds are inside the boundary.
- Forwarding is local only; X11, tunnels and stream-local forwarding are disabled; DNS and last-log recording are off.

**Service restrictions.** Namespace creation is refused, no new privileges can be gained, SUID/SGID execution is refused, and kernel-keyring system calls are denied.

### D3. Persistent-path containment

| Path | Control |
|---|---|
| Swap | Every lease slice, and every provider unit that handles tenant plaintext or key material, has swap usage set to zero. |
| Core dumps | Hard core size limit of zero. The host crash handler is qualified for its behavior with a zero limit before any tenant is admitted, because a piped handler does not necessarily honor that limit. |
| Suspend and hibernation | Blocked while any lease volume exists. The GPU driver can write video-memory backing files during suspend, and blocking hibernation alone does not prevent that. |
| Kernel log | No persistent kernel-log sink while a tenant is exposed. The kernel logs tenant-chosen process names on several paths, so the journal's kernel reader, every other kernel-log collector, persistent console capture, pstore archiving and crash dumps are excluded. Collection is not restored while records written during the lease could still be re-read. Only fixed-schema provider events (event type, error class, timestamps) are copied to provider records, and the disabled state is visible to operators. |
| SSH daemon logs | Written to a provider-only directory inside the lease volume, which is destroyed with the key. Persistent provider records receive only fixed-schema fields: event type, time, lease generation, source address and port, and the fingerprint of the authenticated key. |

### D4. Recoverable lease storage and key custody

**Volume.** Each lease generation gets a LUKS2 volume on a fixed-size, preallocated, root-only backing file, subject to a free-space floor. Its single keyslot is unlocked by a 32-byte secret `S` passed over standard input and never written to disk, logs, the database or configuration.

**Seal.** `S` is sealed to the host TPM as a sealed data object.

- The object's authorization policy is non-empty and equals the `PolicyNV` digest of the lease counter at value `C_G`, with no other branch.
- `USERWITHAUTH` is clear, and `FIXEDTPM` and `FIXEDPARENT` are set.
- The object's public area is verified to match before prepare completes.

**Parent.** A non-exportable restricted storage primary, either rebuilt from a recorded template or held at an authorized persistent handle. Its Name must equal the recorded Name before any unseal. A transient context file is never a recovery path.

**Counter.** One counter-type NV index per host, created with the orderly attribute clear. An orderly counter can be advanced at startup after an unclean shutdown, which would break active-lease recovery.

- The index is initialized by one increment during host setup, and prepare refuses an unwritten index.
- Comparisons use the full 8-byte big-endian value.
- Prepare refuses to proceed within a fixed headroom of the maximum value, so the counter never wraps. No infinite monotonicity is claimed.
- The only recreation claim relied on is that, in the reference implementation, a recreated counter at the same index starts above the deleted counter's high-water mark. That behavior is exercised only on a software TPM.
- An NV rate limit, a write failure or an uncertain increment means quarantine.

**TPM safety.** Operations never clear the TPM, flush broadly, or touch an index or object the lease does not own. Other owners may depend on the same TPM.

**Supervised execution.** A provider-owned, content-addressed request file is
the only input to the storage oneshot. The request and its execution record are
private regular files beneath a private provider directory; the unit receives
only the request digest and a fixed root-owned profile path. It has no secret
argument, environment or output channel. The unit fixes the process in
`system.slice`, enforces zero swap and hard and soft core-size limits of zero,
kills its whole control group on stop, never restarts automatically and admits
only the explicitly configured direct TPM device. Before opening ESAPI or
mutating lease state, the executor verifies request identity and ownership,
the fixed cryptsetup path and version, the exact live unit cgroup, zero swap and
core limits, and no-new-privileges. It also reads the effective kernel
`core_pattern` from procfs and refuses a missing, unreadable, malformed or piped
handler: the inherited hard-zero limit constrains ordinary file dumps but does
not constrain a piped handler. Accepted, running,
completed, refused and quarantined transitions are durable. A changed request
or a prior running lifetime quarantines without dispatching the helper; an
uncertain systemd response is not permission to submit the request again.

**Custody lifetime.** Creation, policy evaluation, load, public verification,
unseal and cleanup run through one ESAPI connection. The production adapter
selects only an explicit provider-qualified TPM device TCTI; an injected
software-TPM transport exists only in the isolated qualification harness. The
executor checks cleanup of only the object and session handles returned within
that live connection and withholds a successful result, including an unsealed
secret, until cleanup and its durable confirmation succeed.

The sealed public and private blobs are durable recovery material. Numeric
object and session handles are not: they describe one process lifetime and may
be reused after it ends. Before a TPM resource is created or loaded, the helper
fsyncs a pending ownership record; it then fsyncs live, close-pending and
confirmed-closed transitions. Any record from a prior lifetime that is not
confirmed closed is an ownership ambiguity. Restart quarantines it without
flushing the stale number, advancing the counter again or claiming recovery.

**Prepare journal.** Before incrementing, prepare fsyncs the pre-increment value `V`.

- Counter still `V`: the increment did not happen.
- Counter `V+1` is accepted as this attempt's increment only when there is durable exclusive-writer evidence for the reserved index. Without it, prepare quarantines.
- Any other value, or an unknown `V`: quarantine without sealing.

**Guarantee.** This protects against later unprivileged tenants, provided custody and cleanup are enforced correctly. Provider root is trusted, and revocation cannot retract a plaintext copy made by root during a lease.

Alternatives rejected:

- **An ephemeral key.** Loses lease data on any reboot, and survival across an unexpected reboot was accepted as a product requirement.
- **A key file on host storage.** Deletion does not prove erasure.
- **A PCR-only TPM seal plus header erasure.** Retained header or blob copies stay usable with the same TPM.
- **Off-host custody as the sole mechanism.** Deletion from the database, backups and logs cannot be proven.
- **A general KMS.** Out of scope.

If a host's TPM lacks the required capability or authorization, that host is unqualified for this mechanism. That does not establish that no other custody design exists; any other design needs its own review.

Preparation and activation share a generation-owned activation journal admitted
only under the host/index lock. Preparation opens its TPM backend lazily after
that journal and the generation fence are admitted. Activation retains the
same lock while it revalidates immutable backing provenance, supplies the
recovered secret only to mapper open, checks final ESAPI-context closure, and
records the loop, mapper, one-time format and native-mount outcome. Before that
flow begins, the activation owner admits the exact live unit, cgroup, boot,
swap, core and effective confinement profile, including the manager-resolved
syscall filter, device allowlist and writable paths. Before format or mount it
binds the published mapper node and kernel device identity to the prepared LUKS
UUID and owned loop, and it admits the manager-resolved native mount fragment,
drop-ins and effective properties before PID 1 starts it. Pending or
quarantined intent is never an instruction to retry or clean up automatically.
The implementation remains uninstalled. One isolated synthetic run exercised
the helper-prepared secret through the production activation supervisor and
owner, with live mapper and mount state retained until whole-guest disposal.
That qualifies this bounded seam, not ordinary role preparation, physical
devices, reverse cleanup, reboot recovery or operational activation.

### D5. Recovery after restart or reboot

Only the provisioning recovery action may reopen a lease volume. All of these must hold:

- the per-host lock is held;
- host identity matches the recorded machine identity, pinned host key and GPU identity;
- generation `G` is active in the database and the host manifest;
- no release intent exists;
- the current time is before the originally persisted lease end;
- the counter equals `C_G`;
- the parent Name matches the recorded Name.

The lock is held from the start of the policy session through unseal and volume open. Recovery may continue a policy session only within the same live ESAPI ownership boundary while its dependent policy operations run. It never saves a session context or deliberately carries a session across a completed executor lifetime, and it requires an explicit checked flush plus durable confirmed-closed evidence before that lifetime succeeds. Recovery runs as a transient unit with zero swap, inherited hard and soft core-size limits of zero, and refusal of a piped effective core handler, and it never writes the lease window.

**Session-creation evidence.** Before any helper creates a policy session or loads the sealed object, it durably records a pending session intent in the host manifest (generation, attempt and helper unit) and fsyncs it. Only then does it create the session, and it records the returned handle before using it. Pending intents, partial records, and each helper's unit and exit evidence are retained, including for interrupted helpers, and cleanup never removes them.

A pending intent without a recorded, confirmed-closed handle is an ownership gap: the TPM may hold a lease-owned session the host never recorded. Recorded handles alone therefore do not show that no lease-owned session exists. An ownership gap is closed only by the qualified TPM restart of the release reboot (D6). Until then it blocks release completion, and if that restart cannot be shown to invalidate lease sessions, the host is quarantined. Reconciliation never enumerates or flushes TPM handles it cannot attribute to the lease, so unrelated TPM state is never flushed.

Fail-closed paths:

- A lease that expired, or whose release was requested while the host was unavailable, goes straight to release without unsealing.
- A missing TPM, missing tools or any failed check means no access, and the lease proceeds through the physical release path.

### D6. Release sequence and completion

Cancellation, expiry and delivery failure all enter the fulfillment teardown that the lease lifecycle already tracks. Bare-metal release uses the same narrow fulfillment-teardown port and durable `fulfillment_id` tracking as VM release: the lease lifecycle neither submits nor polls a reclaim job, and the sequence below is the bare-metal fulfillment provider's teardown, dispatched and retried by fulfillment convergence.

**Sequence.**

1. Acquire the per-host lock.
2. Confirm generation through a conditional state transition.
3. Verify host identity.
4. Durably record release intent in the database and host manifest.
5. Stop the lease socket.
6. Stop the lease slice and kill any remaining processes.
7. Increment the counter, following the retry rules below.
8. Terminate recovery helpers, retaining their pending session intents and partial records, and invalidate every recorded lease-owned TPM session or object handle.
9. Close the volume, then remove the backing file and sealed object as hygiene. Nothing relies on that removal.
10. Reboot.
11. Verify.

**Reboot gate.** The reboot may proceed while this lease's own retained allocation hold remains. Any other allocation on any alias of the physical host refuses it. Capacity is never released in order to permit a reboot.

**Counter retry rules.**

- Increment only when the recorded generation is still `G` and the counter equals `C_G`.
- A counter above `C_G` with this release's intent recorded means already revoked.
- Never increment on behalf of a generation older than the newest recorded one.

**Release is complete only when all of these hold** (incrementing the counter is not enough on its own):

- no recovery helper remains, and every recorded lease-owned session and object handle is confirmed absent;
- every pending session-creation intent is reconciled: its handle was recorded and confirmed closed, or the qualified TPM restart below has closed the ownership gap. An unreconciled gap fails closed into quarantine;
- the counter is above `C_G`;
- the volume mapping is closed and no lease plaintext path remains;
- the reboot shows both a changed boot identity and a TPM restart that qualification has shown invalidates lease-owned sessions;
- an unseal attempt against the retained sealed object in a fresh session fails;
- host identity, management reachability, pinned versions, GPU presence and health, and the provider service baseline all verify.

A changed boot identity alone does not prove that TPM sessions were invalidated. This matters because a policy session satisfied before the increment can still authorize an unseal afterwards: the policy is evaluated when the session is built, not when the object is unsealed.

### D7. Failure classes and quarantine

| Class | Triggers | Action |
|---|---|---|
| Unsafe to continue | Identity mismatch, generation mismatch, missing or corrupt manifest, another active generation, lock not acquired, recorded object identity mismatch | No further mutation. Persist quarantine and an operator notification. |
| Exposure reduction | A failed step on this generation's own validated objects | Continue stopping ingress and terminating the lease slice, revalidating before each step. |
| Destructive | Storage closure and removal, reboot | Only after revalidation under the lock. |

**Quarantine** is a site-authority eligibility state covering every resource and offering-mode alias of the physical host.

- Accounting force-release and automatic teardown retries never clear it.
- Administrator recovery is authenticated and audited, and requires a fresh verification newer than the quarantine record. Its boot-identity comparison is against the last point at which the tenant was exposed, so an already reconciled reboot is accepted.

**Unreachable host.** The physical effects are unknown, so the host is quarantined and its capacity stays held. Financial behavior is unchanged.

### D8. Egress containment

**Networking.** A veth pair connects the lease network namespace to the host, with masquerade through the default route. A dedicated `inet` firewall table matching only lease interfaces carries the rules. Existing host rulesets are not modified.

**Denied destinations:**

- IPv4: `0.0.0.0/8`, `10.0.0.0/8`, `100.64.0.0/10`, `127.0.0.0/8`, `169.254.0.0/16` (including metadata addresses), `172.16.0.0/12`, `192.0.0.0/24`, `192.0.2.0/24`, `192.168.0.0/16`, `198.18.0.0/15`, `198.51.100.0/24`, `203.0.113.0/24`, `224.0.0.0/4`, `240.0.0.0/4`, broadcast;
- the host's own addresses;
- an operator-supplied provider-endpoint set. An empty set refuses prepare.

**Dual stack.** IPv6 is disabled inside the lease namespace and dropped on lease interfaces. If it is enabled later, the equivalent classes are denied (`::1`, `fe80::/10`, `fc00::/7`, `ff00::/8`, `::ffff:0:0/96`, `64:ff9b::/96`, `2002::/16`, documentation prefixes, and provider IPv6 endpoints). Prepare refuses unless the lease table is present and matches for both families.

**Scope.** The initial profile adds no public inbound service endpoint. Future service exposure is subject to site policy.

**Limitation.** These rules block direct connections only. Applications can tunnel or relay over permitted public connections, so provider endpoints reachable from the internet must still enforce their own authentication.

### D9. GPU state

- Tenant termination, device-access revocation, and a supported reset or health check are release steps. They are not sanitation evidence.
- A CUDA allocation is not documented as cleared, and driver-reserved memory is outside user allocations, so an allocate-and-overwrite pass is not a sanitation mechanism.
- Sampled residue tests in a fresh context are detection evidence only.
- Whether GPU residue can cross tenants is a qualification gate for the exact GPU and driver. Until it is resolved, a released host may complete release but is not relisted to a different tenant.

### D10. Workload proof

The renter connects through the advertised buyer endpoint and runs a small program that:

- loads the CUDA driver library;
- launches a fixed PTX kernel over a small integer array;
- checks every output exactly;
- reports the device UUID, which must match the qualified GPU.

There is no CPU path, no toolkit installation and no model download.

### D11. Publication convergence

- A capacity cursor advances only after the work it acknowledges succeeds; otherwise an explicit pending reconciliation persists and is retried.
- Held and quarantined capacity stays closed.
- Relisting uses the current request fields, signing and supported registry transitions.
- Intended request and target identity are persisted, and uncertain remote writes are reconciled through exact authenticated readback before any retry.
- Local state is committed only after confirmation.
- A remote publication failure keeps publication pending and does not repeat completed physical release steps.

### D12. Source disposition

Behavior from earlier bare-metal development work is carried selectively through this branch's current contracts (`listing_resource`, `offering_mode`, current migrations):

- **Ported with tests:**
  - canonical lease-account admission and the separate buyer SSH port, including the producer, storage, inventory and result chain;
  - pinned provisioning SSH trust through Helm;
  - registry credential validation with sanitized failures;
  - neutral SSH access-proof helpers.
- **Used only as reference:** close, reopen and readback implementations.
- **Not revived:** older resource fields and SQL columns.

### D13. Evidence levels

| Level | What it proves |
|---|---|
| Unit | Decision tables and rendering |
| Integration | The real application, database and typed clients, with a controlled executor boundary |
| Disposable software TPM and VM | Custody, recovery, revocation, containment and egress |
| Disposable native storage guest | Synthetic loop, mapper, filesystem, PID 1 mount and checked cleanup under the candidate authority profile |
| Physical qualification | Execution on a real host |

Controlled-boundary results are never reported as physical proof, and evidence from different rentals is never combined into one lifecycle claim.

## Qualification gates

Each gate is a precondition for automatic reuse of a physical host, not an implemented guarantee:

1. TPM counter support, NV space and the authorizations needed to create the lease counter and parent, without affecting other owners of the same TPM.
2. A GPU kernel driver loaded for the running kernel, the device node set, the qualified device identity, and no display or other consumer on the device.
3. Persistent-path controls in place: crash handler, suspend and hibernation, kernel-log sinks, swap accounting.
4. TPM restart and lease-owned session invalidation observed across the release reboot.
5. Cross-tenant GPU residue evaluated for the exact GPU and driver.
6. Management access and protected provider data and services preserved across prepare, recovery and release.

## Risks

- **Sandbox feasibility.** Running `sshd -i` with privilege separation inside the sandboxed unit, and GPU access inside the private device and process view, are unverified until tested. If GPU access fails, the fallback is a container-based environment, which needs its own review.
- **OpenSSH locked-account handling.** With PAM disabled, it depends on build-time definitions. The generated shadow entry is chosen from the installed build, and key-only authentication is verified by test.
- **TPM availability.** A TPM clear, firmware reset of the TPM, or hardware replacement makes lease data unrecoverable. The lease then fails closed through release.
- **Log visibility.** Disabling persistent kernel-log collection during leases reduces diagnostic history on the host. The disabled state is surfaced to operators.

## Open questions

None. Each unresolved physical fact above is an explicit qualification gate, not a decision deferred to implementation.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Lease accounts are derived from settlement identity, never caller-supplied | `openspec/specs/physical-provisioning/spec.md` — "Bare-metal lease accounts are derived, not supplied" (promoted) |
| Tenant endpoint is recorded and reported separately from the management endpoint | `openspec/specs/physical-provisioning/spec.md` — "A bare-metal host's tenant endpoint is distinct from its management endpoint", rationale in `architecture.md` — "The host registry owns the connection" (promoted) |
| Pinned SSH trust binds the selected host at the effective connection boundary | `openspec/specs/physical-provisioning/spec.md` — "Managed bare-metal access reaches only the selected pinned endpoint", rationale in `architecture.md` — "Pinned access to the selected host" (promoted) |
| Absent or changed host trust refuses before the host is contacted | `openspec/specs/physical-provisioning/spec.md` — "Absent or changed bare-metal host trust refuses before contact" (promoted) |
| Account operations report only read-back-verified outcomes, bounded to the current database | `openspec/specs/physical-provisioning/spec.md` — "Bare-metal account operations report only verified outcomes", limit stated in `architecture.md` — "Pinned access to the selected host" (promoted) |
| Registry write credentials are sanitized and publication failures are truthful | `openspec/specs/storefront-publication/spec.md` — "Registry write credentials are sanitized and publication failures are truthful" (promoted) |
| Roadmap disposition | `docs/development/ROADMAP.md` — no goal or gap row names this change; nothing owed (recorded) |
| Campaign index currency | `openspec/changes/README.md` — this change's row records the accepted section 1 and 2.1 checkpoints, verified 2.2 custody and supervision seams, one simulated preparation/retry composition, the bounded native synthetic mapping/mount prerequisite and the prepared-secret activation checkpoint, with overall integration and later sections outstanding (recorded) |
| Managed tenant boundary and runtime view | `openspec/specs/physical-provisioning/spec.md` (pending) |
| Persistent-path containment | `openspec/specs/physical-provisioning/spec.md` (pending) |
| Serialized lease-storage preparation and same-process checked TPM custody | `openspec/specs/physical-provisioning/spec.md` — "Encrypted lease-storage preparation is isolated and fail-closed", rationale in `architecture.md` — "Lease-storage custody has one live owner" (promoted; operational integration remains pending) |
| Provider-owned supervised storage request seam | `openspec/specs/physical-provisioning/spec.md` — "Encrypted lease-storage preparation is isolated and fail-closed", rationale in `architecture.md` — "Lease-storage custody has one live owner" (promoted; role installation and ordinary invocation remain pending) |
| Synthetic mapping, filesystem, native mount and checked-cleanup prerequisite | `openspec/specs/physical-provisioning/spec.md` — "Encrypted lease-storage preparation is isolated and fail-closed", rationale and authority limitation in `architecture.md` — "Lease-storage custody has one live owner" (promoted; production activation and recovery remain pending) |
| Generation-bound prepared-secret activation owner and bounded runtime checkpoint | `openspec/specs/physical-provisioning/spec.md` — "Encrypted lease-storage preparation is isolated and fail-closed", rationale and qualification limits in `architecture.md` — "Lease-storage custody has one live owner" (promoted; installation, physical devices and recovery remain pending) |
| Active-lease storage recovery and release-time counter revocation | `openspec/specs/physical-provisioning/spec.md` and `architecture.md` (pending) |
| Release sequence, completion and fencing | `openspec/specs/physical-provisioning/spec.md` and `docs/development/ARCHITECTURE.md#release` (pending) |
| Egress containment | `openspec/specs/physical-provisioning/spec.md` (pending) |
| Quarantine eligibility and administrator recovery | `openspec/specs/site-capacity/spec.md` (pending) |
| Confirmed relisting and cursor acknowledgement | `openspec/specs/storefront-publication/spec.md` and `architecture.md` (pending) |
| Custody ownership rationale | `openspec/specs/physical-provisioning/architecture.md` — "Lease-storage custody has one live owner" (promoted) |
| Remaining qualification limits and GPU residue boundary | `openspec/specs/physical-provisioning/architecture.md` (pending) |
