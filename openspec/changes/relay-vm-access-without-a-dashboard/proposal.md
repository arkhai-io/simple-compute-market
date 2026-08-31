## Why

VM buyer access runs through an FRP relay. The VM-creation path does not treat
the relay as a tunnel endpoint: it treats the relay's **management dashboard**
as a coordination database, and reaches it over HTTPS at a DNS name with a
second credential.

`roles/vm-management/tasks/vm-create.yml` calls
`https://frp-admin.<frp_domain>/api/proxy/tcp` with basic auth three times per
VM — once to find a free name, once to find a free port, and once per poll
while waiting for the proxy to come online. That imposes four requirements on
every relay the product can use: an enabled dashboard, a DNS record for
`frp-admin`, a TLS certificate for it, and a dashboard password distributed
alongside the relay token.

A relay deployed without a dashboard cannot be used at all. That is not a
hypothetical posture — frps serves its dashboard and admin API unauthenticated
unless separately configured, so omitting them is the defensible default, and a
relay reached by IP has nowhere to put the `frp-admin` name.

Six further defects sit in the same path:

1. **The port window is hardcoded** to 7002–8000 in a shell heredoc. A relay
   bounding `allowPorts` to any other window refuses every proxy the playbook
   registers, and the failure surfaces as a timeout in the online poll rather
   than as a rejected allocation.
2. **Every VM creation restarts `frpc`.** `systemctl restart frpc` closes the
   client's control connection, so frps tears down every proxy that client
   registered. Provisioning a fourth VM drops the live SSH sessions of the
   buyers holding the first three.
3. **One `frpc` process cannot serve two relays.** `serverAddr` and
   `auth.token` are top-level in `frpc.toml` and cannot be overridden per proxy,
   so a host cannot reach a management relay and a buyer relay independently.
4. **The relay token is never forwarded.** `AnsibleService._build_builtin_var_lines`
   passes `frp_server_addr`, `frp_domain`, and `frp_dashboard_password`, and no
   token. `frpc.toml.j2` therefore falls back to
   `frp_auth_token | default('password123456789')` — a literal in a tracked
   template, used verbatim by any host initialized without an out-of-band
   override.
5. **A partial relay configuration produces a VM nobody can reach, and reports
   success.** The direct-NAT port allocation is guarded by
   `when: frp_server_addr is not defined`; the relay allocation is guarded by
   `frp_dashboard_password is defined`. Configure a relay address without a
   dashboard password — exactly what a dashboard-less relay forces — and both
   guards skip. The VM is created, no external route exists, and the job
   succeeds.
6. **`frpc` is pinned to 0.54.0** by a `set_fact` inside the install task,
   independently of whatever the relay runs.

The proxy stanza also carries `subdomain = "<name>"`, and the seller
documentation describes buyers reaching `<vm>.vm.<domain>`. FRP's `subdomain`
option is a vhost feature of its `http` and `https` proxy types; a `tcp` proxy
binds a distinct port regardless. SSH sends no SNI and no `Host` header, so
there is nothing for the relay to demultiplex on. The key is inert, and the
wildcard DNS record and certificate it implies are not needed.

## What Changes

- **Move port allocation into the provisioning service.** The service selects a
  free port from the configured window, records it against the VM, and passes
  it to the job as an input. The playbook writes the stanza it is given and
  chooses nothing. This replaces dashboard coordination with an authority that
  can reclaim what it allocated, and puts allocation behind a surface that can
  later report which ports are held by which VM on which host.
- **Replace the dashboard online-check with `frpc`'s admin API, bound to
  `127.0.0.1`.** The same interface supplies `reload`, which applies a proxy
  diff and leaves unchanged proxies untouched, so adding a VM stops restarting
  the client.
- **Split the host's relay clients in two.** This repository's role owns the
  VM-facing client (`/etc/frp/frpc-vms.toml`, `frpc-vms.service`); the host's
  own management tunnel is written by the infrastructure repository's
  node-initialization playbook and is never touched by a VM operation. Two
  files, two units, no shared write target — which also removes the hazard that
  re-running host setup re-templates one file and erases live VM proxies.
- **Reshape the `connectivity` field** to `relay_addr`, `relay_port`,
  `relay_token`, `vm_port_range_start`, and `vm_port_range_count`. Remove
  `frp_domain` and `frp_dashboard_password`. Relay-neutral naming, because the
  buyer receives a host and a port and has no reason to learn which relay
  implementation produced them.
- **Forward the relay token as a secret** through the provisioning secrets
  profile, and remove the fallback literal from the template so a missing token
  fails initialization instead of configuring a known one.
- **Fail loudly on a partial relay configuration.** A relay address with no
  usable allocation window is a configuration error, rejected before dispatch,
  rather than a VM created with no route.
- **Drop the inert `subdomain` key** from the generated proxy stanza.
- **Make the `frpc` version a variable** rather than a `set_fact` literal, and
  set it to match the relay currently deployed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: the fulfillment request's `connectivity` field
  changes shape, and the adapter forwards a relay token it did not previously
  carry.
