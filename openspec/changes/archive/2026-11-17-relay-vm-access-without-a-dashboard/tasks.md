# Implementation Tasks

Paths are relative to the repository root. IaC paths are under
`domains/vms/provisioning/iac/`.

This change touches five packages, the IaC project, and the provisioning chart.
Ordering matters: sections 1–3 make the service able to allocate and forward,
section 4 makes the host able to receive it, and section 5 rewires VM creation
onto both. Landing 5 before 1–4 leaves VM creation calling a dashboard that is
already gone. Section 1A is the administration surface and depends only on
section 1. Section 9 is what makes a deployment reach a working relay without an
operator API call; it depends on section 1's schema, and its first task fixes
the startup invocation that would otherwise undo section 1A on every pod
restart.

Nothing here needs a live relay to implement. Sections 6 and 8 need one, and
their evidence is supplied by the operator.

## 1. Relay resource, token storage, and configuration reads

A relay is a row, not pool configuration. Sections 1 and 2 carry completed
tasks whose schema this design supersedes; those tasks are preserved with an
amendment rather than rewritten, and the replacement work is appended.

- [x] 1.1 Remove the relay keys from the `connectivity` payload built by
      `_connectivity_settings_from_storefront_config` in
      `domains/vms/storefront/src/market_storefront/services/fulfillment_service.py`:
      `frp_server_addr`, `frp_domain`, `frp_dashboard_password` all go, and
      nothing relay-related replaces them. Which relay a host dials is a
      property of the deployment, so the storefront stops naming one per
      request; the buyer-facing address is returned in the fulfillment result
      instead.
- [x] 1.2 The relay **token does not travel this way.** It is a credential and
      the storefront has no reason to hold one. Confirm the function returns no
      relay field and nothing secret.
- [x] 1.3 Apply the same removal in
      `domains/vms/storefront/src/market_storefront/services/vm_fulfillment_service.py`,
      which builds the same payload on the VM path. Two call sites, one shape;
      a test asserting they agree belongs in section 7.
- [x] 1.4 Remove the three `[provisioning]` relay keys and their comments from
      `domains/vms/storefront/src/market_storefront/settings.toml` and
      `domains/vms/storefront/src/market_storefront/groups/config.py`.
- [x] 1.4a Add `relay_addr`, `relay_port`, `vm_port_range_start`, and
      `vm_port_range_count` to `AnsiblePoolConfig` in
      `provisioning/compute/service/src/compute_provisioning_service/db/models.py`,
      all nullable: a pool with no relay configured uses the direct-NAT path.
      Add the migration and register it in `MIGRATIONS`.

      **Amended by 1.8.** These four columns are superseded by a relay row. The
      window cannot live on the pool: two pools may reference one relay, and
      per-pool windows let them allocate from one listening namespace under
      disagreeing bounds. The migration has not been applied in any
      environment, so it is edited rather than followed by a second one.
- [x] 1.4b Extend the pool-configuration read/write path (`PoolConfigHandler`
      and the pool API models) so an operator can set and read the relay
      reference, following how `default_vm_ram` and its siblings are already
      carried.

      **Amended:** what a pool carries is a reference to a relay, not the
      endpoint and window themselves. The token is never among the fields a
      read returns; see 1.10.
- [x] 1.7b **Say what the relay table models, in its docstring.** It currently
      reads "a tunnel rendezvous that hosts dial", which describes the *host
      management* tunnel — the failsafe an operator reaches a host through when
      `sshd` is unusable. That one is static for the whole provisioning service,
      established when a host is prepared outside this repository, and is not in
      this table. This table is the VM-facing rendezvous that a host's VM tunnel
      client dials on behalf of rented VMs. The two may be the same server and
      are constantly confused; the docstring is where that stops.
- [x] 1.8 Add a `relays` table to
      `provisioning/compute/service/src/compute_provisioning_service/db/models.py`:
      an identifier, `relay_addr`, `relay_port`, `vm_port_range_start`,
      `vm_port_range_count`, an encrypted token column, `enabled`, and
      timestamps. **`UNIQUE(relay_addr, relay_port)`** — one rendezvous cannot
      be recorded twice, which is what stops one relay appearing under two
      identities and issuing the same port to two callers.
- [x] 1.8a Replace the four relay columns on `AnsiblePoolConfig` with a
      nullable foreign key to a relay. Nullable because a pool with no relay
      serves VMs by direct NAT, which stays supported.
- [x] 1.8b Remove the derived `relay_id` property added by 1.4a. Identity is
      the referenced row. Keep the normalization it performed and apply it on
      write to `relay_addr` instead, so two spellings of one endpoint collide
      on the unique constraint rather than creating two rows.
- [x] 1.9 Store the token encrypted, using `encrypt_key` from
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/crypto.py`
      with the `ssh_decryption_key` setting — the same profile key that already
      protects embedded host key material. The database holds ciphertext, so a
      stored token is not a usable credential without a key held outside it.
      *Since moved (2026-10-05, `bare-metal-mock-provisioned-deal`): the VM
      adapter's `crypto.py` is gone; encryption at rest is `encrypt_secret` in
      `kit/config/src/market_config/secret_at_rest.py`, under the same key.*
- [x] 1.9a Do not add a second encryption setting. One profile key with two
      uses is one thing for a deployment to rotate; two keys protecting
      material of the same class is a second rotation path that will drift from
      the first.
- [x] 1.9b **Put the encryption primitive in `kit/config`.** Encrypting a
      configured secret at rest is part of the configuration pattern, not a
      property of VMs, of provisioning, or of this service — `arkhai-kit-config`
      already owns shared configuration loading. An earlier step moved it from
      the VM adapter into the service on the grounds that the key is a service
      setting; that was the right direction and one layer short.
- [x] 1.9c Check the dependency layers before wiring it, per `AGENTS.md`. The
      service and both provisioning adapters would gain a dependency on
      `arkhai-kit-config`; confirm that runs with the layering rather than
      against it, and that `TYPE_CHECKING` imports are counted.
- [x] 1.9d Leave a re-export where the primitive used to live only if a caller
      outside this change still needs it. Otherwise move the call sites.
- [x] 1.10 Split provider-configuration reads in two, in
      `kit/resource-pools/src/market_resource_pools/pool_config_handler.py`
      (the Protocol),
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/ansible_pool_config_handler.py`,
      and
      `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/services/bare_metal_pool_config_handler.py`.
      `read_config` returns no secret and keeps its name; a separately named
      execution read returns the decrypted token. The unqualified name belongs
      to the safe read so that a caller which does not ask for secrets does not
      receive them — a forgotten opt-in then breaks dispatch loudly rather than
      leaking on a read path.
- [x] 1.10a Prefer a distinct method to a boolean parameter. A method name can
      be searched for and cannot be supplied by a stray positional argument.
- [x] 1.10b Route the execution read through the fulfillment path only:
      `get_pool_in_session` in
      `kit/resource-pools/src/market_resource_pools/service.py` gains an
      execution-scoped sibling, and
      `kit/fulfillment/src/market_fulfillment/fulfillment.py` calls it where it
      currently calls `get_pool_in_session`. Leave `_attach_provider_config`,
      `export_pools_yaml`, and `_calculate_reconciliation` on the redacted read.
- [x] 1.11 Make an omitted token preserve the stored value, in `replace_config`
      for both handlers. `update_pool` reads through the redacted read and
      writes back what it read, so without this a request changing only a label
      round-trips a configuration with no token and erases the credential. This
      is an explicit exception to the pool API's replacement semantics, which
      otherwise reset omitted fields; the exception exists because a caller
      cannot restate a value no read ever returned.
- [x] 1.11a Provide no way to clear a token through a partial write. Clearing
      one disables every VM path on that relay and should be an explicit act,
      not an omission.
- [x] 1.12 Return a boolean indicating whether a token is configured, on relay
      and pool reads. An operator needs to answer "is this relay usable" from a
      read without the value being disclosed, and a boolean is sufficient
      because nothing compares tokens across systems.
- [x] 1.13 The relay controller is section 1A. It is the administration surface
      for everything above and is load-bearing rather than incidental: a relay
      is changed through it, not by redeploying.
- [x] 1.14 Fold the relay table, the pool foreign key, and the lease table into
      the single migration `20260901_001_relay_reachable_hosts` rather than
      appending a second. It has not been applied in any environment, so
      editing it costs nothing and keeps the operator step singular.
