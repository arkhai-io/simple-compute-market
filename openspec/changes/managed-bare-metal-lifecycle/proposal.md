## Why

A bare-metal whole-host lease can be granted and reclaimed today, but the reclaim is not a physical release a second, unrelated tenant can rely on:

- reclaim removes one SSH key or locks or deletes one account under a configurable policy, and the access role suppresses account lock and delete failures while still reporting success;
- keys the tenant added, live sessions, background processes, scheduled jobs and persistent writes outside the tenant's home survive reclaim;
- a missing release delegate is treated as immediately complete, so capacity can return with no reclaim at all;
- nothing sanitizes, resets or verifies the host before capacity returns, and the host can be relisted while its physical state is unknown;
- initial and ledger-reset capacity reconciliation can be acknowledged before it succeeds, so a failed reconciliation is never retried.

Safe reuse of a physical host requires one durable release path that stops tenant execution, revokes every access path, makes the tenant's persistent data unrecoverable, resets and verifies the host, and keeps the host unavailable whenever any of that is uncertain. The existing lease lifecycle, fulfillment convergence, site authority and capacity-publication owners carry this behavior; this change adds none of its own.

## What Changes

- **Account, endpoint and trust hardening.** Lease accounts are canonical and provider-owned; arbitrary operator-supplied account names are rejected before privileged execution, and host-side ownership is verified rather than inferred from a name. The buyer endpoint is separate from the management endpoint from ingestion through the returned credentials. The managed-host profile requires pinned SSH host trust.
- **Managed tenant boundary.** Every tenant access method (shell, command execution, file transfer, tenant-added keys) enters one per-lease sandboxed environment reached through a per-lease socket-activated SSH daemon. The tenant has no host account, no privileged group, no container runtime, no raw device, no TPM device and no management credential. It sees a minimal generated runtime view, its own network and IPC namespaces, and one encrypted persistent volume.
- **Persistent-path containment.** Every tenant-writable persistent location lives inside the lease volume. Swap, core dumps, crash handlers, suspend-time driver backing files, kernel log persistence and SSH daemon logs are each either excluded or confined to the volume while a tenant is exposed.
- **Recoverable encrypted lease storage.** Each lease generation's volume survives an unexpected host reboot during the active lease. Its unlock secret is sealed to the host TPM under a policy bound to a monotonic TPM counter. Release advances the counter, so a retained copy of the sealed object or volume header cannot be unsealed afterwards. Revocation does not depend on deleting data from storage.
- **One durable, fail-closed release.** Cancellation, expiry and delivery failure share one serialized, generation-fenced release: fence ingress, terminate execution, revoke the storage secret, invalidate lease-owned TPM sessions, close storage, reboot, verify, and only then return capacity. Any uncertain step quarantines the physical host across every resource alias until an administrator recovers it with fresh verification evidence. Bare-metal release never treats a missing release mechanism as success.
- **Public egress with private destinations denied.** The lease network namespace reaches the public internet through a dedicated firewall table. Private, carrier-grade NAT, loopback, link-local (including cloud metadata), multicast, reserved and documentation ranges, the host's own addresses, and an operator-supplied provider-endpoint set are denied for IPv4 and IPv6. Enforcement fails closed.
- **Restart-safe composition.** The physical lease window and selected host are persisted once. Recovery never extends a lease or selects another host, and late or duplicate results are bound to the exact lease generation.
- **Confirmed relisting.** Held and quarantined capacity stays closed. Relisting succeeds only after confirmed signed remote readback, and a capacity cursor advances only after the work it acknowledges has succeeded.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: managed tenant environment, persistent-path containment, recoverable lease storage with counter revocation, serialized generation-fenced release and recovery, reboot and verification, egress containment, fail-closed bare-metal release completion, pinned selected-host SSH trust enforced at the effective connection boundary with refusal on an absent or changed pin, and bare-metal account operations that report only read-back-verified outcomes.
- `site-capacity`: physical quarantine excludes a host from admission across every offering-mode alias; accounting force-release does not clear it; administrator recovery requires fresh verification.
- `storefront-publication`: capacity publication confirms release relisting through authenticated readback, never acknowledges reconciliation it has not completed, and sanitizes registry write credentials while reporting publication failures truthfully.

