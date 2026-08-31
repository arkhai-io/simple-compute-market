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
| Written by | the operations repository's playbook | this repository's role |

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

So the question the dashboard actually answers is narrow: how do two hosts
sharing one relay avoid choosing the same port? That is the open question
below, and it has answers that do not require a management surface.

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

**The relay token travels in the provisioning secrets profile, not storefront
settings.** It is a credential; the storefront's role is to say which relay to
use, not to hold the key to it. This also matches how `ssh_decryption_key` and
`storefront_admin_key` already reach the service.

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

The cost is accepted deliberately: the service now owns a resource it must
reclaim, and a teardown path that does not run leaks a port. The window is 100
ports wide, so a leak is a slow degradation rather than an outage, and the same
API that reports holdings is where a reconciliation or manual release lands.

Revisit if the playbook needs to run usefully with no provisioning service in
the loop — a standalone seller path, or proving the host in isolation. Under
that requirement the sub-window alternative returns, because it is the only one
of the two that leaves the playbook self-sufficient.

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

No host has yet been initialized against the relay deployed in the operations
repository's dev environment, so there may be no host carrying accumulated
proxy stanzas at all. If one exists, its `/etc/frp/frpc.toml` holds both the
management posture and VM proxies in one file, and the split needs either a
drain or a one-time transcription of existing stanzas into `frpc-vms.toml`.
Confirm which case applies before planning; do not write a migration for a
population that is empty.

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

Needs a live host, verified from supplied logs:

- **Reload preserves established sessions.** The gate described above. Evidence
  is the client's own log across the reload plus an SSH session that outlives
  it.
- A proxy registered inside the configured window is accepted by the relay, and
  one outside it is refused — evidence is the relay's log naming the port.
- The management tunnel is unaffected by VM creation and destruction on the
  same host.
- A buyer connection string produced by the relay path actually connects.
## Open questions

None outstanding. Both questions this change opened have been resolved; their
answers and revisit triggers are recorded under Decisions above.
