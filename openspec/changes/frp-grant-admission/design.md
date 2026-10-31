# Design: A relay admission plugin for signed grants

## Context

Designed against `dev` at `6855f6de7`. This change was split out of
`prove-relay-provisioning`'s design, which settled the admission mechanism and the
plugin's shape; the decisions carried from it are restated here as settled.

frp checks a server plugin on `Login`, `NewProxy`, and a few other events, and a plugin
may refuse. A client sends client-wide metadata at `Login` only; each proxy's own
metadata reaches the plugin only with that proxy's `NewProxy`. frpc's configuration
calls both `metadatas`; frps sends a proxy's own as `content.metas` and the client-wide
ones as `content.user.metas`. frps admits a proxy once, at registration — at create and
again after every client reconnect — and never rechecks a registered one. A plugin's
refusal reason is returned to frpc, which shows it in its log and its admin status.

Existing plugins, as their documentation describes them: `fp-multiuser` (per-user
tokens at `Login`, no port limits), `frp_plugin_allowed_ports` (per-user port lists at
`NewProxy`, on top of `fp-multiuser`), `frps-panel` (per-user tokens, ports, and domains
in one file, with an admin UI), and `frp_jwt_allowed_ports` (a JWT whose `ports` claim
lists allowed ports). None admits by a grant carried per proxy.

What the repository shows, where the change's first account of it was incomplete:

1. frp is pinned twice: frps at 0.54.0
   (`domains/vms/provisioning/iac/ansible/roles/frp-setup/tasks/install-frp-server.yml`)
   and frpc at 0.61.1 (`roles/vm-setup/defaults/main.yml`). Both roles download frp
   without verifying it.
2. A relay runs frps as a native systemd unit (`frp-setup`'s `frps.service.j2`), with no
   container runtime installed.
3. `tools/` is defined as holding no market runtime service (`tools/README.md`), is
   skipped by `check-architecture` (`docs/development/ARCHITECTURE.toml`), and is outside
   `make test` and CI (`tests.yml`). The layout, lock, and Python-version checks do
   cover it.
4. Offline review validation runs each project's `make test` with the network off; tests
   needing an external binary skip in the default suite and run in a gate that fails on a
   skip, as the native Ansible gate does (`docs/development/TESTING.md`).
5. No file in the repository carries a licence header; the repository is MIT through its
   root `LICENSE`.

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

### D2. The grant, explicitly typed

A JWT signed with EdDSA (Ed25519), carried in the proxy's own metadata — `metadatas.grant`
in frpc's configuration, `content.metas.grant` on the wire to the plugin:

```text
header  {"alg": "EdDSA", "kid": "<key thumbprint, D3a>", "typ": "frp-grant+jwt"}
claims  {"aud": "<audience>", "port": <remote port>, "exp": <expiry>,
         "sub": "<optional subject>", "jti": "<optional grant id>", "iat": <optional issued at>}
```

`aud`, `port`, and `exp` are required. `sub` and `jti` identify the grant in the
plugin's log and never decide admission: a client's `user` is whatever its configuration
says.

The `typ` is also the specification's major version. The plugin admits only types it
implements and refuses any other, `JWT` and an absent `typ` included. Verifiers ignore
claims they do not know, so adding an optional claim is compatible; a change that makes
a conforming verifier refuse what an earlier version admitted, or admit what it refused,
is incompatible and takes a new type (`frp-grant.v2+jwt`). A plugin knowing both types
admits both while independently operated signers migrate one at a time, and an older
plugin refuses the newer type. The README states the specification's version as
`frp-grant 1.x`.

Why: per-proxy metadata is the only place a grant can change without restarting the
client — client-wide metadata is sent at `Login`, so a change there ends every session
the client carries. The grant must stay valid for its port's whole tenure, because frps
asks again after every reconnect; expiry is the issuer's choice, typically the end of
whatever the port was granted for. Explicit typing is RFC 8725's recommendation against
cross-JWT confusion, and it gives an incompatible change a migration path on a relay
whose signers do not coordinate.

Rejected: client-wide grants listing a client's ports (every new port restarts the
client); a home-made envelope instead of a JWT (no gain, and every library reads JWTs);
grants without expiry, revoked at the relay (revocation needs state on the relay or a
call out); `typ: JWT` with no version (an incompatible change could not be told apart);
a version claim (read only after the signature, non-standard, and leaves RFC 8725's
protection unused); explicit typing later (itself the incompatible change it would
enable).

