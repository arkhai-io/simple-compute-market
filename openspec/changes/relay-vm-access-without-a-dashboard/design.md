# Design

## The two tunnel layers, and why they are separate clients

A host participating in this system holds two reverse tunnels that answer to
different authorities and carry different traffic.

| | Management | Buyer access |
|---|---|---|
| Reaches | the host's own administrative interface | one rented VM |
| Consumed by | the operator and the provisioning service | the buyer |
| Relay | the operator's relay | the site's relay, which may differ |
| Proxies | one, static, written at initialization | one per VM, added and removed continuously |
| Token supplied by | node initialization, out of band | the provisioning service, at VM creation |
| Written by | host provisioning, outside this repository | this repository's role |

They cannot share a process. `frpc.toml` carries exactly one `serverAddr`,
one `serverPort`, and one `auth.token` at the top level, and a proxy cannot
override them. The moment the two layers may address different relays — which
the site-operated deployment shape assumes — two clients follow as a
consequence rather than as a choice.

Separating them buys three things beyond the requirement. The management
tunnel, which is the recovery path, is on a client no VM operation touches, so
its blast radius excludes VM churn structurally rather than by care. A
malformed VM proxy stanza cannot break it. And re-running host setup no longer
re-templates a file holding live VM proxies, because the two clients own
different files.

## Why the relay token must not reach the VM

Running `frpc` inside each VM would dissolve the reconfiguration problem
entirely: each VM writes its own configuration at creation and dials the relay
itself, and the host client is never modified.

It is rejected because the buyer has root in the VM, and therefore the token.
The relay's `allowPorts` spans both the management and VM windows, so a buyer
holding the token can register a proxy into the management window. If a host's
management tunnel drops, its port becomes free and the buyer can bind it —
answering, as that host, the connections the provisioning service makes to
administer it.

This is not addressed by per-VM or per-host tokens. Distinct tokens bound the
damage to one relay's admission, but the relay still admits the holder to
whatever `allowPorts` permits, and a per-VM token is one more credential to
mint, deliver, and revoke on a machine the buyer controls. The property worth
holding is that the token never lands on buyer-controlled hardware at all,
which the host-side client gives for free.

A site operator's trust relationship with the relay operator does not cover
this. The buyer is not party to that relationship.

## Why coordination is host-local rather than relay-side

The dashboard is a monitoring surface that the current path uses as a
distributed lock: it is queried to discover which ports and names are taken
before choosing one. That works, and it costs a dashboard, a DNS name, a
certificate, a second credential, and an HTTPS round trip inside a task that
also has a local answer available.

The local answer is already in the code. The port-selection task unions the
dashboard's `remotePort` values with `grep remotePort /etc/frp/frpc.toml`,
because the dashboard omits `conf` for offline proxies and the local file is
the only place their reservations survive. The local file is authoritative for
one host's own proxies; the dashboard adds visibility of *other* hosts'
proxies on the same relay.

So the question the dashboard actually answers is narrow: how do two clients
sharing one relay avoid choosing the same port? That is a coordination question
about a relay-wide resource, and it is answered by a port lease held in the
provisioning service — see the lease decision below — rather than by a
management surface on the relay.

Verification has a cleaner local answer still. `frpc`'s admin API, bound to
`127.0.0.1`, reports proxy status for the client that owns the proxy — which is
the client the playbook just configured. Polling the relay to learn whether the
local client succeeded is a round trip to ask a third party about our own
state.

## Reload rather than restart

`systemctl restart frpc` closes the control connection. The relay treats that
as the client going away and tears down every proxy it registered, so every
established TCP connection through any of them dies. The current path does this
on every VM creation, so buyers on a host lose their sessions each time a
neighbour is provisioned.

`frpc reload` re-reads the configuration and applies a diff: unchanged proxies
are left alone, new ones added, removed ones closed. It covers proxy sections
only — `serverAddr`, `auth`, and `transport` are not hot-reloadable — which is
acceptable because those are written once at initialization and never change
afterward.

**This claim needs live proof before it is relied on.** It is documented frp
behaviour and it is the reason the admin API exists, but "an established SSH
session survives a reload that adds an unrelated proxy" is exactly the kind of
assumption that should be tested rather than reasoned about. The test is small:
open a session through a tunnel, append a proxy, reload, and check the session.
It belongs in the plan as an explicit gate, and its outcome decides whether the
fallback below is needed.

