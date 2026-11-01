# Design: Prove relay provisioning, and sell bare metal over a relay

## Context

Designed against `dev` at `16d585d9d`, and reconciled with `frp-grant-admission`'s
settled design (its `design.md`, decisions D1–D15 and its notes for this change), which
owns the grant specification this change's signer conforms to. Where this document
names that change's decisions it says so (its D2, its D3a, and so on).

The relay path `relay-vm-access-without-a-dashboard` built has never run on real
hardware, and that change cannot close until its reload gate (its section 6) and its
live checks (its section 8) are run. No end-to-end lane runs a relay-backed pool. The
real-provisioning lane `prove-real-vm-provisioning` built proves direct access only:
its target (version 1) names one KVM host and admits only `access.mode: direct`, and
its listing takes the host's whole capacity, so it cannot hold two guests at once.

What the code shows, where the proposal's first account of it was wrong:

1. **The relay tables are the VM domain's.** `Relay`, `RelayPortLease`, and
   `AnsiblePoolConfig` (which holds a pool's `relay_id`) live in
   `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/db.py`, with the
   allocator, relay administration, the definitions importer, the rebinding
   refusals, execution-time token resolution, the reconciliation worker, and the
   release effect beside them. The bare-metal provider's pool configuration accepts
   no field (`BareMetalPoolConfigHandler`).
2. **Bare metal can already be reached through a relay, but only by a fixed route.**
   A host's connection carries a buyer-facing route, `public_host` and
   `public_port`, each falling back to the connection's own, and a bare-metal grant
   delivers that route (`grant_evidence` in `bare_metal_provisioning_adapter/codec.py`).
   A bare-metal host reached through its management tunnel and stating no buyer
   route is therefore delivered to its buyer at the management tunnel's endpoint.
   What is missing is a port leased per grant and removed at reclaim.
3. **This repository holds no bare-metal host preparation.**
   `domains/bare_metal/provisioning/iac/` holds only `playbooks/node-access.yaml`
   and the `bare-metal-access` role. VM's buyer-facing client is installed by
   `roles/vm-setup/tasks/frp-client.yml`; a proxy is added in `vm-create.yml` and
   removed by `remove_guest_proxy` in `roles/vm-management/files/guest_teardown.sh`.
4. **A relay port is released with its reservation's capacity**, by the release
   effect `release_reservation_ports`, registered through the family's
   `ReleaseEffects` seam; a failed create keeps its port. It is not released on a
   fulfillment's terminal transition.
5. **Version 1 of the target already reaches a host through a tunnel**: it carries
   `ssh_host` and `ssh_port`. It lacks several hosts, a domain per host, a relay
   reference, and a buyer route other than a required `public_host`.
6. **The relay's `allowPorts` is not the application's window.** frps enforces its
   own `allowPorts`, which spans management and VM windows; the application's
   window (`vm_port_range_*`) is not relay-enforced. "A proxy outside the window is
   refused", as the relay change's 8.2 states it, conflates the two.
7. **The buyer-facing client's admin API is unauthenticated on loopback**
   (`frpc-vms.toml.j2`, port 7400), and frp v0.61.1's client admin API serves
   `GET /api/config` (the configuration, token included, unredacted), `PUT
   /api/config`, `/api/reload`, and `/api/stop`. The client runs as root. Any
   account on the host other than root can therefore read the relay token, and can
   rewrite the configuration and reload it to add any proxy, including frp's
   `static_file` and `unix_domain_socket` client plugins: local root. A
   bare-metal tenant is such an account; the tenant account the
   `bare-metal-access` role creates has no sudo.
8. **A second guest comes only from a second deal.** The operator's VM-create path
   (`vm_operations_service`) allocates no relay port.
9. **`e2e_bare_metal_deal` is a different scenario**: a `market bare-metal buy`
   purchase settled through Arkhai payments against supply registered beforehand,
   with an operator-pinned `known_hosts` and a role-scoped key; it registers
   nothing and runs no shared compute stage.
10. **The two real lanes run against two provisioning services.** A provisioning
    service trusts one storefront, and the umbrella refuses a release running both
    compute storefronts on one provisioning service, so the VM lane runs against
    release 1 and the bare-metal lane against release 2, each with its own relay
    rows, leases, and keys.
11. **No reclaim policy ends the tenant's activity.** `remove_lease_key` removes the
    key; `lock_user` locks the password and sets `nologin`; `delete_user` runs
    `user: state=absent remove=yes` with `failed_when: false`, so `userdel`
    refusing an account with running processes is swallowed and the reclaim
    reports success. None ends processes, sessions, lingering, or cron or `at`
    jobs.
12. **frp is installed unpinned and only when absent.** `frp-setup` pins frps 0.54.0
    and `vm-setup` frpc 0.61.1; both download without verifying the archive, and both
    install only when a binary is absent (`when: not frps_binary.stat.exists`, `when:
    not frpc_binary.stat.exists`), so a changed version never replaces an installed
    binary, and a host whose management client already placed `/usr/local/bin/frpc`
    downloads nothing for the buyer client and runs whatever binary is there. A
    checksum on a download alone would not close either gap.
13. **`frp-setup` publishes its secrets.** It prints the relay token and the dashboard
    password, writes both to a credentials file on the controller and returns them
    through `set_stats`, and installs nginx and certbot for the dashboard, a fixed ufw
    window of 7002–8000, and fail2ban, then reboots the relay.
14. **The plugin's settled design fixes what D16–D20 first left open.** A grant's
    `typ` is `frp-grant+jwt`, and `JWT` or none is refused (its D2); a key's id is its
    RFC 7638 thumbprint, which the plugin derives itself, so any other `kid` is
    unknown (its D3a); the configuration is TOML, keys grouped under issuers with one
    audience and one range each (its D3, D13); a signer serializes header and claims
    as RFC 8785 JSON and reproduces the vector's tokens byte for byte (its D7); expiry
    and issue time are checked on the relay's clock with no leeway (its D12); and the
    plugin ships as a wheel runnable under systemd and as an image, neither published
    until it moves to its own repository (its D11).

## Goals and non-goals

Goals: bare metal sold over a relay with a port leased per grant; relay admission
that admits a proxy only for a port its provisioning service granted; the
real-provisioning target's version 2; real VM and bare-metal lanes over a relay;
and the live evidence `relay-vm-access-without-a-dashboard` waits on.

Non-goals are in `proposal.md`.

## Decisions

### D1. Bare metal gets per-lease relay access in this change

A bare-metal pool may reference a relay, as a VM pool does. A grant on a
relay-backed pool leases a port from the relay's window, adds one buyer proxy from
the host's `127.0.0.1:22` to that port, and delivers
`ssh -p <port> <tenant>@<relay address>`. A reclaim removes the proxy and releases
the port.

Why: the relay design names a GPU pool and a bare-metal pool sharing one
rendezvous as the ordinary case, and only an application-accounted port can share
a relay with VM leases without colliding; a leased port also closes at reclaim,
which a fixed route does not. Selling bare metal over a relay rests on that relay
enforcing admission, which is the operator's installation, proven by the runbook's
admission check before its pools serve buyers (D19).

Rejected:

- *A fixed route only* (an operator-prepared static proxy, registered as the host's
  `public_host`/`public_port`): no adapter code, but the port is not leased, so a
  later widening of the relay's window collides asynchronously, and the drain rule
  does not cover bare-metal buyers. Remains how a tunnel-reached bare-metal host in
  a pool with no relay is sold (D15b).
- *Splitting bare-metal relay access into its own change*: proposed during design
  and declined by the owner. Bare metal cannot be sold over a relay without
  admission (D14), and there is little value in adding either without the other.

### D2. The relay machinery is the compute family's

**(a) Placement.** The `Relay` and `RelayPortLease` models, the allocator, the
release effect, reconciliation, relay administration, the definitions importer,
the rebinding refusals, and execution-time token resolution move from the VM
adapter into the base family kit as `compute_provisioning.relays`. The relay wire
models and route contracts move to `compute_provisioning_contracts`, the client
methods to `compute_provisioning_client`, and the framework-free route service to
the family kit; the provisioning service binds the routes. The service registers
the release effect, the reconciliation worker, and the definitions document once
for every domain. Each domain keeps only its share: what its playbook does with a
proxy, how its codec reads the relay endpoint into delivery evidence, and its
plan's call to allocate. Table names, route paths, operation names, and the
definitions document are unchanged; `vm_provisioning_operator` loses its relay
methods.

Why: sibling domains never import each other, and the family-kit placement tests
pass: a relay is a rendezvous a family host dials, and a third domain could lease
ports through it by contributing a codec. The family kit already owns tables,
workers, and the release-effect seam. Not an optional distribution: it carries no
heavy dependency and is not Ansible.

Rejected: a copy in bare metal (two allocators over one port namespace); a
repository-wide kit (a relay is family knowledge).

**(b) The pool's relay reference.** One family table, `pool_relays(pool_id →
resource_pools, relay_id → relays)`, holds every pool's reference. Both providers
accept `provider_config.relay_id` on the wire and read and write it through one
family function, which runs the rebinding check. One migration creates
`pool_relays`, copies any reference from `ansible_pool_configs.relay_id`, and drops
that column. It departs from the additive-by-default schema rule, and the upgrade is
fail-forward (28 F4): an older provisioner maps the column on every VM pool read and
cannot read the table once it is dropped, so rolling back past the migration means
restoring a database backup taken before the upgrade, or rolling forward. The
deployment guide records it beside the `hosts.gpu_count` drop, with the same
pre-upgrade backup. No rollout runs two provisioner versions over one database (the
chart's `strategy: Recreate` over one ReadWriteOnce volume), and no relay-backed
pool exists in any deployment, so there is nothing for expand/contract to protect.

Why: which relay a pool's hosts dial is a fact about where they are, not provider
configuration; one table answers "which relay does this pool use" and "which pools
use this relay" in one query, and keeps the rebinding rule in one place.

Rejected: a side table per provider (one concept in several tables, a lookup
contributed per provider, rules depending on each handler); a field on the pool
itself (`kit/resource-pools` has empty scope and cannot know relays);
expand/contract (nothing to preserve).

### D3. Buyer-facing tunnel tasks are shared family roles

A family IaC project, `provisioning/compute/iac/ansible/roles/`, holds:

- `relay-client`, installing the buyer-facing client, renamed `frpc-buyers`
  (`/etc/frp/frpc-buyers.toml`, unit `frpc-buyers`);
- `relay-proxy`, whose *add* checks the client's baseline against the resolved
  relay, adds a marked proxy block (name, local address and port, remote port,
  grant), reloads, and waits for the proxy to run, and whose *remove* deletes the
  block and reloads (`remove_guest_proxy` moves here);
- `relay-server`, replacing VM's `frp-setup`, preparing a relay on a VPS: frps under
  systemd, and the admission plugin as a plain program (D23);
- `frp-binary`, holding the one frp pin and its verified install, which `relay-client`
  and `relay-server` include (D22).

VM's `vm-setup`, create, and teardown tasks call them; `bare-metal-access` calls
`relay-proxy` on grant and reclaim; a new bare-metal host-preparation playbook under
`domains/bare_metal/provisioning/iac/ansible/playbooks/host-kit/` applies
`relay-client`. The service image copies the family tree, and the IaC tests move
with the tasks.

Playbooks and roles name the family roles bare (`relay-proxy`), found through
Ansible's role search path (28 F5): the service image copies the family tree beside
the domain trees and sets `ANSIBLE_ROLES_PATH` to its roles, as it sets the
collections path; each domain's own `ansible.cfg` adds the family tree's
repository-relative path to its `roles_path` for manual runs (VM's gains the entry;
bare metal gains an `ansible.cfg`). The shared service `ansible.cfg` stays free of
any domain's paths. Both domains' playbooks pass `ansible-playbook --syntax-check`
under their own configuration and under the image's environment. Rejected: an Ansible
collection (a namespace, metadata, and an install step for three roles in one
repository); relative paths into the family tree (they resolve in the repository or
in the image, not both).

Every task that renders, writes, sends, or reads the grant, the relay token, or the
client's admin password sets `no_log` (28 F3), and the relay family supplies one set
of those variables' names that every codec whose jobs carry them includes in its
secret fields, so the executor's redaction covers them in VM and bare-metal jobs
alike. Bare metal's codec, which names no secret field today, gains them because its
grant and reclaim jobs now carry the token and the grant.

`relay-server` discloses no secret either (correction 13): the relay token is a required
input with no default, as `relay-client` asserts its own, and is never generated and
printed; the debug output of credentials, the credentials file on the controller, the
`set_stats` return, the dashboard with its nginx and certbot, and the reboot are not
carried over; every task rendering `frps.toml` or the plugin's configuration sets
`no_log`. frps's `allowPorts`, its ufw rule, and fail2ban's ports come from one variable,
which must cover every issuer's range (D20). A change to the plugin's configuration
reloads the plugin; a change to `frps.toml` or to frps's version restarts frps, which
drops every session on the relay, so the runbook makes either change drained.

Why: a domain's tooling never depends on a sibling's, and one behaviour is chosen
for both domains where nothing requires a difference. The live run then proves
the tasks both domains ship. The client configuration belongs to the host, not a
domain: a host belongs to at most one pool, whose offering mode is VM or bare
metal, so a machine is sold as VM slices or a whole host, never both at once. No
host carries a relay client yet, so the rename is free.

Rejected: a bare-metal copy of the tasks (two implementations of behaviour every
buyer's session depends on); bare metal calling VM's role (cross-domain tooling);
the service rendering the proxy (proxy edits are host-local; the service allocates
and the playbook applies); moving `frp-setup` with only its dashboard and subdomain
settings removed (a relay token in plaintext output and on the operator's disk,
against this decision's own `no_log` rule).

### D4. The buyer-facing client's admin API is locked down on every host

`relay-client` generates a per-host admin password at preparation and writes it
into the root-only configuration, and binds the admin API to a loopback port below
1024 (a template variable, defaulting to a privileged port). `relay-proxy` reads
the password with `become` for its reload and status calls.

Why (correction 7): an unauthenticated admin API gives any account other than root
the relay token and local root. A port below 1024 closes the remaining gap: on an
unprivileged port, an account other than root can bind the port while frpc is
down and capture the password from the next reload, or fake a proxy's status. Only
root can bind below 1024, and frpc runs as root.

Recorded with it:

- The seller documentation makes a separate buyer-only relay the default:
  management ports belong on a relay buyers' tokens cannot reach, and the
  operator's management client runs with its admin API off or authenticated.
- `physical-provisioning`'s architecture records the boundary: on a host, the relay
  token is protected only by the account being other than root — a root-only
  configuration and an authenticated admin API on a privileged port.
- `ROADMAP.md` gains an unowned gap: the provisioning service's Ansible
  configuration sets `host_key_checking = False`, which makes any relay compromise
  worse.

Rejected: turning off the admin API on bare-metal hosts only (leaves the root
escalation on VM hosts, and splits one host-level configuration by domain);
accepting and documenting it.

### D14. A relay admits a proxy only for a port its provisioning service granted

The provisioning service signs a grant per lease; the proxy carries it; a plugin on
the relay admits the proxy only when the grant's signature holds and its port is
the one requested. Nothing on the relay calls an SCM service.

Why: whoever holds a relay's token can otherwise register any free port its
`allowPorts` covers — claiming ports the allocator has not handed out (so the next
lease's proxy fails and its buyer reaches the claimant), taking a dropped host's
management port, or exhausting every port. Bare metal cannot be sold over a relay
until this holds.

Rejected:

- *A per-host account and fixed port range* enforced by an existing plugin
  (`frps-panel`, or `fp-multiuser` with `frp_plugin_allowed_ports`): existing
  software and per-host credentials, but a partitioning policy with a fixed cap per
  host, an operator edit on the relay for every host, and drift between SCM's ranges
  and the relay's file. Signed grants are the better design: admission is exactly
  the leased ports, the allocator stays the only authority, and the relay holds no
  per-host state.
- *Only frp's built-in settings* (`maxPortsPerClient`, a buyer-only relay): neither
  stops port claiming nor one token opening many clients.
- *The relay calling the provisioning service* for each registration: relay
  infrastructure never calls an SCM service.
- *Building admission in a later change*: declined; see D1.

### D16. The grant

A grant is a grant of `frp-grant-admission`'s specification, version 1: a JWT of type
`frp-grant+jwt`, signed with EdDSA (Ed25519), one per lease, carried in that proxy's
own `metadatas.grant`. Serialized as the specification requires (RFC 8785 JSON, keys
sorted, then unpadded base64url); the key id shown is RFC 8037's published thumbprint
of RFC 8032's test key, an example only:

```text
header  {"alg":"EdDSA","kid":"kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k","typ":"frp-grant+jwt"}
claims  {"aud":"relay-bm","exp":1798765200,"jti":"lease-7f3a","port":6203,"sub":"example-bm-1"}
```

`aud` is the relay's id, `port` the leased port, `exp` the lease end plus a grace,
`sub` the host, `jti` the lease, and `kid` the signing key's thumbprint (D17). The type
is a constant naming the specification's version 1; an incompatible version would take
the specification's next type.

The grant carries no `iat`. The plugin refuses an `iat` later than the relay's clock,
with no leeway (its D12), so a service clock even seconds ahead of the relay's would
refuse a freshly signed grant until frpc's own retry, failing a create whose status
wait is shorter; and no reader uses the claim — the plugin logs `kid`, `sub`, `jti`,
and `exp`, and `jti` already names the grant. No `nbf` is set either.

The plugin admits a proxy only when its type is `tcp`, the signature is valid under
a configured key matching `kid`, `aud` is the key's issuer's audience, `port` equals
the requested `remote_port` and lies in the issuer's range (D20), and `exp` has not
been reached on the relay's clock. `sub` and `jti` serve the plugin's log line only:
anyone holding the token can set the client's `user`, so the grant alone authorizes
the port.

**Signing.** The family kit signs a header and claims into a compact token — RFC 8785
JSON of each, unpadded base64url, joined, signed with an Ed25519 private key — through
`cryptography` and `rfc8785` (the JCS library `kit/identity` uses), with no JWT
library: the specification requires a signer to reproduce its vector's tokens byte for
byte (its D7), and PyJWT's encoder does not sort claims. The grant signer builds the
header and claims from a lease and calls it. `compute_provisioning` declares both at
runtime. Conformance is the vector check (D18).

Lifecycle:

1. Allocation records `grant_expires_at` on the lease: the reservation's lease end
   plus a configured grace covering teardown.
2. Execution signs the grant from the lease, immediately before the job's variables
   are written, as the relay token is resolved, on every attempt of the job; it never
   enters job parameters, and never a job's logs, error, or result (D3's `no_log` and
   redaction, 28 F3).
3. A released port is not reissued until its `grant_expires_at` plus a reuse margin
   has passed, so a copied grant cannot claim a port another host now holds. The
   margin is a service setting, `relay_port_reuse_margin_seconds`, defaulting to 300,
   which the allocator reads when it selects a port, so raising it covers leases
   already released. The plugin checks `exp` on the relay's clock with no leeway, and
   its design leaves the skew to the issuer's reuse rule (its note 8): without a
   margin, a relay clock δ behind the service's admits a copied grant for δ after the
   port is reissued. The relay's and the service's clocks are kept synchronised, with
   skew well under the margin.
4. Teardown is the revocation: it removes the proxy and the access (the guest, or
   the key and the tenant's activity, D15). The grant's remaining life matters only
   to root on that host, and only for its own former port. A host teardown cannot
   reach keeps its live registration until an operator acts on the relay or the
   host; frp checks admission only at registration, so no grant scheme removes
   that, and the runbook gains a relay step for it.

Extending a lease would mean re-signing and rewriting the stanza, which drops that
buyer's session; it is a recorded limit, and no fulfillment path extends a lease
today. `relay_port_leases` gains `grant_expires_at` (additive).

Why: frp checks admission at every registration — at create and after every client
reconnect — so the grant must live as long as the lease; client-wide metadata is
sent only at login, so changing it restarts the client and ends every session.

The copied grant the margin guards against is narrow: it exists only in the former
host's root-only client configuration (a tenant is not root, and the admin API is
authenticated, D4); a reissued port goes to another host of the same provisioning
service, since each issuer's range is its own (D20); and frps admits one proxy per port,
so the copy lands only while the new holder's proxy is unregistered. The margin is
cheap beside it: a released port held five minutes longer. It does not apply to D17's
retirement bound, since by `exp` the lease the grant served has ended.

Rejected: short-lived grants renewed (renewal drops the session, and an expiry
mid-lease stops the proxy returning after a reconnect); `iat` backdated by a margin (a
deliberately wrong timestamp, and a skew constant in the signer); `iat` kept with a
status wait sized to frpc's retry (slow creates on a skewed clock, and every real
failure reported later); a reuse time stored per lease (another column, and a raised
margin would reach only new leases); clocks synchronised with no margin (a residual
window of whatever the skew is, which nothing measures); folding the margin into `exp`
(the skew window follows whatever `exp` is); a grant per host listing its
ports in client-wide metadata (every lease restarts the client); a home-made
envelope instead of a JWT (no gain, and every plugin library reads JWTs); signing with
PyJWT (its claims are not serialized canonically, so it cannot reproduce the vector);
`json.dumps` with sorted keys standing in for RFC 8785 (equal only for the values sent
today); importing `kit/identity`'s canonical JSON (an edge to the identity kit for one
call); grants
without expiry revoked at the relay (revocation needs state on the relay or a call
into SCM); signed revocations pushed by the service to the plugin (an outbound path
and plugin state for a risk that reaches only root on the same host).

### D17. Each relay holds its own grant-signing key

Each relay row holds its Ed25519 grant-signing private key, encrypted under
`ssh_decryption_key`, and its key id. A definitions-document entry names the profile
key holding it (`grant_key_secret_key`), read once at creation, as
`token_secret_key` is. Reads return the public half, the active key id, any staged
key, and each retired key with the time its grants stay valid until — never a
private key. Rotation is two controller operations: *stage* generates a key pair in
the service and returns its public half, the operator adds it to the plugin under the
relay's issuer, and *activate* starts signing with it.

A key's id is its RFC 7638 JWK thumbprint — the base64url SHA-256 of
`{"crv":"Ed25519","kty":"OKP","x":"<raw public key, base64url>"}` — computed when the
service generates the key and stored for active, staged, and retired keys alike. The
plugin derives the same id from each public key it is configured with and knows no
other (its D3a), so the id carries no prefix and no counter. A public half is read as
the single-line standard base64 of its DER SubjectPublicKeyInfo, the form the plugin's
configuration takes, so it is pasted unchanged; field names are the contracts'
(the key is RFC 8032's test key, an example only):

```json
"grant_keys": {
  "active":  {"kid": "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k",
              "public_key": "MCowBQYDK2VwAyEA11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=",
              "activated_at": "2026-11-01T12:00:00Z"},
  "staged":  null,
  "retired": [{"kid": "…", "retired_at": "…", "grants_valid_until": "…"}]
}
```

Staging answers with the same `kid` and `public_key`. A retired key is reported by id
and validity only: the operator removing it from the plugin matches it by the
thumbprint the plugin's `check` prints.

A retired key's grants stay valid until the latest `grant_expires_at` among the
unreleased leases allocated before it was retired (28 F2). A grant is signed on
every attempt of a job, so one lease may have grants from more than one key on its
host — an attempt that installed a grant signed by key A, failed, and was retried
after key B was activated — and a record of one key per lease could report A
removable while a host still holds its grant. The bound is never short: every grant
a key signed was signed before its retirement, for a lease allocated before it, and
a lease's grant expiry is fixed at allocation. Released leases are left out, since
teardown is the revocation (D16), and refusing a reconnect from a host teardown
could not reach is wanted. Each lease still records the key id that signed its
latest grant, as a diagnostic the holdings read reports. The bound can keep a key in
the plugin longer than strictly needed; an emergency rotation removes the old key at
once and accepts that sessions on it fail at their next reconnect, as the runbook
says.

Rejected: recording every key that signed a lease's grants (exact, but state every
signing writes, for a bound time gives free); keeping a lease's key stable across
retries (retired private keys kept for signing); key ids prefixed with the relay id, or
counted or random (the plugin refuses any `kid` but the thumbprint); PEM (multi-line in
the plugin's key list); the bare JWK `x` (not self-describing, and not the plugin's
format).

Why: it treats the key exactly as the relay token is treated — a relay is
establishable by applying the chart alone, and no private key passes through a
workstation — and bounds a leaked key to one relay.

Rejected: one key for the whole service in the secrets profile (every relay exposed
by one leak, rotation by redeployment); reusing the service's marketplace identity
key (one key signing two protocols, and every identity rotation forcing a plugin
change).

### D18. The relay plugin is our own, standalone, SCM-agnostic tool

The plugin is written in Python as a standalone tool, `tools/frp-grant-admission/`,
with no internal dependency. It owns the grant specification, its configuration
format, a published test vector, and its frp pins file; SCM's signer conforms to that
specification, and SCM's tests check its own copies against the tool's files. It ships
as a wheel runnable as a plain program under systemd and as an image, neither
published; a VPS relay runs the plain program, installed by `relay-server` (D23), and
a containerised relay runs the image as a sidecar (D23). It is built by the
prerequisite change `frp-grant-admission`, and a later change moves it to its own
open-source repository, where publishing its wheel and a public image belong.

**Conformance.** A family test reads the tool's published vector (its
`vector/frp-grant-1.json`) in place: for every signing case,
the family's header-and-claims signer (D16) given the case's key, header, and claims
produces exactly the case's token, and the thumbprint case equals the family's key-id
derivation (D17). It runs no verification case, since SCM verifies no grant. A second
test requires `frp-binary`'s pin to equal the tool's `frp-pins.toml` (D22). Both read
the producer from the consumer, the direction the tool's design permits; once the tool
moves out they read a copy vendored by content hash, as
`kit/arkhai-payments/schema/SOURCE.md` vendors its schema. Both need the tool on this
branch, so they land once `frp-grant-admission` is archived (D13).

Why: no existing plugin fits. `frp_jwt_allowed_ports`, the nearest, documents
claims `sub` and `ports` and appears to read client-wide metadata, which D16
rejects, and its maintenance and licence are unverified. Generic infrastructure that
is not specific to SCM does not belong in SCM, so the plugin names no SCM concept
and can be lifted out as it stands; having to build it is a warning sign, weighed
and overridden here because the design is better.

Rejected: adopting `frp_jwt_allowed_ports` (very probably incompatible with
per-proxy grants, unverified, and Go); forking it (a Go toolchain the repository
does not have, for code largely rewritten); our own plugin in Go (a second
implementation of the grant format); placing it in `domains/compute/` with the
grant format as an SCM contract (backwards: the plugin owns its specification).

### D19. Every relay is configured for admission, and management ports use another relay

Every relay holds an active grant key and every proxy carries a grant: fulfillment
preparation refuses a pool whose relay has no active key, naming the relay and what
is missing, as it refuses one with no token. A definitions-document entry must name
`grant_key_secret_key`; a relay created through the API with no key gets one
generated by the service, and is not usable until the operator has configured the
plugin with its public half. Management ports must be on a different relay: a host
placed in a relay-backed pool is refused when its connection address is that relay's
address, and so is the reverse. The check compares normalized addresses and catches
the obvious case only, which is how it is documented.

What the service guarantees is that every proxy it configures carries a grant and
that it refuses a relay with no active key. That a relay enforces admission is the
operator's installation (28 F1): `physical-provisioning`'s specification and the
operator documentation state what a relay must run — frps with the admission plugin
configured with an issuer for the relay: its audience, its range, and the relay's
public keys — and the runbook's admission check proves it
on the deployed relay, an ungranted proxy refused with the plugin's refusal in its
log, before a relay-backed pool first serves buyers and after any change to the
relay's plugin configuration. A relay deployed without it accepts any port; that is
the operator's fault, and the service does not verify it.

Why: the service cannot verify a relay runs the plugin — nothing on the relay calls
SCM, and nothing in this design calls the relay — so one mode for every relay leaves
no domain with admission accidentally off. A readiness probe from the service
(registering an ungranted proxy with the relay token and expecting refusal) was
declined (28 F1): it needs an frp client in the service image and a path from the
service to every relay, and proves admission only at the moment of the probe, which
the runbook check already does. Management proxies carry no grant, and a
static allow-list for them would bring back the attack on a dropped host's
management port. No relay is live, so nothing migrates.

Rejected: a per-relay declared admission mode (two modes, and a declaration nobody
can verify); requiring admission for bare metal only (a key standing in for an
unverifiable claim).

### D20. A relay may be shared, with each signing key bound to its own port range

The plugin's configuration names issuers, each with the audience it signs as (the
relay's id in that issuer's provisioning service), one port range, and its public
keys; a grant outside its issuer's range is refused, and overlapping ranges refuse
to load (its D3, D13). Each provisioning service's relay row keeps its own window,
which lies within its issuer's range: the service does not know the range, and the
plugin refuses ports outside it, so a wider window shows as a refused registration
that fails its create.

```toml
listen = "127.0.0.1:7300"