- [x] 1.7 Forward the token as `frp_auth_token` from
      `_build_builtin_var_lines` in
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/ansible_service.py`,
      which currently passes `frp_server_addr`, `frp_domain`, and
      `frp_dashboard_password`, and no token at all. The value comes from the
      execution read, never from a pool response.
- [x] 1.7a Confirm the token does not reach the job's persisted variable
      snapshot in cleartext, or if it must, that the snapshot is not returned by
      any read path. Follow how the existing redaction in `ansible_service.py`
      treats `password` and `ssh_key_path_host`.
      *Since moved (2026-10-05, `bare-metal-mock-provisioned-deal`): the VM
      adapter's `ansible_service.py` is gone. VM's codec forwards the token
      (`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/codec.py`),
      lists `frp_auth_token` among `VM_SECRET_FIELDS`, and the Ansible
      distribution redacts those fields
      (`provisioning/compute/ansible/src/compute_provisioning_ansible/runner.py`,
      `redact_ansible_output`).*

**Validation:** `make test` in `domains/vms/storefront`,
`provisioning/compute/service`, `domains/vms/provisioning`, and
`kit/resource-pools`.

## 1A. The relay controller

The administration surface for relays. It is what makes a relay changeable
against a running service, which is the property the whole resource shape exists
to provide — and the property section 9's seeding must not quietly take back.

- [x] 1A.1 Add `relays_controller.py` alongside
      `provisioning/compute/service/src/compute_provisioning_service/controllers/pools_controller.py`,
      following its authentication and router-registration pattern rather than
      inventing a second one.
- [x] 1A.2 Implement create, list, detail, and update. Update covers the
      rendezvous address, port, and window, so a relay can be repointed without
      recreating it and without invalidating the leases held against it.
- [x] 1A.3 Implement token rotation as an explicit operation rather than as a
      field on a general update. Rotation is the one write whose effect is
      invisible in every read, so it should be requested deliberately and
      should be distinguishable in an audit log from an edit that happened to
      carry a token.
- [x] 1A.4 Return `relay_token_configured` and never the token, on every
      response this controller produces. The redacted read from 1.10 is what
      serves it; the controller does not reach past it.
- [x] 1A.5 Implement enable and disable. Disable is what section 3 rejects a
      dispatch against, and it is the operator's answer to "stop using this
      relay" without deleting a row that leases still reference.
- [x] 1A.6 **Do not implement deletion.** `design.md` records it as an open
      question: a relay with live leases cannot simply be removed, and
      refusing, disabling, or cascading a release are all defensible. Task
      1A.7 is the gate.
**Moved (2026-10-05).** `bare-metal-mock-provisioned-deal` task 5B.9 moved the relay
code from the provisioning service into the VM adapter
(`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/`): the relay services
(`relay_service.py`, `relay_definitions.py`, `relay_rebinding.py`,
`relay_port_allocator.py`, `relay_execution.py`) under `services/`; the `Relay`,
`RelayPortLease`, and `AnsiblePoolConfig` models in `db.py`; and the relays controller as
the router factory `controllers/relays_controller.py`. The release on a fulfillment's
terminal transition is now VM's contributed terminal effect
(`release_fulfillment_ports`), which fulfillment convergence and the release guard run;
the relay definitions document and the port reconciliation are VM's contributions too.
The relay routes admit only the administrator. Completed tasks below keep the paths they
were done at; the open ones name none of the moved files.

- [x] 1A.7 **Decide and record** the deletion semantics in `design.md` once
      section 2's reconciliation behaviour is settled, then implement the
      decision or record why it stays deferred. This is a decision task, not an
      instruction to implement one of the three.
      *Met:* nothing deletes a relay, and disabling one drains it (`design.md`
      D1–D5, on the owner's direction after closeout returned it to design on
      2026-11-16), implemented by sections 10a–10e.
- [x] 1A.8 Reject an update that would duplicate another relay's rendezvous,
      with both relay identifiers named. The unique constraint would catch it,
      but a constraint violation surfacing as a 500 is not an administration
      surface.
- [x] 1A.9 Register the router where the pools router is registered, and add it
      to whatever surface enumerates routes for the typed client, so the Level 2
      suite can drive it through the canonical client rather than a hand-built
      request body.

**Validation:** `make test` in `provisioning/compute/service`, including the
Level 2 integration suite, since the controller is a contract rather than an
internal seam.

## 1B. Relay rebinding and drain

A relay is bound to a VM at creation and recorded on its lease. Nothing moves an
existing VM between relays, because the buyer already holds the rendezvous
address and the port, and a remote port is not portable between relays. See
`design.md`; the rule below is the whole of what enforces it.

- [x] 1B.1 Reject a change to a pool's `relay_id` while any host in that pool
      holds an active lease. Name the host and the lease in the rejection: an
      operator who has to drain needs to know what is holding it open.
- [x] 1B.2 Reject a change to a host's pool assignment under the same
      condition, in the host service.
- [x] 1B.3 Reject a change to a relay's `relay_addr` or `relay_port` while that
      relay holds an active lease. This is the same rule seen from the relay
      side and affects every host on it at once.
- [x] 1B.4 Allow all three unconditionally when the relay is identical on both
      sides of the change. Nothing about a delivered connection string moves, so
      there is nothing to protect.
- [x] 1B.5 **Do not add a drain primitive.** Disabling a pool already excludes
      it from new scheduling without invalidating active workloads — see
      `openspec/specs/resource-pool-management/spec.md`, "Non-destructive pool
      lifecycle". Rebinding is disable, wait, rebind, re-enable. Adding a second
      draining concept beside the existing one would leave two things to
      understand and keep consistent.
- [x] 1B.6 State the drain sequence in the rejection message rather than only in
      documentation. The operator hitting this rule is the operator who needs to
      know what to do about it.
- [x] 1B.7 Record in `design.md` that relay uniformity per host is an
      implementation limit of one client per host, not a model limit — the lease
      already carries a per-VM relay. If section 6's gate forces one client per
      VM, this rule relaxes with no schema change. Do not build per-VM clients
      to obtain that.

**Validation:** `make test` in `provisioning/compute/service`.

## 2. Service-side port allocation

The service allocates; the playbook applies what it is given. Recorded decision;
see `design.md` for why, and for the revisit trigger.

- [x] 2.1 Add a `relay_port_leases` table to
      `provisioning/compute/service/src/compute_provisioning_service/db/models.py`:
      `relay_id`, `remote_port`, the host, the fulfillment or job that holds it,
      a state, and timestamps. **`UNIQUE(relay_id, remote_port)`** — not
      `(host, port)`. `remotePort` binds a listening socket on the relay, so two
      hosts on one relay share the port namespace; a host-scoped key would issue
      a port already bound, and the refusal would appear asynchronously in a
      client log rather than as a failed allocation.

      **Amended by 2.1b.** The table and its uniqueness survive unchanged. Only
      what `relay_id` refers to changes: a foreign key to a relay row rather
      than a string derived from an address.
- [x] 2.1a Derive `relay_id` from the normalized `relay_addr:relay_port` held in
      the owning pool's configuration. Not a separately administered
      identifier, and **not the pool id**: two pools may point at one relay, so
      a pool-scoped key would issue a port another pool already holds. See
      `design.md` for both, and for the `relays`-table revisit.

      **Superseded by 2.1b.** The revisit trigger fired: the credential moved
      into the database, which left the pool as the only home for a relay fact
      and made per-pool windows reachable by ordinary configuration.
- [x] 2.1b Make `relay_id` a foreign key to the relay row added in 1.8, and
      resolve it through the pool's relay reference rather than by assembling a
      string. The uniqueness that 2.1 established is unchanged and its tests
      still hold: one relay cannot issue a port twice, two hosts on one relay
      cannot share a port, two pools on one relay cannot share a port, and two
      relays may each issue the same port. What changes is that identity
      survives a relay changing address.
- [x] 2.2 Schema ships as **one** migration, `20260901_001_relay_reachable_hosts`,
      covering `hosts.ssh_port`, the pool relay columns, and the lease table.
      A schema version costs an operator step whether or not it carries much,
      and these deploy together, so they are one event rather than three.
      Appending makes `check_schema_version` require it before startup — a
      deployment consequence, recorded in section 10.

      **Amended by 1.14.** Still one migration; its contents grow to carry the
      relay table and the pool foreign key in place of the pool relay columns.
- [x] 2.3 Allocate on VM creation: first free port in the **relay's** window,
      recorded before the job is dispatched. Allocating after dispatch means a
      crash between the two leaves a port bound on the relay that no record
      claims.
- [x] 2.4 Release on **every terminal outcome**, not only teardown: a dispatch
      that never starts, a permanently failed creation, a cancellation, and an
      expiry each end a VM's life without a teardown running. A release attached
      to teardown alone leaks on all four.
- [x] 2.4a Add reconciliation: a periodic sweep releasing leases whose owning
      job or fulfillment has been terminal beyond a grace period. A set of code
      paths is never provably exhaustive, and this bounds the leak from the one
      that was missed. Follow the existing recovery-worker pattern rather than
      inventing a second scheduling mechanism.
- [x] 2.5 Fail the request when the window is exhausted for that relay, with a
      message naming the relay and the window. A relay refusing a proxy surfaces
      asynchronously in a client log; an exhausted window must not reach that
      point.
- [x] 2.6 Pass the allocated port to the job as an input, so `vm-create.yml`
      receives a port rather than deriving one.
- [x] 2.7 Make allocation idempotent for one owner: allocating again for a
      fulfillment that already holds an active lease returns that lease rather
      than issuing a second port. Without it a retry after a crash between
      allocation and dispatch consumes a second port and orphans the first,
      which reconciliation only recovers after the grace period.
- [x] 2.7a Enforce it in the database as well as in the query, so a concurrent
      pair of allocations for one owner cannot both succeed. Note the
      interaction with soft release: a released lease keeps its row, so a
      constraint on `(owner_kind, owner_id)` has to be conditional on the lease
      being unreleased. Verify the chosen form works on both SQLite and
      PostgreSQL before relying on it.
- [x] 2.8 **Teardown reads the lease, not the pool.** `prepare_teardown`
      currently resolves relay configuration from `pool_config`, so after any
      rebinding it would reload the wrong host client and release a port against
      a relay it was never bound on. The lease recorded where the port actually
      went and is the only thing that still knows.
- [x] 2.9 **Make preparation pure.** `validate_fulfillment` calls
      `_prepare_fulfillment`, so validation currently leases a real port.
      Validation is specified to persist nothing, and repeated validation can
      exhaust a finite window without a single accepted fulfillment.
- [x] 2.9a Allocate after durable acceptance rather than during preparation.
      Preparation stays the place that *rejects* an unusable relay — section 3's
      checks are pure reads and belong where they are.
- [x] 2.10 Wire release to the settlement record's terminal transition in
      `provisioning/compute/service/src/compute_provisioning_service/services/fulfillment_convergence.py`,
      in `_converge_create_record` and `_converge_teardown_record`. This is the
      one place a record reaches succeeded or failed for both directions.
- [x] 2.10a Release **inside** the transaction that records the terminal state.
      Outside it, a crash between the two recreates precisely the leak
      reconciliation exists to bound — on a schedule, rather than by an
      unforeseen path.
- [x] 2.10b Do not sprinkle `release()` calls along individual lifecycle paths.
      That was the earlier shape and it is what produced an allocator whose
      comments claimed every terminal outcome released while nothing called it
      at all. One observer of terminal state is correct and checkable; a set of
      call sites is neither.
- [x] 2.11 Run reconciliation as a real periodic worker following the existing
      recovery-worker pattern, not as library code with no caller. It is the
      backstop for paths that bypass the terminal transition, and a backstop
      that is never invoked is a comment.
- [x] 2.12 Correct the allocator's comments once the wiring exists. They
      currently assert that release is attached to every terminal outcome, which
      is not true of the code they sit in.

## 2A. Token confidentiality on the execution path

The change claims the database holds no usable relay credential. It does not
hold today: `prepare_create` puts the plaintext token in `AnsibleJobParams`,
`dataclasses.asdict` writes it into the `ansible_jobs.params` JSON column, and
`_to_status_response` returns `job.params` verbatim through
`GET /api/v1/jobs/{job_id}` and the job list. The token is neither encrypted at
rest nor withheld from a read.

- [x] 2A.1 Remove `relay_token` from `AnsibleJobParams` and from
      `AnsiblePreparedJobParameters`. What the accepted operation carries is the
      relay reference and the leased remote port.
- [x] 2A.2 Resolve the relay's address and token immediately before the job's
      variables are written, in the worker path that reads `job.params` and
      builds the vars file. This crosses the adapter/service seam: the resolver
      has to be injected rather than reached for.
- [x] 2A.3 Fail the job when the referenced relay is absent, disabled, or holds
      no token at execution. A configuration error, not a retryable one — a
      retry against unchanged configuration fails identically, and burning the
      retry budget only delays the same outcome behind a misleading state.
- [x] 2A.4 Late binding is a **deliberate exception** to the requirement that an
      accepted operation snapshots its resolved provider variables. Record it as
      such where that requirement lives, not only in this change. Two
      independent reasons: a snapshot is persisted and returned, and a rotated
      token must take effect on a retry of a job accepted before the rotation.
- [x] 2A.5 Assert that the persisted parameters carry no token, against the
      stored row rather than the model. A field removed from a dataclass can
      return through any dict the provider assembles on the way.
- [x] 2A.6 Assert that no job status or job list response carries a token, at
      Level 2 through the canonical typed client. This is the surface that
      published it, so this is the surface the test has to use.
- [x] 2A.7 The rendered vars file holds the decrypted token, so it needs the
      same lifetime and access restrictions as other decrypted secret material
      on the execution path, as `physical-provisioning`'s "Relay admission
      tokens are resolved at execution" requires. The existing handling meets
      that requirement: `write_extra_vars` creates the file owner-only (`0600`)
      and `O_EXCL`, under a uuid name in the process temporary directory, and
      the Ansible job executor removes it in a `finally` covering success,
      failure, timeout, and cancellation (`test_no_file_outlives_its_run`), as
      decrypted key files are. No change records a dependency for it.
      *Revised:* this task first asked for a per-operation directory, which
      `contain-embedded-host-key-material`'s design (D3) rejected.
      *Met, as D6 records:* the existing handling meets the requirement, with
      no revisit trigger recorded against this change; no code changed.

**Validation:** `make test` in `provisioning/compute/service`.

## 3. Reject partial relay configuration before dispatch

- [x] 3.1 Today the two access paths are guarded by different conditions —
      direct NAT by `frp_server_addr is not defined`, relay by
      `frp_dashboard_password is defined`. A configuration satisfying neither
      creates a VM with no external route and reports success. Add validation
      where other malformed VM requirements are already rejected, so exactly
      one access path is always selected.
- [x] 3.2 The invariant to enforce and to test: no configuration selects zero
      access paths. Assert it against the *configuration*, not against the
      playbook's guards, so a later change to the guards cannot quietly
      reintroduce the hole.
- [x] 3.3 Reject before dispatch when a pool references a relay that is
      disabled, has no usable allocation window, or has no token configured.
      Each produces a VM with no route by a different mechanism, and each is
      knowable from configuration before any host is touched.
- [x] 3.4 Name the relay and the missing element in the rejection. The failure
      this replaces is a relay refusing a proxy asynchronously in a client log;
      a rejection that says only "misconfigured" reproduces the diagnostic
      problem the change exists to remove.

**Validation:** `make test` in `provisioning/compute/service`.

## 4. Two relay clients on the host

- [x] 4.1 Rework `ansible/roles/vm-setup/tasks/frp-client.yml` to install the
      binary and the **VM-facing** client only: `/etc/frp/frpc-vms.toml` and
      `frpc-vms.service`. The host's management tunnel is written by the
      host preparation, outside this repository, and is never touched by a VM
      operation.
- [x] 4.2 Rename `ansible/roles/vm-setup/templates/frpc.toml.j2` to
      `frpc-vms.toml.j2` and `frpc.service.j2` to `frpc-vms.service.j2`. Two
      files, two units, no shared write target — which also removes the hazard
      that re-running host setup re-templates one file and erases live VM
      proxies.
- [x] 4.3 Remove the fallback token. `frp_auth_token | default('password123456789')`
      means a host initialized without an explicit token is configured with a
      value published in a tracked file. An undefined token must fail the task;
      replacing the literal with a better literal preserves the failure mode.
- [x] 4.4 Bind `frpc`'s admin API to `127.0.0.1` in the VM client's
      configuration. It supplies both the reload and the status check that
      replace the two dashboard uses.
- [x] 4.5 Make the version a variable rather than a `set_fact` literal inside
      the install task, and set it to match the deployed relay. The client
      version is a property of which relay the fleet talks to, so it must be
      settable without editing a task.
- [x] 4.6 Update the `restart frpc` handler in
      `ansible/roles/vm-setup/handlers/main.yml` for the renamed unit, and
      confirm nothing else references the old unit name.
- [x] 4.7 Set the client version to **0.61.1**, matching the `frps_image_tag`
      the deployment runs. `frps` and `frpc` negotiate a protocol version, so a
      client two minor versions behind the relay is a real mismatch and not a
      cosmetic one. Carrying 0.54.0 forward from the old `set_fact` was the
      miss that making it a variable was supposed to prevent.
- [x] 4.8 **Delete `ansible/roles/vm-management/handlers/main.yml`** rather than
      leaving it holding only a comment. A handlers file that handles nothing is
      a file whose purpose a reader has to reconstruct. The invariant belongs
      where somebody would write `notify:` — beside the reload tasks in
      `vm-create.yml` and `vm-undefine.yml`, where it already is.
- [x] 4.9 **Condition the VM tunnel role on relay configuration.**
      `ansible/roles/vm-setup/tasks/main.yml` includes `frp-client.yml`
      unconditionally, and 4.3's assertions now fail without a relay address and
      token — so host setup for a direct-NAT host fails partway through. A
      deployment with no relay is a supported state, and an optional mode must
      not break initialization of hosts that do not use it.
- [x] 4.9a Skip the role rather than defaulting inside it. Defaults are what
      produced a published fallback token; the correct behaviour for an absent
      relay is that no VM tunnel client is installed at all.

**Validation:** `make validate` in `domains/vms/provisioning/iac`, plus the
structural checks in `tests/test_ansible_structure.py`, which cover task files
`--syntax-check` does not reach.

## 5. VM creation without a dashboard

- [x] 5.1 In `ansible/roles/vm-management/tasks/vm-create.yml`, delete the
      three dashboard calls: the subdomain-discovery request, the used-port
      request, and the online-status poll against
      `https://frp-admin.<frp_domain>/api/proxy/tcp`.