**Fallback if reload does not preserve sessions:** one `frpc` process per VM,
each with its own unit and configuration, so a reconfiguration affects exactly
one buyer. It is not free — a unit to create and reap per VM, a control
connection each, and the template's `transport.poolCount = 5` means five idle
connections per VM against a relay where `transport.maxPoolCount` is unset. It
also relocates allocation rather than removing it. Held as a contingency,
not built speculatively.

## What the buyer receives

Port-based, and relay-implementation-agnostic. The proxy stanza's
`subdomain` key is dropped: FRP's `subdomain` is a vhost feature of the `http`
and `https` proxy types, and a `tcp` proxy binds a distinct port whatever the
key says. SSH sends no SNI and no `Host` header — client and server exchange
version banners immediately on connect — so many names resolving to one address
give the relay nothing to demultiplex on. The wildcard DNS record and
certificate that `docs/seller-frp-setup.md` instructs sellers to create serve
nothing for SSH.

The connection string is therefore `ssh -p <port> <user>@<relay-host>`, which
`ssh_commands` already produces in the direct-NAT path. The buyer learns a host
and a port and never learns which relay implementation is behind them, which is
why the field's keys are named `relay_*` rather than `frp_*`.

## Decisions

**A relay is a first-class resource, and the token belongs on it.**

An earlier version of this design put the relay endpoint and window on the pool
and the token in the deployment's secrets profile, keyed by an identity derived
from `relay_addr:relay_port`. Two facts moved it.

*The window can diverge.* Two pools may point at one relay — a site running a
GPU pool and a bare-metal pool through one rendezvous is the ordinary case, and
the lease decision below depends on it being ordinary. Deriving one identity
from two pools unifies the *lease key* and nothing else. `vm_port_range_start`
and `vm_port_range_count` stay per-pool, so two pools can allocate from one
listening namespace under disagreeing bounds, and "the configured window for
that relay" has no single answer.

*The token would be duplicated state.* N pools sharing a relay would hold N
encrypted copies of one credential. Rotation becomes N writes, and a missed one
fails at admission — asynchronously, in a client log, which is the failure mode
this change exists to remove.

So a relay is a row: address, port, allocation window, and token, each stated
once. Pools reference it. Divergence stops being discouraged and becomes
unrepresentable, and a lease keys on a row rather than on a string assembled
from an address.

This was previously deferred, on the grounds that a table, its CRUD, and an
admin surface were too much to solve a problem arising only under deliberate
operator action in a deployment with one relay. That reasoning held while the
credential lived outside the pool, in the secrets profile. It does not survive
the credential moving into the database: the pool then becomes the only place a
relay fact can live, and the divergence above becomes reachable by ordinary
configuration rather than by operator error.

**Relay identity is a row, not a derived address.**

Deriving identity from the endpoint had one real virtue: a derived value cannot
lie about where a port was bound, whereas a separately administered identifier
can disagree with reality in both directions — two pools claiming one identifier
while pointing at different relays would collide leases that do not conflict,
and one relay under two identifiers would issue the same port twice.

A row keeps that virtue and drops the cost. The endpoint is unique on the
relay table, so two rows cannot describe one rendezvous and one rendezvous
cannot appear as two identities. Identity is then stable across an address
change: moving a relay updates one field, and every lease referencing that row
follows it, rather than the old address's leases becoming stale while the new
identity reissues ports still bound.

**The token is stored encrypted; the profile holds the root key, not the
credential.**

`ssh_decryption_key` in the provisioning secrets profile already encrypts host
SSH key material at rest for `embedded` hosts. The relay token is the same class
of material and takes the same treatment: Fernet-encrypted in the relay row,
decrypted only on the execution path.

The database therefore holds no usable credential. Recovering a token needs both
the row and a key that never leaves the secrets profile. That is what makes
storing it acceptable at all — *plaintext* in the database would be strictly
worse than the mounted profile, since it adds the pool read surfaces, the export
endpoint, and database backups while losing the profile's access control,
versioning, and audit trail.

The comparison worth stating is against what this repository already stores: an
`embedded` host row carries an SSH private key granting root on that host. A
relay token admits a client to a rendezvous within `allowPorts` and grants
nothing on any machine. The lower-value credential is not getting weaker
treatment than the higher-value one.

**Two readers, and the redacted one has the unqualified name.**

