## Why

An frp relay admits anyone holding its admission token to every port its
`allowPorts` covers. A token holder can claim ports the provisioning service has not
yet leased, so the next lease's proxy fails to register and its buyer reaches the
claimant; take a dropped host's management port; or exhaust every port the relay
allows. frps accepts one token for every client, and the token sits on every host the
relay serves, so a relay cannot be sold over — bare metal least of all, where the buyer
logs into the host — until the relay admits a proxy only for a port its provisioning
service granted.

`prove-relay-provisioning`'s design settled the mechanism: the provisioning service
signs a grant per lease, the proxy carries it, and a plugin on the relay checks it. No
existing frp plugin admits by a grant carried per proxy, so this change builds that
plugin, as generic infrastructure that names nothing about SCM.

## What Changes

- **A standalone frps server plugin** at `tools/frp-grant-admission/`: an HTTP endpoint
  frps calls through `[[httpPlugins]]` for `NewProxy` only, listening on loopback,
  holding no state, calling nothing, and depending on no internal package.
- **The admission rule.** A proxy is admitted only when its type is `tcp`, its own
  `metadatas.grant` is a JWT signed with EdDSA (Ed25519) by a configured issuer matched
  by `kid`, its `aud` is that issuer's audience, its `port` equals the requested remote
  port and lies in that issuer's range, and its `exp` has not passed. Anything else,
  a malformed request included, is refused, the reason logged with the grant's `sub`,
  `jti`, and `kid` and nothing secret.
- **Configuration**: a file naming the listen address and the issuers, each with its
  `kid`, public key, audience, and port range.
- **The grant specification**, owned here: the claims, where a grant is carried, the
  configuration format, and a published test vector of keys, grants, and expected
  verdicts that signers elsewhere conform to.
- **Tests against real frp**: integration tests run `frps` and `frpc` at the pinned
  version and show a valid grant admitted and each invalid grant refused.
- **Shipping**: a container image, built and versioned as the repository's others are,
  and runnable as a plain program.

## Capabilities

### New Capabilities

- `relay-grant-admission`: admission of relay proxies by signed grants, the grant
  specification, and the plugin's configuration. The design confirms the name.

### Modified Capabilities

None.

## Non-Goals

- Admission at login; a shared token still lets every client log in.
- Revoking a grant before it expires.
- The SCM signer, relay keys, and their rotation, which are `prove-relay-provisioning`'s.
- Installing the plugin on a relay (`prove-relay-provisioning`'s `relay-server` role).
- Moving the plugin to its own open-source repository, which is a later change.

## Impact

- `tools/frp-grant-admission/` (new): the plugin, its README specification, test
  vector, configuration example, and tests.
- The repository's image builds and its CI: one new image, and a test job that fetches
  pinned frp binaries.

## Dependencies and Related Changes

- `prove-relay-provisioning`: depends on this change for implementation; its signer
  conforms to this change's specification and test vector, and its live run deploys
  this plugin.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification
- [x] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The admission rule, the grant specification, and the configuration →
  `relay-grant-admission`'s `spec.md` and the tool's README.
- Why the plugin is SCM-agnostic and stateless, and why grants travel per proxy →
  `relay-grant-admission`'s `architecture.md`.
