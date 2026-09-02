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
- **Scope the lease to the relay, not the host.** A `tcp` proxy's `remotePort`
  binds a listening socket on the relay, so hosts sharing a relay share one port
  namespace. The lease is unique on relay and port; the host is an attribute.
  Releases attach to every terminal outcome rather than to teardown alone, with
  a reconciliation sweep bounding whatever path is missed.
- **Replace the dashboard online-check with `frpc`'s admin API, bound to
  `127.0.0.1`.** The same interface supplies `reload`, which applies a proxy
  diff and leaves unchanged proxies untouched, so adding a VM stops restarting
  the client.
- **Split the host's relay clients in two.** This repository's role owns the
  VM-facing client (`/etc/frp/frpc-vms.toml`, `frpc-vms.service`); the host's
  own management tunnel is written when the host is prepared, outside this
  repository, and is never touched by a VM operation. Two
  files, two units, no shared write target — which also removes the hazard that
  re-running host setup re-templates one file and erases live VM proxies.
- **Make a relay a first-class resource.** A relay row holds the rendezvous
  address, port, allocation window, and token; pools reference it. Each fact is
  stated once, so two pools sharing a relay cannot allocate from one listening
  namespace under disagreeing windows, and rotating a token is one write rather
  than one per pool.
- **Remove relay configuration from the `connectivity` field entirely.** Remove
  `frp_server_addr`, `frp_domain`, and `frp_dashboard_password` and add nothing
  in their place. Which relay a host dials is a durable fact about the fleet,
  not a property of the request being served, and the buyer-facing address is
  returned in the fulfillment result rather than supplied with it.
- **Store the relay token encrypted, rooted in the secrets profile.** The token
  is Fernet-encrypted in the relay row using the same profile key that already
  protects host SSH key material, so the database holds no usable credential.
  Reads split in two: the reader without secrets carries the unqualified name
  and serves the pool endpoints, the export document, and reconciliation, while
  an explicit execution reader serves fulfillment. A write that omits the token
  preserves the stored one.
- **Give relays their own controller.** Create, list, detail, update, token
  rotation, enable, and disable, against a running service. A relay is
  infrastructure an operator repoints and rotates, so requiring a redeployment
  for each change is the inflexibility that motivated moving the credential out
  of the deployment's profile in the first place.
- **Reconcile a definition document when it changes, not when a pod starts.**
  The service currently re-applies its pool definition document at every
  startup, on the stated grounds that import is idempotent. It is idempotent
  with respect to the document, not the database, so re-running it reverts
  whatever else changed the database — silently, on eviction, drain, and crash
  recovery. The service now records a digest of each document it has imported
  and reconciles only when the document differs. Authoritative import is
  unchanged and remains what an explicit import request performs.
- **Establish relays from a mounted definition document.** A deployment reaches
  a working relay by applying the chart alone, with no operator API call and no
  credential passing through a workstation. The document carries no credential;
  an entry names which profile key holds its token, read once when the relay is
  created and never re-read, so a rotation through the controller survives a
  later reconciliation.
- **Remove the fallback literal from the client template** so a missing token
  fails initialization instead of configuring a value published in a tracked
  file.
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

- `physical-provisioning`: relays become an administered resource with their own
  endpoints; the fulfillment request's `connectivity` field sheds its relay keys;
  the service allocates and reclaims VM relay ports; and provider configuration
  gains a credential that read paths must not return.
- `resource-pool-management`: provider configuration reads split into a
  redacted default and a named execution read, and full replacement stops
  applying to fields a read never returned.
- `vm-storefront-fulfillment`: the storefront's provisioning settings keys are
  removed with the field.

## Non-Goals

- Do not make connectivity terms buyer-specified or negotiated. That is
  `add-buyer-vm-connectivity-terms`, which extends the negotiation envelope.
  This change alters what the field contains, not who supplies it; the two
  interact and are sequenced in Dependencies below.