[[issuers]]
name = "vm-site"
audience = "relay-vm"
ports = { start = 6100, end = 6199 }
keys = [ { public_key = "MCowBQYDK2VwAyEA11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=" } ]  # RFC 8032 test key, example only

[[issuers]]
name = "bm-site"
audience = "relay-bm"
ports = { start = 6200, end = 6249 }
keys = [ { public_key = "MCowBQYDK2VwAyEA…" } ]
```

The plugin's own file is the only representation: `relay-server` takes it as its input
(D23), and the runbook's steps edit it. A site's onboarding sends the public key from
its relay read and is assigned an issuer name, an audience, and a range. Narrowing a
range, or removing a key or an issuer, waits until the grants it would refuse have
ended — for SCM's own rotation, D17's `grants_valid_until` — because frps rechecks a
proxy only when it registers again; widening a range or adding a key or an issuer is
safe at any time.

Why (correction 10): two provisioning services pointing at one relay would
otherwise grant overlapping ports with nothing to stop them, and Arkhai intends to
run a relay serving several sites it does not control, each with its own storefront
and provisioning service. Onboarding a site to a shared relay is the site sending its
public key and being assigned a range, which the runbook describes.

Rejected: one relay per provisioning service (a rule enforced only by documentation,
and a relay per site); a YAML issuer list `relay-server` renders into the plugin's
TOML (a mirror of the plugin's format that must follow every change to it).

### D21. Admission at login on a shared relay is deferred

frps accepts one token for every client, so on a shared relay every site's hosts can
log in and open connections and pools; grants limit only which ports they register.
That is a way to exhaust the relay, not to reach anyone's guests or hosts, and
removing a site's key does not stop its hosts logging in. See Open Questions.

Rejected now: admission at login in this change (a further credential, its
distribution to hosts without passing through a workstation, and its rotation, for a
threat the live run does not involve).

### D22. frp comes from one verified pin, installed at a versioned path

A family role, `frp-binary`, holds the one frp pin and its install; `relay-client`
includes it for `frpc` and `relay-server` for `frps`:

```yaml
# provisioning/compute/iac/ansible/roles/frp-binary/defaults/main.yml
frp_version: "0.61.1"
frp_archives:                      # keyed by platform; gains entries without changing shape
  linux_amd64:
    url: "https://github.com/fatedier/frp/releases/download/v0.61.1/frp_0.61.1_linux_amd64.tar.gz"
    sha256: "<the archive's digest, recorded from a verified download>"