- [x] 5.2 Delete the port-selection loop and its hardcoded 7002–8000 window.
      The port now arrives as a job input.
- [x] 5.3 Drop `subdomain` from the generated proxy stanza. FRP's `subdomain`
      is a vhost feature of the `http` and `https` proxy types; a `tcp` proxy
      binds a distinct port whatever the key says, and SSH sends no SNI and no
      `Host` header for a relay to demultiplex on.
- [x] 5.4 Write the stanza to `/etc/frp/frpc-vms.toml` rather than
      `/etc/frp/frpc.toml`.
- [x] 5.5 Replace `systemctl restart frpc` with a reload through the
      loopback-bound admin API. A restart closes the control connection, so the
      relay tears down every proxy that client registered and every buyer's
      established session with it.
- [x] 5.6 Replace the dashboard online-poll with a status check against the
      same local admin API. Polling the relay to learn whether the local client
      succeeded is a round trip to ask a third party about our own state.
- [x] 5.7 Apply the same substitutions to
      `ansible/roles/vm-management/tasks/vm-undefine.yml`, which removes the
      stanza and restarts the client on teardown.
- [x] 5.8 Produce the buyer connection string as `ssh -p <port> <user>@<relay>`,
      matching what `ssh_commands` already emits on the direct-NAT path.

**Validation:** `make validate` in `domains/vms/provisioning/iac`.

## 6. Reload verification gate

- [x] 6.1 **[log]** Prove that `frpc reload` preserves established sessions.
      Open an SSH session through a tunnel, append an unrelated proxy stanza,
      reload, and check the session is still alive. Supplied: the client's log
      across the reload, and evidence the session outlived it.
      *Met through `prove-relay-provisioning`'s D9 mapping*, by the VM
      real-provisioning lane's D8 sequence rather than a separate CLI reload: an
      independent operator deployment ran `e2e_vm_real_provisioning` (47 passed) at
      `72b40a25b` against a real KVM host and a deployed buyer relay running the
      grant-admission plugin, and again on a branch from it whose only difference is
      a bare-metal storefront fix. In each run the second guest's create job appended
      its proxy and reloaded the buyer client through its admin API (`/api/reload`),
      and its teardown removed the proxy and reloaded again. Through both, the first
      guest's heartbeat session stayed open (stages 09f, 09k, 09n), with a longest
      gap of 2.000 s and then 1.007 s. A later run on the same deployment,
      purchasing through the shipped buyer, measured 1.006 s.
      `prove-relay-provisioning`'s 16.2 and 16.7 recorded the same behaviour by its
      accepted Arkhai method.
- [x] 6.2 **Decide and record** in `design.md`. If reload preserves sessions,
      section 5 stands as written. If it does not, the recorded fallback is one
      `frpc` process per VM, and that decision is taken here rather than
      assumed either way now.
      *Decided: reload preserves sessions; section 5 stands and the per-VM client
      fallback is not built.* Recorded under "Reload rather than restart".
- [x] 6.3 If the fallback is needed, note that `transport.poolCount = 5` in the
      current template means five idle connections per VM, against a relay
      where `transport.maxPoolCount` is unset. Sizing is part of that decision,
      not a detail to discover later.
      *Not applicable:* 6.2 does not take the fallback.

## 7. Tests

- [x] 7.1 The `connectivity` payload's new shape survives storefront to adapter
      to extra-vars, and none of the three removed keys appears anywhere in the
      chain. Split by boundary rather than tested as one span: the client-to-API
      contract belongs in the Level 2 suite through the canonical typed client,
      and what the storefront passes to that client is a storefront unit test.
      A hand-built request body standing in for the client proves nothing about
      the contract it is imitating.
- [x] 7.2 Both storefront call sites build the identical payload.
- [x] 7.3 An undefined relay token fails rather than templating a default.
- [x] 7.3a Token resolution: a pool reaches its referenced relay's token; two
      pools referencing one relay reach the same token and the same window; a
      pool referencing a relay with no token fails before dispatch rather than
      borrowing another relay's; a pool referencing no relay needs no token.
- [x] 7.3b No pool or relay read response carries a token, under any
      configuration. Assert against the serialized response rather than the
      model, since that is where a future field would leak. Cover the export
      document in the same test, because it is a second read surface fed by the
      same reader and is not a response model.
- [x] 7.3c The token is ciphertext at rest: a stored relay row read directly
      does not yield a usable token, and a round trip through encrypt and
      decrypt returns the original.
- [x] 7.3d Preserve-on-absent: a full replacement omitting the token retains it;
      an explicit value replaces it; there is no request shape that clears it.
      Assert on PUT specifically, since PUT's documented semantics reset omitted
      fields and this is the exception.
- [x] 7.3e The execution read returns the token and the redacted read does not,
      over the same pool, so the split cannot be satisfied by a handler that
      returns nothing to either.
- [x] 7.3f Reconciliation reports an unchanged definition document as unchanged
      on a second import. This is the test that catches a redacted read being
      compared against a document, which would otherwise diverge silently on
      every import forever.
- [x] 7.4 A configuration selecting no access path is rejected before dispatch.
- [x] 7.5 Allocation, as unit tests over the lease store: a port is recorded
      before dispatch; a second allocation does not reuse a held port;
      **two different hosts sharing one relay never receive the same port**;
      the same port on two different relays is allowed; an exhausted window
      fails with a message naming the relay and window.
- [x] 7.5a **Rename and rescope the release primitive test.** The existing
      `test_every_terminal_ending_releases_the_lease` passes ending names as
      `owner_id` strings and then calls `release()` itself. It proves the
      primitive works when something calls it; its name and docstring claim it
      proves the lifecycle calls it. That is the failure mode where a test makes
      incomplete wiring look finished, and it is worse than no test because a
      reviewer reads the name. Rename to describe the primitive, and move the
      lifecycle claim to 7.5a-i.
- [x] 7.5a-i Lease release **through the orchestration**: drive each terminal
      path and assert the lease is gone afterwards. Covered for a failed
      creation and a completed teardown, with the two non-releasing cases
      asserted alongside them — a successful create keeps its port because the
      VM is live, and a failed teardown keeps its port because the state is not
      terminal and the proxy may still be registered.

      Asserting per path rather than through one representative found a second
      bypass: `_apply_teardown_success` writes its terminal state directly
      rather than through `_apply_transition`, so a completed teardown released
      nothing. One representative would have passed.
- [x] 7.5a-i-a Remaining terminal paths. There is no distinct cancellation or
      expiry state: a dispatch that never starts, a cancellation, and an expiry
      all reach `abandoned` through capacity reclamation, or `failed` through
      convergence.

      `abandoned` is written by `abandon_if_assigned` in the fulfillment kit,
      from capacity reclamation — a component that knows nothing about ports.
      Allocation runs in its own transaction, so a lease taken during an
      acceptance that then rolls back outlives the record's return to
      `assigned` and is later abandoned. Nothing on the settlement transition
      path observes that, so this state is covered by reconciliation rather
      than by the terminal transition. Recorded as a deliberate division
      rather than a gap, asserted in the allocator suite, and the reason is
      stated where `reconcile` is defined.
- [x] 7.5a-i-b The terminality predicate reconciliation is given, asserted
      against every lifecycle state rather than the terminal ones alone. It is
      the whole of what stands between an orphaned lease and a permanently
      smaller window, and it must also refuse: `teardown_failed` is not
      terminal because recovery may retry and the proxy may still be bound, and
      an owner kind it cannot inspect must not be reported terminal.
- [x] 7.5a-ii Validation leases nothing: validate a relay-backed request and
      assert no lease exists and the window is undiminished. Repeat it and
      assert the same, since the failure mode is cumulative.
- [x] 7.5a-iii Acceptance leases exactly one port, and an equivalent retry
      returns the same lease rather than a second port.
- [x] 7.5a-iv Reconciliation recovers a lease orphaned deliberately — write one
      whose owner is terminal, past the grace period, and assert the sweep
      releases it. The backstop needs evidence it runs, not only that it works.
- [x] 7.5b Reconciliation: a lease whose owner has been terminal beyond the
      grace period is released; one whose owner is still live is not.
- [x] 7.5c Level 2, through the canonical typed client: the allocation
      lifecycle across the real fulfillment API — validation takes no port
      (asserted repeatedly, since the failure mode is cumulative), acceptance
      takes exactly one, an equivalent retry takes no second, and a direct-NAT
      pool takes none at all.

      Two harness gaps had to be closed first, and both were the same shape as
      the empty encryption key found earlier: the integration conftest built
      `AnsiblePoolConfigHandler` with no settings, so no integration test could
      decrypt a relay token, and built `AnsibleFulfillmentProvider` with no
      port allocator, so every relay-backed fulfillment was rejected as invalid
      provider configuration. Neither is a defect in the code under test; both
      meant the path was unreachable from Level 2, which is indistinguishable
      from covered until something tries to reach it.
- [x] 7.5d Relay identity survives an address change: leases held against a
      relay remain associated with it after its `relay_addr` is updated. This
      is the property the foreign key buys over a derived string, so it is the
      test that fails if 2.1b is reverted.
- [x] 7.5e A duplicate rendezvous is rejected: creating a second relay with an
      address and port already recorded fails, including when the address
      differs only by normalization.
- [x] 7.8 Digest gating, as unit tests over the import path: a first startup
      with no recorded digest reconciles; a restart with an unchanged document
      does not; an edited document reconciles; an explicit import request
      reconciles regardless of the digest.
- [x] 7.8a **The restart case is the point of the whole mechanism.** Change
      state through the API, restart the service against the same mounted
      document, and assert the API change survived. Assert it over a real
      restart path rather than a second call to the import function — a test
      that never rebuilds the service from its configuration does not exercise
      the failure being prevented.
- [x] 7.8b A failed apply leaves the recorded digest unchanged, so the next
      startup retries rather than treating a half-applied document as done.
- [x] 7.8c An edited document still reconciles: an entry whose window changed is
      updated, and a **pool** the document no longer names is disabled. Digest
      gating changes *when* reconciliation happens, not what it does.
- [x] 7.8c-i A **relay** the document no longer names is retained and stays
      enabled, and pools referencing it keep dispatching. This is the one place
      relays and pools differ, so it is asserted rather than assumed.
- [x] 7.8d A token rotated through the controller survives a subsequent
      reconciliation of an edited document that still names the profile key
      holding the old value. This is the one field a reconciliation must never
      revert, and it is protected structurally rather than by the digest.
- [x] 7.8e Relay definitions: a document naming a profile key creates the relay
      with the encrypted token; a document naming a key absent from the profile
      fails with the key named rather than storing an empty token.
- [x] 7.8f A relay established from a document remains present and enabled after
      the document is unmounted, and pools referencing it still dispatch.
- [x] 7.8g A pool referencing a relay that does not exist fails before dispatch
      with both names, rather than dispatching against a missing relay.
- [x] 7.9 Controller behaviour, at Level 2 through the canonical typed client:
      create, list, detail, update, rotate, enable, disable. No response carries
      a token; every response carries whether one is configured.
