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

- [ ] 1.1 Remove the relay keys from the `connectivity` payload built by
      `_connectivity_settings_from_storefront_config` in
      `domains/vms/storefront/src/market_storefront/services/fulfillment_service.py`:
      `frp_server_addr`, `frp_domain`, `frp_dashboard_password` all go, and
      nothing relay-related replaces them. Which relay a host dials is a
      property of the deployment, so the storefront stops naming one per
      request; the buyer-facing address is returned in the fulfillment result
      instead.
- [ ] 1.2 The relay **token does not travel this way.** It is a credential and
      the storefront has no reason to hold one. Confirm the function returns no
      relay field and nothing secret.
- [ ] 1.3 Apply the same removal in
      `domains/vms/storefront/src/market_storefront/services/vm_fulfillment_service.py`,
      which builds the same payload on the VM path. Two call sites, one shape;
      a test asserting they agree belongs in section 7.
- [ ] 1.4 Remove the three `[provisioning]` relay keys and their comments from
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
- [ ] 1.4b Extend the pool-configuration read/write path (`PoolConfigHandler`
      and the pool API models) so an operator can set and read the relay
      reference, following how `default_vm_ram` and its siblings are already
      carried.

      **Amended:** what a pool carries is a reference to a relay, not the
      endpoint and window themselves. The token is never among the fields a
      read returns; see 1.10.
- [ ] 1.8 Add a `relays` table to
      `provisioning/compute/service/src/compute_provisioning_service/db/models.py`:
      an identifier, `relay_addr`, `relay_port`, `vm_port_range_start`,
      `vm_port_range_count`, an encrypted token column, `enabled`, and
      timestamps. **`UNIQUE(relay_addr, relay_port)`** — one rendezvous cannot
      be recorded twice, which is what stops one relay appearing under two
      identities and issuing the same port to two callers.
- [ ] 1.8a Replace the four relay columns on `AnsiblePoolConfig` with a
      nullable foreign key to a relay. Nullable because a pool with no relay
      serves VMs by direct NAT, which stays supported.
- [ ] 1.8b Remove the derived `relay_id` property added by 1.4a. Identity is
      the referenced row. Keep the normalization it performed and apply it on
      write to `relay_addr` instead, so two spellings of one endpoint collide
      on the unique constraint rather than creating two rows.
- [ ] 1.9 Store the token encrypted, using `encrypt_key` from
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/crypto.py`
      with the `ssh_decryption_key` setting — the same profile key that already
      protects embedded host key material. The database holds ciphertext, so a
      stored token is not a usable credential without a key held outside it.
- [ ] 1.9a Do not add a second encryption setting. One profile key with two
      uses is one thing for a deployment to rotate; two keys protecting
      material of the same class is a second rotation path that will drift from
      the first.
- [ ] 1.10 Split provider-configuration reads in two, in
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
- [ ] 1.10a Prefer a distinct method to a boolean parameter. A method name can
      be searched for and cannot be supplied by a stray positional argument.
- [ ] 1.10b Route the execution read through the fulfillment path only:
      `get_pool_in_session` in
      `kit/resource-pools/src/market_resource_pools/service.py` gains an
      execution-scoped sibling, and
      `kit/fulfillment/src/market_fulfillment/fulfillment.py` calls it where it
      currently calls `get_pool_in_session`. Leave `_attach_provider_config`,
      `export_pools_yaml`, and `_calculate_reconciliation` on the redacted read.
- [ ] 1.11 Make an omitted token preserve the stored value, in `replace_config`
      for both handlers. `update_pool` reads through the redacted read and
      writes back what it read, so without this a request changing only a label
      round-trips a configuration with no token and erases the credential. This
      is an explicit exception to the pool API's replacement semantics, which
      otherwise reset omitted fields; the exception exists because a caller
      cannot restate a value no read ever returned.
- [ ] 1.11a Provide no way to clear a token through a partial write. Clearing
      one disables every VM path on that relay and should be an explicit act,
      not an omission.
- [ ] 1.12 Return a boolean indicating whether a token is configured, on relay
      and pool reads. An operator needs to answer "is this relay usable" from a
      read without the value being disclosed, and a boolean is sufficient
      because nothing compares tokens across systems.
- [ ] 1.13 The relay controller is section 1A. It is the administration surface
      for everything above and is load-bearing rather than incidental: a relay
      is changed through it, not by redeploying.
- [ ] 1.14 Fold the relay table, the pool foreign key, and the lease table into
      the single migration `20260901_001_relay_reachable_hosts` rather than
      appending a second. It has not been applied in any environment, so
      editing it costs nothing and keeps the operator step singular.
- [ ] 1.7 Forward the token as `frp_auth_token` from
      `_build_builtin_var_lines` in
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/ansible_service.py`,
      which currently passes `frp_server_addr`, `frp_domain`, and
      `frp_dashboard_password`, and no token at all. The value comes from the
      execution read, never from a pool response.