- `vm-storefront-fulfillment`: the storefront's provisioning settings keys
  change with the field.

## Non-Goals

- Do not make connectivity terms buyer-specified or negotiated. That is
  `add-buyer-vm-connectivity-terms`, which extends the negotiation envelope.
  This change alters what the field contains, not who supplies it; the two
  interact and are sequenced in Dependencies below.
- Do not write, own, or configure the host's management tunnel. That belongs to
  the infrastructure repository's node-initialization playbook. This change only
  stops the VM path from writing the file that tunnel lives in.
- Do not replace FRP. Whether a reverse-tunnel relay is the right mechanism at
  all is a separate question; this change makes the existing mechanism work
  against a relay that exposes no management surface.
- Do not remove the direct-NAT path. A host with a public address and no relay
  configured keeps working unchanged.
- Do not add an SSH-independent recovery path for a host. No in-band mechanism
  survives the failure that motivated one; see `design.md`'s decision on what
  the management client proxies, and `never-strand-the-host-on-passthrough` for
  where that failure is prevented.

## Compatibility

**Wire.** The `connectivity` field's shape changes. It is optional and,
per `openspec/specs/physical-provisioning/spec.md#requirement-ansible-fulfillment-adapter`,
opaque metadata the adapter forwards without interpreting — so the blast radius
is the storefront that populates it and the playbook that consumes it, both in
this repository.

**Deployment.** Storefront `[provisioning]` keys `frp_server_addr`,
`frp_domain`, and `frp_dashboard_password` are replaced. A deployment carrying
the old keys must be reconfigured; the relay token moves into the provisioning
secrets profile rather than storefront settings, because it is a credential and
the storefront has no reason to hold it.

**Host state.** None to migrate. The dev cluster has never run a live-fire
provisioning test and is deployed in mock mode, so no host has been initialized
against the relay and none carries accumulated VM proxy stanzas in a single
`/etc/frp/frpc.toml`.

**Delivery.** The relay token is one more key in the `provisioning-secrets`
dynaconf profile, which is already rendered, already projected by External
Secrets, and already mounted into the provisioning service. No new Secret
Manager shell, no new ExternalSecret, no new volume or mount, and no chart or
values change in any environment. The operations-repository delta is an added
line where that profile is rendered.

**Documentation.** `docs/seller-frp-setup.md` describes the dashboard, the
wildcard record, and the three storefront keys, and instructs sellers to expect
subdomain-form connection strings. It becomes wrong in most of its detail and
is rewritten as part of this change rather than left to contradict the code.

## Dependencies and Related Changes

- `add-host-ssh-port` — needed to register a host reached through a management
  tunnel. Independent code; either order.
- `add-buyer-vm-connectivity-terms` — plans to populate this same field from
  negotiated terms rather than storefront configuration. It is in design phase
  and not yet planned. This change should land first: it is cheaper to settle
  the field's contents once and then decide who supplies them than to negotiate
  a shape containing a dashboard credential that no longer exists.
- Paired infrastructure work — the relay itself, its port windows, its token,
  and the host management tunnel are declared in the operations repository. The
  windows this change reads from configuration are that repository's to choose.

## Impact

- A relay with no dashboard, no DNS name, and no certificate becomes usable,
  which is the deployment shape the operations repository has already built.
- Buyers holding live SSH sessions stop losing them when an unrelated VM is
  provisioned on the same host.
- A host can reach a management relay and a buyer relay independently, so the
  two need not be the same server.
- The relay token stops having a published default value.
- Two silent failure modes — a VM with no route reported as success, and a
  discarded relay token — become loud.

## Permanent documentation impact

- [x] Existing subsystem specification: `openspec/specs/physical-provisioning/spec.md` — `connectivity` field shape, relay token handling, allocation ownership
- [x] Existing subsystem specification: `openspec/specs/vm-storefront-fulfillment/spec.md` — storefront-configured connectivity source
- [x] Existing capability architecture: `openspec/specs/physical-provisioning/architecture.md` — why relay coordination is host-local rather than relay-side
- [ ] `docs/development/ARCHITECTURE.md` — no repository-wide shape change anticipated
- [ ] `docs/development/ROADMAP.md` — no roadmap goal currently covers reaching hosts without an inbound route; whether one is warranted is a closeout decision, not an omission

### Knowledge to promote

- A relay's management surface is not a coordination interface; port allocation
  and proxy verification are host-local → `openspec/specs/physical-provisioning/architecture.md`
- Buyer VM access is port-based, and vhost subdomain routing cannot serve SSH →
  `openspec/specs/physical-provisioning/architecture.md`
- The relay token is never held by a buyer-controlled machine, which is why the
  tunnel client runs on the host rather than in the VM →
  `openspec/specs/physical-provisioning/architecture.md`
- The `connectivity` field's resolved shape and its forwarding contract →
  `openspec/specs/physical-provisioning/spec.md`
- The provisioning service allocates VM relay ports and owns their reclamation;
  the playbook applies what it is given →
  `openspec/specs/physical-provisioning/spec.md`