- [x] 7.9a A rotated token reaches the host, not only the job's variables.

      The original wording — "takes effect on the next dispatch without a
      restart" — was wrong in both halves, and the test written to it stopped
      one boundary short of the claim. A host adopts a new token only by
      restarting its tunnel client, because `auth` is not among the sections a
      reload applies, and `frps` admits on one token, so a rotation invalidates
      every client still holding the old one at its next reconnect. A shared
      bearer token cannot be rotated one host at a time.

      So rotation now joins the drain rule (1B), refused while the relay
      carries tunnels; and `vm-create.yml` reconciles the client's rendezvous
      and credential before writing a proxy, restarting only when they changed.
      That restart is safe exactly there: a baseline can only have gone stale
      through a change the service refuses while leases exist, so a host
      reaching it has no proxies of its own to lose.

      Whether the restarted client reconnects cleanly against a real relay is
      section 6's business. Nothing below the live gate can show it.
- [x] 7.9b An update duplicating another relay's rendezvous is rejected with
      both identifiers named, rather than surfacing as a constraint violation.
- [x] 7.6 Rendered client configuration contains no `subdomain` key and no
      dashboard address. Assert against non-comment lines, as
      `tests/test_passthrough_audit.py` does, so the check cannot be satisfied
      by rewording a comment.
- [x] 7.7 Shell logic in the reworked `vm-create.yml` runs under
      `tests/shell_harness.py` with the admin API faked, in the manner of
      `tests/test_gpu_attachment_discovery.py`. Substring assertions over YAML
      cannot prove the reload path behaves.

      The reload and status paths turned out to have no shell to harness: both
      became `uri:` module calls, so what a substring assertion cannot prove
      about them, an Ansible module boundary already does.

      The shell that remains is the cleanup script `vm-create.yml` writes onto
      the host, which removes the VM's proxy stanza with `sed` and reloads the
      client with `curl`, unattended. `tests/test_cleanup_script_relay_teardown.py`
      runs it for real with both binaries faked, and asserts the two properties
      YAML cannot show: that it edits only the VM-facing client, leaving the
      management tunnel — the operator's recovery path — untouched, and that it
      reloads rather than restarts, so tearing down one buyer's VM does not end
      every other buyer's session on that host.

      Both are verified by mutation: pointing the script at `frpc.toml` fails
      three tests, and swapping the reload for `systemctl restart` fails two.

- [x] 7.10 Relay administration at Level 2 **through the canonical typed
      client**, not a hand-built wrapper. The `/api/v1/relays` controller has no
      client methods at all today; add them. `TESTING.md` is explicit that "the
      client doesn't expose it yet" is not a raw-HTTP exception, because a
      private test wrapper and the production client drift independently while
      the test stays green.
- [x] 7.10a Migrate `test_fulfillment_api.py` off its local `FulfillmentApi`
      wrapper onto `ComputeProvisioningClient` over an `ASGITransport`. The
      canonical client already has `schedule_resource`, `begin_fulfillment`,
      `begin_fulfillment_teardown`, `get_fulfillment_status`, and
      `get_fulfillment_result`; add `validate_fulfillment` if it is missing
      rather than reaching past it.
- [x] 7.11 A relay-bearing request through the real `ProvisioningClient`, at
      Level 2, proving the service receives what the client emits. The only
      relay request test today is the deliberate raw-HTTP malformed-body case,
      which proves rejection and no happy path.
- [x] 7.12 Rebinding: reject a pool relay change, a host pool move, and a relay
      repoint while a lease is held; accept each after the lease is released;
      accept a host move between pools sharing one relay regardless of leases.
- [x] 7.13 Teardown after a rebinding releases against the relay on the lease,
      not the pool's current one.

**Validation:** `make test` in each touched package and in
`domains/vms/provisioning/iac`.

## 8. Live verification [log]

Requires a rented, initialized host and the deployed relay.

The items below were met by the independent operator deployment that 6.1 describes,
mapped by `prove-relay-provisioning`'s D9. The run's raw output stays with the operator.
The outcomes recorded here are sanitized and name no address, host, or credential.

- [x] 8.1 **[log]** A proxy registered inside the configured window is accepted.
      Supplied: the relay's log naming the port.
      *Met:* the buyer relay's admission plugin logged one `admit` per guest, each
      under the operator's grant-signing key, for the three leases the run allocated
      (ports 6100–6102). Each create's status wait required the proxy running, and
      the buyer connected through it.
- [x] 8.2 **[log]** A proxy outside the window is refused. Supplied: the same
      log. This is what proves the window is enforced by the relay rather than
      only respected by the client.
      *Met as restated by D9:* a proxy without a valid grant is refused. The
      admission check against each deployed buyer relay refused five probes, each
      for its own reason: no grant (`grant_missing`), a forged signature
      (`signature_invalid`), a grant for another port (`port_mismatch`), a port
      outside the operator's range (`port_outside_range`), and another operator's
      key (`key_unknown`). For each, both the client and the plugin recorded the
      refusal and the port stayed closed. Each relay's token was also refused by the
      other relays. *Not shown live:* `frps` refusing a port outside its own
      `allowPorts`. That the buyer relays allow only their window was read from
      their configuration, not observed as a refusal.
- [x] 8.3 **[log]** Creating a second VM leaves the first VM's established SSH
      session alive. Supplied: client log plus the surviving session.
      *Met:* stage 09k, by the heartbeat 6.1 describes.
- [x] 8.4 **[log]** The host's management tunnel is unaffected by VM creation
      and teardown. Supplied: management client status across both.
      *Met:* the management client's unit, read on the host before and after the
      module, was active with zero restarts, the same start time, and the same
      configuration hash. The lane's checks of management connectivity before each
      teardown (09i, 09l, 10b2) passed, every job having run over that tunnel.
- [x] 8.5 **[log]** A buyer connection string produced by the relay path
      connects. Supplied: the string and a successful session.
      *Met:* stages 09d and 09j. The buyer reached each guest at its delivered
      relay string from the operator's machine, outside the cluster. An unrelated
      key was refused (09e), and after teardown the string no longer connected
      (09m, 11d).
- [x] 8.6 **[log]** Teardown releases the port, and it is reused by the next
      VM. Supplied: allocation records before and after.
      *Met as restated by D9:* teardown releases the port. The relay's holdings
      read after the module showed every lease released, each keeping its grant
      expiry and with no competing lease on its port. *Not shown physically:*
      reuse. A released port is held until its grant's original expiry plus the
      reuse margin, so a single run cannot show it; reuse after that hold is
      covered by the allocator's integration suite.

## 9. Definition documents and deployment wiring

The deployment path is Terraform applying a Helm chart. A relay must be
establishable by applying the chart alone, with no operator API call and no
credential passing through a workstation.

**The import mechanism is shared with pools, and its invocation is fixed first.**
`import_pool_definitions_if_configured` currently runs `import_pools` at every
startup, justified in a comment on the grounds that import is idempotent and
diff-based. The premise is wrong: import is idempotent with respect to the
*document*, not the *database*, so re-running it reverts anything else that
changed the database. Section 1A's controller would be undone by any pod
restart. See `design.md`.

- [x] 9.1 Record a durable digest per definition document and reconcile at
      startup only when the current document differs from the recorded one.
      Follow the `schema_migrations` precedent in
      `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`
      — a table recording what has been applied, consulted before applying it
      again — rather than inventing a second bookkeeping mechanism.
- [x] 9.1a Update the digest in the **same transaction** that applies the
      reconciliation. A digest written on a failed apply suppresses the retry
      and leaves the database in a state no document describes.
- [x] 9.1b Leave the explicit import endpoint unconditional. An operator
      submitting a document has asked for reconciliation, and gating that on a
      digest would make a resubmission silently do nothing.
- [x] 9.1c Correct the comment in `app_runtime.py` that asserts re-running on
      every restart is correct. State the actual invariant: reconciliation
      follows a change to the document, and a process restart is not one.
- [x] 9.2 Add a relay definition document and a `relay_definitions_path`
      setting, reconciled by the same digest-gated path as pools. Relays and
      pools get one rule, not two: a reader who knows one should not guess wrong
      about the other.
- [x] 9.2a Each entry holds a rendezvous address, port, and window, and **no
      credential** — so the document is an ordinary mounted configuration file
      and needs no Secret.
- [x] 9.2b Each entry may name which key of the secrets profile holds its
      token. The key is read **only when the relay is created** and never
      re-read, so a token rotated through the controller survives a later
      reconciliation of an edited document.
- [x] 9.2c Fail the import, naming the key, when an entry names a profile key
      the profile does not carry. Creating a relay with an empty token defers
      the failure to admission, which is the diagnostic failure this change
      exists to remove.
- [x] 9.2d Reconcile relays before pools, so a pool referencing a relay
      resolves on a first boot.
- [x] 9.3 Declare `relay_token` in
      `provisioning/compute/service/src/compute_provisioning_service/settings.toml`
      with an empty default, replacing the `frp_server_addr`, `frp_domain`, and
      `frp_dashboard_password` block. Read it as `ssh_decryption_key` is read,
      with a default, so an environment whose profile predates the key loads
      rather than crashing. It is a **bootstrap value**, not a store: nothing
      reads it at dispatch, and nothing re-reads it once a relay exists.
- [x] 9.3a An absent token is a valid state — a deployment with no relay uses
      the direct-NAT path. Section 3 is what makes a *partial* relay
      configuration fail.
- [x] 9.4 Wire `relay_definitions_path` into the provisioning chart in
      `helm/charts/provisioning`: a values key, a ConfigMap carrying the
      document, and a mount into the application container only. The migrate
      init container runs migrations and imports nothing.
- [x] 9.4a Wiring `pool_definitions_path` becomes safe once 9.1 lands, but is
      still **not done here**. It is currently connected to nothing, so wiring
      it would newly subject every existing deployment's pools to declarative
      reconciliation — a change to what a deployment means, not a bug fix.
      Worth doing, deliberately, in its own change.
- [x] 9.4b **Remove `definitions.pools` from the chart.** It currently renders
      `pool-definitions.yaml` and a mount, and its comment says setting it makes
      pool inventory declarative — which contradicts 9.4a in the same change.
      Ship the relay half only.
- [x] 9.4c **Make the mount and the path one fact.** `config.*_definitions_path`
      defaults to empty and does not change when `definitions.*` is set, so a
      deployment can render and mount a document that the service then skips
      because its path is unset — a silent no-op that looks like configuration.
      Either derive the path from the presence of the document, or require the
      path explicitly and fail the render when a document is supplied without
      one. Do not leave a combination that implies more automation than exists.
- [x] 9.7 **Extract the definition-document logic out of `app_runtime`** into
      its own class. There are now five functions there — digest computation,
      digest read, digest write, and two importers — that form one
      responsibility. `app_runtime` should call it, not contain it.
- [x] 9.7a The extraction is what makes 9.8 natural rather than bolted on: one
      object owning the read, the diff, the apply, and the digest can hold them
      in one transaction, where five module-level functions cannot.
- [x] 9.8 **Apply the reconciliation and record the digest in one transaction.**
      They are two commits today, which the spec forbids and for a reason a test
      will not catch by accident: a digest written after an already-committed
      apply is indistinguishable at the next startup from one recorded before a
      crash.
- [x] 9.8a This needs a **session-scoped import** on `ResourcePoolService` in
      `kit/resource-pools`: `import_pools` opens and commits its own
      transaction, so it cannot be composed with the digest write. Changing the
      kit is in scope. Keep the existing self-contained entry point for the API
      path, which has nothing to compose with.
- [x] 9.9 Relay omission **retains** the relay; only pools are disabled on
      omission. Disabling a relay would break every pool referencing it and
      every live tunnel on it, which is far worse than a stale row and is not
      what an operator editing an unrelated entry expects. Task 7.8c previously
      said otherwise and is corrected below.
- [x] 9.5 Keep the document out of the Secret carrying the profile. It holds no
      credential by construction, and putting it there would make every window
      edit a secret rotation.
- [x] 9.6 State the configuration contract in
      `docs/development/DEPLOYMENT_AND_CONFIG.md`: what the service reads, what
      each document may contain, that reconciliation follows a change to the
      document rather than a restart, and what happens when each is absent.

**Validation:** `make test` in `provisioning/compute/service` and
`kit/resource-pools`; `helm template` against the chart for each environment's
values to confirm the mount renders and the document is not placed in a Secret.

## 10. Documentation and deployment consequences

- [x] 10.1 Rewrite `docs/seller-frp-setup.md`. It describes the dashboard, the
      `frp-admin` subdomain, the wildcard DNS record, the certificate, the
      three replaced storefront keys, and subdomain-form buyer connection
      strings. Most of its detail becomes wrong; leaving it to contradict the
      code is worse than the edit.
