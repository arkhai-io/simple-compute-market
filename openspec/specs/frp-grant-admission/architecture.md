# frp grant admission — architecture

The normative contract is [`spec.md`](spec.md). The byte-level formats — the grant, its
signing, the configuration, the reason codes, the log, the test vector, and the pins
file — are the tool's [README](../../../tools/frp-grant-admission/README.md), which is the
published specification and travels with the tool. This document explains why the
plugin is shaped as it is, and where its limits lie.

## What problem it solves

frps admits a client by one shared token, and a client holding it may register a
proxy on any port frps's `allowPorts` covers. On a relay serving many hosts, that token
sits on every host, so any of them can claim a port allocated to another, take a port
before its rightful proxy registers, or exhaust the window. frp's own settings
(`allowPorts`, `maxPortsPerClient`) are server-wide and stop none of this, and the
existing plugins partition ports per user account, which puts a fixed cap and an edit
per client on the relay and lets its file drift from whatever allocates the ports.

The plugin admits a proxy only for the port a signed grant names. Whoever allocates
ports signs the grants, so admission is exactly what the allocator granted, the
allocator stays the only authority over which port belongs to whom, and the relay
holds nothing per client.

## Why a grant travels with each proxy

frpc sends two kinds of metadata. Client-wide metadata reaches frps once, at login;
each proxy's own metadata reaches the plugin with that proxy's `NewProxy`. A grant is
carried in the proxy's own metadata because that is the only place it can change
without restarting the client: an frpc reload registers only the proxies it changed,
while a change to client-wide metadata ends every proxy the client carries. A grant
listing many ports in the client-wide metadata would make every new port a restart.

frps asks the plugin once per registration — at creation and again after every client
reconnect — and never rechecks a registered proxy. A grant therefore stays valid for
its port's whole tenure, and its expiry is the end of whatever the port was granted
for.

## Stateless, calling nothing, loopback only

The plugin decides each `NewProxy` from the request and its configuration alone. It
keeps no record of what it admitted and never calls the issuer: relay infrastructure
does not depend on the issuing service being reachable, and a stateless check cannot
drift from the allocator's state because it holds none. The consequences are the
limits below — no revocation, and the drain rule.

It listens only on a loopback address, decided from the address itself without a
resolver, so it stays a local seam of frps. That is what lets it run as a bare standard
library HTTP server with no authentication and answer every refusal with its reason:
on a reachable port every decision could be probed, and each slow body would hold a
thread for the socket timeout. A remote plugin would need transport security and access
control that no caller asks for. The container image therefore runs in frps's network
namespace, never beside it on a network.

It handles `NewProxy` only. Admission at login is outside it (see the limits), and
`CloseProxy` would add nothing: frps logs closes, and a stateless plugin could not
attach a close to the grant that admitted it.

## Issuers, ranges, and the drain rule

Keys are grouped under issuers, each with one audience and one port range. Several
independently operated issuing services may share a relay, and ranges keep two of them
from granting one port. Grouping is what lets the plugin tell a rotation — two keys in
one issuer, one range — from two issuers mistakenly given overlapping ranges, and refuse
the second at load; a flat list of keys, each with its own range, would make the two
look alike. The audience is per issuer because each issuing service names the relay by
its own identifier. An issuer's name appears only in logs and errors, never in a grant.
One range per issuer suffices for a contiguous allocation window, and a later format
listing several would fail to load in this plugin, since unknown fields are refused.

Because frps never rechecks a registered proxy and the plugin cannot know its previous
configuration, a change that would refuse a grant already admitted — narrowing a range,
removing a key or issuer, changing an audience — takes effect on that proxy only when
its client next reconnects, which then drops it. The operator therefore drains first:
such a change waits until every affected grant has ended. Widening a range, or adding a
key or an issuer, is safe at any time. This rule, a signer granting only within its
range, and ranges lying within frps's `allowPorts` are the operator's to keep; the
README states all three.

## Key ids are thumbprints

A key's id is its RFC 7638 JWK thumbprint, derived by the plugin from the public key
the configuration lists. Ids are then unique across independent signers with no one
assigning them and nothing to mistype, and the only collision left, one key listed
twice, is a real error the loader refuses, since one key cannot carry two ranges.
Onboarding a signer is pasting its public key; `check` prints the id the signer's grants
will name, so an operator matches a key to log lines.

## Explicit typing is the major version