Provider configuration reaches five consumers through one reader today, and they
do not share a trust level.

| Consumer | Token |
|---|---|
| Fulfillment, via the pool loaded in the caller's transaction | required |
| `PoolResponse` from pool list and get | must not appear |
| The pool export document | must not appear |
| Pool update's read-modify-write | must survive |
| Reconciliation's configuration comparison | must not diverge on it |

Stripping inside the single reader breaks fulfillment; not stripping leaks to
two read surfaces and makes every reconciliation compare unequal forever. So
there are two readers, and the one *without* secrets carries the unqualified
name. A caller that forgets to ask for secrets loses the token loudly on the
execution path rather than leaking it quietly on a read path — the failure
direction is chosen, not incidental.

A separate method is preferred to a boolean parameter because a name can be
grepped for and cannot be supplied accidentally by a positional argument.

**An absent token on a write preserves the stored one.** Pool update reads,
merges, and writes back, and it reads through the redacted reader. Without an
explicit preserve rule, a request changing only a label would round-trip a
configuration containing no token and erase the credential — an unrelated edit
destroying key material, which is a failure this system has already met once and
should not rebuild one layer down. Absent means unchanged; only an explicit
value replaces one. There is deliberately no way to express "clear the token"
through a partial write, because clearing one disables every VM path on that
relay and should be an explicit act.

**A definition document is reconciled when it changes, not when a pod starts.**

Deployment is Terraform applying a Helm chart. A relay must be establishable by
applying the chart alone, with no operator API call and no credential passing
through a workstation. The service already imports a pool definition document at
startup, and that is the mechanism to reuse — but not as it currently behaves.

`import_pool_definitions_if_configured` runs `import_pools` at every startup. The
code justifies this on the grounds that import is idempotent and diff-based, so
re-running it is harmless. That premise is wrong in a way worth stating
precisely: **the import is idempotent with respect to the document, not with
respect to the database.** Running it twice against an unchanged database is a
no-op. Running it against a database that something else changed reverts that
change, because a diff against the document is exactly what detects it.

So every pod restart silently re-asserts a document nobody just submitted.
Eviction, node drain, an OOM kill, and crashloop recovery all revert operator
work with no failure and no log line anyone would think to check. That is the
defect, and it belongs to the *invocation*, not to the import.

The distinction matters because the import's authoritative behaviour is correct
and specified. An operator submitting a document is declaring desired state, and
disabling what the document omits is what makes it a declaration rather than a
merge. Nothing should change there. What should change is that a pod starting up
is not an operator submitting a document.

So the service records a digest of each definition document it has imported and
reconciles only when the digest differs from the one recorded. Editing the
document and redeploying reconciles. Submitting a document through the import
endpoint reconciles, because the operator asked. A pod restarting against an
unchanged document does nothing at all.

This is the same bookkeeping the schema migrations already use — a durable record
of what has been applied, consulted before applying it again — rather than a new
mechanism.

**Relays and pools use one gate, and differ in one rule.** An earlier version of
this design gave relays create-if-absent semantics precisely to escape the
restart problem, leaving pools reconciled and relays not. That was solving the right
problem in the wrong place. It bought restart-safety at the cost of making the
document a bootstrap that could never be edited afterwards, and it put two
contracts behind one idea, so a reader who knew the pool rule would guess wrong
about relays. Fixing the invocation fixes both resources with one gate, and lets a relay's
window be edited in the document and reconciled like anything else.

They differ in one rule, deliberately. A pool omitted from its document is
disabled, because the document declares what the deployment offers and a pool it
no longer names should not be scheduled. A relay omitted from its document is
*retained*, because disabling one breaks every pool referencing it and every
live tunnel on it — a far worse outcome than a stale row, and one an operator
editing an unrelated entry would not expect. Retention is also what makes a
relay established from a document and then administered through the API one
relay rather than two.

**Digest granularity is the whole document, and the token is why that is safe.**
A per-entry digest would avoid reconciling entry A because entry B changed. It is
not needed, because the field an operator is most likely to have changed through
the API — the token — is structurally protected: the document never carries a
token, reads never return one, and an absent token preserves the stored value. A
reconciliation therefore cannot revert a rotation, whatever else it touches.

What a reconciliation can revert is a window or an address changed through the
API while the document still declares the old one. That is correct: those are
fields the document declares, and an operator who has just edited the document
is asserting them. It is also visible, in the reconciliation diff that import
already returns.