- [x] 10.2 Update the chart values and any examples carrying the removed keys.
      Searching rather than assuming found four beyond the two storefront files:
      `helm/charts/provisioning/values.yaml` still shipped `frp_server_addr` and
      `frp_domain`; both values schemas forbade `frp_dashboard_password`, a key
      that no longer exists, while permitting `relay_token`, a credential that
      must never be rendered into a ConfigMap; `helm/scripts/test-render.sh`
      asserted the absence of the old key rather than the new one; and
      `ansible/inventory/vm-vars-example.yaml` documented the removed inputs as
      the way to reach a VM through a relay.

      The chart deliberately does **not** gain a `relay_token` value. The
      schema forbids it for the same reason it forbade the dashboard password:
      a credential in plain chart values is a credential in a ConfigMap. It
      reaches the service through the provisioning-secrets profile.
- [x] 10.3 Recorded, and deliberately not written into permanent documentation.
      `docs/development/DEPLOYMENT_AND_CONFIG.md`'s "Migrations at startup"
      already states the general rule — the init container applies migrations
      and the application rejects drift rather than applying them in-process —
      and that rule is what governs here. A permanent document saying "this
      change adds a migration" would be change narrative in a place that
      describes the current system.

      The operator consequence belongs here: `check_schema_version` compares
      against the last known migration, so a pod carrying this code against an
      unmigrated database raises `SchemaDriftError` and does not come up. The
      Helm init container handles it on the normal path. Applying it is an
      external mutation requiring its own authorized packet; this change does
      not perform it.
- [x] 10.4 No host migration. The dev cluster has never run a live-fire
      provisioning test and is deployed in mock mode, so no host has been
      initialized against the relay and none carries an accumulated
      `/etc/frp/frpc.toml`. The population is empty; write no migration for it.
      Host inventory automation and the non-mock redeploy are separate later
      work.
- [x] 10.5 Remove the published fallback token literal from every document that
      quotes it once section 4 has removed it from the template. A credential
      must not survive in permanent documentation because a change document
      needed to name the defect it was removing.

## 10a. The allocator and execution drain a disabled relay