A grant's `typ` is `frp-grant+jwt`, and the plugin refuses every other type, `JWT` and
an absent `typ` included. Explicit typing is RFC 8725's defence against a token minted
for another purpose being read as a grant, and it doubles as the specification's major
version: unknown claims are ignored, so an optional claim is a compatible addition,
while a change that makes a conforming verifier refuse what it admitted, or admit what
it refused, takes a new type. A plugin knowing both types admits both while signers that
do not coordinate migrate one at a time, and an older plugin refuses the newer type. A
version claim would be read only after the signature and leave RFC 8725's protection
unused.

## No leeway on time

Expiry is checked on the relay's clock in whole seconds with no leeway: a grant is
refused from the second the clock reaches its `exp`. An allocator reuses a port once its
grant has expired, and any leeway would let a copy of the old grant claim the port
again in the window after; a leeway published as a constant would also become something
every allocator must know. The residual skew between the relay's and a signer's clocks
is the allocator's reuse rule to cover, by waiting past `exp` by more than the clocks can
differ. A signer whose clock runs ahead costs at most a `grant_not_yet_valid` refusal
that frpc's own retry clears, which is why `nbf` and `iat` have no leeway either.

## Where PyJWT ends

PyJWT, over `cryptography`, parses the token and decides its signature, its `aud`, and
the presence of the required claims, so the plugin writes no JWS parsing of its own and
needs no web framework for its one loopback route. The header rules (`kid`, `typ`,
`crit`), the time comparisons against the clock the caller passes, the claim types, and
the port are the plugin's own checks, as the specification requires.

The vector is replayed at two tested points: the locked dependencies, and each runtime
dependency at its declared floor. The declared ranges have no upper bound, so no test
proves a verdict for a release between those points or above the lock; a later release
is proven when the lock moves to it. What the specification promises across releases is
that structure, not identical verdicts from every release the wheel permits.

## Reload by validated SIGHUP

SIGHUP re-reads the file through the startup loader, and a file that loads replaces the
running configuration in one reference assignment, requests in flight finishing under
the one they began with. A file that does not load leaves the running configuration and
logs every problem, so a typo in one issuer's onboarding leaves a shared relay admitting
as it was rather than refusing every issuer's registrations. A restart, by contrast,
refuses to start on such a file. Watching the file was rejected: a save in the middle of
an edit — a key removed before its replacement is pasted — would take effect, against
the drain rule. `listen` is bound once, at startup.

Reloading loses nothing: frps fails closed while the plugin cannot answer, and frpc
retries a refused proxy on its own, so a proxy refused during a gap is admitted on its
retry without restarting frpc.

## Proven against real frp

The plugin's correctness on its own is proven by the vector and its unit and in-process
tests. What only real frp shows is the frp behaviour the design rests on: frps failing
closed on any bad answer, frpc retrying a refused proxy, a refusal's reason reaching
frpc, frps never rechecking a registered proxy, and an frpc reload asking only about the
proxies it changed. The real-frp tests run each of those, and a valid grant carrying
traffic, against the frp release the tool pins, from archives verified against a
SHA-256 recorded in the tool — never against the checksums file served beside the
release, which proves nothing about an archive from the same place. They run in a CI
gate that fails on a skip, beside the floor run; the default suite skips them and stays
offline. See [`TESTING.md`](../../../docs/development/TESTING.md#2-integration-tests).

## Placement

The plugin is generic infrastructure: it names frp and nothing about this marketplace.
It is a standalone component under `tools/`, depending on `cryptography`, PyJWT, and the
standard library alone, with its own licence and semantic version, and can be lifted into
a repository of its own as it stands
([`ARCHITECTURE.md`](../../../docs/development/ARCHITECTURE.md#kind)). It owns its
specification, its vector, and its pins file; whatever signs grants conforms to them,
checking itself against the vector's signing cases, and may read the pins file to install
and verify the same frp. Nothing in the plugin reads market code.

It ships two ways: a wheel run as a plain program under systemd beside frps, which needs
no container runtime on a relay host, and a container image for a relay hosted in
containers, running the plugin as PID 1 so a signal to the container reloads it. Which
one a relay runs is the installer's choice.

## Limits

- **No admission at login.** Every holder of frps's token can still log in and open
  connections: a way to exhaust a relay, not to reach anyone's port.
- **No revocation.** A grant admits its port until its `exp`; revoking earlier would
  need state on the relay or a call out.
- **The drain rule rests on operators.** Narrowing early drops a live proxy at its
  client's next reconnect, and the plugin cannot detect it.
- **A relay without the plugin admits any proxy.** Nothing in the tool can tell whether
  frps is configured to call it.
- **No probe command.** The kubelet's probes cannot reach a loopback listener, so a
  sidecar relies on its restart policy, during which frps refuses new proxies.