**The token is read once, at creation.** A relay entry names which profile key
holds its token; the key is read when the relay is created and never re-read.
Rotation is a controller operation. Treating the profile as continuing desired
state would make it silently authoritative over a value the controller can also
set, and the two would fight on a schedule nobody observes.

**Nothing in the definition document is a credential.** It carries a rendezvous
address, a port, a window, and the *name* of a profile key. It needs no Secret
and can be an ordinary mounted configuration file. Only the profile holds the
token, and it holds it as a bootstrap value rather than as the store.

**The rendezvous token and the relay token are the same value in dev and are
not the same setting.** The management tunnel's token is consumed by node
initialization directly, and never by this service; the buyer-facing relay's
token is what a relay row carries. Today both address one relay and one source
supplies both. Keeping them distinct settings is what allows the buyer-facing
relay to become a different server without re-plumbing anything.

**The template's fallback token is removed rather than changed.**
`frp_auth_token | default('password123456789')` currently means a host
initialized without an explicit token is configured with a value published in
a tracked file. Replacing the literal with a better literal preserves the
failure mode. An undefined token must fail the task.

**A relay configured without a usable allocation window is rejected before
dispatch.** Today the two access paths are guarded by different conditions —
NAT by `frp_server_addr is not defined`, relay by `frp_dashboard_password is
defined` — and a configuration satisfying neither produces a VM with no
external route and a successful job. Whatever the final guards are, the
invariant is that exactly one access path runs, and no configuration selects
zero. This is validated where other malformed VM requirements are already
rejected, rather than discovered mid-playbook.

**The `frpc` version becomes a variable.** It is currently a `set_fact` in the
middle of the install task, so it can only be changed by editing the task.
`frps` and `frpc` negotiate a protocol version, which makes the client version
a property of which relay the fleet talks to.

**The provisioning service allocates a VM's relay port; the playbook applies
it.** The service selects a free port from the configured window, records it
against the VM, and passes it in as a job input. The playbook writes the proxy
stanza it is given and never chooses a port.

The alternative was a per-host sub-window recorded on the host row, with the
playbook allocating inside its own slice. Both remove the relay dashboard as a
coordination point and both were close on effort. Service-side wins on three
counts. Allocation state lives where reclamation can act on it, so a port
released on teardown is released by the component that also knows the teardown
failed. One authority means no partitioning policy to maintain as hosts are
registered and removed, and no fixed per-host cap. And it puts the allocation
behind an API surface that can later expose which ports are held, by which VM,
on which host — visibility and operator control that a shell loop reading a
file on a host cannot offer, and which can be changed by deploying a service
rather than by reaching every host in the fleet.

Revisit if the playbook needs to run usefully with no provisioning service in
the loop — a standalone seller path, or proving the host in isolation. Under
that requirement the sub-window alternative returns, because it is the only one
of the two that leaves the playbook self-sufficient.

**Relay location is deployment configuration, not request configuration.**

Which relay a host dials is a fact about where that host physically is, not
about the request being served. Carrying it in the storefront's `connectivity`
payload lets a storefront name a different relay per request for the same host,
and makes a durable property of the fleet depend on a caller getting its
configuration right.

So `connectivity` carries nothing relay-related at all, and the buyer-facing
address is returned in the fulfillment result rather than supplied with the
request. The pool names which relay its hosts dial, and the relay row holds the
endpoint and window.

The pool is the right place for the *reference* for the same reason it holds
`playbook_path`, `inventory_group`, `extra_vars`, and the default VM shape: it
is where operator-set facts about how a set of hosts is driven already live. It
is the wrong place for the endpoint and window themselves, because those are
facts about the relay and are shared by every pool that points at it — see the
first decision above.

This also removes the weakest part of the original shape. Deriving relay
identity from a request payload meant a storefront misconfiguration could split
one relay into two identities, or merge two into one. Under a referenced row the
identity is set once by an operator, cannot vary per request, and two pools
naming the same relay reference the same row — so a genuine collision is
detected rather than missed.

**A port lease is scoped to the relay, not to the host — and not to the pool.**

This corrects an error in the first version of this design, which made the lease
unique on `(host, port)`. That is the wrong boundary. For a `tcp` proxy,
`remotePort` binds a listening socket on `frps` itself, not on the node. Two
nodes dialing one relay are not independent namespaces: if node A holds
`R:6100`, node B cannot also hold it, and a `(host, port)` uniqueness constraint
would happily issue it. The relay would refuse the second registration, and the
refusal would surface asynchronously in a client log rather than as a failed
allocation — the exact failure mode this change set out to remove by taking the
dashboard out of the coordination path.