- Do not write, own, or configure the host's management tunnel. It is
  established when the host is prepared, outside this repository. This change
  only stops the VM path from writing the file that tunnel lives in.
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
`frp_domain`, and `frp_dashboard_password` are removed. A deployment carrying
them must be reconfigured. Nothing replaces them in storefront settings: the
relay endpoint becomes deployment configuration in the definition document, and
the token becomes durable state in the database, because a credential has no
business in a storefront's configuration.

**Host state.** None to migrate. The dev cluster has never run a live-fire
provisioning test and is deployed in mock mode, so no host has been initialized
against the relay and none carries accumulated VM proxy stanzas in a single
`/etc/frp/frpc.toml`.

**Schema.** One migration carries the relay table, the port lease table, and the
host connection port. It has not been applied in any environment, so it is a
single operator step against an unmigrated database rather than a sequence.

**Delivery.** The token seed is one more key in the `provisioning-secrets`
dynaconf profile — already rendered, already projected, already mounted — so it
needs no new secret shell, no new volume, and no new mount. The relay definition
document is an ordinary mounted configuration file carrying no credential, so it
needs a ConfigMap and a mount but no Secret. That mount is the one delivery-side
addition, and it is a values and template change rather than a new mechanism.

`pool_definitions_path` is deliberately left unwired. It exists in the service
and is connected to nothing, so no deployment reconciles pools today. The
digest gate makes wiring it safe, but doing so would newly subject every
deployment's pools to declarative reconciliation — a change to what a deployment
means rather than a bug fix. Worth doing, deliberately, in its own change.

**Bootstrap.** A deployment reaches a working relay-backed pool by applying the
chart alone. No operator API call is required to establish the first relay, and
no credential passes through an operator's workstation to get there. Adding a
relay after deployment is an API operation and needs no redeploy.

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
- The relay itself, its port windows, its token, and the host management
  tunnel are deployment concerns outside this repository. The windows this
  change reads from configuration are chosen there, not here.

## Impact

- A relay with no dashboard, no DNS name, and no certificate becomes usable,
  which is the deployment shape a relay is free to take.
- Buyers holding live SSH sessions stop losing them when an unrelated VM is
  provisioned on the same host.
- A host can reach a management relay and a buyer relay independently, so the
  two need not be the same server.
- A relay can be added, repointed, rotated, or disabled against a running
  service, so neither adding a rendezvous nor changing one requires a
  deployment, and neither is undone by a pod restart.
- The relay token stops having a published default value, and stops being
  recoverable from the database alone.
- Two silent failure modes — a VM with no route reported as success, and a
  discarded relay token — become loud.

## Permanent documentation impact

- [x] Existing subsystem specification: `openspec/specs/physical-provisioning/spec.md` — relay resource and its lifecycle, token confidentiality on read paths, `connectivity` field shape, allocation ownership
- [x] Existing subsystem specification: `openspec/specs/vm-storefront-fulfillment/spec.md` — removal of storefront-configured connectivity keys
- [x] Existing capability architecture: `openspec/specs/physical-provisioning/architecture.md` — why relay coordination is host-local rather than relay-side, and why a relay is a resource rather than pool configuration
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — the definition documents' paths and contents, and that reconciliation follows a change to a document rather than a restart
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
- A relay is a resource, not pool configuration, because its window and token
  are shared by every pool that points at it →
  `openspec/specs/physical-provisioning/architecture.md`
- The `connectivity` field's resolved shape and its forwarding contract →
  `openspec/specs/physical-provisioning/spec.md`
- The provisioning service allocates VM relay ports and owns their reclamation;
  the playbook applies what it is given →
  `openspec/specs/physical-provisioning/spec.md`
- Relay tokens are encrypted at rest under the profile key and are never
  returned by a configuration read path →
  `openspec/specs/physical-provisioning/spec.md`
- Import authority is scoped to submitting a document; a process restart is not
  a submission →
  `openspec/specs/resource-pool-management/spec.md`
- Why import authority exists at all, and why omitted entries are disabled
  rather than erased →
  `openspec/specs/resource-pool-management/spec.md`
- Reconciliation follows a change to a document rather than a restart →
  `docs/development/DEPLOYMENT_AND_CONFIG.md`
- Relays are administered through their own controller, including rotation,
  without redeployment →
  `openspec/specs/physical-provisioning/spec.md`