- [ ] 1.7a Confirm the token does not reach the job's persisted variable
      snapshot in cleartext, or if it must, that the snapshot is not returned by
      any read path. Follow how the existing redaction in `ansible_service.py`
      treats `password` and `ssh_key_path_host`.

**Validation:** `make test` in `domains/vms/storefront`,
`provisioning/compute/service`, `domains/vms/provisioning`, and
`kit/resource-pools`.

## 1A. The relay controller

The administration surface for relays. It is what makes a relay changeable
against a running service, which is the property the whole resource shape exists
to provide — and the property section 9's seeding must not quietly take back.

- [ ] 1A.1 Add `relays_controller.py` alongside
      `provisioning/compute/service/src/compute_provisioning_service/controllers/pools_controller.py`,
      following its authentication and router-registration pattern rather than
      inventing a second one.
- [ ] 1A.2 Implement create, list, detail, and update. Update covers the
      rendezvous address, port, and window, so a relay can be repointed without
      recreating it and without invalidating the leases held against it.
- [ ] 1A.3 Implement token rotation as an explicit operation rather than as a
      field on a general update. Rotation is the one write whose effect is
      invisible in every read, so it should be requested deliberately and
      should be distinguishable in an audit log from an edit that happened to
      carry a token.
- [ ] 1A.4 Return `relay_token_configured` and never the token, on every
      response this controller produces. The redacted read from 1.10 is what
      serves it; the controller does not reach past it.
- [ ] 1A.5 Implement enable and disable. Disable is what section 3 rejects a
      dispatch against, and it is the operator's answer to "stop using this
      relay" without deleting a row that leases still reference.
- [ ] 1A.6 **Do not implement deletion.** `design.md` records it as an open
      question: a relay with live leases cannot simply be removed, and
      refusing, disabling, or cascading a release are all defensible. Task
      1A.7 is the gate.
- [ ] 1A.7 **Decide and record** the deletion semantics in `design.md` once
      section 2's reconciliation behaviour is settled, then implement the
      decision or record why it stays deferred. This is a decision task, not an
      instruction to implement one of the three.
- [ ] 1A.8 Reject an update that would duplicate another relay's rendezvous,
      with both relay identifiers named. The unique constraint would catch it,
      but a constraint violation surfacing as a 500 is not an administration
      surface.
- [ ] 1A.9 Register the router where the pools router is registered, and add it
      to whatever surface enumerates routes for the typed client, so the Level 2
      suite can drive it through the canonical client rather than a hand-built
      request body.

**Validation:** `make test` in `provisioning/compute/service`, including the
Level 2 integration suite, since the controller is a contract rather than an
internal seam.

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
- [ ] 2.1b Make `relay_id` a foreign key to the relay row added in 1.8, and
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
- [ ] 2.3 Allocate on VM creation: first free port in the **relay's** window,
      recorded before the job is dispatched. Allocating after dispatch means a
      crash between the two leaves a port bound on the relay that no record
      claims.
- [ ] 2.4 Release on **every terminal outcome**, not only teardown: a dispatch
      that never starts, a permanently failed creation, a cancellation, and an
      expiry each end a VM's life without a teardown running. A release attached
      to teardown alone leaks on all four.
- [ ] 2.4a Add reconciliation: a periodic sweep releasing leases whose owning
      job or fulfillment has been terminal beyond a grace period. A set of code
      paths is never provably exhaustive, and this bounds the leak from the one
      that was missed. Follow the existing recovery-worker pattern rather than
      inventing a second scheduling mechanism.
- [ ] 2.5 Fail the request when the window is exhausted for that relay, with a
      message naming the relay and the window. A relay refusing a proxy surfaces
      asynchronously in a client log; an exhausted window must not reach that
      point.
- [ ] 2.6 Pass the allocated port to the job as an input, so `vm-create.yml`
      receives a port rather than deriving one.

**Validation:** `make test` in `provisioning/compute/service`.