## Impact

- Bare-metal domain: `domains/bare_metal/src/arkhai_bare_metal/` (lease account admission, schema).
- Bare-metal provisioning adapter: `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/{runtime,release}.py` and `services/{bare_metal_operations_service,bare_metal_fulfillment_provider}.py`, plus the package's missing test entrypoint and CI coverage.
- Host automation: `domains/vms/provisioning/iac/ansible/roles/bare-metal-access/` and its tests in `domains/vms/provisioning/iac/tests/`.
- Compute provisioning: `provisioning/compute/src/compute_provisioning/lease_lifecycle.py` and `provisioning/compute/service/src/compute_provisioning_service/{config.py,db/}`.
- Site authority: `kit/site/src/market_site/{authority,ledger,db}.py` for quarantine eligibility.
- Capacity publication: `kit/capacity-publication/src/market_capacity_publication/{capacity_remote,publication}.py` and the bare-metal publication wiring.
- Deployment: `helm/charts/provisioning/` for pinned provisioning SSH trust.
- Database: additive migrations for release intent, lease generation, storage and key custody records, quarantine state and pending reconciliation. No existing column is removed or repurposed.

## Non-Goals

- Any payment work: hosted or blockchain configuration, payment-ready or financial callbacks, collection, capture, refund, payout, payment-state migrations, mechanism selection, funded-deal tests or live financial actions. Existing settlement behavior, including financial cleanup guards, stays unchanged. Physical release completes without any financial service participating.
- A full-control or root-capable tenant tier, BMC, PXE, firmware management, or provider hardware configuration choices.
- An inference server, model download, cache demonstration or public inbound service endpoint.
- A general sandbox, container or key-management platform. One managed host profile is implemented.
- Retiring the `vm_remove_job_id` mirror or the multi-language credits middleware signing work, which stay with their owning changes.
- VM or API-credit feature work beyond the parity tests required if a shared publication contract changes.

## Qualification boundary

Accepting this design authorizes implementation and tests at the unit and integration levels, and in explicitly designated disposable environments (a software TPM and a disposable VM). It is not physical qualification. A managed host becomes eligible for automatic reuse only after it passes the qualification gates recorded in `design.md`. Those include:

- TPM capability and authorization on the physical host;
- the GPU driver and device state;
- persistent-path controls;
- verification of lease-owned TPM session invalidation;
- cross-tenant GPU residue evaluation.

A host that has not passed those gates may complete release but remains unavailable for a different tenant.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` (Release; Recovery workers)
- [x] Existing subsystem specification: `openspec/specs/{physical-provisioning,site-capacity,storefront-publication}/spec.md`
- [x] Existing subsystem architecture companions: `openspec/specs/physical-provisioning/architecture.md`, `openspec/specs/storefront-publication/architecture.md`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

Promoted, and therefore describing current behavior rather than a proposed delta:

- Derived lease accounts, the tenant endpoint distinct from the management endpoint, selected-host pinned SSH trust with refusal on an absent or changed pin, and account operations reporting only read-back-verified outcomes are in `physical-provisioning/spec.md`, with the rationale for enforcing trust at the effective connection boundary, the endpoint distinction, and the account-database read-back limit in `physical-provisioning/architecture.md`.
- Registry write-credential sanitization and truthful publication failure reporting are in `storefront-publication/spec.md`.

Still held by this change, because the behavior is not implemented:

- Managed tenant boundary, persistent-path containment, recoverable storage and counter revocation, release sequence, and egress containment go to `physical-provisioning/spec.md`, with their rationale, trade-offs and qualification limits in `physical-provisioning/architecture.md`.
- Quarantine eligibility and administrator recovery go to `site-capacity/spec.md`.
- Confirmed relisting and acknowledged-work cursor semantics go to `storefront-publication/spec.md` and its architecture companion.
- The release flow and recovery-worker ownership are summarized in `docs/development/ARCHITECTURE.md`.