frp_install_root: /usr/local/lib/frp
```

The role downloads the archive for the host's platform, checks it against the pinned
SHA-256 before extracting anything, and installs the named binary at
`/usr/local/lib/frp/<version>/<binary>`, skipping only when that exact path exists; it
returns the path, which `frpc-buyers.service` and `frps.service` run. It refuses a
version or platform it has no digest for, naming both. The digest is recorded from a
download of the official archive, checked against the release's published checksum
when recorded, and never read from that checksum at run time. frp 0.61.1 is the
version the plugin is tested against (its D5), for frps and frpc alike.

A version change changes the unit's binary, so it restarts `frpc-buyers` or frps: the
version is part of the client's baseline (D3, D4), and the runbook makes the change
drained. Once `frp-grant-admission` is on this branch, a family IaC test holds the pin
equal to the tool's `frp-pins.toml` (D18).

Why (correction 12): one digest proves only a download that happens, so the
skip-when-present check has to name the version; a versioned path does, and it takes the
buyer client off `/usr/local/bin/frpc`, which a host's management client may own, so
this role can never replace the operator's binary. One role keeps frps and frpc from
drifting apart again, and one release archive carries both binaries.

Rejected: a version and digest in each role, held equal by a test (two copies, and the
verified install written twice); reading the plugin's pins file at run time (the service
image does not carry `tools/`, and the file leaves with the tool); bumping frps only
(unverified downloads, and installs skipped whenever any binary is present).

### D23. How a relay runs the plugin

`relay-server` prepares a VPS relay, which runs frps as a native systemd unit with no
container runtime, and installs the plugin as a plain program beside it, from inputs it
is given and never builds or fetches:

```yaml
# relay-server inputs (illustrative)
frp_grant_admission_wheel: "<path to the tool's wheel>"
frp_grant_admission_requirements: "<path to its hash-pinned runtime requirements>"
frp_grant_admission_config: "<path to the plugin's TOML (D20)>"
```

On the relay it requires `python3` 3.11 or later, creates a virtual environment under
`/opt/frp-grant-admission`, installs the requirements with `--require-hashes` and then
the wheel with `--no-deps`, and runs the plugin as its own unprivileged user under a
unit templated from the tool's systemd example. It checks the configuration with the
plugin's `check` before installing it, writes it root-owned and readable by the
plugin's group under `no_log`, and reloads the plugin on a change. frps gains the
`[[httpPlugins]]` entry (`path = "/"`, `ops = ["NewProxy"]`, the plugin's loopback
address), which restarts frps once. Until the move-out change publishes a wheel, the
runbook builds it from the repository (the tool's `make build`) and exports the
requirements from the tool's lock (`uv export --frozen --no-dev --no-emit-project`);
after it, the inputs name the published wheel. Either way the move-out is off this
change's critical path.

A relay running frps in containers runs the plugin's image as a sidecar in frps's
network namespace — the same pod, Compose's `network_mode: service:frps`, or host
networking — pinned by revision, with its configuration mounted read-only and reloaded
by SIGHUP, beside the upstream frps image at the pinned version (D22) with the same
`[[httpPlugins]]` entry. This repository ships no frps deployment manifest, so the
runbook describes these steps rather than templating them; their input is the image
reference.

The live run's buyer relay is of the second kind, so section 16 proves the image path;
`relay-server`'s plugin install has IaC tests and syntax checks only, and no live
evidence.

Why: the plain program fits how `relay-server` already builds a relay, as the plugin's
design notes for a VPS (its note 7); hash-pinned dependencies keep the install as
verified as D22's downloads; and taking the plugin as an input means its publication
never gates this change. Documenting the image covers the other kind of relay without a
second install path in the role.

Rejected: the image installed by `relay-server` (a container runtime and registry
credentials on a VPS for one loopback process, and no public image to pull); both,
chosen by a variable (two install paths, the live run proving one); no plugin install
in the role (the one requirement every relay must meet, D19, without tooling); a
throwaway VPS relay in the live run to exercise the role (declined by the owner: the
role's tests are its evidence).

### D15. Every reclaim policy ends the tenant's activity

Where the tenant account exists, every policy removes the lease's key, ends the
account's sessions (`loginctl terminate-user`) and lingering (`loginctl
disable-linger`), kills what remains (`pkill -KILL -u`), and removes the account's
crontab and `at` jobs, and only then keeps, locks, or deletes the account. A failed
lock or delete, or a process still alive after the kill, fails the reclaim, so
teardown fails and convergence requeues it rather than a release being recorded. The
reclaim's fact reports what was ended and stays diagnostic. A reclaim for an account
that does not exist still succeeds reporting it absent.

Why (correction 11): the boundary D4 records assumes the tenant is gone after
reclaim; a process left behind outlives the lease and can wait for a privilege
escalation, a client restart, or the next tenant. This holds for direct access as
well.

Rejected: ending activity only under `lock_user` and `delete_user` (the default
leaves the tenant on the host); recording the gap.

**D15b. A tunnel-reached bare-metal host in a pool with no relay** is delivered at
its connection's route unless it states a buyer route. The seller documentation and
`physical-provisioning`'s architecture say such a host must be in a relay-backed pool
or state `public_host`/`public_port`. No guard: the service cannot tell a connection
runs through a tunnel.

### D5. The real-provisioning target's version 2

One section, `REAL_PROVISIONING_TARGET`, version 2, loaded by the
`real-provisioning-target` profile from an ignored
`config-real-provisioning-target.yml` beside a committed `.example`:

```yaml
REAL_PROVISIONING_TARGET:
  version: 2
  hosts:
    - host_id: example-kvm-1
      domain: vm
      connection: {ssh_host: 198.51.100.20, ssh_port: 6001, ssh_user: provisioner,
                   ssh_key_path: /run/secrets/example-host-key}
      access: {mode: relay, relay_id: relay-vm}        # or {mode: direct, public_host: 192.0.2.10}
      capacity: {vcpu_count: 4, ram_gb: 8, disk_gb: 60}
      listing_shape: {vcpu_count: 2, ram_gb: 3, disk_gb: 25}
    - host_id: example-bm-1
      domain: bare_metal
      physical_host_id: example-machine-1
      connection: {ssh_host: 198.51.100.20, ssh_port: 6002, ssh_user: provisioner,
                   ssh_key_path: /run/secrets/example-host-key}
      access: {mode: relay, relay_id: relay-bm}
      capacity: {vcpu_count: 2, ram_gb: 4, disk_gb: 40}
      ssh_host_public_key: "ssh-ed25519 AAAA… example"