## 3. Reject partial relay configuration before dispatch

- [ ] 3.1 Today the two access paths are guarded by different conditions —
      direct NAT by `frp_server_addr is not defined`, relay by
      `frp_dashboard_password is defined`. A configuration satisfying neither
      creates a VM with no external route and reports success. Add validation
      where other malformed VM requirements are already rejected, so exactly
      one access path is always selected.
- [ ] 3.2 The invariant to enforce and to test: no configuration selects zero
      access paths. Assert it against the *configuration*, not against the
      playbook's guards, so a later change to the guards cannot quietly
      reintroduce the hole.
- [ ] 3.3 Reject before dispatch when a pool references a relay that is
      disabled, has no usable allocation window, or has no token configured.
      Each produces a VM with no route by a different mechanism, and each is
      knowable from configuration before any host is touched.
- [ ] 3.4 Name the relay and the missing element in the rejection. The failure
      this replaces is a relay refusing a proxy asynchronously in a client log;
      a rejection that says only "misconfigured" reproduces the diagnostic
      problem the change exists to remove.

**Validation:** `make test` in `provisioning/compute/service`.

## 4. Two relay clients on the host

- [ ] 4.1 Rework `ansible/roles/vm-setup/tasks/frp-client.yml` to install the
      binary and the **VM-facing** client only: `/etc/frp/frpc-vms.toml` and
      `frpc-vms.service`. The host's management tunnel is written by the
      host preparation, outside this repository, and is never touched by a VM
      operation.
- [ ] 4.2 Rename `ansible/roles/vm-setup/templates/frpc.toml.j2` to
      `frpc-vms.toml.j2` and `frpc.service.j2` to `frpc-vms.service.j2`. Two
      files, two units, no shared write target — which also removes the hazard
      that re-running host setup re-templates one file and erases live VM
      proxies.
- [ ] 4.3 Remove the fallback token. `frp_auth_token | default('password123456789')`
      means a host initialized without an explicit token is configured with a
      value published in a tracked file. An undefined token must fail the task;
      replacing the literal with a better literal preserves the failure mode.
- [ ] 4.4 Bind `frpc`'s admin API to `127.0.0.1` in the VM client's
      configuration. It supplies both the reload and the status check that
      replace the two dashboard uses.
- [ ] 4.5 Make the version a variable rather than a `set_fact` literal inside
      the install task, and set it to match the deployed relay. The client
      version is a property of which relay the fleet talks to, so it must be
      settable without editing a task.
- [ ] 4.6 Update the `restart frpc` handler in
      `ansible/roles/vm-setup/handlers/main.yml` for the renamed unit, and
      confirm nothing else references the old unit name.

**Validation:** `make validate` in `domains/vms/provisioning/iac`, plus the
structural checks in `tests/test_ansible_structure.py`, which cover task files
`--syntax-check` does not reach.

## 5. VM creation without a dashboard

- [ ] 5.1 In `ansible/roles/vm-management/tasks/vm-create.yml`, delete the
      three dashboard calls: the subdomain-discovery request, the used-port
      request, and the online-status poll against
      `https://frp-admin.<frp_domain>/api/proxy/tcp`.
- [ ] 5.2 Delete the port-selection loop and its hardcoded 7002–8000 window.
      The port now arrives as a job input.
- [ ] 5.3 Drop `subdomain` from the generated proxy stanza. FRP's `subdomain`
      is a vhost feature of the `http` and `https` proxy types; a `tcp` proxy
      binds a distinct port whatever the key says, and SSH sends no SNI and no
      `Host` header for a relay to demultiplex on.
- [ ] 5.4 Write the stanza to `/etc/frp/frpc-vms.toml` rather than
      `/etc/frp/frpc.toml`.
- [ ] 5.5 Replace `systemctl restart frpc` with a reload through the
      loopback-bound admin API. A restart closes the control connection, so the
      relay tears down every proxy that client registered and every buyer's
      established session with it.
- [ ] 5.6 Replace the dashboard online-poll with a status check against the
      same local admin API. Polling the relay to learn whether the local client
      succeeded is a round trip to ask a third party about our own state.
- [ ] 5.7 Apply the same substitutions to
      `ansible/roles/vm-management/tasks/vm-undefine.yml`, which removes the
      stanza and restarts the client on teardown.
- [ ] 5.8 Produce the buyer connection string as `ssh -p <port> <user>@<relay>`,
      matching what `ssh_commands` already emits on the direct-NAT path.

