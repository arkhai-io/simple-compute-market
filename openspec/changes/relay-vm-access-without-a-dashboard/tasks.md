# Implementation Tasks

Paths are relative to the repository root. IaC paths are under
`domains/vms/provisioning/iac/`.

This change touches four packages and the IaC project. Ordering matters:
sections 1–3 make the service able to allocate and forward, section 4 makes the
host able to receive it, and section 5 rewires VM creation onto both. Landing 5
before 1–4 leaves VM creation calling a dashboard that is already gone.

Nothing here needs a live relay to implement. Section 8 needs one, and its
evidence is supplied by the operator.

## 1. Relay configuration and the token

- [ ] 1.1 Remove the relay keys from the `connectivity` payload built by
      `_connectivity_settings_from_storefront_config` in
      `domains/vms/storefront/src/market_storefront/services/fulfillment_service.py`:
      `frp_server_addr`, `frp_domain`, `frp_dashboard_password` all go, and
      nothing relay-related replaces them. Relay location is pool
      configuration, so the storefront stops naming a relay per request; the
      buyer-facing address is returned in the fulfillment result instead.
- [ ] 1.2 The relay **token does not travel this way.** It is a credential and
      the storefront has no reason to hold one. Confirm the function returns
      the four fields above and nothing secret.
- [ ] 1.3 Apply the same replacement in
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
- [ ] 1.4b Extend the pool-configuration read/write path (`PoolConfigHandler`
      and the pool API models) so an operator can set and read them, following
      how `default_vm_ram` and its siblings are already carried. All four are
      ordinary configuration and are returned by the pool endpoints; the
      credential is not among them, so there is nothing secret in a pool row to
      redact from a read response and no write path through which a token could
      be set. See `design.md`'s open question on whether relay administration
      eventually warrants its own resource.
- [ ] 1.5 The relay token reaches the service as `relay_token` in the existing
      `provisioning-secrets` dynaconf profile. The name matches what the
      deployment renders and follows the flat snake_case convention of
      `ssh_decryption_key` and `storefront_admin_key`; `_token` rather than
      `_key` because it is a shared bearer token, not key material. Declare it
      in `settings.toml` with an empty default alongside the FRP block it
      replaces. No new mount, no new Secret, no
      chart change — the profile is already rendered into Secret Manager,
      already projected by ESO, and already mounted at
      `/app/config/config-provisioning-secrets.yml` in both the migrate init
      container and the application container. Read it exactly as
      `ssh_decryption_key` is read, via `getattr(self._settings, ...)` with a
      default, so an environment whose profile predates the key loads rather
      than crashing.
- [ ] 1.5a Resolve the token **per relay** from `relay_tokens[relay_id]`, with
      **no scalar fallback and no default**. Relays reached by different pools
      are operated by different parties and admit on different tokens; a
      fallback would either fail at admission with an error naming the relay's
      rejection rather than the missing configuration, or — if two relays happen
      to share a token — succeed and hide the misconfiguration until they do
      not. Declare `relay_tokens` as an empty map in `settings.toml`.
- [ ] 1.5b Key the map by the derived `relay_id`, not by a separate label, so
      there is one fact and no second identifier to keep consistent with the
      endpoint.
- [ ] 1.5c Fail before dispatch when a pool has a relay configured and no
      matching entry exists, alongside the other partial-configuration
      rejections in section 3.
- [ ] 1.6 Default it to empty rather than requiring it. A deployment with no
      relay configured is valid — it uses the direct-NAT path — so an absent
      token is a state, not an error. Section 3 is what makes a *partial*
      relay configuration fail.