The lease is therefore `UNIQUE(relay_id, remote_port)`, with the host recorded
as an attribute rather than as part of the key. Uniqueness then matches the
resource: one listening socket on one relay.

Keying on the pool instead is the obvious simplification, and it has the same
defect one level up. Nothing stops two pools pointing at one relay — a site
running a GPU pool and a bare-metal pool through one rendezvous is the ordinary
case — and `UNIQUE(pool_id, remote_port)` would let both issue 6100. The relay
would bind the first and refuse the second, asynchronously, in a client log.
Uniqueness has to match the resource, and the resource is one listening socket
on one relay.

The lease therefore references the relay row, and `UNIQUE(relay_id, remote_port)`
is uniqueness on the row rather than on a string assembled from an address. One
relay is one row is one listening namespace, by construction: the relay table's
endpoint is unique, so one rendezvous cannot appear under two identities and
issue the same port twice, and two rows cannot describe one rendezvous and
collide leases that do not conflict.

Moving a relay to a new address updates one field, and its leases reference the
row and follow it — so the proxies that persist across the move stay accounted
for rather than becoming records under an identity nothing points at any more.

That is a claim about *accounting*, and an earlier version of this design let it
stand as though it were a claim about safety. It is not. The buyer holds
`ssh -p <port> <user>@<relay>`, and the relay half of that string is already
delivered. A foreign key keeps the ledger honest across a move; it does nothing
for the connection string a buyer is holding. See the rebinding decision below
for what actually governs when a relay may move.

**A lease is released on every terminal outcome, and reconciliation is the
backstop.**

Allocating before dispatch is deliberate: allocating afterwards means a crash
between the two leaves a port bound on the relay that no record claims. But it
also means the lease outlives any path that fails before teardown would ever
run. A dispatch that never starts, a VM creation that fails permanently, a
cancelled request, and an expired lease each end the VM's life without a
teardown, and a release attached only to teardown leaks on all four.

So release is attached to the lifecycle's terminal states rather than to one
path through it. Even that is not sufficient on its own — a set of code paths
is never provably exhaustive, and the one that is missed is the one nobody
thought of. A periodic reconciliation releases leases whose owning job or
fulfillment has been terminal beyond a grace period, which converts an
unenumerated leak into a bounded one.

The window is 100 ports wide, so an unreleased lease is a slow degradation
rather than an outage, and the same API that reports holdings is where a manual
release lands.

**The host management client proxies `127.0.0.1:22` and nothing else.** The
question was whether a second proxy should reach an `sshd`-independent recovery
service, so a host with a broken `sshd` stayed administrable. The failure that
motivated it turned out to be the loss of the host's network interfaces to a
passthrough binding, not a failure of `sshd`. No in-band mechanism survives
that: a tunnel, a second `sshd` on another port, a shell service, and a
self-heal loop all require the interface that was taken. A second proxy would
have added a token-guarded shell endpoint without covering the case that
motivated it. The failure is prevented at its source by
`never-strand-the-host-on-passthrough`, and out-of-band console access remains
the last resort, owned by an operations runbook rather than by either
repository's playbooks.

Revisit if a failure is observed in which the host retains its network path but
`sshd` is unusable — that is the case a second proxy would genuinely address,
and no evidence for it exists yet.

**A relay is bound to a VM at creation, not to a host.**

The lease records `relay_id`, and that record — not the pool's current
configuration — is where a VM's relay lives for the whole of its life. A pool's
relay reference determines which relay a *new* VM gets. Nothing moves an
existing one.

This is forced rather than chosen. The buyer was given a host and a port. Both
halves are delivered artifacts of a paid rental, and the port is not portable
between relays: 6142 on one rendezvous says nothing about 6142 on another, which
may already be leased to a different host. Repointing a host's client at a new
relay does not migrate its VMs; it strands every buyer on that host and asks the
new relay for ports that may not be free.

Two consequences follow, and both are corrections to how earlier drafts read.

*Teardown reads the lease, not the pool.* Resolving the relay from pool
configuration at teardown means that after any repoint, teardown reloads the
wrong client and releases against the wrong relay. The lease is the authority
because the lease is what recorded where the port was actually bound.