**Validation:** `make validate` in `domains/vms/provisioning/iac`.

## 6. Reload verification gate

- [ ] 6.1 **[log]** Prove that `frpc reload` preserves established sessions.
      Open an SSH session through a tunnel, append an unrelated proxy stanza,
      reload, and check the session is still alive. Supplied: the client's log
      across the reload, and evidence the session outlived it.
- [ ] 6.2 **Decide and record** in `design.md`. If reload preserves sessions,
      section 5 stands as written. If it does not, the recorded fallback is one
      `frpc` process per VM, and that decision is taken here rather than
      assumed either way now.
- [ ] 6.3 If the fallback is needed, note that `transport.poolCount = 5` in the
      current template means five idle connections per VM, against a relay
      where `transport.maxPoolCount` is unset. Sizing is part of that decision,
      not a detail to discover later.

## 7. Tests

- [ ] 7.1 The `connectivity` payload's new shape survives storefront to adapter
      to extra-vars, and none of the three removed keys appears anywhere in the
      chain. Split by boundary rather than tested as one span: the client-to-API
      contract belongs in the Level 2 suite through the canonical typed client,
      and what the storefront passes to that client is a storefront unit test.
      A hand-built request body standing in for the client proves nothing about
      the contract it is imitating.
- [ ] 7.2 Both storefront call sites build the identical payload.
- [ ] 7.3 An undefined relay token fails rather than templating a default.
- [ ] 7.3a Token resolution: a pool reaches its referenced relay's token; two
      pools referencing one relay reach the same token and the same window; a
      pool referencing a relay with no token fails before dispatch rather than
      borrowing another relay's; a pool referencing no relay needs no token.
- [ ] 7.3b No pool or relay read response carries a token, under any
      configuration. Assert against the serialized response rather than the
      model, since that is where a future field would leak. Cover the export
      document in the same test, because it is a second read surface fed by the
      same reader and is not a response model.
- [ ] 7.3c The token is ciphertext at rest: a stored relay row read directly
      does not yield a usable token, and a round trip through encrypt and
      decrypt returns the original.
- [ ] 7.3d Preserve-on-absent: a full replacement omitting the token retains it;
      an explicit value replaces it; there is no request shape that clears it.
      Assert on PUT specifically, since PUT's documented semantics reset omitted
      fields and this is the exception.
- [ ] 7.3e The execution read returns the token and the redacted read does not,
      over the same pool, so the split cannot be satisfied by a handler that
      returns nothing to either.
- [ ] 7.3f Reconciliation reports an unchanged definition document as unchanged
      on a second import. This is the test that catches a redacted read being
      compared against a document, which would otherwise diverge silently on
      every import forever.
- [ ] 7.4 A configuration selecting no access path is rejected before dispatch.
- [ ] 7.5 Allocation, as unit tests over the lease store: a port is recorded
      before dispatch; a second allocation does not reuse a held port;
      **two different hosts sharing one relay never receive the same port**;
      the same port on two different relays is allowed; an exhausted window
      fails with a message naming the relay and window.
- [ ] 7.5a Lease lifecycle: each terminal outcome releases the lease — teardown,
      a dispatch that never starts, a permanently failed creation, a
      cancellation, an expiry. Assert per-path rather than through one
      representative, since the point is that no path is missed.
- [ ] 7.5b Reconciliation: a lease whose owner has been terminal beyond the
      grace period is released; one whose owner is still live is not.
- [ ] 7.5c Level 2, through the canonical typed client in
      `provisioning/compute/service/tests/integration/`: the allocation and
      release lifecycle wherever the API is part of the contract, following
      `test_hosts_api.py`.
- [ ] 7.5d Relay identity survives an address change: leases held against a
      relay remain associated with it after its `relay_addr` is updated. This
      is the property the foreign key buys over a derived string, so it is the
      test that fails if 2.1b is reverted.
- [ ] 7.5e A duplicate rendezvous is rejected: creating a second relay with an
      address and port already recorded fails, including when the address
      differs only by normalization.
- [ ] 7.8 Digest gating, as unit tests over the import path: a first startup
      with no recorded digest reconciles; a restart with an unchanged document
      does not; an edited document reconciles; an explicit import request
      reconciles regardless of the digest.