Delivers D1's items 2 and 3: no lease is allocated on a disabled relay, whoever
asks, under a lock on the relay row; every job already holding a lease runs.
Implements "Disabling a relay drains it" (its allocator paragraph, and the
scenarios "A new owner asks the allocator for a port on a disabled relay" and "A
relay is disabled while an acceptance is in flight") and the MODIFIED "Relay
admission tokens are resolved at execution". Touches
`provisioning/compute/src/compute_provisioning/relays/` (`allocator.py`,
`execution.py`, and comments in `db.py`, `pool_relays.py`, `route_service.py`) and
the VM and bare-metal adapters' codec tests.

- [x] 10a.1 In `RelayPortAllocator.allocate_in_session`, which standalone
      `allocate` also runs, keep returning an owner's existing active lease
      first, then read the relay row locked (`with_for_update`, as
      `RelayExecutionResolver.resolve_into` reads it) and refuse a new owner
      on a disabled relay before any port is claimed, naming the relay. Raise
      it as an allocator error, which `_lease_remote_port` in both domains'
      plans already turns into `ProviderConfigInvalidError`. (D1 item 2; 06 F2)
      *Done:* `RelayDisabledError`, exported from the relay package, names the
      relay and its rendezvous. The locked read also refreshes the row
      (`populate_existing`; why, `design.md` D1 item 2), held by 10a.5's second
      test.
- [x] 10a.2 In `RelayExecutionResolver.resolve_into`, drop the refusal of a
      disabled relay. An absent relay, a relay with no token, and a create's
      relay with no active grant key or no lease for its reservation are still
      refused as `RelayUnusableAtExecutionError`. (D1 item 3; MODIFIED "Relay
      admission tokens are resolved at execution")
- [x] 10a.3 Rewrite every comment and docstring in the relay package that
      describes disabling as a stop refusing jobs — `execution.py`'s class and
      method docstrings, `route_service.py`'s module docstring ("Disable is the
      operator's answer…"), and any other the package's search for "disabled"
      finds — to the invariant: disabling a relay drains it; no new lease, and
      leased work runs. (D1; `docs/guidance/engineering/comments.md`)
      *Done:* in `execution.py`, `route_service.py`, `allocator.py`,
      `pool_relays.py` (docstring and refusal message), and on `Relay.enabled`
      in `db.py`; 10d extended the last two to the deliverable-hosts filter.
- [x] 10a.4 Library integration, in
      `provisioning/compute/tests/integration/test_relay_port_allocator.py`:
      a new owner is refused on a disabled relay through `allocate` and through
      `allocate_in_session`, with no lease recorded; an owner already holding a
      lease receives it again; enabling the relay lets the new owner allocate.
      (Scenario "A new owner asks the allocator for a port on a disabled relay")
      *Done:* `TestADisabledRelayLeasesNoNewPort`, four tests, the relay
      disabled through `RelayService.set_enabled`. Passing.
- [x] 10a.5 Library integration, a database-concurrency test following
      `docs/guidance/engineering/concurrency-tests.md` with independent sessions
      and bounded explicit synchronization, in both orders: an acceptance that
      has allocated but not committed, then a disable, ends with the relay
      disabled and holding that lease; a disable committed first ends with the
      acceptance refused and no lease. No lane here runs PostgreSQL, whose row
      lock is what the first order relies on there, so the same suite also
      holds, through an ORM execute listener, that the relay is read with a
      `FOR UPDATE` lock before the claim. (Scenario "A relay is disabled while
      an acceptance is in flight")
      *Done:* `TestADisableRacingAnAcceptance`, three tests, every wait bounded
      at 10 s, passing. The first order shows SQLite's single writer, not the
      allocator; the second and the rendered `FOR UPDATE` hold the allocator's
      lock (`design.md`, "How the drain was proven").
- [x] 10a.6 Library integration, in
      `provisioning/compute/tests/integration/test_relay_administration.py`:
      replace the parametrized case expecting a disabled relay to be refused
      at execution (around line 767) with cases where it is not — a removal
      (no port) resolves the address and token, and a create whose
      reservation holds the lease resolves and signs its grant — and keep the
      absent, no-token, no-grant-key, and wrong-reservation refusals.
      (Scenario "A relay is disabled between acceptance and execution")
      *Done:* `test_a_relay_with_no_token_fails_the_job`,
      `test_a_removal_on_a_disabled_relay_is_resolved`, and
      `test_a_create_holding_its_lease_on_a_disabled_relay_is_signed_its_grant`;
      the other refusals stand. Passing.
- [x] 10a.7 Unit, in each domain's codec suite
      (`domains/vms/provisioning/adapter/tests/unit/test_vm_codec.py` and
      `domains/bare_metal/provisioning/adapter/tests/test_bare_metal_codec.py`): a VM `vm_remove` and a bare-metal
      reclaim whose lease names a disabled relay prepare their job, as both
      codecs call the resolver.
      *Done at library integration, not unit* (why, `design.md`, "How the
      drain was proven"): `test_a_teardown_on_a_disabled_relay_is_prepared` in
      `domains/vms/provisioning/adapter/tests/integration/test_relay_pool_configuration.py`
      and `test_a_reclaim_on_a_disabled_relay_is_prepared` in
      `domains/bare_metal/provisioning/adapter/tests/integration/test_relay_reclaim.py`,
      both passing. The bare-metal adapter's `dev` group gained
      `cryptography>=42.0` and `sqlalchemy>=2.0`, relocked.
- [x] 10a.8 **Verification:** `make test` in `provisioning/compute`,
      `domains/vms/provisioning/adapter`, and
      `domains/bare_metal/provisioning/adapter` (unit and library integration);
      `scripts/change-workflow run pre-commit relay-vm-access-without-a-dashboard`.
      End-to-end: none. None is owed: whether a relay is disabled is provisioning-service
      state that no relay or host sees, and the real relay lanes'
      teardowns run on enabled relays as before.
      *Results:* `make test` passed in `provisioning/compute` (539),
      `domains/vms/provisioning/adapter` (293), and
      `domains/bare_metal/provisioning/adapter` (138);
      `make -C provisioning/compute/service test` passed (622 unit, 540
      application integration); `run pre-commit` passed. `test-before`
      produced no evidence (`design.md`, "How the drain was proven"). No
      end-to-end scenario, none owed, no `Owed by validation:` line.
      *Outside the plan:* a comment in `scripts/tests/test_change_workflow_log.py`
      naming a section number was reworded.

**Handoff (10a).** An adapter's or the service's suite sees a change to
`provisioning/compute` only through the wheel: `make dist-compute-provisioning`
before `make -C <package> test`.

## 10b. The relay read reports the drain

Delivers D2: every relay read reports `active_lease_count` and `drained`, both
required in the typed response. Implements "A relay reports whether it has
drained". Touches
`provisioning/compute/contracts/src/compute_provisioning_contracts/relays.py`
(`RelayResponse`) and `provisioning/compute/src/compute_provisioning/relays/service.py`
(`RelayView`, `list_relays`, `get_relay`, `_view`). The canonical client parses
through `RelayResponse` and needs no change.

- [x] 10b.1 Add `active_lease_count: int` and `drained: bool` to `RelayResponse`,
      required, with no default. (D2; 06 F3)
      *Done.*
- [x] 10b.2 Add both to `RelayView`, computed from `relay_port_leases`:
      `drained` is true exactly when the relay is disabled and holds no active
      lease. `list_relays` counts every relay's active leases in one grouped
      query; `_view` serves every write's response. Nothing is persisted. (D2)
      *Done:* `RelayView.of` requires `active_lease_count`, so no caller
      inherits a default that would read a disabled relay as drained.
- [x] 10b.3 Version the packages whose contents change as
      `docs/guidance/repository/package-versions.md` says: run
      `make check-version-bumps` and bump any package this change has not
      already bumped against `dev`, relocking where a lower bound moves.
      *Done;* `make check-version-bumps` passed:

      | Package | Version | Lower bounds raised |
      |---|---|---|
      | `arkhai-compute-provisioning-contracts` | 0.14.0 → 0.15.0 | — |
      | `arkhai-compute-provisioning` | 0.27.0 → 0.28.0 | contracts `>=0.15.0` |
      | `arkhai-compute-provisioning-service` | 0.25.0 → 0.26.0 | contracts `>=0.15.0`, compute `>=0.28.0` |
      | `arkhai-compute-provisioning-client` | 0.10.0 → 0.11.0 | contracts `>=0.15.0` |
      | `arkhai-vms-provisioning-adapter` | 0.19.0 → 0.19.1 | compute `>=0.28.0` |
      | `arkhai-bare-metal-provisioning-adapter` | 0.13.0 → 0.13.1 | compute `>=0.28.0` |

      Contracts and compute are minor bumps: the response gains required
      fields, and `RelayView.of` and the allocator's and resolver's behaviour
      change. Each raised bound is a reader that needs the new fields or 10a's
      resolver. `make lock` relocked the 12 projects naming these packages.
      (The round's triage later bumped `arkhai-kit-resource-pools` 0.10.0 →
      0.10.1; see 10d.)
- [x] 10b.4 Unit, in `provisioning/compute/contracts/tests/unit/test_contracts.py`: a relay read shaped as
      `marketplace-v0.3.0` serves it, with neither field, fails to parse as
      `RelayResponse`. (Scenario "A client reads a service that does not report
      the drain")
      *Done:* `test_a_relay_read_that_does_not_report_the_drain_is_refused`
      (either field or both missing) and
      `test_a_relay_read_reporting_the_drain_is_accepted`, passing. The
      v0.3.0-shaped body is written from that release's fields, not captured
      from a running service.
- [x] 10b.5 Library integration, in `test_relay_administration.py`: an enabled
      relay with no lease reads `drained` false; a disabled relay with one
      active lease reads count 1 and `drained` false; after that lease is
      released, while its grant has not expired, count 0 and `drained` true;
      enabled again, `drained` false. The list agrees with the read. (Scenarios
      "A disabled relay still carries a lease", "A disabled relay's last lease
      is released", "An enabled relay holds no lease")
      *Done:* `TestTheDrainReport`, three tests, passing; the released lease's
      grant expiry is asserted still in the future, and a third test holds the
      grouped count per relay.
- [x] 10b.6 Application integration through the canonical typed client, in
      `provisioning/compute/service/tests/integration/test_relays_api.py`: list,
      read, create, update, enable, disable, rotate, and grant-key activation
      each return both fields, and disabling a relay with a lease reads count 1
      and `drained` false.
      *Done:* `TestTheDrainReportOverTheApi`, two tests through
      `ComputeProvisioningClient`, covering all eight routes, passing.
- [x] 10b.7 **Verification:** `make test` in `provisioning/compute/contracts`,
      `provisioning/compute`, and `provisioning/compute/service` (unit, library
      integration, application integration);
      `scripts/change-workflow run pre-commit relay-vm-access-without-a-dashboard`.
      End-to-end: none, and none is owed: no scenario reads the relay
      administration routes.
      *Results:* `make test` passed in `provisioning/compute/contracts` (160)
      and `provisioning/compute` (542); the service passed (622 unit, 542
      application integration); `run pre-commit` passed. No end-to-end
      scenario, none owed, no `Owed by validation:` line.

## 10c. Refusals name the drain's scope

Delivers D5's refusal rule: a refusal under the rebinding rule names the drain
at the scope that clears it. Implements the MODIFIED "A relay binding is fixed
for a lease's life" (its drain paragraph, and the scenarios "A relay is repointed
while it carries leases" and "A pool's relay reference change is refused").
Touches `provisioning/compute/src/compute_provisioning/relays/rebinding.py`.

- [x] 10c.1 Split `_DRAIN_HINT` in two: the pool's (disable the pool, wait for
      its leases to be released, change, re-enable) for a pool's relay reference
      and a host's pool move; the relay's (disable the relay, wait until it
      reads `drained`, change, re-enable) for a relay's address or port and
      its token rotation. (D5)
      *Done:* `_POOL_DRAIN_HINT` and `_RELAY_DRAIN_HINT`, each check passing
      its scope's hint to `_refuse`.
- [x] 10c.2 Rewrite `rebinding.py`'s module docstring to state the two scopes:
      disabling a pool drains a pool, disabling a relay drains every pool on
      it, and no other drain exists. (D5; comments rule)
- [x] 10c.3 Library integration, in the existing rebinding tests
      (`provisioning/compute/tests/integration/test_pool_relays.py` and
      `test_relay_administration.py`): each of the four refusals carries its
      scope's hint. Application integration, in `test_relays_api.py` and
      `test_pool_relays_api.py`: a relay move and a token rotation refused with
      409 carry the relay's hint, and a pool's relay change the pool's.
      *Done:* one test per check asserts its scope's hint and not the other's —
      whole at library integration, by key phrase through the 409 at
      application integration (why both, `design.md`, "How the drain was
      proven"). All pass. A host's pool move is not asserted for its hint at
      application level; the plan named none there.
- [x] 10c.4 **Verification:** `make test` in `provisioning/compute` and
      `provisioning/compute/service` (library and application integration);
      `scripts/change-workflow run pre-commit relay-vm-access-without-a-dashboard`.
      End-to-end: none, and none is owed.
      *Results:* `make test` passed in `provisioning/compute` (542); the
      service passed (622 unit, 542 application integration); `run
      pre-commit` passed, and the rebinding suites (100) and comment hygiene
      on the final docstring. No end-to-end scenario, none owed, no `Owed by
      validation:` line; `test-before` not run.

## 10d. A disabled relay's pools' hosts take no new delivery

Delivers D1's item 1, its reversibility, and the drain end to end in the running
service. Implements "Disabling a relay drains it" (its deliverability sentence,
and the scenarios "A relay is disabled while it carries deliveries", "A claim
reaches fulfillment on a disabled relay", "A relay disabled by mistake is enabled
again before it drains", and "The definition document stops listing a drained
relay"). Touches `provisioning/compute/src/compute_provisioning/relays/` (a
deliverable-hosts composition, exported from `__init__.py`) and
`provisioning/compute/service/src/compute_provisioning_service/container.py`.
`kit/site` does not change.

- [x] 10d.1 In the relay package, compose the host authority's
      `DeliverableHosts` (`kit/resource-pools`'s protocol): the hosts it reports,
      less every host whose pool's `pool_relays` row references a disabled
      relay, read in the caller's session, as `deliverable_host_ids` is. (D1
      item 1)
      *Done:* `RelayDeliverableHosts` in `relays/deliverability.py`, exported
      from the package, leaves out hosts placed in, or declared in, a pool on a
      disabled relay (the reading, `design.md` D1 item 1; promoted to the
      `physical-provisioning` companion, 11.16). It reads the site's
      `capacity_buckets` in the same session; `kit/site` does not change.
- [x] 10d.2 Pass it in `container.py` wherever `deliverable_hosts=host_authority`
      is passed today (the capacity ledger and scheduling, around lines 451 and
      609), so admission, placement, and projection read it. (D1 item 1)
      *Done:* a `deliverable_hosts` provider over `host_authority`, mirrored
      in `tests/integration/conftest.py`, and held by
      `test_the_ledger_and_the_scheduler_read_one_report_of_deliverable_hosts`.
- [x] 10d.3 Library integration: a host in a pool on a disabled relay is left
      out; on an enabled relay, or in a pool with no relay, it is reported; a
      disabled host stays out whatever its relay.
      *Done:* `provisioning/compute/tests/integration/test_relay_deliverability.py`,
      five tests, passing: the plan's cases, re-enabling, an unplaced host
      declared in the pool, and a disable uncommitted in the caller's session.
- [x] 10d.4 Application integration through the canonical typed client, beside
      the relay-bearing suites (`test_fulfillment_convergence.py`,
      `test_bare_metal_relay.py`, and `test_host_requirement_api.py`'s
      disabled-host cases): with a VM lease and a bare-metal lease on one
      relay, disable it; the declarations of its pools' hosts are projected not
      enabled and a new claim is neither admitted nor placed; the VM's teardown
      and the bare-metal reclaim run when their leases end and release their
      ports; and the relay then reads `drained` true. (Scenario "A relay is
      disabled while it carries deliveries")
      *Done:* `test_a_disabled_relay_takes_no_new_delivery_and_its_leases_drain`
      in `provisioning/compute/service/tests/integration/test_relay_drain_api.py`,
      passing: after the disable, admission finds no capacity on the pinned VM
      declaration, placement refuses an earlier hold, both pools'
      declarations project not enabled, and the teardown and reclaim run to
      `torn_down`, releasing both ports, and the relay reads `drained` true.
      The site's bare-metal admission is not separately asserted, its one
      machine already held. How the test paces convergence, `design.md`, "How
      the drain was proven".
- [x] 10d.5 Application integration: fulfillment acceptance on a pool whose
      relay is disabled is refused, naming the relay, and records no lease.
      (Scenario "A claim reaches fulfillment on a disabled relay")
      *Done:* `test_acceptance_on_a_pool_whose_relay_is_disabled_leases_no_port`,
      passing: 422 `provider_config_invalid`, no lease. Acceptance's answer
      carries the code alone, as every provider-configuration refusal does,
      so the relay is shown named on validation.
- [x] 10d.6 Application integration: a relay disabled while it holds a lease and
      enabled again before it drains returns its pools' hosts to new delivery,
      allocation on it resumes, and the leased delivery's job runs unaffected.
      (Scenario "A relay disabled by mistake is enabled again before it drains")
      *Done:* `test_a_relay_enabled_again_before_it_drains_takes_new_delivery`,
      passing. "Runs unaffected" is shown as the delivery and its lease
      untouched by the disable; a job running during one is 10a.6's and the
      round triage's 15 F2 test.
- [x] 10d.7 Confirm that the existing relay-omission test (task 9.9) holds the
      scenario "The definition document stops listing a drained relay" for a
      disabled relay, and add a disabled case if it does not.
      *Corrected:* no relay-omission test existed;
      `test_a_drained_relay_the_document_stops_listing_is_left_as_it_is` in
      `test_relay_administration.py` adds it, passing.
      *Outside the plan:* the importer's comment in `relays/definitions.py`
      now gives D4's reason.
- [x] 10d.8 **Verification:** `make test` in `provisioning/compute` and
      `provisioning/compute/service` (library and application integration);
      `scripts/change-workflow run pre-commit relay-vm-access-without-a-dashboard`.
      End-to-end: none, and none is owed: the drain is provisioning-service
      state the application-integration suite reaches through the typed
      client, and no scenario disables a relay.
      *Results:* `make test` passed in `provisioning/compute` (548); the
      service passed (622 unit, 545 application integration, the drain tests
      also on two further runs); `run pre-commit` passed. No end-to-end
      scenario, none owed, no `Owed by validation:` line.
      *Declined from the fresh-context check:* the drain test sets up the
      bare-metal deal through `bare_metal_deal`, the bare-metal suites' one
      setup, rather than through the site clients.

**Permanent texts defining the deliverable-hosts report (15 F1).** The
fulfillment requirement and `physical-provisioning`'s "Disabling a host keeps
new deliveries off it" are MODIFIED in the deltas (11.11); the
`site-capacity` companion and `ARCHITECTURE.md` are 11.16 rows; the
`DeliverableHosts` docstring was fixed in the round's triage (below).

**Round triage fixes (15-implementation, 17-implementation-owner).**
- *O1:* `parse_relay_definitions` refuses an `enabled` that is not a YAML
  boolean, `null` included, naming the entry, as hosts do; unit tests in
  `provisioning/compute/tests/unit/test_relay_definitions.py`.
- *O2:* `test_a_listed_relay_is_drained_through_its_entry_and_enabled_by_omission`
  in `test_relay_administration.py`.
- *15 F2:* `test_a_create_accepted_before_its_relay_is_disabled_runs` in
  `test_relay_drain_api.py`.
- *15 F1:* the `DeliverableHosts.deliverable_host_ids` docstring;
  `arkhai-kit-resource-pools` 0.10.0 → 0.10.1, relocked.
- *O3:* `docs/seller-frp-setup.md`, "Retiring a relay" step 4.
- *Evidence:* the focused suites passed, and `run pre-commit` on the final
  state (`provisioning/compute` 556; the service 622 unit, 546 application
  integration). The fresh-context check's one finding, parse-only tests at
  library integration, moved them to unit.

**Pre-closeout triage fix (26-pre-closeout).** *26 F1, outside the plan:*
`RelayService.held_ports`, which had no caller and duplicated
`RelayPortAllocator.held_ports`, is removed, covered by the existing 0.28.0
bump. `make -C provisioning/compute test` (556) and `run pre-commit` passed.

**Handoff (10d).** The service's application-integration harness builds its own
wiring in `tests/integration/conftest.py`; a change to `container.py`'s
composition is mirrored there.

## 10e. The procedure for draining and retiring a relay

Delivers D5's procedure and D4's consequence for a document-listed relay, and
records D6. Touches `docs/seller-frp-setup.md`,
`docs/development/VALIDATION_RUNBOOK.md` §28, and this task list.

- [x] 10e.1 In `docs/seller-frp-setup.md`: in "Registering the relay", token
      rotation becomes disable the relay, wait for `drained: true`, rotate,
      enable again; "Changing a relay later" names both drain scopes — the pool
      for a pool's relay or a host's pool, the relay for its address, port, or
      token — and adds retiring a relay in D5's five steps, including that a
      relay the definition document lists is disabled and enabled through its
      `enabled` entry, since an API disable is reverted when the document next
      changes. Present tense, describing the current system. (D4, D5)
      *Done:* "Changing a relay later" covers both domains, the four refused
      changes with each scope's steps, reversibility, and a listed relay; a
      new "Retiring a relay" gives D5's five steps and what a reinstated
      server takes (D3); token rotation drains every registering operator's
      relay on a shared server.
- [x] 10e.2 In `docs/development/VALIDATION_RUNBOOK.md` §28: add "Retire a
      relay" for the relay's operator — wait for `drained: true` on the relay
      read, then remove the server, or on a shared relay this relay's active
      and retired keys and its range from the admission plugin; enable the
      relay again only once a server runs at its rendezvous. Restate the
      section's "stop admission and drain" steps ("Native systemd relay",
      "Container relay", "Rotate keys and change admission policy") as
      disabling the relay and waiting for `drained`. (D2, D5)
      *Done:* "Retire a relay" follows "Rotate keys and change admission
      policy", naming each step's actor; every restatement that restarts frps
      drains the relay in every provisioning service registering the server.
      *Left as they were:* "Prove admission" step 4 and the seller guide's
      registration wording, which describe a relay not yet carrying buyers.
- [x] 10e.3 Tick 1A.7 once sections 10a–10d are complete, and 2A.7, which D6
      records as met by the existing handling with no revisit trigger.
      *Done.*
- [x] 10e.4 **Verification:** `make check-doc-citations
      CHANGE=relay-vm-access-without-a-dashboard`;
      `scripts/change-workflow run pre-commit relay-vm-access-without-a-dashboard`.
      End-to-end: none.
      *Results:* `make check-doc-citations` passed (4 documents); `run
      pre-commit` passed. No end-to-end scenario, none owed, no `Owed by
      validation:` line.

## 11. Closeout

Per `docs/guidance/workflow/closeout.md`, with this repository's parts in `openspec/README.md#this-repositorys-closeout-parts`.

Listed in an earlier order; closeout works the parts in `docs/guidance/workflow/closeout.md`'s order.

- [x] 11.1 **Comment hygiene.** `make check-comment-hygiene` from the
      repository root, then read the touched files for what the target cannot
      catch. The invariant belongs in the comment — the token never reaches a
      buyer-controlled machine; allocation is the service's and the playbook
      applies what it is given — never the change that introduced it.
- [x] 11.2 **Import placement.** Six imports this change added or touched were
      function-level. Each was moved by attempting the move and running the
      real suite rather than by assuming: `AnsiblePoolConfig` in
      `relay_rebinding`, `import_relay_definitions_in_session` in
      `definition_documents`, `SettlementRecord`/`SettlementRecordState` in
      `app_runtime`, `RelayPortAllocator` in the VM adapter's `runtime`, and
      `market_config`'s encryption helpers in `host_service` and
      `ansible_service`. None had a circular dependency; all six are now at
      module level.

      One placement error worth noting: an automated move put an import above
      `from __future__ import annotations`, which must be first. A syntax check
      would have caught it, but so did the suite — which is the check this task
      asks for, and the reason it asks for it.
- [x] 11.3 **Documentation compliance.** Applied directly rather than deferred
      to review, and it caught two classes of problem.

      *Journal-style prose in permanent documentation.* Seven passages
      described the system by contrast with what it replaced — "an earlier
      version of this document", "what you no longer need", "there is one
      credential now where there were two". Permanent documents describe the
      current system; that reasoning belongs in `design.md`, which has it.
      Rewritten in the present tense with the operational warnings preserved.

      *Unresolvable cross-references.* `AGENTS.md` requires a cross-reference
      check before promoting and treats a broken citation as blocking. Four
      failed, all pre-existing on the baseline: a scheduler test file that
      exists nowhere, and three paths under a directory structure the
      repository does not have. Two were in files this change was already
      promoting into, so all four were repointed at their real locations —
      after checking, since a citation that resolves to the wrong file is worse
      than one that fails.
- [x] 11.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first, sections 10a–10e and the replanned 1A.7 and 2A.7 included.
      *Done:* moved to `design.md` first — the allocator's refreshed locked
      read and the placed-or-declared reading (D1 items 2 and 1), and a new
      "How the drain was proven" (the race's three proofs, the codec tests'
      level, the hints at two levels, the drain test's pacing, `test-before`'s
      environment). Then 10a–10e's notes, 1A.7, 2A.7, and "Implementation
      progress" were shortened to behaviour, evidence, and destinations; the
      progress section's stale "release attached to the settlement record's
      terminal transition" now names release with the reservation's capacity.
- [x] 11.5 **Roadmap currency.** Decided for the campaign: **no separate
      goal.** The product already sells VMs on hosts it reaches by tunnel, so
      this is not capability it lacks — what the work fixes is that the
      mechanism required a relay to expose a management surface and required
      the storefront to hold physical facts. Both are defects in how the
      mechanism was built, and they belong to Goal 1's consolidation of
      physical authority in the provisioning service.

      Goal 1's current state now records that buyer-access infrastructure is
      provisioning-owned, and its gap table names this change and
      `contain-embedded-host-key-material`. The disposition itself is written
      into the goal so a later reader finds the reasoning rather than only its
      absence.
      *Correction:* Goal 1's per-host-key gap row was removed at
      `contain-embedded-host-key-material`'s closeout, since per-host keys are
      registered through the host API; the goal's current state records them,
      and its gap table does not name that change.
- [x] 11.6 **Promotion.**
      This task synchronized the specification by hand at the first closeout. The
      archive (11.11) later merged only the relay-drain deltas, without
      `--skip-specs`, and 11.16 completes this record with the drain's rows.

| Accepted decision | Permanent location |
|---|---|
| A relay's management surface is not a coordination interface | `openspec/specs/physical-provisioning/architecture.md` |
| Buyer VM access is port-based; vhost subdomain routing cannot serve SSH | `openspec/specs/physical-provisioning/architecture.md` |
| The relay token never reaches a buyer-controlled machine, which is why the tunnel client runs on the host | `openspec/specs/physical-provisioning/architecture.md` |
| A relay is a resource rather than pool configuration, because its window and token are shared by every pool referencing it | `openspec/specs/physical-provisioning/architecture.md` |
| Relays are administered resources with unique rendezvous endpoints, addable without redeployment | `openspec/specs/physical-provisioning/spec.md` |
| Relay tokens are encrypted at rest and never returned by a configuration read path | `openspec/specs/physical-provisioning/spec.md` |
| The provisioning service allocates VM relay ports and owns their reclamation; the playbook applies what it is given | `openspec/specs/physical-provisioning/spec.md` |
| A relay port lease is unique per relay, because `remotePort` binds a socket on the relay rather than on the host | `openspec/specs/physical-provisioning/spec.md` |
| A lease is released on every terminal outcome, with reconciliation as the backstop | `openspec/specs/physical-provisioning/spec.md` |
| Relay definitions are imported from a mounted document; the token key is read once, at creation | `openspec/specs/physical-provisioning/spec.md` |
| Relays are administered through their own controller, including token rotation, without redeployment | `openspec/specs/physical-provisioning/spec.md` |
| Import authority is scoped to submitting a document; a process restart is not a submission, so reconciliation is digest-gated | `openspec/specs/resource-pool-management/spec.md` |
| Why import authority exists at all — a declaration an import could silently ignore is not a description of the system | `openspec/specs/resource-pool-management/spec.md` |
| Reconciliation follows a change to the document rather than a restart | `docs/guidance/engineering/definition-documents.md` |
| The resolved `connectivity` field shape and its forwarding contract | `openspec/specs/physical-provisioning/spec.md` |
| Provider configuration reads split into a redacted default and a named execution read | `openspec/specs/resource-pool-management/spec.md` |
| Full replacement does not reset a field a read never returned | `openspec/specs/resource-pool-management/spec.md` |
| The storefront selects no buyer access infrastructure and holds no relay credential | `openspec/specs/vm-storefront-fulfillment/spec.md` |
| The definition document's configuration contract and mount | `docs/guidance/engineering/definition-documents.md` (the contract); `docs/development/DEPLOYMENT_AND_CONFIG.md` (the mount) |
| A relay binding is fixed for a VM's life; rebinding requires draining | `openspec/specs/physical-provisioning/spec.md` |
| Relay tokens are resolved at execution, never carried in a persisted snapshot or returned by a job read | `openspec/specs/physical-provisioning/spec.md` |
| Lease release attaches to the settlement record's terminal transition, in the same transaction | `openspec/specs/physical-provisioning/spec.md` |
| Import and digest commit together, which requires a session-scoped import | `openspec/specs/resource-pool-management/spec.md` |
| Relay uniformity per host is a limit of one client per host, not of the model | `openspec/specs/physical-provisioning/architecture.md` |
| Encrypting a configured secret at rest is part of the configuration pattern | `kit/config` module docstring |
| One SSH key currently reaches every host in an environment; per-host material is supported and unused | recorded in this change's `design.md`; per-host keys are registered through the host API, and `contain-embedded-host-key-material` names one that cannot be decrypted, so no fix is owed |

      The two lease-release rows record what was promoted here. A later change
      rewrote that rule: a lease is now released with its reservation's capacity,
      in the same transaction, and never on a fulfillment state alone
      (`openspec/specs/physical-provisioning/spec.md`, "Relay port leases are
      unique per relay" and "What is held for a reservation is returned with its
      capacity").
- [x] 11.7 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph (the line naming it "returned to design: relay drain"), in
      `openspec/changes/README.md`, and run `make check-change-index`. Other rows'
      `Depends on` are left alone: archive cleanup releases dependents after the
      closeout gate.
      *Done:* the row reads `in closeout`, its Notes rewritten to the validation,
      live evidence, settled gates, and promotion destinations; the campaign's
      graph line and introduction say the change is in closeout and that
      disabling a relay drains it. No other row's `Depends on` or status
      changed; no row depends on this change. `make check-change-index`
      passed. The row's link moves to the archive at 11.11.
- [x] 11.8 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=relay-vm-access-without-a-dashboard` and resolve every
      match, then `scripts/change-workflow openspec validate
      relay-vm-access-without-a-dashboard --strict`.
      *Done:* `make check-doc-citations` passed (5 documents, every cited path
      resolves); `scripts/change-workflow run pre-commit` passed — the index,
      tasks, and skills checks, `validate relay-vm-access-without-a-dashboard
      --strict` ("is valid"), and `make check-repository` (comment hygiene,
      citations, specification index, decision destinations, history wording,
      version bumps, local imports, capability index, guidance).
- [x] 11.9 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change, or an explicit blocker
      naming its cause and the change that owns it, with the validations it gates
      treated as unrun. Sections 6 and 8 are met by the relay-backed real lane, as
      recorded there; sections 10a–10e have no covering scenario and owe none.
      *Recorded:* validation 31 passed at `ac5b91c71`, the merge of `dev` that
      carries the pre-closeout triage's fix: pipeline run 44121374956 (e2e.yml)
      succeeded — `e2e-apicredits`, `e2e-vm`, `e2e-bare-metal`,
      `native-ansible-gate` — with local (`check-packaging`, `test`) and Helm
      (render, deploy, served scenarios, payments and mediation checks) passing.
      CI was not owed: no section carries an `Owed by validation:` line. No
      pipeline or Helm scenario exercises relay access, so the run is regression
      evidence only. The change's scenario, `e2e_vm_real_provisioning`, needs a
      real KVM host and a deployed relay; it met sections 6 and 8 through
      `prove-relay-provisioning`'s D9 mapping on an independent operator
      deployment at `72b40a25b`. Closeout changes no code, so the run describes
      the code the closeout commit carries: it names the merged `HEAD` closeout
      started from, after the pre-closeout review, with no waiver.
- [x] 11.10 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
      *Done:* `scripts/change-workflow run pre-archive` at `ac5b91c71` passed:
      `make check-packaging` (every lock, build, layer, scope, dependency, kind,
      and release check OK) and `make check-architecture-change`, which reports
      the change owns no architecture row. The change touched no `.agents/`,
      `.claude/`, or `.codex/` path.
- [x] 11.11 **Archival.** Last, once every other part is checked. The deltas now
      carry only the relay drain, written against main's text (06 F1): ADDED
      "Disabling a relay drains it" and "A relay reports whether it has drained",
      MODIFIED "A relay binding is fixed for a lease's life", "Relay admission
      tokens are resolved at execution" and "Disabling a host keeps new
      deliveries off it", and, under `fulfillment`, MODIFIED "A provider declares
      whether its delivery needs a host" (15 F1). So the archive merges them rather than
      skipping them, and 11.6's hand synchronization is not applied twice, since
      none of its requirements is in the deltas any more. First compare each
      MODIFIED block with main's current requirement and carry into the block any
      text main gained since, so the merge replaces nothing another change wrote.
      Then `scripts/change-workflow openspec archive
      relay-vm-access-without-a-dashboard -y` merges the deltas and moves the change
      under `openspec/changes/archive/`; point the index row at the archived
      directory, and run `scripts/change-workflow openspec validate --specs --strict`.
      *Done:* each MODIFIED block was compared with main's requirement; `dev`'s
      merge changed no specification, and no commit touched these requirements
      after the deltas were written, so each carries all of main's text. The
      archive merged the deltas (`fulfillment` 1 modified; `physical-provisioning`
      2 added, 3 modified) and moved the change to
      `openspec/changes/archive/2026-11-17-relay-vm-access-without-a-dashboard/`.
      The diff of both `spec.md` files shows each requirement once, as its delta
      states it, and nothing else changed. The index row links the archived
      directory, and `scripts/change-workflow run pre-commit` validated every
      specification strictly.
- [x] 11.12 **Comment hygiene**, for sections 10a–10e: `make check-comment-hygiene`,
      then read the comments those sections added or rewrote against
      `docs/guidance/engineering/comments.md` — the invariant (disabling a relay
      drains it; the allocator refuses a new owner under the relay row's lock),
      never the change. A finding returns the change to implementation.
      *Confirmed:* `make check-comment-hygiene` passed. The comments and
      docstrings in `allocator.py`, `execution.py`, `deliverability.py`,
      `rebinding.py`, `route_service.py`, `service.py`, `definitions.py`,
      `pool_relays.py`, `db.py`, `container.py`, the contracts' `RelayResponse`,
      and the kit's `DeliverableHosts` state the drain's invariant and its
      reasons in the present tense, naming no change, task, review, or earlier
      behaviour; the stale `held_ports` docstring (26 F1) is gone with the
      method.
- [x] 11.13 **Import placement**, for sections 10a–10e: confirm the imports they
      added are at module level; one that should move returns the change to
      implementation.
      *Confirmed:* no indented import is among the lines 10a–10e and their
      triage fixes added (`4568681ad..56c372624`); the new imports
      (`deliverability.py`, `service.py`'s `func`, the new test modules') are
      at module level.
- [x] 11.14 **Documentation compliance**, for sections 10a–10e and the promotion
      below: `docs/seller-frp-setup.md`, runbook §28, and every promoted passage
      describe the current system, declaratively and with no wording relative to the
      change, and sit where the placement rules put them.
      *Done:* the seller guide's "Registering the relay", "Changing a relay
      later" and "Retiring a relay", and runbook §28's restated drains and
      "Retire a relay", read as present-tense procedure with no wording
      relative to the change; they sit where D5 placed them, the procedure
      beside the relay's existing administration, with the contract in the
      specification. The promoted passages (11.16) are declarative, and each
      decision sits where the placement tables put it: requirements in
      `spec.md` by the archive, rationale and the mechanism in the
      `physical-provisioning` companion, the cross-system report in
      `ARCHITECTURE.md` and the `site-capacity` companion, and the goal's
      state in the roadmap. Checked against the code: `deliverability.py`,
      `allocator.py`, `execution.py`, `rebinding.py`, and `service.py` do what
      the passages say.
- [x] 11.15 **Roadmap currency.** In `docs/development/ROADMAP.md` Goal 1, the gap
      row "Relay deletion under live leases remains an open lifecycle decision…",
      owned by this change, is settled: remove it, and state in the goal's current
      state that disabling a relay drains it and its server's removal is the relay
      operator's. Name the edit in the design-promotion record (11.16).
      *Done:* the gap row is removed; the buyer-access paragraph of Goal 1's
      current state says disabling a relay drains it, for both domains, until
      its read reports `drained`, that nothing deletes a relay, and that a
      drained relay's server is its operator's to remove; the host-placement
      paragraph's hosts taking new delivery now leave out hosts placed or
      declared in a pool on a disabled relay. Named in 11.16's record.
- [x] 11.16 **Promotion** of the relay drain, completing the design-promotion record
      with its own rows, since 11.6's table predates these decisions:

      | Accepted decision | Permanent location |
      |---|---|
      | D1, D3 — disabling a relay drains it, reversibly; nothing deletes a relay | `openspec/specs/physical-provisioning/spec.md`, "Disabling a relay drains it" and MODIFIED "Relay admission tokens are resolved at execution" — written by the archive (11.11) |
      | D1 — removing the relay server is its operator's, outside this repository; the drain and its stated condition are this repository's part | `openspec/specs/physical-provisioning/architecture.md`, a new "Disabling a relay drains it" subsection under "Buyer access to provisioned hosts", after "Rebinding requires draining" |
      | D2 — the relay read's `active_lease_count` and `drained`, required, not waiting for grant expiry | `openspec/specs/physical-provisioning/spec.md`, "A relay reports whether it has drained" — written by the archive |
      | D4 — a relay the document stops listing is left as it is; a listed relay is drained through its `enabled` entry | `openspec/specs/physical-provisioning/spec.md`, "Disabling a relay drains it" (scenario) — written by the archive; the procedure in `docs/seller-frp-setup.md`, "Changing a relay later" (10e.1) |
      | D5 — the relay drain is the pool drain at the relay's scope; refusals name the scope | `openspec/specs/physical-provisioning/spec.md`, MODIFIED "A relay binding is fixed for a lease's life" — written by the archive; `openspec/specs/physical-provisioning/architecture.md`, "Rebinding requires draining"; the procedure in `docs/seller-frp-setup.md` and `docs/development/VALIDATION_RUNBOOK.md` §28 (10e) |
      | D1 item 1 — the hosts taking new delivery the compute composition reports leave out every host placed in, or declared in, a pool referencing a disabled relay (10d.1) | `openspec/specs/fulfillment/spec.md`, MODIFIED "A provider declares whether its delivery needs a host", and `openspec/specs/physical-provisioning/spec.md`, MODIFIED "Disabling a host keeps new deliveries off it" — written by the archive; `openspec/specs/site-capacity/architecture.md` (the `DeliverableHosts` paragraph) and `docs/development/ARCHITECTURE.md` (the usable-host paragraph), each still calling the report "the identifiers of registered, enabled hosts" (15 F1) |
      | D6 — a provisioning container is never shared between users, by design | `openspec/specs/physical-provisioning/architecture.md`, "Relay credentials stay on the host and in the service" |
      | D7 — implementation cadence | no permanent destination |
      | Roadmap: the relay-deletion gap row settled | `docs/development/ROADMAP.md`, Goal 1 (11.15) |
      | D1 item 1's reading — hosts placed in, or declared in, such a pool | `openspec/specs/physical-provisioning/architecture.md`, "Disabling a relay drains it"; `openspec/specs/site-capacity/architecture.md` and `docs/development/ARCHITECTURE.md`, as above |
      | D1, D5 — a leaked client token drains the relay in every registering service | `openspec/specs/physical-provisioning/architecture.md`, "Relay sharing and containment" |
      | The usable-host rule's wording at the site layer | `openspec/specs/site-capacity/testing.md`, "Host Requirement Enforcement" |
      | How the drain was proven | `design.md` only: change history |
      | Campaign index | `openspec/changes/README.md`, the change's row, its campaign's graph line and introduction (11.7) |

      `physical-provisioning` has no `index.md`, so no index entry is owed; run
      `make check-spec-index CHANGE=relay-vm-access-without-a-dashboard`.
      *Done:* the `physical-provisioning` companion gained "Disabling a relay
      drains it" after "Rebinding requires draining", which now states the two
      scopes and the scoped refusal; "Relay credentials stay on the host and in
      the service" states the variables file's protection and that a
      provisioning container is never shared between users; "Relay sharing and
      containment" drains a leaked token's relay. The `site-capacity` companion
      and `ARCHITECTURE.md` describe the report as registered, enabled hosts
      less any the composition withholds, naming the compute composition's
      relay rule and linking the companion. The specification rows are written
      by the archive (11.11). `make check-spec-index` result recorded at 11.8.
- [x] 11.17 **Guidance placement.** Read the guidance sections changed since the
      return to design against the layer test; the drain's promotions go to a
      specification, its companion, a handbook-level guide, and the runbook, not to
      guidance, so record that this return touched no guidance if so, and run
      `make check-guidance`.
      *Done:* since the return, one guidance passage changed:
      `openspec/specs/site-capacity/testing.md`, "Host Requirement
      Enforcement", whose statement of the usable-host rule now names a host
      the composition reports taking new delivery rather than a registered,
      enabled one. It pertains to `site-capacity` alone and stays beside its
      specification; it states no rule beyond the capability, so the layer
      test leaves it where it is. No placement needs a decision.
      `make check-guidance` passed (104 files).

## Sequencing against the sibling changes

`never-strand-the-host-on-passthrough` should land first: section 8 needs a
rented host, and host preparation is the step that can lose one.

`add-host-ssh-port` is independent code but a practical prerequisite for
section 8, because a host reached through a management tunnel cannot be
registered without it.

`contain-embedded-host-key-material` is not a prerequisite for section 8. A
rented host whose operator supplies its own SSH key is registered with it
through the host API (`POST /api/v1/hosts` with `secrets`, or the INI import's
`embedded` mode); that change names such a key when it cannot be decrypted. It
shares no code with this change, and neither depends on the other.

## Implementation progress

Every implementation task is complete. Closeout returned the change to design
on 2026-11-16, on the owner's direction, for its two decision gates (1A.7 and
2A.7); the design settled both (D1–D6), and sections 10a–10e implement the
relay drain.

**Done — the service.** The relay resource, its controller, encryption at rest
under the profile key, the redacted/execution reader split, preserve-on-absent,
rebinding refusal with drain, the port allocator with owner-idempotent
allocation, release with the reservation's capacity (`design.md`, "Lease
release goes with the reservation's capacity"), reconciliation as a background
worker, execution-time token resolution, pre-dispatch rejection, the
digest-gated definition importer, and the relay drain.

**Done — everything around it.** The storefront's removal of relay
connectivity, the two host tunnel clients, VM creation without a dashboard, the
chart wiring, relay methods on the canonical client, and the rewritten seller
documentation.

**The live gates are met:** section 6's reload gate and section 8, through
`prove-relay-provisioning`'s D9 mapping, by an independent operator deployment
running `e2e_vm_real_provisioning` against a real host and a deployed buyer
relay. Reload preserves established sessions, so the per-VM client fallback is
not built, and the relay-uniformity limit stands. 8.2 and 8.6 are met as D9
restates them: refusal without a valid grant, and release without physical
reuse.

**A correction worth carrying forward.** Code review found the change claimed
more than it did in three places, and each is now fixed rather than argued with:
the relay token was persisted in `ansible_jobs.params` and returned by the job
endpoints; `release()` and `reconcile()` had no production callers while the
allocator's comments said release was attached to every terminal outcome; and
`validate_fulfillment` leased a real port. A test named
`test_every_terminal_ending_releases_the_lease` passed against an allocator
nothing called — it parametrized terminal path names, passed them as `owner_id`
strings, and called `release()` itself. It is renamed to describe the primitive,
and the wiring claim moved to a test that drives convergence and fails without
the wiring.

**Four gaps only the higher-level tests could find.** Each was invisible to a
unit test calling a service directly, and each is the kind of defect that
presents in production as something else entirely.

`/api/v1/relays/*` had no entries in `PROVISIONING_ROUTE_CONTRACTS`, so every
relay request failed authentication — the controller worked and its routes were
unreachable. `RelayRebindingRefused` escaped the controller as a 500, so an
operator hitting the drain rule got a stack trace instead of the drain
instructions the message carries. The direct VM-create API carried the relay
token into persisted job parameters, a second instance of the leak already
fixed on the fulfillment path. And leases were recorded with `pool_id=None`
while the rule refusing a pool repoint looks leases up *by pool*, so that rule
could never fire — permissive, silently, and observable only by repointing a
pool that was carrying tunnels and watching it succeed.

The integration harness also set `ssh_decryption_key=""`, so at-rest
encryption failed closed and no integration test had ever reached an encrypted
path.

## Validation evidence

Run as the repository runs them, against a clean checkout with the fileset
applied.

| Suite | Baseline | Current |
|---|---|---|
| `make test` unit, `provisioning/compute/service` | 522 | **628** |
| `make test` integration, same | 196 | **215** |
| `make test`, `kit/resource-pools` | 94 | 94 |
| `make test`, `kit/fulfillment` | 152 | **154** |
| `make test`, `domains/vms/provisioning/iac` | 52 | **65** |
| `make check-comment-hygiene` | passes | passes |

`test_test_controller.py` intermittently reports one failure across
`TestDrain`, `TestWaitForJob`, and `TestJobSummary`; all pass on re-run and are
the known flakes recorded in the campaign handoff.

**Unrun, and why.**

- `domains/vms/storefront` — `make test` runs `reinit`, which runs
  `verify-hosted-release`, which needs a staged hosted release this environment
  cannot obtain. Five storefront files changed here, two of them tests, and
  **none of it is verified by test**.
- `helm` `make test-render` — no `helm` binary available and its download host
  is outside the egress allowlist. The chart changes are **unrendered**.
- `domains/vms/provisioning/iac` `make validate` and `make validate-inventory` —
  no `ansible` binary, and `ansible/inventory/hosts` is gitignored and absent.
  Sections 4 and 5 carry `test_vm_management_contracts.py` coverage only;
  `--syntax-check` and lint remain owed. Whether `make validate-inventory`
  passes vacuously is recorded elsewhere as a repository defect and was **not**
  confirmed here either way.
- Section 6's reload gate and section 8 — needed the rented host and the deployed
  relay. *Since met* by the operator deployment those sections record.

**Owed then, and not substitutable by anything above.** The live FRP gate, since
met by sections 6 and 8 (one item is still not shown: a client restarted to
adopt a rotated token reconnecting with it). No test
here runs `frpc` or `frps`, so nothing above shows that a reload preserves an
established session, that a proxy comes up, that the relay accepts a port inside
its window and refuses one outside it, or that a client restarted to adopt a
rotated token reconnects with it. Substring assertions over a playbook are not
evidence about `frpc`, and neither is a harness that fakes it: the cleanup
script's shell is executed for real, but with `curl` and `systemctl` stubbed,
which proves which commands run and nothing about what they do.

That gap is section 6 and section 8, and it is the reason those sections exist
rather than an omission in the ones above them.
