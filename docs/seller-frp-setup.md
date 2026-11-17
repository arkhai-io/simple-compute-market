# Seller relay setup

How to run a tunnel relay so buyer VMs and whole hosts are reachable when your KVM host has no
inbound route of its own.

The default seller flow ([`seller-quickstart.md`](./seller-quickstart.md)) uses
direct port-forward NAT: the KVM host's public IP exposes each VM on a port
(`ssh -p <port> tenant@<kvm-host-ip>`). A relay replaces that with a
publicly-reachable machine running `frps`, and a tunnel client on the KVM host
that dials out to it. Buyers then reach a port on the relay instead of a port
on your host.

Use a relay if your KVM host isn't directly reachable — NAT'd, behind a
corporate firewall, on a VPN-only network — or if you run several hosts and
want one ingress address.

Skip it if your host has a public IP and you don't mind port-numbered access.
Direct NAT is simpler, has one fewer moving part, and remains fully supported.

## What a buyer receives

A host and a port:

```console
ssh -p 6142 tenant@relay.example.com
```

Buyer access is port-based. There are no per-VM subdomains, and a wildcard DNS
record serves nothing here.

The reason is a property of the protocol rather than a choice. FRP's `subdomain`
option belongs to its `http` and `https` proxy types, which demultiplex on the
`Host` header. SSH runs over a `tcp` proxy: it sends no SNI and no `Host`
header, and client and server exchange version banners immediately on connect.
A relay has nothing to route on, so a `tcp` proxy binds a distinct port whatever
the `subdomain` key says.

## What the relay does not need

**No dashboard.** Nothing in the provisioning path reads one. Ports are
allocated by the provisioning service, and proxy status is read from the tunnel
client on your own host over loopback — the client that registered the proxy is
the one that knows whether registration succeeded. `frps` serves its dashboard
and admin API unauthenticated unless separately configured, so leaving them off
is the defensible default.

**No DNS name for an admin interface,** and no certificate for one.

**No public admin interface.** The relay token authenticates clients; the admission
plugin separately checks each proxy's signed port grant. Both are required.

## Prerequisites

- A publicly-reachable machine, at least 2 vCPU / 4 GB RAM, Ubuntu 22.04+, any
  provider. Around $5–10/mo is plenty.
- SSH access to it as a user with passwordless `sudo`.
- A DNS name or static IP for it. A plain `A` record is enough.
- Inbound TCP open on the rendezvous port (7000 by default) and across the port
  window you allocate for VMs.

## Choosing a port window

The relay binds one listening socket per VM, inside a window you choose.
6100–6199 is a reasonable default: 100 concurrent VMs across every host dialling
this relay.

Two things to know:

- **The window is shared by every host on the relay.** A remote port binds a
  socket on the relay itself, not on your KVM host, so two hosts dialling one
  relay draw from one pool. Size it for the whole fleet behind it.
- **It must match what you register.** Bound it with `allowPorts` in
  `frps.toml` and register the same window with the provisioning service. A
  proxy outside the window is refused by the relay, and that refusal appears in
  a tunnel client's log rather than as a failed provisioning request.

## Server configuration

```toml
# /etc/frp/frps.toml
bindPort = 7000

auth.method = "token"
auth.token = "<a long random string>"

# The window buyer VM tunnels may bind. Nothing outside it is admitted.
allowPorts = [{ start = 6100, end = 6199 }]

# No dashboard: nothing in the provisioning path reads one, and it is
# unauthenticated unless separately configured.

log.to = "/var/log/frp/frps.log"
log.level = "info"
log.maxDays = 30

[[httpPlugins]]
name = "grant-admission"
addr = "127.0.0.1:7300"
path = "/"
ops = ["NewProxy"]
```

Generate a distinct token with `openssl rand -base64 32` and keep it in private
configuration. Run frps and frpc **0.61.1**, the verified family pin. The plugin
must run on loopback in frps's network namespace, with an issuer whose audience
is the registered relay id, public keys from that relay's grant-key read, and a
port range containing the registered allocation window. A token alone must not
admit a proxy.