- [ ] 7.8a **The restart case is the point of the whole mechanism.** Change
      state through the API, restart the service against the same mounted
      document, and assert the API change survived. Assert it over a real
      restart path rather than a second call to the import function — a test
      that never rebuilds the service from its configuration does not exercise
      the failure being prevented.
- [ ] 7.8b A failed apply leaves the recorded digest unchanged, so the next
      startup retries rather than treating a half-applied document as done.
- [ ] 7.8c An edited document still reconciles authoritatively: an entry the
      document no longer names is disabled, and an entry whose window changed
      is updated. Digest gating changes *when* reconciliation happens, not what
      it does.
- [ ] 7.8d A token rotated through the controller survives a subsequent
      reconciliation of an edited document that still names the profile key
      holding the old value. This is the one field a reconciliation must never
      revert, and it is protected structurally rather than by the digest.
- [ ] 7.8e Relay definitions: a document naming a profile key creates the relay
      with the encrypted token; a document naming a key absent from the profile
      fails with the key named rather than storing an empty token.
- [ ] 7.8f A relay established from a document remains present and enabled after
      the document is unmounted, and pools referencing it still dispatch.
- [ ] 7.8g A pool referencing a relay that does not exist fails before dispatch
      with both names, rather than dispatching against a missing relay.
- [ ] 7.9 Controller behaviour, at Level 2 through the canonical typed client:
      create, list, detail, update, rotate, enable, disable. No response carries
      a token; every response carries whether one is configured.
- [ ] 7.9a A rotated token takes effect on the next dispatch without a restart.
      This is the property the controller exists to provide, so it is asserted
      end to end rather than inferred from a successful write.
- [ ] 7.9b An update duplicating another relay's rendezvous is rejected with
      both identifiers named, rather than surfacing as a constraint violation.
- [ ] 7.6 Rendered client configuration contains no `subdomain` key and no
      dashboard address. Assert against non-comment lines, as
      `tests/test_passthrough_audit.py` does, so the check cannot be satisfied
      by rewording a comment.
- [ ] 7.7 Shell logic in the reworked `vm-create.yml` runs under
      `tests/shell_harness.py` with the admin API faked, in the manner of
      `tests/test_gpu_attachment_discovery.py`. Substring assertions over YAML
      cannot prove the reload path behaves.

**Validation:** `make test` in each touched package and in
`domains/vms/provisioning/iac`.

## 8. Live verification [log]

Requires a rented, initialized host and the deployed relay.

- [ ] 8.1 **[log]** A proxy registered inside the configured window is accepted.
      Supplied: the relay's log naming the port.
- [ ] 8.2 **[log]** A proxy outside the window is refused. Supplied: the same
      log. This is what proves the window is enforced by the relay rather than
      only respected by the client.
- [ ] 8.3 **[log]** Creating a second VM leaves the first VM's established SSH
      session alive. Supplied: client log plus the surviving session.
- [ ] 8.4 **[log]** The host's management tunnel is unaffected by VM creation
      and teardown. Supplied: management client status across both.
- [ ] 8.5 **[log]** A buyer connection string produced by the relay path
      connects. Supplied: the string and a successful session.
- [ ] 8.6 **[log]** Teardown releases the port, and it is reused by the next
      VM. Supplied: allocation records before and after.

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

- [ ] 9.1 Record a durable digest per definition document and reconcile at
      startup only when the current document differs from the recorded one.
      Follow the `schema_migrations` precedent in
      `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`
      — a table recording what has been applied, consulted before applying it
      again — rather than inventing a second bookkeeping mechanism.
- [ ] 9.1a Update the digest in the **same transaction** that applies the
      reconciliation. A digest written on a failed apply suppresses the retry
      and leaves the database in a state no document describes.
- [ ] 9.1b Leave the explicit import endpoint unconditional. An operator
      submitting a document has asked for reconciliation, and gating that on a
      digest would make a resubmission silently do nothing.
- [ ] 9.1c Correct the comment in `app_runtime.py` that asserts re-running on
      every restart is correct. State the actual invariant: reconciliation
      follows a change to the document, and a process restart is not one.
- [ ] 9.2 Add a relay definition document and a `relay_definitions_path`
      setting, reconciled by the same digest-gated path as pools. Relays and
      pools get one rule, not two: a reader who knows one should not guess wrong
      about the other.
- [ ] 9.2a Each entry holds a rendezvous address, port, and window, and **no
      credential** — so the document is an ordinary mounted configuration file
      and needs no Secret.