### D3. Keys are grouped under issuers, each bound to an audience and a port range

The configuration names issuers; each has a name, the audience it signs as, one port
range, and one or more keys. A grant is admitted only inside its key's issuer's range.
The plugin refuses to load a configuration with a key listed twice, a duplicate issuer
name, ranges of two issuers that overlap, an issuer with no keys, or a range outside
1–65535 or ending before it starts. The issuer's name appears only in logs and errors,
never in a grant.

Audience is per issuer because each issuing service names the relay by its own
identifier. Rotation is adding a key to its issuer and later removing the old one.

Why: several issuing services may share one relay — Arkhai intends to run a relay for
sites it does not control, each with its own storefront and provisioning service — and
ranges keep two issuers from granting one port. Only grouping lets the plugin tell a
rotation (two keys, one range) from two issuers given overlapping ranges, and refuse the
second. One site onboarding is one issuer with its range and keys.

Rules the plugin cannot enforce, stated in its README:

- **Drain before refusing what was admitted.** frps rechecks a proxy only when it
  re-registers, so a change that would refuse a grant once admitted — narrowing a range,
  removing a key or an issuer, changing an audience — waits until every affected grant
  has ended; otherwise a live proxy keeps running until its client reconnects and is then
  refused, dropping a buyer. Widening a range and adding a key or an issuer are safe at
  any time. The plugin holds no state and cannot know its previous configuration.
- **A signer grants only within its range.** An issuing service's port window lies
  within its assigned range; a wider window shows as a refused registration that fails
  its create visibly, which is the intended failure.
- **Ranges lie within frps's `allowPorts`.** frps refuses ports outside it; the plugin
  does not read frps's configuration, and management ports belong on another relay.

One range per issuer: a site's window is one contiguous range, and an older plugin
reading a later list of ranges refuses to load, which is fail-safe.

Rejected: one flat list of keys, each with its own audience and range (rotation and
overlap look alike, so overlap goes unchecked and repeated fields can drift); a flat list
treating identical audience and range as one issuer (two issuers given the same range by
mistake pass as a rotation); one relay per issuer (a rule only documentation enforces).

### D3a. A key's id is its JWK thumbprint

A key's id is its RFC 7638 JWK thumbprint (the base64url SHA-256 of
`{"crv":"Ed25519","kty":"OKP","x":"…"}`, RFC 8037). The configuration lists only public
keys; the plugin derives each id at load, and a grant's `kid` names it.

Why: ids are then unique by construction across independent sites, with no coordination
and nothing to mistype; the only collision left, one key listed twice, is a real error,
since one key cannot carry two ranges. Onboarding is a site sending its public key.

Rejected: thumbprints also stated in the configuration and checked (a field that can
only disagree); ids namespaced by an issuer name the relay operator assigns (uniqueness
rests on onboarding, and a site on two relays may get two names); random ids (unchecked,
and free-form ids remain possible).

### D4. The plugin is a standalone, SCM-agnostic Python tool

`tools/frp-grant-admission/`, depending on `cryptography`, PyJWT, and the standard
library, and on no internal package. It owns the grant specification, its configuration
format, the test vector, and its pins file; signers elsewhere conform to them. Nothing in
it names hosts, leases, sites, or SCM, and it can be lifted into its own repository as it
stands, which a later change does.

- `tools/README.md` gains a section: `tools/` also holds standalone infrastructure
  components — not market runtime services, depending on no internal package, intended
  for their own repositories — naming this one, its targets, and its gate.
- Because `check-architecture` skips `tools/`, a structure test in the tool asserts that
  its lock resolves nothing from the wheelhouse and that its source imports only the
  standard library, `jwt`, and `cryptography`.
- No per-file licence header, which has no precedent here: `license = "MIT"` in its
  `pyproject.toml` and a copy of the root `LICENSE` in its directory, so it lifts out
  carrying its licence.
- `ARCHITECTURE.md`'s statement that tooling projects are outside the architecture gains
  that a standalone component under `tools/` depends on no internal package, beside the
  principle in "Principles for `ARCHITECTURE.md`" below.