*Relay uniformity on a host is an implementation limit, not a model limit.* One
`frpc` process carries one `serverAddr` and one token, so a host can serve only
VMs whose leases name the relay its client dials. The model already permits a
per-VM relay; the current client topology is what does not. If the reload gate
in section 6 fails, its recorded fallback — one client per VM — removes that
limit for free and without a schema change, since the lease already carries the
relay. Building per-VM clients *for* relay heterogeneity is not worth a unit, a
control connection, and `poolCount` idle connections per VM to buy something
nothing currently needs.

**Rebinding requires draining, and draining already exists.**

From the above, exactly one rule covers every way a relay binding can change:

> A host's pool, a pool's relay reference, and a relay's address or port may
> each change only while no affected host holds an active lease — unless the
> relay on both sides of the change is the same, in which case nothing about
> any delivered connection string moves and the change is free.

No new primitive is needed. Disabling a pool is already specified as a draining
operation: it excludes the pool from new scheduling without invalidating
existing reservations or active workloads. So rebinding is disable, wait for
leases to clear, rebind, re-enable.

Rejecting the change while leases are held is preferred to accepting it and
reissuing every buyer's connection string. A reissue is not something this
system can deliver — the buyer already has the string, and nothing in the
protocol pushes them a new one.

**The relay token is resolved at execution, not carried in the accepted
snapshot.**

`physical-provisioning` requires that accepted operations snapshot the resolved
playbook and provider variables with the submitted job, so that an operator
editing pool configuration after dispatch cannot change what a running job does.
The token is a deliberate exception, for two independent reasons.

It must not be in the snapshot. The snapshot is persisted in a JSON column and
returned by the job endpoints, so a token placed there is neither encrypted at
rest nor withheld from a read — which is the whole of what this change claims
about relay credentials.

And it should not be in the snapshot. A token rotated through the relay
controller has to take effect on the next execution, including a retry of a job
accepted before the rotation. A snapshot pins the value that was correct at
acceptance, which is exactly the value that no longer works.

So the accepted operation carries `relay_id` and the leased `remote_port`, and
the address and token are resolved immediately before the job's variables are
written. A relay that has been disabled, deleted, or had its token cleared
between acceptance and execution fails the job rather than retrying: the
configuration is wrong, not the moment, and a retry against unchanged
configuration would fail identically.

The resolved variables file is secret material for the same reason a decrypted
host key file is, and gets the same treatment — owner-only, in a directory the
operation owns and removes. That work belongs with the host key material change
rather than half here, because it is one mechanism serving both.

**Lease release attaches to the settlement record's terminal transition.**

`FulfillmentConvergenceWatchdog` is the single place a settlement record reaches
succeeded or failed, for creates and teardowns alike. Release belongs there,
inside the same transaction that records the terminal state.

Not in the same transaction is the tempting simplification and it is wrong: a
crash between the two leaves exactly the leak reconciliation exists to bound,
recreated on a schedule rather than by an unforeseen path. Reconciliation should
be cleaning up after paths nobody enumerated, not after the enumerated one.

Attaching release to individual code paths — teardown, cancellation, expiry —
was the earlier shape and is what produced an allocator whose comments claimed
every terminal outcome released while nothing called it at all. One observer of
terminal state is both correct and checkable.

## Alternatives considered

**One static range proxy covering the whole VM window.** Configure the client
once and never reconfigure it. FRP's `range:` prefix expands one stanza into N
proxies sharing a single `localIP`, and VM SSH needs N ports fanning out to N
different libvirt addresses, so the syntax cannot express it. It becomes
possible only by pairing a range proxy with per-VM DNAT on the host, which
moves allocation from a configuration file into iptables rather than removing
it — with the one genuine benefit that the client is never reloaded. Worth
reconsidering only if reload proves to disturb sessions.

**Keep the dashboard, deploy one alongside every relay.** Preserves the current
code. It requires every relay operator to run an unauthenticated-by-default
management surface, publish a DNS name for it, obtain a certificate, and
distribute a second credential — to answer a question the host can mostly
answer locally.

**Allocate from the relay by attempting and retrying.** Ask for a port; if the
relay refuses it as taken, try the next. Needs no shared state at all and is
robust to any number of hosts. Rejected as the primary mechanism because the
refusal surfaces asynchronously in the client's log rather than as a task
failure, so the playbook would have to parse a log to detect it. Viable as a
safety net beneath whichever authority is chosen.