- [ ] 9.2b Each entry may name which key of the secrets profile holds its
      token. The key is read **only when the relay is created** and never
      re-read, so a token rotated through the controller survives a later
      reconciliation of an edited document.
- [ ] 9.2c Fail the import, naming the key, when an entry names a profile key
      the profile does not carry. Creating a relay with an empty token defers
      the failure to admission, which is the diagnostic failure this change
      exists to remove.
- [ ] 9.2d Reconcile relays before pools, so a pool referencing a relay
      resolves on a first boot.
- [ ] 9.3 Declare `relay_token` in
      `provisioning/compute/service/src/compute_provisioning_service/settings.toml`
      with an empty default, replacing the `frp_server_addr`, `frp_domain`, and
      `frp_dashboard_password` block. Read it as `ssh_decryption_key` is read,
      with a default, so an environment whose profile predates the key loads
      rather than crashing. It is a **bootstrap value**, not a store: nothing
      reads it at dispatch, and nothing re-reads it once a relay exists.
- [ ] 9.3a An absent token is a valid state — a deployment with no relay uses
      the direct-NAT path. Section 3 is what makes a *partial* relay
      configuration fail.
- [ ] 9.4 Wire `relay_definitions_path` into the provisioning chart in
      `helm/charts/provisioning`: a values key, a ConfigMap carrying the
      document, and a mount into the application container only. The migrate
      init container runs migrations and imports nothing.
- [ ] 9.4a Wiring `pool_definitions_path` becomes safe once 9.1 lands, but is
      still **not done here**. It is currently connected to nothing, so wiring
      it would newly subject every existing deployment's pools to declarative
      reconciliation — a change to what a deployment means, not a bug fix.
      Worth doing, deliberately, in its own change.
- [ ] 9.5 Keep the document out of the Secret carrying the profile. It holds no
      credential by construction, and putting it there would make every window
      edit a secret rotation.
- [ ] 9.6 State the configuration contract in
      `docs/development/DEPLOYMENT_AND_CONFIG.md`: what the service reads, what
      each document may contain, that reconciliation follows a change to the
      document rather than a restart, and what happens when each is absent.

**Validation:** `make test` in `provisioning/compute/service` and
`kit/resource-pools`; `helm template` against the chart for each environment's
values to confirm the mount renders and the document is not placed in a Secret.

## 10. Documentation and deployment consequences

- [ ] 10.1 Rewrite `docs/seller-frp-setup.md`. It describes the dashboard, the
      `frp-admin` subdomain, the wildcard DNS record, the certificate, the
      three replaced storefront keys, and subdomain-form buyer connection
      strings. Most of its detail becomes wrong; leaving it to contradict the
      code is worse than the edit.
- [ ] 10.2 Update the storefront chart values and any `[provisioning]` examples
      carrying the removed keys. Find them rather than assuming the two files
      in 1.4 are all of them.
- [ ] 10.3 Record that the migration makes `check_schema_version` require it
      before startup, and that applying it to a deployed database is an
      operator step this change does not perform. The Helm init container
      handles it on the normal path.
- [ ] 10.4 No host migration. The dev cluster has never run a live-fire
      provisioning test and is deployed in mock mode, so no host has been
      initialized against the relay and none carries an accumulated
      `/etc/frp/frpc.toml`. The population is empty; write no migration for it.
      Host inventory automation and the non-mock redeploy are separate later
      work.
- [ ] 10.5 Remove the published fallback token literal from every document that
      quotes it once section 4 has removed it from the template. A credential
      must not survive in permanent documentation because a change document
      needed to name the defect it was removing.

## 11. Closeout

- [ ] 11.1 **Comment hygiene.** `make check-comment-hygiene` from the
      repository root, then read the touched files for what the target cannot
      catch. The invariant belongs in the comment — the token never reaches a
      buyer-controlled machine; allocation is the service's and the playbook
      applies what it is given — never the change that introduced it.
- [ ] 11.2 **Import placement.** Check each import added for a real reason to
      be local before moving it; verify with `make test`.
- [ ] 11.3 **Documentation compliance.** Re-read `openspec/README.md`'s
      placement rules and apply them directly.
- [ ] 11.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, material evidence, and unresolved work.
- [ ] 11.5 **Roadmap currency.** Decide once for all three changes in this
      campaign whether `docs/development/ROADMAP.md` warrants a goal covering
      reaching hosts and VMs without an inbound route, and record the
      disposition either way.