Why: generic infrastructure that is not specific to SCM does not belong in SCM, and
having to build it is a warning sign — weighed and overridden because no existing plugin
admits by a per-proxy grant. One language with the repository keeps its layout, lock,
and Python-version checks in force; the structure test and the CI gate (D5) cover what
`tools/` is otherwise exempt from.

Rejected: adopting `frp_jwt_allowed_ports` (it appears to read client-wide metadata, its
claims differ, its maintenance and licence are unverified, and it is Go); forking it (a
Go toolchain the repository lacks, for code largely rewritten); writing it in Go (a
second toolchain); placing it in a compute-family package with the grant as an SCM
contract (backwards: the plugin owns its specification); classifying it in
`ARCHITECTURE.toml` (tooling is outside the architecture by design).

### D5. Tests run real frp

**Version.** The tool pins frp 0.61.1 for both `frps` and `frpc`, the frpc version hosts
already run, in one TOML pins file holding each archive's URL and SHA-256 for
`linux_amd64`. The README names the version. The pins file's format is published, since
consumers may read it; it gains entries and does not change shape. Other platforms use
`FRPS_BIN` and `FRPC_BIN`, or the real-frp tests skip.

**Binaries.** A fetch step downloads the official release archive, verifies it against
the SHA-256 pinned in the tool — never against the release's own checksums file, which
proves nothing about an archive from the same place — and extracts into an ignored
cache.

**Where they run.** The tool's `make test` runs the vector-driven unit tests and
in-process endpoint tests and skips the real-frp tests without binaries, so it passes
offline. The tool's `make test-frp` fetches the binaries and runs the real-frp tests,
failing on a skip or on no tests. The root's `test-frp-grant-admission` joins `make test`
and the `tests.yml` matrix, and a separate `tests.yml` job runs the gate — in `tests.yml`
because it is the workflow validation may dispatch, so the plan can owe the job to
validation.

**Cases against real frp.** A valid grant admitted, and carrying traffic through the
remote port to a local listener, since registration and traffic are different proofs;
refused: no grant, a forged signature, the wrong port, the wrong audience, an expired
grant, a port outside its issuer's range, and one issuer's grant for another issuer's
range; and:

- a non-`tcp` proxy refused;
- a grant only in client-wide metadata refused;
- frps refusing the proxy while the plugin is stopped, answers 500, or answers a
  malformed body, and frpc's own retry admitting it once the plugin answers again,
  without restarting frpc;
- a registered proxy surviving a reload that removes its key, and refused once frpc is
  restarted;
- an frpc reload adding a second proxy causing exactly one `NewProxy` decision, counted
  from the plugin's decision log.

Every verdict and reason is proven exhaustively by the vector at unit level.

**Test rules.** No sleeps: proxy state is read from frpc's admin `/api/status` with a
bounded wait; the recovery wait is sized to frpc's retry interval, with a comment saying
why it is that long. Every port — frps's bind port, the plugin's, `allowPorts`, the
issuer range, and the remote ports — is chosen at runtime on 127.0.0.1.

Why: the property worth proving is frps's behaviour with the plugin, not the plugin's
answer alone; D9 and D3 rest on frps failing closed, frpc retrying, and frps never
rechecking, which only real frp shows.

Rejected: testing frps 0.54.0 (a value copied into `frp-setup`; no relay runs the plugin
yet, and `relay-server` installs frps afresh); a matrix of both frps versions (keeps an
old frps supported for no deployment); unofficial frp container images or a source
build (Docker or a Go toolchain); fetching in the default suite (breaks offline review
validation).

### D6. Login admission and revocation are out of scope

The plugin handles `NewProxy` only. On a shared relay every token holder can still log
in and open connections — a way to exhaust the relay, not to reach anyone's resources.

### D7. The test vector, and what a signer's conformance is

The vector is one JSON file with the test key, a configuration, verification cases, and
signing cases:

- **Verification cases**: a time, a proxy type and remote port, a token, and the verdict
  with its reason code. The plugin's own tests replay every one.
- **Signing cases**: a key, a header, claims, and the exact token. A conforming signer
  serializes header and claims as RFC 8785 (JCS) and encodes them as unpadded base64url,
  and must reproduce each token byte for byte — Ed25519 being deterministic. Verifiers
  accept any valid serialization; canonical form is required of signers only.
