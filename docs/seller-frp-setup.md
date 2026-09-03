# Seller relay setup (optional)

How to run a tunnel relay so buyer VMs are reachable when your KVM host has no
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

**No dashboard password.** The relay's admission token is the only credential.

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
```

Generate the token with something like `openssl rand -base64 32`. It is the
whole of the relay's admission control: anyone holding it can register a proxy
within `allowPorts`.

Run a `frps` version compatible with the tunnel client the fleet installs.
`frps` and `frpc` negotiate a protocol version, so a large gap between them is a
real mismatch rather than a cosmetic one.

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

Then point a resource pool at it; hosts in that pool dial that relay.

The token is encrypted at rest and is never returned by any read. Relay and pool
responses report *whether* a token is configured, not what it is.

To change it, rotate on both sides: update `frps.toml` and restart `frps`, then

```console
POST /api/v1/relays/site-a/token
```

The new value takes effect on the next VM created, including a retry of one
accepted before the rotation. VMs already running keep their existing tunnels.

## Storefront configuration

None. A storefront names no relay, and any relay-shaped keys under
`[provisioning]` in a storefront configuration are inert.

Which relay a host dials is a property of where that host is, recorded against
the relay its pool references. A storefront naming a relay per request would
make a fleet-wide fact depend on one caller's configuration, and would let two
requests for the same host disagree about how it is reached.

## Changing a relay later

A VM's relay is fixed for that VM's life. The buyer holds an address and a port,
and a port on one relay means nothing on another, so an existing VM cannot be
moved to a different rendezvous.

Three changes are therefore refused while any affected host still runs a VM:
repointing a relay's address or port, changing which relay a pool uses, and
moving a host into a pool that dials a different relay. Each is allowed once the
affected hosts hold no leases.

To make one:

1. Disable the pool. New VMs stop being scheduled onto it; running VMs are
   untouched.
2. Wait for its VMs to be torn down or to expire.
3. Make the change.
4. Re-enable the pool.

Moving a host between pools that dial the *same* relay needs none of this.
Nothing a buyer holds changes.

## Verifying

On the KVM host, after a VM has been created:

```console
systemctl status frpc-vms
curl -s http://127.0.0.1:7400/api/status | jq '.tcp[].name'
tail -f /var/log/frp/frpc-vms.log
```

That loopback admin API is what the provisioning path itself reads to confirm a
proxy came up.

On the relay:

```console
journalctl -u frps -f
```

A proxy registering outside the window is refused here, naming the port. That is
the log to check when a VM is created successfully but a buyer cannot reach it.

Note the unit name: `frpc-vms`. If your host also runs a management tunnel that
lets an operator reach the host itself, that is a separate unit and a separate
configuration file, established when the host was prepared. No VM operation
touches it, and it is not what this document describes.