- [ ] 11.6 **Promotion.**

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
| Reconciliation follows a change to the document rather than a restart | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| The resolved `connectivity` field shape and its forwarding contract | `openspec/specs/physical-provisioning/spec.md` |
| Provider configuration reads split into a redacted default and a named execution read | `openspec/specs/resource-pool-management/spec.md` |
| Full replacement does not reset a field a read never returned | `openspec/specs/resource-pool-management/spec.md` |
| The storefront selects no buyer access infrastructure and holds no relay credential | `openspec/specs/vm-storefront-fulfillment/spec.md` |
| The definition document's configuration contract and mount | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| One SSH key currently reaches every host in an environment; per-host material is supported and unused | recorded in this change's `design.md`; the fix is owned by `contain-embedded-host-key-material` |

## Sequencing against the sibling changes

`never-strand-the-host-on-passthrough` should land first: section 8 needs a
rented host, and host preparation is the step that can lose one.

`add-host-ssh-port` is independent code but a practical prerequisite for
section 8, because a host reached through a management tunnel cannot be
registered without it.

`contain-embedded-host-key-material` is a practical prerequisite for section 8
whenever the rented host's operator supplies its own SSH key rather than
accepting the deployment's shared one. It shares no code with this change and
either may land first.

## Implementation progress

**Done — schema foundation, partly superseded.** A previous session added
`relay_addr`, `relay_port`, `vm_port_range_start`, `vm_port_range_count` and a
derived `relay_id` property to `AnsiblePoolConfig`, added `RelayPortLease` with
`UNIQUE(relay_id, remote_port)`, and folded all of it plus `hosts.ssh_port` into
one migration, `20260901_001_relay_reachable_hosts`. Covered by
`tests/unit/services/test_relay_port_leases.py`.

The lease table and its uniqueness stand. The pool columns and the derived
identity do not: a relay is now a row, and tasks 1.8, 1.8a, 1.8b, and 2.1b carry
the replacement. The completed tasks are preserved with amendment notes rather
than rewritten, so the record shows what was built and why it changed.

`test_relay_port_leases.py` pins invariants rather than representation — one
relay cannot issue a port twice, two hosts on one relay cannot share a port, two
pools on one relay cannot share a port, two relays may each issue the same port.
Every one of those survives the move to a foreign key, and 7.5d adds the
property the key buys that a derived string could not: identity surviving an
address change. The tests are expected to need mechanical updating for how a
relay is referenced, not rewriting for what they assert. If an invariant becomes
awkward to state, the change is wrong.

**Migration not applied anywhere,** so it is edited rather than superseded by a
second one, and the deployment remains a single operator step.

**Not started.** Everything else: sections 1 (except the amended schema tasks),
1A, 2's allocator, 3, 4, 5, 6, 7, 8, 9, 10, and 11. The Ansible work in 4 and 5
is the largest remaining piece and is independent of the service-side allocator.
The relay resource in 1, the controller in 1A, and the seeding in 9 are new
since the previous session's plan.

**Section 1A is the shortest path to a usable dev loop.** Sections 1, 1A, and 3
together give a relay that can be created, repointed, and rotated against the
running dev service. Sections 4 and 5 are what a live host needs, and section 9
only matters for a cluster rebuilt from scratch.

**Sequencing note for whoever continues.** Section 6's reload gate needs the
node. Sections 1–5 are written against the assumption that `frpc reload`
preserves established sessions; if the gate fails, the rework is confined to how
the VM-facing client is configured — one process per VM instead of one per host
— and does not reach the lease model, the relay resource, or the connectivity
shape.

## Validation evidence

| Suite | Baseline | With the work so far |
|---|---|---|
| `make test` unit, `provisioning/compute/service` | 475 passed | **522 passed** |
| `make test` integration | 185 passed | **196 passed** |
| `make test`, `domains/vms/provisioning/iac` | 52 passed | 52 passed |

No failures. The schema work adds 16 unit tests.

`make validate` in `domains/vms/provisioning/iac` has **not** been run: the
session environment has no `ansible` binary, and `ansible/inventory/hosts` is
gitignored and absent from a fresh checkout. Sections 4 and 5 therefore land
with `tests/test_ansible_structure.py` coverage only, and `--syntax-check`
remains owed against an environment that has Ansible installed. `make
validate-inventory` cannot be run for the same reason, and its passing without
validating anything is a known repository defect recorded elsewhere, not a
result this change may cite.