- **A thumbprint case**: a public key and its id.

The key is RFC 8032 §7.1's TEST 1 key, labelled in the file and the README as a
deterministic test value never to be used on any network.

Why: every caller — the plugin's tests, SCM's signer test (which cannot import the
plugin), other sites' signers, and SCM after the tool moves out (vendoring the vector by
content hash, as `kit/arkhai-payments/schema/SOURCE.md` does) — checks conformance
through the vector alone, with a one-line comparison that is strict exactly where the
plugin is. JCS has precedent in the repository.

Rejected: verdict cases only (a signer can check itself only by running the plugin);
signing cases checked by decoding (every signer's test re-implements the checks, and a
lenient decoder passes what the plugin refuses).

### D8. PyJWT verifies, behind the standard library's HTTP server

The plugin serves frps with `http.server.ThreadingHTTPServer` on loopback, with a body
cap, a socket timeout, and `POST /` only. Grants are verified with PyJWT over
`cryptography`. `requires-python >= 3.11`, so the plain program runs on a stock relay's
Python; the image uses the repository's declared Python.

Why: a library's JWS parsing is trusted over hand-written parsing. One route on loopback
needs no web framework, and the tool stays liftable with two runtime dependencies.

Rejected: JWS verification written over `cryptography` (sixty lines of our own parsing);
joserfc or Authlib (heavier, the same mismatch with our rules); uvicorn with Starlette or
FastAPI (several dependencies for one loopback route); aiohttp (async for a synchronous,
quick check).

### D9. Configuration reloads on SIGHUP, validated before it is swapped

SIGHUP re-reads the file through the same loader as startup. A valid file replaces the
configuration in one reference assignment, requests in flight finishing under the one
they started with; an invalid one leaves the old configuration in place and logs every
problem. A restart refuses to start on an invalid file. `frp-grant-admission check
<file>` validates a file without touching a running plugin and prints each issuer with
its range and its keys' thumbprints, so an operator can match a pasted key to a signer's
key id and to log lines.

Why: frps fails closed when the plugin cannot answer, and frpc retries a refused proxy,
so any reload loses nothing already registered; validate-then-swap means a typo in one
site's onboarding leaves admission as it was rather than refusing every site's
registrations on a shared relay.

Rejected: restart only (an invalid edit refuses every registration on the relay until
fixed); watching the file (a valid save in the middle of an edit takes effect, such as a
key removed before its replacement is pasted, against D3's drain rule; and a watcher's
own care with renames and symlink swaps).

### D10. Refusals explain themselves, and every decision is logged

A refusal returns a stable reason code with a short text, which frps passes to frpc, so
a host operator diagnoses without the relay's log. The plugin writes one JSON line on
stderr per decision — admission or refusal — and per configuration load or reload:

```json
{"ts":"2026-11-01T12:00:00Z","event":"admit","proxy":"host-1.guest-17","type":"tcp","remote_port":6101,"issuer":"vm-site","kid":"kPrK_qmx…","sub":"host-1","jti":"lease-0001","exp":1798761600,"verified":true}
{"ts":"2026-11-01T12:00:05Z","event":"refuse","reason":"signature_invalid","proxy":"x.y","type":"tcp","remote_port":6150,"kid":"kPrK_qmx…","sub":"host-9","jti":"lease-0042","verified":false}
```

`verified` says whether the claims passed the signature and checks; on a forged or
malformed token they are attacker-chosen or absent, and JSON encoding keeps them from
forging lines. The grant itself is never logged: a valid grant is a bearer credential for
its port until it expires. The plugin handles `NewProxy` only.

Why: diagnosing from the host is what makes a relay shared across operators workable,
and the reasons reveal nothing that grants anything (key ids are public thumbprints;
ranges are not secret and probing them grants nothing). Admissions are rare and are the
audit record of which subject held which port under which key.

Rejected: a generic refusal to the client (every refusal needs the relay operator's
log); logging refusals only (no record of who was admitted); handling `CloseProxy` (frps
already logs closes by proxy name, and a stateless plugin could not attach the grant to
one).

### D11. The tool ships as a plain program and an image