Use one buyer-only relay per operator. Put management tunnels on a different
relay, with their client admin API disabled or authenticated. A shared buyer
relay uses one token across all operators' hosts; token rotation touches them
all, and an frps restart to end one operator's sessions interrupts everyone.
Each operator needs a distinct issuer/key and nonoverlapping assigned range.
See the [relay operations runbook](development/VALIDATION_RUNBOOK.md#28-prepare-and-operate-buyer-relays)
for native/container setup and the mandatory deployed admission check.

## Registering the relay

A relay is a resource in the provisioning service, not a setting on your
storefront. Register it once:

```console
POST /api/v1/relays/
{
  "id": "site-a",
  "relay_addr": "relay.example.com",
  "relay_port": 7000,
  "vm_port_range_start": 6100,
  "vm_port_range_count": 100,
  "token": "<the token from frps.toml>"
}
```

This is a signed administrator request, sent through the canonical provisioning
client; the block illustrates its body rather than an unauthenticated shell command.
Then set the resource pool's `provider_config.relay_id`; hosts in that pool dial that relay.
Creation generates a grant key. Read `grant_keys.active.public_key` and configure
it in the plugin before enabling buyer admission. For reinstallable definitions,
use an operator-retained `grant_key_secret_key` as the runbook describes.

The token is encrypted at rest and is never returned by any read. Relay and pool
responses report *whether* a token is configured, not what it is.

To rotate the token, drain the relay first: disable it, and wait until its read
reports `"drained": true`, as "Changing a relay later" below describes. A
restart of frps ends every session the server carries, so on a shared relay
every operator registering it disables and drains their relay first. Then
update `frps.toml`, restart frps, update every host client baseline and send the
signed rotation request with body `{"token": "<replacement>"}`:

```console
POST /api/v1/relays/site-a/token
```

Verify the new client baselines and ungranted-proxy refusal, then enable the
relay again. Token rotation is refused while the relay has unreleased leases.

## Storefront configuration

None. A storefront names no relay, and any relay-shaped keys under
`[provisioning]` in a storefront configuration are inert.

Which relay a host dials is a property of where that host is, recorded against
the relay its pool references. A storefront naming a relay per request would
make a fleet-wide fact depend on one caller's configuration, and would let two
requests for the same host disagree about how it is reached.

## Changing a relay later

A delivery's relay, for a VM or a bare-metal grant, is fixed for that delivery's
life. The buyer holds an address and a port, and a port on one relay means
nothing on another, so an existing delivery cannot be moved to a different
rendezvous.

Four changes are refused while an affected delivery still holds a lease.
Changing which relay a pool uses, moving a host into a pool that dials a
different relay, and repointing a relay's address or port would each move what
a buyer holds. Rotating a relay's token makes every host's client restart to
adopt it, since a reload does not apply a new token, and a restart drops the
proxies the client carries.
Each is allowed once the affected leases are released. Draining is the same
lifecycle at two scopes, stop new work and let existing work finish, and the
refusal names the scope that clears it.

For a pool's relay, or a host's pool, drain the pool:

1. Disable the pool. New deliveries stop being scheduled onto it; running ones
   are untouched.
2. Wait for its leases to be released, as its deliveries are torn down or
   expire.
3. Make the change.
4. Re-enable the pool.

For a relay's address, port, or token, drain the relay, since the change
affects every pool that references it:

1. Disable the relay (`POST /api/v1/relays/site-a/disable`). No new delivery
   is placed on any of its pools' hosts or leased a port on it; running
   deliveries are untouched, and their teardowns run.
2. Wait until the relay read (`GET /api/v1/relays/site-a`) reports
   `"drained": true`. Its `active_lease_count` shows how many leases remain,
   and the holdings read (`GET /api/v1/relays/site-a/leases`) names what holds
   it open.
3. Make the change.
4. Enable the relay again (`POST /api/v1/relays/site-a/enable`).

Disabling a relay is reversible at any time, before or after it drains, and
removes no proxy and releases no lease.

Moving a host between pools that dial the *same* relay needs none of this.
Nothing a buyer holds changes.

A relay the definition document lists is disabled and enabled through its
entry's `enabled`, not through the API: an API disable is reverted when the
document next changes. A relay the document stops listing is left as it is.

### Retiring a relay

Nothing in the provisioning service deletes a relay. To take one out of
service:

1. Disable the relay, through its entry's `enabled: false` when the
   definition document lists it.
2. Wait until the relay read reports `"drained": true`. The holdings read
   names what holds it open.
3. Remove the relay server, or, on a shared relay, remove this relay's active
   and retired keys and its port range from the admission plugin. This is the
   relay operator's step, outside the provisioning service; the
   [relay operations runbook](development/VALIDATION_RUNBOOK.md#retire-a-relay)
   gives it for both cases.
4. Point any pool still referencing the relay at another relay. The next
   delivery on each host in a repointed pool rewrites the host's buyer-client
   settings from the new relay, which may restart the client. That is safe,
   since the host holds no lease, and the host needs no preparing again.
5. Enable a relay again only when a server runs at its rendezvous. The service
   never checks that a relay server exists, so an enabled relay with no server
   sells capacity nothing can deliver.

The drained relay's record stays, disabled, as the record its leases, keys,
and pool references point at. A server later reinstated at the same address
and port is the same relay: rotate its token, stage a key, configure its public
half in the reinstated server's admission plugin and prove admission as the
runbook's "Prove admission before enabling a pool" describes, activate the key,
and enable the relay again.

## Verifying

On the KVM host, after a VM has been created:

```console
systemctl status frpc-buyers
tail -f /var/log/frp/frpc-buyers.log
```

The admin API binds loopback on privileged port 740 by default and requires a
generated per-host password stored only in root-owned mode-0600
`/etc/frp/frpc-buyers.toml`. Do not expose it or copy the password into command
arguments/logs. Provisioning reads this protected configuration to authenticate
its status/reload requests. The host's unprivileged-port boundary must still make
the chosen port privileged; preparation checks that condition.

The client executes `/usr/local/lib/frp/0.61.1/frpc`. Drain before changing its
connection baseline or version: those changes restart the client. Per-proxy
changes reload it and preserve unrelated buyer sessions.

On the relay:

```console
journalctl -u frps -f
```

A proxy registering outside the window is refused here, naming the port. That is
the log to check when a VM is created successfully but a buyer cannot reach it.

Note the unit name: `frpc-buyers`. If your host also runs a management tunnel that
lets an operator reach the host itself, that is a separate unit and a separate
configuration file, established when the host was prepared. No buyer provisioning operation
touches it, and it is not what this document describes.