## Migration

None. The dev cluster has never run a live-fire provisioning test and is
deployed in mock mode, so no host has been initialized against the relay and
none carries an accumulated `/etc/frp/frpc.toml`. The split into two client
configurations has no existing population to move.

Recorded rather than left implicit because the question is reasonable and the
answer is not obvious from the code: a reader seeing one configuration file
become two would expect a migration, and its absence is a fact about the
deployment rather than an oversight.

## Verification

No relay, host, VM, or Ansible runtime is available in the session environment.
The following distinguishes what can be verified from source from what needs a
live host, and the live items are expected to be verified against operator-
supplied logs.

Verifiable from source and focused tests:

- The `connectivity` field's new shape survives storefront → adapter →
  extra-vars without the removed keys appearing.
- A relay configuration selecting no access path is rejected before dispatch.
- An undefined relay token fails rather than templating a default.
- Rendered client configuration contains no `subdomain` key and no dashboard
  address.
- A stored relay token is ciphertext at rest and is recoverable only with the
  profile's encryption key.
- The redacted configuration reader never yields a token, on the pool read
  endpoints or in the export document, and the execution reader does.
- A pool or relay update that omits the token leaves the stored one intact.
- Reconciliation reports a seeded definition as unchanged on a second import
  rather than diverging on a field one side cannot see.
- A definition document naming a profile key seeds the token; one naming none
  leaves an API-set token untouched across a restart.

Needs a live host, verified from supplied logs:

- **Reload preserves established sessions.** The gate described above. Evidence
  is the client's own log across the reload plus an SSH session that outlives
  it.
- A proxy registered inside the configured window is accepted by the relay, and
  one outside it is refused — evidence is the relay's log naming the port.
- The management tunnel is unaffected by VM creation and destruction on the
  same host.
- A buyer connection string produced by the relay path actually connects.

## Recorded findings

These are true of the current system, were found while designing this change,
and are not fixed by it. They are recorded here so they are decisions rather
than discoveries the next reader makes again.

**One SSH key reaches every host in an environment.** The provisioning service
is deployed with a single keypair, mounted at a fixed path, and host registration
defaults to referencing that path rather than carrying key material. Every host
in an environment is therefore reached with the same private key, across all
pools. Per-host material is supported — an `embedded` host row carries its own
encrypted key — but nothing populates it today.

That support is the escape hatch, and it is sufficient: a host whose operator
supplies its own key is registered as `embedded` and reached with that key,
while hosts registered without one keep the shared fallback. What is missing is
not a mechanism but a policy, and generating per-host keypairs and placing the
public half in a node's `authorized_keys` is host preparation, outside this
repository. Recorded rather than fixed because the exposure grows with the
second independently operated host, not the first.

## Open questions

**Should relay administration have its own API surface?** *Resolved: yes.*

This was previously deferred alongside the `relays` table, on the reasoning that
both were the same question about whether a relay is a first-class resource.
That reasoning was correct, and the answer arrived when the token became durable
state: a credential that can be rotated needs somewhere to live that is not a
pool row, and a resource with its own controller is the better shape than a
write-only field on an otherwise readable model.

So a relay is administered directly — created, listed, updated, and its token
rotated — rather than through the pool that references it. The alternative that
loses is not the write-only field, which is still needed for the token itself,
but leaving relays seed-only: that would keep the deployment as the only way to
add a relay, and cycling a deployment to point a new pool at a new rendezvous is
the inflexibility that motivated moving the credential out of the profile in the
first place.

Authorization is the pool controller's, not a new boundary. A caller that can
write a pool can already set `playbook_path`, which is arbitrary playbook
execution on every host in that pool; setting a relay token is not a greater
privilege than one already held.

**What deletes a relay, and what happens to its leases?**

Not decided. A relay with live leases cannot simply be removed — the proxies it
carries outlive the row, and a deletion that orphans leases loses the record of
which ports on that rendezvous are bound. The plausible answers are refusing
deletion while any lease is held, disabling rather than deleting in the manner
hosts already use, or cascading a release that does not correspond to anything
actually torn down on the relay.

Deferred because the first relay will not be deleted and the answer is a
lifecycle decision that wants the reconciliation behaviour settled first. What
this change owes is that the schema does not foreclose any of the three.