The tool builds a wheel; its README documents the plain-program install with an example
systemd unit (`ExecReload=/bin/kill -HUP $MAINPID`, hardened as frps's unit is). The
image follows the repository's convention: `tools/frp-grant-admission/Dockerfile`, a uv
builder and a slim runtime for `linux/amd64` running as a non-root user, built by the
root target `build-frp-grant-admission` as `arkhai:frp-grant-admission$(IMAGE_SUFFIX)`,
included in `make build` and `make push-images`, with the tool's version as an OCI label
and `frp-grant-admission serve --config <path>` as its entrypoint. The tool keeps its own
semantic version, separate from SCM's packages and from the specification's version.
Publishing the wheel, and a public image, belong with the move to its own repository.

Why: the wheel comes free of a Python project; the image is what a relay hosted in
containers needs; a relay on a VPS runs frps under systemd and can run the plugin beside
it without a container runtime. Which one `relay-server` installs is
`prove-relay-provisioning`'s choice.

Rejected: the image only (a container runtime and registry access on a VPS relay for one
small process); the plain program only (a containerised relay builds its own image).

### D12. The admission rule, in full

In order, refusing at the first failure:

1. The body is valid JSON, at most 64 KiB, read within a 5-second socket timeout, and
   `op` is `NewProxy` (`malformed_request`, `operation_not_supported`).
2. `proxy_type` is exactly `tcp` (`proxy_type_not_allowed`).
3. `group` is absent or empty (`group_not_allowed`), so frps's one proxy per port holds.
4. `remote_port` is an integer from 1 to 65535 (`port_invalid`); port 0, which asks frps
   to choose, is refused.
5. The grant is `content.metas.grant`, at most 4 KiB (`grant_missing`,
   `grant_malformed`); `content.user.metas` is never read.
6. The unverified header's `kid` names a configured key (`key_unknown`).
7. `jwt.decode_complete` with `algorithms=["EdDSA"]`, the issuer's audience,
   `options={"require": ["exp", "aud", "port"], "strict_aud": True}`, and a 60-second
   leeway (`signature_invalid`, `claim_missing`, `audience_mismatch`, `grant_expired`,
   `grant_not_yet_valid`, `grant_malformed`).
8. The header's `typ` is `frp-grant+jwt` and it carries no `crit`
   (`grant_type_unsupported`, `grant_malformed`).
9. `port` is a JSON integer, not a boolean, equal to `remote_port` (`port_mismatch`), and
   inside the issuer's range (`port_outside_range`).

An admission answers `{"reject": false, "unchange": true}`: the plugin never rewrites a
proxy. A refusal answers HTTP 200 with `reject: true` and the reason. Where PyJWT has a
behaviour the rule adopts it unless it is less safe: padded segments are accepted (signers
still never pad), `nbf` and `iat` are validated as PyJWT does, and `strict_aud` makes
`aud` one string. Each rule has a vector case.

Why: the checks PyJWT cannot know — `typ`, the thumbprint lookup, the port — are the
plugin's; the rest is the library's, as D8 chose. Refusing groups and port 0 keeps one
grant to one port.

Rejected: refusing padding and `aud` lists ourselves (checks around the library chosen
for not writing them; `strict_aud` covers the list, and padding is harmless); allowing
groups (a group lets a second proxy share a granted port).

### D13. The configuration is TOML; keys are SPKI DER in base64

```toml
listen = "127.0.0.1:7300"

[[issuers]]
name = "vm-site"
audience = "relay-1"
ports = { start = 6100, end = 6199 }
keys = [
  { public_key = "MCowBQYDK2VwAyEA11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=" },
]

[[issuers]]
name = "bm-site"
audience = "relay-1"
ports = { start = 6200, end = 6249 }
keys = [ { public_key = "MCowBQYDK2VwAyEA…" } ]
```

The key shown is RFC 8032's TEST 1 public key, an example only. Each key is the
single-line standard base64 of its DER SubjectPublicKeyInfo, as `openssl pkey -pubout
-outform DER | base64` writes it. frps is configured with `[[httpPlugins]]` naming the
plugin's address, `path = "/"`, and `ops = ["NewProxy"]`.

Why: `tomllib` adds no dependency, it is the format of the `frps.toml` beside it, and its
types are strict. The key encoding is self-describing (it carries Ed25519's OID) and
fits on one line.

Rejected: YAML (PyYAML for familiarity alone); PEM (multi-line in a key list); the bare
32-byte JWK `x` (not self-describing).

### D14. Capability `frp-grant-admission`, and how its documents divide

The capability is named `frp-grant-admission`, after the tool: the tool is SCM-agnostic
and named for frp, while "relay" is SCM's word, and one name makes the later move carry
or remove one capability.

- The tool's README is the published specification and travels with it: the grant, its
  type and compatibility rule, thumbprint ids, JCS signing, the configuration format,
  reload and `check`, the reason codes, the vector's and the pins file's formats, the
  supported frp version, and D3's operating rules.
- `openspec/specs/frp-grant-admission/spec.md` holds the normative requirements with
  scenarios and cites the README for byte-level formats.
- `openspec/specs/frp-grant-admission/architecture.md` holds why: per-proxy grants, no
  state, the SCM-agnostic placement, the issuer model, thumbprint ids, explicit typing,
  reload by signal, and the limits — no login admission, no revocation, the drain rule.
- `openspec/specs/README.md` gains its row.

### D15. Implementation cadence

One round of two sessions, then one implementation review before closeout:

- **Session 1 — the plugin, proven in-process**: the configuration loader with its load
  refusals, thumbprints, and `check`; grant verification through PyJWT; the reason codes;
  the vector and the unit tests it drives; the HTTP endpoint and request handling;
  decision logging; SIGHUP reload; the README specification.
- **Session 2 — real frp, CI, and shipping**: the pins file and fetch; the real-frp tests;
  the tool's and the root's make targets; the `tests.yml` matrix entry and gate job; the
  wheel, Dockerfile, build and push targets, and systemd example; the `tools/` README, the
  structure test, and the licence.

The real-frp gate lands against a complete plugin. If a premise about frp it tests —
frps failing closed, frpc retrying a refused proxy, a refusal reason reaching frpc, a
reload leaving unchanged proxies registered — is false, the change returns to design
rather than being worked around.

## Notes for `prove-relay-provisioning`

This design changes what that change's signer and roles conform to. To be sent once this
design is settled:

1. D16's grant header carries `typ: "frp-grant+jwt"`.
2. D17's key id is the key's RFC 7638 JWK thumbprint.
3. D17's read returns each public key as single-line base64 of its DER
   SubjectPublicKeyInfo, with its thumbprint.
4. The runbook's shared-relay steps say: narrow a range, or remove a key or an issuer,
   only after the grants it would refuse have ended; and an issuing service's window lies
   within its assigned range.
5. `relay-server` installs frp 0.61.1, the version the plugin is tested against.
6. `relay-client` and `relay-server` verify a pinned SHA-256 of the archive they
   download, preferably taking version and checksum from the plugin's pins file (SCM
   reading the tool is the permitted direction), until the tool moves out and then from
   its release's metadata; at minimum, the runbook names the version.
7. On a VPS relay, the plugin's plain program under systemd matches frps and needs no
   container runtime.

## Principles for `ARCHITECTURE.md`

Stated in this design and recorded in no permanent document; promoted at closeout:

- Generic infrastructure that is not specific to SCM does not belong in SCM; having to
  build it is a warning sign, overridden only when no existing software fits. A
  standalone component publishes its interface — specification, test vector, pins — and
  SCM conforms to it and may check its own copies against it, the consumer reading the
  producer; the component never reads SCM. → `docs/development/ARCHITECTURE.md`, beside
  the tooling statement D4 amends.
- Registration and traffic are different proofs: a test that a connection was admitted
  also carries traffic through it. → `docs/development/TESTING.md`.

## Risks and trade-offs

- **The frp premises are tested, not assumed.** D9 and D10 rest on frp behaviour the
  real-frp gate proves; a failure there returns the change to design.
- **The drain rule rests on operators.** The plugin cannot know its previous
  configuration, so narrowing early drops a buyer at their client's next reconnect.
- **A relay without the plugin admits any proxy**, and nothing in this tool can tell;
  installing and checking it is `prove-relay-provisioning`'s.

## Open Questions

Deferred beyond this change:

- **Admission at login on a shared relay.** Revisit when the first site Arkhai does not
  control joins an Arkhai relay; likely a per-site credential signed by the site's key in
  client-wide metadata and checked on `Login`, so removing an issuer refuses its hosts'
  next logins.
