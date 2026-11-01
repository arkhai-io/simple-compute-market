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
  holding no state, calling nothing, and depending on no internal package — only
  `cryptography`, PyJWT, and the standard library.
- **The admission rule.** A proxy is admitted only when its type is `tcp`, it is in no
  load-balancer group, its remote port is a real port, and its own metadata carries a
  grant: a JWT of type `frp-grant+jwt`, signed with EdDSA (Ed25519) by a configured key
  named by its thumbprint, whose `aud` is that key's issuer's audience, whose `port`
  equals the requested remote port and lies in that issuer's range, and whose `exp` has
  not been reached on the relay's clock, with no leeway. Time claims are integers and
  `sub` and `jti` strings; the header, time, and claim-type checks are the plugin's own,
  not left to the PyJWT release installed. Anything else is refused
  with a stable reason code that reaches the client.
- **Configuration**: a TOML file naming the listen address, which must be loopback, and the issuers, each with a
  name, an audience, one port range, and its public keys; overlapping ranges and repeated
  keys are refused at load. SIGHUP reloads it, validated before it replaces the running
  configuration, and a `check` command validates a file and prints each key's id.
- **Logging**: one JSON line per decision, admission or refusal, saying whether the
  grant's claims were verified; the grant itself is never logged.
- **The grant specification**, owned here in the tool's README: the claims, where a
  grant is carried, its type as the specification's major version, signing in canonical
  JSON, the configuration format, the reason codes, and the rules an operator keeps — draining
  before narrowing a range, and each signer granting only within its range.
- **A published test vector** of a test key, verification cases with verdicts and
  reasons, signing cases a conforming signer reproduces byte for byte, and a thumbprint
  case.
- **Tests against real frp**: a gate fetches frp 0.61.1 from archives whose SHA-256 the
  tool pins and runs `frps` and `frpc` against the plugin — admission, each refusal,
  frps failing closed on any bad answer, frpc's retry, and the drain rule's premise —
  as a `tests.yml` job, which also runs the unit tests with each runtime dependency at
  the lowest release the tool declares; the default suite passes offline.
- **Shipping**: a wheel, runnable as a plain program under systemd, and a container image
  built as the repository's others are.

## Capabilities

### New Capabilities

- `frp-grant-admission`: admission of frp proxies by signed grants, the grant
  specification and its conformance vector, and the plugin's configuration, reload, and
  logging.

### Modified Capabilities

None.

## Non-Goals

- Admission at login; a shared token still lets every client log in.
- Revoking a grant before it expires.
- The SCM signer, relay keys, and their rotation, which are `prove-relay-provisioning`'s.
- Installing the plugin on a relay (`prove-relay-provisioning`'s `relay-server` role),
  and which of the plain program or the image a relay runs.
- Publishing the wheel or a public image, and moving the plugin to its own open-source
  repository, which a later change does.

## Impact

- `tools/frp-grant-admission/` (new): the plugin, its README specification, test
  vector, pins file, configuration example, systemd example, Dockerfile, licence, and
  tests.
- `tools/README.md`: standalone infrastructure components under `tools/`.
- The root `Makefile`: `test-frp-grant-admission` in `make test`, and
  `build-frp-grant-admission` in `make build` and `make push-images`.
- `.github/workflows/tests.yml`: the matrix entry and a real-frp gate job.

## Dependencies and Related Changes

- `prove-relay-provisioning`: depends on this change for implementation; its signer
  conforms to this change's specification and test vector, and its live run deploys
  this plugin. This design's notes for it (`design.md`, "Notes for
  `prove-relay-provisioning`") change its grant type, key ids, key format, runbook
  steps, frp version, download verification, and port-reuse rule.
- This change is renamed `admit-relay-proxies-by-grant` on `dev` before its design
  review (`design.md`, D16 and D17), since no code line may contain a change's name and
  the tool keeps `frp-grant-admission`; `prove-relay-provisioning`'s `Depends on` follows
  the rename.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification
- [x] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The admission rule, reload, logging, and the plugin's ownership of its specification
  and vector → `openspec/specs/frp-grant-admission/spec.md`.
- The grant specification, configuration format, reason codes, vector and pins formats,
  supported frp version, and operating rules → the tool's README.
- Why grants travel per proxy, why the plugin is SCM-agnostic and stateless, the issuer
  model, thumbprint ids, explicit typing, reload by signal, and the limits →
  `openspec/specs/frp-grant-admission/architecture.md`.
- Standalone components under `tools/` depend on no internal package; generic
  infrastructure not specific to SCM does not belong in SCM, and SCM conforms to a
  standalone component's published interface → `docs/development/ARCHITECTURE.md`.
- Registration and traffic are different proofs → `docs/development/TESTING.md`.
- `tools/` holds standalone infrastructure components → `tools/README.md`.
- The capability's index row → `openspec/specs/README.md`.
