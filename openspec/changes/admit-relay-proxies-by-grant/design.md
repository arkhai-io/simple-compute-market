# Design: A relay admission plugin for signed grants

## Context

This change was split out of `prove-relay-provisioning`'s design, which settled the
admission mechanism and the plugin's shape. The decisions below are carried from that
discussion, with their reasoning and the alternatives it rejected; this change's own
design confirms them, settles the open questions at the end, and records its cadence.

frp checks a server plugin on `Login`, `NewProxy`, and a few other events, and a plugin
may refuse. A client sends client-wide `metadatas` at `Login` only; each proxy's own
`metadatas` reach the plugin only with that proxy's `NewProxy`. frps admits a proxy
once, at registration — at create and again after every client reconnect — and never
rechecks a registered one.

Existing plugins, as their documentation describes them: `fp-multiuser` (per-user
tokens at `Login`, no port limits), `frp_plugin_allowed_ports` (per-user port lists at
`NewProxy`, on top of `fp-multiuser`), `frps-panel` (per-user tokens, ports, and domains
in one file, with an admin UI), and `frp_jwt_allowed_ports` (a JWT whose `ports` claim
lists allowed ports). None admits by a grant carried per proxy.

## Decisions

### D1. Admission is by a signed grant per proxy

A proxy is admitted only when it carries a grant, signed by an issuer the plugin is
configured with, for exactly the port it requests.

Why: admission is then exactly the ports the issuer granted, the issuer's allocator
stays the only authority, and the relay holds no state per host.

Rejected:

- *Per-host accounts and fixed port ranges* (`frps-panel`, or `fp-multiuser` with
  `frp_plugin_allowed_ports`): existing software, but a partitioning policy with a fixed
  cap per host, an edit on the relay for every host, and drift between the issuer's
  ranges and the relay's file.
- *frp's built-in settings* (`allowPorts`, `maxPortsPerClient`): server-wide, so they
  stop neither port claiming nor one token opening many clients.
- *The relay calling the issuing service* per registration: relay infrastructure never
  calls an SCM service.

### D2. The grant

A JWT signed with EdDSA (Ed25519), carried in the proxy's own `metadatas.grant`:

```text
header  {"alg": "EdDSA", "typ": "JWT", "kid": "<issuer key id>"}
claims  {"aud": "<relay id>", "port": <remote port>, "exp": <expiry>,
         "sub": "<optional subject>", "jti": "<optional grant id>", "iat": <issued at>}
```

The plugin admits a `NewProxy` only when the proxy type is `tcp`, the signature is valid
under the issuer key matching `kid`, `aud` equals that issuer's audience, `port` equals
the requested remote port and lies inside that issuer's range, and `exp` has not passed.
`sub` and `jti` are logged with a refusal and never decide one: a client's `user` is
whatever its configuration says.

Why: per-proxy metadata is the only place a grant can change without restarting the
client — client-wide metadata is sent at `Login`, so a change there ends every session
the client carries. The grant must stay valid for its port's whole tenure, because frps
asks again after every reconnect; expiry is therefore the issuer's choice, typically the
end of whatever the port was granted for.

Rejected: client-wide grants listing a client's ports (every new port restarts the
client); a home-made envelope instead of a JWT (no gain, and every plugin library reads
JWTs); grants without expiry, revoked at the relay (revocation needs state on the relay
or a call out).

### D3. Issuers are bound to audiences and port ranges

The configuration maps each issuer key to the audience it signs as and the port range it
may grant, and a grant outside its issuer's range is refused:

```yaml
listen: 127.0.0.1:7300
issuers:
  - {kid: "vm-site/relay-1/1", public_key: "MCowBQYDK2VwAyEA…", audience: relay-1,
     ports: {start: 6100, end: 6199}}
  - {kid: "bm-site/relay-1/1", public_key: "MCowBQYDK2VwAyEA…", audience: relay-1,
     ports: {start: 6200, end: 6249}}
```

Why: several issuing services may share one relay — Arkhai intends to run a relay for
sites it does not control, each with its own storefront and provisioning service — and
without ranges two issuers could grant one port, or one could grant another's. Key
rotation is listing the new key beside the old until the old key's grants have expired.

Rejected: one relay per issuer (a rule only documentation enforces).

### D4. The plugin is a standalone, SCM-agnostic Python tool

`tools/frp-grant-admission/`, depending on `cryptography` and a small HTTP server and on
no internal package. It owns the grant specification, its configuration format, and a
published test vector; signers elsewhere conform to it. Nothing in it names hosts,
leases, sites, or SCM; it carries a licence header and can be lifted into its own
repository as it stands, which a later change does.

Why: generic infrastructure that is not specific to SCM does not belong in SCM, and
having to build it is a warning sign — weighed here and overridden because no existing
plugin admits by a per-proxy grant. One language with the repository keeps its
packaging, test, and CI checks in force.

Rejected: adopting `frp_jwt_allowed_ports` (it appears to read client-wide metadata,
its claims differ, its maintenance and licence are unverified, and it is Go); forking it
(a Go toolchain the repository lacks, for code largely rewritten); writing it in Go (a
second toolchain); placing it in a compute-family package with the grant as an SCM
contract (backwards: the plugin owns its specification).

### D5. Tests run real frp

Integration tests start real `frps` and `frpc` binaries at the pinned version and show a
valid grant admitted, and refused: no grant, a forged signature, the wrong port, the
wrong audience, an expired grant, a port outside its issuer's range, and one issuer's
grant for another issuer's range.

Why: the property worth proving is frps's behaviour with the plugin, not the plugin's
answer alone.

### D6. Login admission and revocation are out of scope

The plugin handles `NewProxy` only. On a shared relay every token holder can still log
in and open connections — a way to exhaust the relay, not to reach anyone's resources.

## Open Questions

To settle in this change's design:

- How the configuration is reloaded: a signal, a file watch, or a restart.
- The HTTP server and the image's base, build, and versioning.
- How the integration tests obtain pinned `frps` and `frpc` binaries in CI.
- The capability's name and the split of its `spec.md` and `architecture.md`.
- Whether the plugin also logs `CloseProxy` for an audit trail.
- The README's statement of the specification's own versioning.

Deferred beyond this change:

- **Admission at login on a shared relay.** Revisit when the first site Arkhai does not
  control joins an Arkhai relay; likely a per-site credential signed by the site's key
  and checked on `Login`.