```

Each host states its domain, connection, access, and capacity; fields belonging to
another domain or mode are refused (`public_host` under relay access, `relay_id`
under direct access). Each lane uses the one host of its domain, and two hosts of
one domain are refused. A host's `relay_id` names a relay row in the provisioning
service its own lane runs against (correction 10). Version 1 is refused with a
message naming the profile to use and how its fields map. Values in the example are
documentation addresses and invented names.

Why: one file per environment and one model documenting both domains; no relay is
used by any customer, so retiring version 1 costs one edit of an operator-rendered
file.

Rejected: keeping version 1 readable (two names and loaders for a file only
operators write); two sections, one per domain (the relay reference and connection
shape stated twice); keeping the name `REAL_VM_TARGET` (misleading).

### D6. The target names a relay by id only

The lane reads the relay through the API and requires it enabled, its token
configured, and an active grant key before it writes anything. It never creates or
edits a relay.

Why: the token is never in the target, and a relay's address, window, and keys come
from the deployment's definitions document; restating them would be a second copy
that can disagree.

### D7. The target states the lane's listing shape

Each VM host carries `listing_shape`; the reader refuses one that does not fit
twice within `capacity`, naming the dimension. The lane writes it as its pool's
`listing_shapes` hint, declares `capacity` unchanged, deals on it twice, and
compares guests and an adopted listing against it.

Why: one declaration already sells as many guests as fit; the earlier lane chose a
listing equal to the whole capacity, so its one deal filled the host. Nothing in
negotiation or at the site changes.

Rejected: deriving half the capacity (rounding can yield a guest that does not
boot, and the shape is in no file); a fixed shape in the lane (one shape for every
environment, held in code).

### D8. The VM lane runs a second deal while a session stays open

Between the first deal's access checks and its expiry, real-lane stages:

1. open a heartbeat session to guest 1 — one `ssh` process printing the time each
   second, with `ServerAliveInterval`, which must stay running;
2. run a second deal on the same listing — negotiate, escrow, settle, poll its
   create job, advance to active — and check guest 2 at its own delivered access and
   port;
3. check the heartbeat ran through the second create with no gap beyond a stated
   bound;
4. cut the second deal's lease short, advance the workers, poll its teardown job,
   and check its capacity and port are released;
5. check the heartbeat through the second proxy's removal, then close it.

The second deal's fields have one producer stage each, and the module's finaliser
recovers both deals. The sequence runs in both access modes; in direct mode it shows
the same of the DNAT rules VM creation adds.

Why: one module holds both guests and the session; the shared stages and mock lanes
are untouched; bare metal's mock lane runs its own second deal the same way.

Rejected: running the canonical stages twice (a session cannot span modules);
concurrent deals as a shared-stage concept (changes both mock lanes for a property
only a real reload shows); leaving session survival to a manual step.

### D9. What the lane proves, and what the operator supplies

| Relay change evidence | Shown by |
|---|---|
| 6.1 reload keeps established sessions | D8 step 3 (lane) |
| Removing a proxy keeps established sessions | D8 step 5 (lane) |
| 8.1 a granted proxy is accepted | each create's status wait requires the proxy running, and the buyer connects (lane) |
| 8.2, restated: a proxy without a valid grant is refused | the plugin's integration tests against real `frps` and `frpc`, and a runbook step against the deployed relay — frps in a container with the plugin's image as a sidecar (D23) — with the plugin's refusal from its log (correction 6) |
| 8.3 a second VM leaves the first session alive | D8 step 3 (lane) |
| 8.4 the management tunnel is unaffected | host connectivity through the provisioning service (`GET /api/v1/hosts/{id}/connectivity`) before and after each create and teardown, every job having run over it (lane); the management client's status across the run (operator) |
| 8.5 the delivered string connects from outside the cluster | the lane runs from the operator's machine |
| 8.6, restated: teardown releases the port | the holdings read shows the lease released with its grant's expiry and no other lease on the port (lane); reuse after expiry at integration level, since D16 holds a port until its grant's original expiry |

The service gains an administrator-only holdings read,
`GET /api/v1/relays/{relay_id}/leases`: each lease's port, host, owning reservation,
`released_at`, `grant_expires_at`, and signing key id. The live run's output, free of
addresses and host names, is recorded here against each item, and the relay change's
closeout records its sections 6 and 8 from it.

Why: the lane can drive only the application, which always writes a valid grant; the
management client and the plugin's log are outside SCM; and no route reports
holdings today.

Rejected: the lane only (nothing shows the deployed relay enforces admission);
operator logs only (unreproducible).

### D10. The real bare-metal lane takes the real VM lane's shape

`e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_real_provisioning_deal.py`,
marker `e2e_bare_metal_real_provisioning`, in no lane, skipping and naming the
profile when the target has no bare-metal host, run against the bare-metal release.
A real bare-metal `ComputeDealDriver` without `MockGates` registers, from the target,
a backed pool delivering and advertising bare metal with `provider_config.relay_id`,
the host with its connection, and the declaration. It runs every shared stage,
bare metal's non-mock stages (publication, the listing closing, evidence
publication), and real-lane stages: the bare-metal executor is real; the settlement
preview chose the target host; grant- and reclaim-job polls; the tenant connects
with a key generated for the run at `ssh -p <leased port> <tenant>@<relay>`, and an
unrelated key is refused; connectivity over the management tunnel; after release the
string is refused and the holdings read shows the lease released. The finaliser cuts
the lease short so reclaim runs. The host key is pinned from the target's
`ssh_host_public_key`, following `e2e_bare_metal_deal`, since the operator knows a
bare-metal host's key. `e2e_bare_metal_deal` is unchanged.

A rerun adopts the listing publication already holds (settled in planning, as this
decision delegated). A bare-metal listing is derived by the publication loop, never
created, and its derivation identity is its Physical Resource and its shape's digest:
a rerun against the same declaration derives the same candidate, which publication
refreshes or reopens rather than publishing anew, while a corrected declaration
closes the old listing and publishes a successor. So the lane's publication stages
accept, for its resource, either a `publish` action or no new listing beside one
already open, and record the one open listing on its resource; several open
listings on it, or none after the step, fail naming them, before any deal stage
writes. Nothing pauses or creates a listing, unlike the VM lane's adoption.

Rejected: extending `e2e_bare_metal_deal` (rebuilding it into what the shared stages
already provide, and losing its payment qualification).

### D11. One SSH helper

`e2e-tests/tests/e2e/roles/helpers/ssh_access.py` becomes the one SSH helper and
gains a pinned `known_hosts` mode and the heartbeat session. `bare_metal_access.py`
keeps only its purchase helpers, and `e2e_bare_metal_deal` moves onto `ssh_access.py`
with its behaviour unchanged.

Why: `prove-real-vm-provisioning` recorded that the two helpers converge once both
exist.

### D12. Both create-fact variants name their relay block `relay`

`vm-create.yml`'s buyer-key fact names its relay block `frp` and its generated-key
fact `relay`; the codec reads only `frp`. Both become `relay`, and the codec, the mock
output, and the codec's tests follow.

Why: the relay design names delivered fields `relay_*` so the buyer never learns the
relay implementation, and D3 rewrites these tasks anyway. No path runs a relayed
create without a buyer key today (correction 8).

Rejected: renaming only the generated-key block to `frp`; leaving the variants
inconsistent.

### D13. Implementation cadence

On the owner's direction after the design review (workflow log seq 39), the work
that does not need the admission plugin comes first, and `frp-grant-admission` gates
only the work that does and this change's closeout. Nothing in SCM imports the
plugin: the signer is built to the grant format D16 states, which is the
prerequisite's settled specification, and the family roles take the plugin's wheel and
configuration as inputs (D23). What needs the plugin itself is a fourth round:
installing it on a relay, checking the signer against the plugin's published test
vector and the frp pin against its pins file (D18), the operator documentation of
admission, and the live run. So rounds 1–3 below start
now, round 4 waits for `frp-grant-admission` to be archived, and the operator
documentation the third round first carried moves to round 4, since it describes
the plugin's configuration. Four rounds, each ending in its own review:

- **Round 1 — the service core.** Session 1: the relay machinery's move into the
  family kit, contracts, client, and routes; the `pool_relays` migration; the
  holdings read; bare metal's pool configuration accepting `relay_id`. Session 2:
  keys per relay with staged rotation, thumbprint ids, and public halves read as the
  plugin takes them (D17); the grant signer built to D16's format, with no `iat`,
  through `cryptography` and `rfc8785`; the expiry grace and the port quarantine with
  its reuse margin (D16); preparation refusing a relay with no active key; the
  management-address check.
- **Round 2 — hosts and playbooks.** Session 1: the family IaC project; `frp-binary`
  with the 0.61.1 pin and versioned install paths (D22); `relay-client` and
  `relay-proxy` with the admin API locked down; `relay-server` replacing `frp-setup`,
  frps from the pin and no secret disclosed (D3), the plugin not yet; VM's tasks onto
  the roles; the relay block rename.
  Session 2: bare-metal relay access (allocation, the codec's endpoint, grant and
  reclaim through `relay-proxy`); bare-metal host preparation; reclaim ending the
  tenant's activity.
- **Round 3 — the lanes.** Session 1: target version 2 and the VM lane over a relay,
  with the second-deal sequence and its evidence stages. Session 2: the real
  bare-metal lane; the SSH helper convergence.
- **Round 4 — admission end to end, once `frp-grant-admission` is archived.**
  Session 1: `relay-server` installing the plugin from a wheel path, checking its
  configuration before reloading (D23); the vector check and the pins check (D18);
  the runbook — relay preparation, a containerised relay with the plugin's image
  pinned by revision beside frps at the pinned version, onboarding a site to a shared
  relay, the window within its range, the drain rule, synchronised clocks, key
  rotation, and the admission check — and seller documentation and the e2e README.
  Session 2: a live-verification section in the `[log]` form
  `prove-real-vm-provisioning` used, on a containerised relay (D23): the owner
  supplies the run's output, free of environment identifiers, and the change is
  `blocked in implementation` until then.

Sections 1–3 (round 1, session 1) are implemented and are unaffected by the
reconciliation with the plugin's settled design: none of them signs or stores a grant.

## Risks and trade-offs

- **The change is large**: a family refactor, a new trust mechanism, a second
  domain's relay access, and two lanes. The cadence orders it so each round rests on
  a reviewed one.
- **A relay without the plugin accepts any proxy**, and the service cannot tell
  (D19). Running it is the operator's responsibility; the runbook's admission check
  is the proof.
- **A retired grant key may stay in the plugin longer than needed** (D17): until the
  longest unreleased lease allocated before its retirement ends.
- **Port quarantine after a lease is cut short** holds a port until the lease's
  original end plus the grace and the reuse margin; a window can run short under heavy
  early termination.
- **The reuse rule assumes synchronised clocks** (D16): a relay clock lagging the
  service's by more than the reuse margin reopens a window for a copied grant.
- **`relay-server`'s plugin install has no live evidence** (D23): the live run's relay
  is containerised, so the role is proven by its IaC tests and syntax checks only.
- **Lease extension would drop the session** of the extended lease (D16).
- **The real lanes are not in the pipeline** and can rot; their markers, the
  `.example`, and the runbook keep them reproducible.

## Open Questions

- **Admission at login on a shared relay (D21).** Revisit when the first site Arkhai
  does not control joins an Arkhai relay. Likely design: the plugin also handles
  `Login`, requiring a per-site or per-host credential signed by the site's key in
  client-wide metadata, so removing a site's issuer refuses its next logins.
- **Relay deletion** stays `relay-vm-access-without-a-dashboard`'s decision gate
  1A.7; nothing here forecloses its answers.