- [ ] 1.7 Forward it as `frp_auth_token` from `_build_builtin_var_lines` in
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/ansible_service.py`,
      which currently passes `frp_server_addr`, `frp_domain`, and
      `frp_dashboard_password`, and no token at all.

**Validation:** `make test` in `domains/vms/storefront`,
`provisioning/compute/service`, and `domains/vms/provisioning`.

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
- [x] 2.1a Derive `relay_id` from the normalized `relay_addr:relay_port` held in
      the owning pool's configuration. Not a separately administered
      identifier, and **not the pool id**: two pools may point at one relay, so
      a pool-scoped key would issue a port another pool already holds. See
      `design.md` for both, and for the `relays`-table revisit.
- [x] 2.2 Schema ships as **one** migration, `20260901_001_relay_reachable_hosts`,
      covering `hosts.ssh_port`, the pool relay columns, and the lease table.
      A schema version costs an operator step whether or not it carries much,
      and these deploy together, so they are one event rather than three.
      Appending makes `check_schema_version` require it before startup — a
      deployment consequence, recorded in section 9.
- [ ] 2.3 Allocate on VM creation: first free port in the configured window for
      that relay, recorded before the job is dispatched. Allocating after
      dispatch means a crash between the two leaves a port bound on the relay
      that no record claims.
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
- [ ] 7.3a Token resolution: two relays with different entries each get their
      own; a relay with no entry fails before dispatch rather than borrowing
      another's; a pool with no relay configured needs no entry.
- [ ] 7.3b No pool read response carries a token, under any pool configuration.
      Assert against the serialized response rather than the model, since that
      is where a future field would leak.
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

## 9. Documentation and deployment consequences

- [ ] 9.1 Rewrite `docs/seller-frp-setup.md`. It describes the dashboard, the
      `frp-admin` subdomain, the wildcard DNS record, the certificate, the
      three replaced storefront keys, and subdomain-form buyer connection
      strings. Most of its detail becomes wrong; leaving it to contradict the
      code is worse than the edit.
- [ ] 9.2 Update the storefront chart values and any `[provisioning]` examples
      carrying the removed keys. Find them rather than assuming the two files
      in 1.4 are all of them.
- [ ] 9.3 Record that section 2's migration makes `check_schema_version` require
      it before startup, and that applying it to a deployed database is an
      operator step this change does not perform.
- [ ] 9.5 Record what a deployment must supply for the relay path to work: the
      four `connectivity` fields, and a `relay_token` key in the
      `provisioning-secrets` dynaconf profile. State it as a configuration
      contract — what the service reads and what happens when it is absent —
      rather than as instructions for any particular deployment.
- [ ] 9.4 No host migration. The dev cluster has never run a live-fire
      provisioning test and is deployed in mock mode, so no host has been
      initialized against the relay and none carries an accumulated
      `/etc/frp/frpc.toml`. The population is empty; write no migration for it.
      Host inventory automation and the non-mock redeploy are separate later
      work.

## 10. Closeout

- [ ] 10.1 **Comment hygiene.** `make check-comment-hygiene` from the
      repository root, then read the touched files for what the target cannot
      catch. The invariant belongs in the comment — the token never reaches a
      buyer-controlled machine; allocation is the service's and the playbook
      applies what it is given — never the change that introduced it.
- [ ] 10.2 **Import placement.** Check each import added for a real reason to
      be local before moving it; verify with `make test`.
- [ ] 10.3 **Documentation compliance.** Re-read `openspec/README.md`'s
      placement rules and apply them directly.
- [ ] 10.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, material evidence, and unresolved work.
- [ ] 10.5 **Roadmap currency.** Decide once for all three changes in this
      campaign whether `docs/development/ROADMAP.md` warrants a goal covering
      reaching hosts and VMs without an inbound route, and record the
      disposition either way.
- [ ] 10.6 **Promotion.**

| Accepted decision | Permanent location |
|---|---|
| A relay's management surface is not a coordination interface | `openspec/specs/physical-provisioning/architecture.md` |
| Buyer VM access is port-based; vhost subdomain routing cannot serve SSH | `openspec/specs/physical-provisioning/architecture.md` |
| The relay token never reaches a buyer-controlled machine, which is why the tunnel client runs on the host | `openspec/specs/physical-provisioning/architecture.md` |
| The provisioning service allocates VM relay ports and owns their reclamation; the playbook applies what it is given | `openspec/specs/physical-provisioning/spec.md` |
| Relay location and port window are pool configuration; the storefront names no relay | `openspec/specs/physical-provisioning/spec.md` |
| The relay credential is resolved per relay, never shared across relays operated by different parties | `openspec/specs/physical-provisioning/spec.md` |
| A relay port lease is scoped to the relay, because `remotePort` binds a socket on the relay rather than on the host | `openspec/specs/physical-provisioning/spec.md` |
| A lease is released on every terminal outcome, with reconciliation as the backstop | `openspec/specs/physical-provisioning/spec.md` |
| The resolved `connectivity` field shape and its forwarding contract | `openspec/specs/physical-provisioning/spec.md` |
| The storefront supplies relay location, never the relay credential | `openspec/specs/vm-storefront-fulfillment/spec.md` |

## Sequencing against the sibling changes

`never-strand-the-host-on-passthrough` should land first: section 8 needs a
rented host, and host preparation is the step that can lose one.

`add-host-ssh-port` is independent code but a practical prerequisite for
section 8, because a host reached through a management tunnel cannot be
registered without it.

## Implementation progress

Started this session; the remainder is a clean handoff, not a partial state.

**Done — schema foundation.** `AnsiblePoolConfig` gains `relay_addr`,
`relay_port`, `vm_port_range_start`, `vm_port_range_count`, all nullable so a
pool with no relay keeps serving VMs by direct NAT, plus a derived `relay_id`
property. `RelayPortLease` is added with `UNIQUE(relay_id, remote_port)`. Schema ships as one
migration, `20260901_001_relay_reachable_hosts`, folding in the `hosts.ssh_port`
column that `add-host-ssh-port` previously carried separately.

Covered by `tests/unit/services/test_relay_port_leases.py`, which pins the
constraint at the database rather than in an allocator that could be rewritten
around it: one relay cannot issue a port twice; two hosts on one relay cannot
share a port; **two pools on one relay cannot share a port**; two relays may
each issue the same port; identity is derived, normalized, shared by pools on
one endpoint, and absent when no relay is configured; existing pool rows keep
working.

**Not started.** Sections 1 (connectivity reshape and token forwarding, except
1.4a), 3, 4, 5, 6, 8, 9, 10, and the allocator itself (2.2–2.8). The Ansible
work in 4 and 5 is the largest remaining piece and is independent of the
service-side allocator.

**Sequencing note for whoever continues.** Section 6's reload gate needs the
node. Sections 1–5 are written against the assumption that `frpc reload`
preserves established sessions; if the gate fails, the rework is confined to how
the VM-facing client is configured — one process per VM instead of one per host
— and does not reach the lease model or the connectivity shape.

## Validation evidence

| Suite | Baseline | With the work so far |
|---|---|---|
| `make test` unit, `provisioning/compute/service` | 475 passed | **522 passed** |
| `make test` integration | 185 passed | **196 passed** |

No failures. The schema work adds 16 unit tests.
