# Design: A relay admission plugin for signed grants

## Context

Designed against `dev` at `6855f6de7`, and settled again at `2c4e080b8` after section 1
of implementation returned the change to design (D16–D23). This change was split out of
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

`aud`, `port`, and `exp` are required. `exp`, `nbf`, and `iat` are JSON integers (D18);
`sub` and `jti`, when present, are strings (D19). `sub` and `jti` identify the grant in
the plugin's log and never decide admission beyond being well-formed: a client's `user`
is whatever its configuration says.

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
validation. The gate also runs the unit tests with each runtime dependency at the lowest
release the tool declares (D23).

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
`cryptography`: PyJWT parses the token and checks its signature, `aud`, and required
claims; the header, time, and claim-type rules are the plugin's own (D18, D19, D22).
`PyJWT>=2.8.0`, the first release with `strict_aud` (D20). `requires-python >= 3.11`, so the plain program runs on a stock relay's
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
key id and to log lines. The `listen` address is bound once, at startup: a reload that
changes it applies the rest of the file and logs that the new address waits for a
restart.

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

The image runs the plugin as PID 1, so SIGHUP sent to the container reloads it without
restarting frps; the README has the configuration's directory mounted, never the file or
a Kubernetes `subPath`, since a single-file mount keeps the file it first saw (45 O2). The
plugin has no probe command (45 O3): the kubelet's TCP and HTTP probes cannot reach a
loopback listener, and a sidecar relies on its restart policy.

Why: the wheel comes free of a Python project; the image is what a relay hosted in
containers needs; a relay on a VPS runs frps under systemd and can run the plugin beside
it without a container runtime. Which one `relay-server` installs is
`prove-relay-provisioning`'s choice.

Rejected: the image only (a container runtime and registry access on a VPS relay for one
small process); the plain program only (a containerised relay builds its own image); a
`probe` command that connects to `listen` for an exec liveness probe (45 O3: the socket
lives exactly as long as the process and the kernel completes a handshake from the
backlog, so it detects nothing the restart policy misses); a `probe` command that sends
an HTTP request and accepts any answer (45 O3: it would detect a hung accept loop, but no
one can describe such a hang, and it adds a command to the interface).

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
7. The unverified header's `typ` is `frp-grant+jwt` (`grant_type_unsupported`) and it
   carries no `crit` (`grant_malformed`) (D22).
8. `jwt.decode_complete` with `algorithms=["EdDSA"]`, the issuer's audience, and
   `options={"require": ["exp", "aud", "port"], "strict_aud": True, "verify_exp":
   False, "verify_nbf": False, "verify_iat": False, "verify_sub": False, "verify_jti":
   False}` (`signature_invalid`, `claim_missing`, `audience_mismatch`,
   `grant_malformed`).
9. `exp`, and `nbf` and `iat` when present, are JSON integers, not booleans
   (`grant_malformed`); on the injected clock a grant is expired from the second
   `now ≥ exp` (`grant_expired`), and not yet valid while an `nbf` or `iat` is later
   than `now` (`grant_not_yet_valid`), with no leeway (D18).
10. `sub` and `jti`, when present, are strings (`grant_malformed`) (D19).
11. `port` is a JSON integer, not a boolean, equal to `remote_port` (`port_mismatch`), and
    inside the issuer's range (`port_outside_range`).

An admission answers `{"reject": false, "unchange": true}`: the plugin never rewrites a
proxy. A refusal answers HTTP 200 with `reject: true` and the reason. PyJWT decides the
token's parsing, its signature, `aud`, and the presence of the required claims; padded
segments are accepted (signers still never pad), and `strict_aud` makes `aud` one string.
A header that is not canonical base64url of a JSON object is `grant_malformed` at step
5, since steps 6 and 7 cannot read it; an `alg` other than `EdDSA`, `none` included, is
`signature_invalid`, as PyJWT's refusal of an algorithm not allowed is mapped there.
Every rule whose PyJWT behaviour is known to differ between the releases the tool
declares — the time checks, the types of `sub` and `jti`, and `crit` — is the plugin's
own, so none of them decides a verdict through the library; the vector holds at the lock
and at the dependencies' floors (D23). Each rule has a vector case;
the expiry boundary has three — one second before `exp` admitted, exactly `exp` refused
as `grant_expired`, and an `iat` one second ahead refused as `grant_not_yet_valid`.

Why: the checks PyJWT cannot know — `typ`, the thumbprint lookup, the port — and the ones
whose behaviour it changes between releases are the plugin's; JWS parsing and the
signature are the library's, as D8 chose. Refusing groups and port 0 keeps one
grant to one port. No leeway (14 F1), because an issuer reuses a port once its grant's
`exp` has passed, and a leeway would let a copied grant claim the port again in the
window after; the expiry boundary is the one both contracts state, and the residual skew
between relay and signer clocks is the issuer's reuse rule to cover (note 8 for
`prove-relay-provisioning`). A signer whose clock runs ahead costs at most a refusal
that frpc's own retry clears.

Rejected: refusing padding and `aud` lists ourselves (checks around the library chosen
for not writing them; `strict_aud` covers the list, and padding is harmless); allowing
groups (a group lets a second proxy share a granted port); a 60-second leeway with every
issuer's quarantine lengthened by it (the plugin's tolerance becomes a published
constant every allocator must know, and a relay clock further behind reopens the
window); leeway on `nbf` and `iat` only (buying only what frpc's retry already gives).

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

`listen` is a loopback address and a port: an IPv4 address in `127.0.0.0/8`, or `::1`
written `[::1]:<port>`. Startup, reload, and `check` refuse any other address, a
hostname such as `localhost` included, so the check never depends on a resolver (14 F2).
The image runs in frps's network namespace — a sidecar in the same pod, Compose's
`network_mode: service:frps`, or host networking — as the README says wherever it
describes the image.

Why: `tomllib` adds no dependency, it is the format of the `frps.toml` beside it, and its
types are strict. The key encoding is self-describing (it carries Ed25519's OID) and
fits on one line. Loopback only keeps the plugin a local seam of frps, which D8's bare
server and D10's open refusal reasons assume: on a reachable port every decision could
be probed and each slow body would hold a thread for the socket timeout.

Rejected: YAML (PyYAML for familiarity alone); PEM (multi-line in a key list); the bare
32-byte JWK `x` (not self-describing); any listen address (a remote plugin needs its own
transport security and access control, which no caller asks for).

### D14. Capability `frp-grant-admission`, and how its documents divide

The capability is named `frp-grant-admission`, after the tool: the tool is SCM-agnostic
and named for frp, while "relay" is SCM's word, and one name makes the later move carry
or remove one capability. The change itself carries another name (D17), since no code
line may contain a change's name.

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
rather than being worked around. D21 restates this cadence after the return.

### D16. The change is renamed on `dev` first

The change's name moves to D17's through a pull request to `dev`, before the design
review, and `dev` is then merged into this change's branch and into
`prove-relay-provisioning`'s, so both branches name it the same way at once. The tool,
its distribution, console script, image, and capability keep `frp-grant-admission`.

The orchestrating session carries it out, once this design is committed and pushed
under the old name — a step's outcome is recorded through the change's directory, so no
step may be running across the rename:

1. A worktree on a new branch from `dev` renames `openspec/changes/frp-grant-admission/`
   and the three index cells naming the change — its row, the campaign graph line, and
   `prove-relay-provisioning`'s `Depends on` — and passes `make check-change-index`.
2. Once that pull request merges, `dev` is merged into `feat/frp-grant-admission` and
   into `prove-relay-provisioning`'s branch.
3. The change gets a clone of its new name, `make change-clone
   CHANGE=admit-relay-proxies-by-grant BRANCH=feat/frp-grant-admission`, since a clone's
   directory is derived from its change's name; the untracked `reviews/` is copied into
   it and checked identical with `diff -r`, and the old clone is retired by hand.
4. Orchestration resumes under the new name. Planning updates `tasks.md`'s commands that
   name the change.

The branch keeps its name: branch names are not scanned, and the clone's marker records a
non-default branch.

Why: `make check-comment-hygiene` refuses every code line containing any change's name,
archived ones included, and D11 and D14 make `frp-grant-admission` the tool's public
name. The change's name is the workflow's bookkeeping. Renaming on `dev` first keeps
`prove-relay-provisioning`'s branch consistent with this one rather than carrying the
old name until this change lands.

Rejected: renaming on this branch alone (`prove-relay-provisioning`'s branch keeps the
old name until this change merges); also renaming the branch (a new remote branch and
the old one deleted, for no functional gain); narrowing the hygiene check to exempt a
change named after a capability or a `tools/` project it creates (a repository-policy
edit outside this change, weakening the rule for exactly such names); renaming the tool
(gives up D14's one name).

### D17. The change is named `admit-relay-proxies-by-grant`

A verb phrase for what the change does, as change names here are. No planned code line
contains it; it is no substring of the tool's names (`frp-grant-admission`,
`test-frp-grant-admission`, `build-frp-grant-admission`), and it does not contain
`archive`. "Relay" is SCM's word, which suits the workflow's bookkeeping, where D14 kept
it out of the SCM-agnostic tool's name.

Rejected: `build-frp-proxy-admission-plugin` (says less of the behaviour, and its prefix
reads as a make target); `gate-relay-ports-by-signed-grant`.

### D18. The time checks are the plugin's, against an injected clock

PyJWT's `verify_exp`, `verify_nbf`, and `verify_iat` are off. The plugin requires `exp`,
and `nbf` and `iat` when present, to be JSON integers and not booleans
(`grant_malformed`), and compares them against the clock it is given: expired from the
second `now ≥ exp`, not yet valid while `nbf` or `iat` is later than `now`, with no
leeway. The clock is a parameter of the grant check; the server passes the system clock.
The vector gains cases of time claims of the wrong type.

Why: PyJWT takes no clock — every release from 2.8.0 to 2.15.1 reads `datetime.now()`
inside `_validate_claims` — so the vector's exact-time cases could not be replayed
without overriding private methods or patching time. Its time semantics have also moved
between releases (2.6.0 changed `exp < now` to `exp <= now`), and it reads each time
claim through `int()`, admitting a string or truncating a float. The expiry boundary is
the rule this design tightened on purpose (D12, 14 F1); it is exact and stable only as
the plugin's own few comparisons. PyJWT keeps what D8 chose it for.

Rejected: subclassing PyJWT to feed its private `_validate_exp`, `_validate_nbf`, and
`_validate_iat` the injected clock (rests on private methods, and makes PyJWT's loose
types the specification); freezing time in tests with a dev dependency (patches
`datetime` globally, leaves no clock seam in the check, and keeps the release-dependent
semantics).

### D19. `sub` and `jti` are strings when present

The plugin refuses a grant whose `sub` or `jti` is present and not a string, as
`grant_malformed`, by its own check; PyJWT's `verify_sub` and `verify_jti` are off. The
vector gains an integer-`jti` case and an object-`sub` case.

Why: PyJWT after 2.9.0 refuses non-string `sub` and `jti` by default and 2.8.0 and 2.9.0
do not, so inside the declared range a grant's verdict depended on the installed
release. RFC 7519 defines both as strings, so a signer on any JOSE library agrees with
the plugin, and the decision log's `sub` and `jti` are always strings when verified.

Rejected: accepting any JSON value and only logging it (admits what RFC 7519 forbids,
and the log's field types vary); adopting PyJWT's check by raising the floor (the rule
would move with PyJWT's releases).

### D20. The PyJWT floor is 2.8.0

`PyJWT>=2.8.0`, the first release with `strict_aud`, the one feature the plugin needs
beyond EdDSA verification. On 2.8.0 the `verify_sub` and `verify_jti` option keys are
harmless: options merge into a dictionary, and only known keys are read. After D18, the
release at which PyJWT first refuses a future `iat` no longer bears on the floor.

### D21. Implementation cadence after the return

D15 stands: one round of two sessions, then one implementation review. Session 1
re-checks section 1's work after the rename and the merge of `dev`, then delivers grant
verification with the plugin's own header, time, and claim-type checks (D18, D19, D22),
the vector, the server, and the README. Session 2 delivers real frp, CI with D23's
floor run over both runtime dependencies, and shipping. The rename (D16) is the orchestrating session's work before the
design review, not an implementation round.

### D22. `typ` and `crit` are checked from the unverified header, before PyJWT

The plugin refuses a `typ` other than `frp-grant+jwt` (`grant_type_unsupported`) and any
`crit` (`grant_malformed`) from the unverified header, beside the `kid` lookup and before
`jwt.decode_complete` (D12 step 7). The vector gains a forged grant carrying `crit`,
refused as `grant_malformed`.

Why: PyJWT 2.15.1 validates `crit` while parsing, before the signature, and honours
`crit: ["b64"]` (RFC 7797); 2.8.0 ignores `crit`. Checked after decoding, a forged grant
with `crit` was refused as `grant_malformed` on one release and `signature_invalid` on
the other. Every check must pass, so checking the header first changes only which
refusal is reported, and a header grants nothing.

Rejected: keeping the order and mapping PyJWT's `crit` error to `grant_malformed` (the
reason still depends on the release).

### D23. The vector is proven at the lock and at every runtime dependency's floor

The tool's `make test-floor` runs the unit tests, the vector included, with each runtime
dependency — PyJWT and `cryptography` — resolved at the lowest release the tool declares,
as uv's `lowest-direct` resolution does; the real-frp gate job runs it beside `make
test-frp`, since it needs the network. The default suite runs on the lock and stays
offline.

What this proves, and what the specification promises, is two tested points: the floor
and the lock. The declared range has no upper end, and PyJWT still decides parsing, the
signature, `aud`, and the required claims, so no test proves a verdict for a release in
between or above the lock; a later release is proven when the lock moves to it, since
the vector runs on every lock. The specification therefore promises the structure — the
header, time, and claim-type rules are the plugin's own, not a library's — and the
vector at both tested points, not identical verdicts on every release the wheel permits
(27 F2).

Why: the wheel installs any release from the floors up, and the release-dependent
behaviours D18, D19, and D22 remove were found by hand. Running the published vector at
the floors catches the next one there; `cryptography` performs the Ed25519 verification
and is floored with PyJWT at no extra cost.

Rejected: pinning exactly or narrowly (burdens installing the wheel beside other
software); relying on the vector at each relock (proves only the locked release); an
explicit tested set of every PyJWT minor release (a middle release is installed only
when another package constrains PyJWT, and the list needs a hand edit each release);
bounding the range with an upper limit (still untested across the range, and an upper
bound burdens installation and needs a bump at every major release); promising identical
verdicts on every declared release (no test can hold it, 27 F2).

## Notes for `prove-relay-provisioning`

This design changes what that change's signer and roles conform to. To be sent once this
design is settled. The decision numbers in these notes (D16, D17) are that change's own,
not this design's D16 and D17:

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
8. The plugin verifies expiry with no leeway: on the relay's clock a grant is refused
   from the second `now ≥ exp`. D16's reuse rule waits until `grant_expires_at` plus a
   clock-skew margin that change chooses, and states that the relay's and the signer's
   clocks are kept synchronised; a relay clock behind the signer's otherwise lets a
   copied grant claim a reissued port for the difference.

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

## Implementation record

What implementation settled within the decisions above, what it declined, and what it
left unproven. Moved here from `tasks.md`'s notes at closeout, which keep only final
behaviour, evidence, and destinations.

### Choices within the design

- **Configuration.** An unknown field at any level is refused, so a file written for a
  later format (D3's "a later list of ranges") fails to load rather than loading with
  part of it ignored. A key must be canonical: strict base64 that re-encodes to the same
  DER, so trailing bytes are refused. `listen` is parsed with `ipaddress` alone, which
  also refuses `127.1` and `[::ffff:127.0.0.1]`. A valid range is checked for overlap
  whatever its issuer's other fields, so fixing one problem never reveals another.
- **Grant check.** The unverified header is read by the plugin, padded or unpadded, and
  must be canonical base64url of a JSON object, else `grant_malformed` before the `kid`
  lookup (recorded in D12). PyJWT's `InvalidSignatureError` and `InvalidAlgorithmError`
  map to `signature_invalid` (so `alg: none` is), `MissingRequiredClaimError` to
  `claim_missing`, `InvalidAudienceError` to `audience_mismatch`, and any other PyJWT
  error to `grant_malformed`. A grant holding an unpaired surrogate is `grant_malformed`,
  and so is a `RecursionError` escaping PyJWT's parser on deep nesting — a defence with
  no test, since whether 4 KiB of nesting overflows depends on the Python version.
  "Never reads the system clock" holds for the plugin's own code: PyJWT reads
  `datetime.now()` while decoding, but every time check it would make with it is off.
- **`decode_complete`.** D12 step 8 and D22 write `jwt.decode_complete`; PyJWT 2.8.0, the
  declared floor, exports no module-level `decode_complete`, which the floor run found
  (45 unit failures at the floor). The plugin calls the same function, with the same
  options, on one `jwt.PyJWT()` instance, which every declared release carries; no
  decision changed. The permanent documents say PyJWT's `decode_complete`.
- **Request handling.** The request checks are a pure module, `request.py`, so they are
  unit-tested from a request dict and the log names a decision without importing the
  server. The handler answers `POST` to `/` with any query (frps appends
  `?version=…&op=NewProxy`); another path is 404 and another method the standard
  library's 501. A body with no or a bad `Content-Length` is `malformed_request`; at most
  64 KiB + 1 bytes are read whatever the declared length. A non-string `metas.grant` is
  `grant_malformed`, an empty one `grant_missing`. Binding skips the standard library's
  host-name lookup, so it makes no resolver call, and `::1` binds IPv6.
- **Decision log.** `verified` is on every decision line (false when no grant was read).
  A forged grant's line carries `issuer` and the unverified `exp`, which D10's example
  line omits; the README states the fields. Lines are strict ASCII JSON under a reentrant
  lock, so a SIGHUP landing during a write cannot deadlock; a non-finite number is logged
  as text and a field nested too deeply for a recursion to walk as a placeholder, so no
  decision loses its line. The configuration lines (`config_loaded`, `config_refused`,
  `listen_at_restart`, `kept`) are implementation's shape, stated in the README.
- **Reload.** The handler is installed only after binding and the startup line; a SIGHUP
  before then ends the process by its default action, which frps meets as a plugin that
  does not answer. Any exception in a reload keeps the running configuration.
- **Vector.** It carries RFC 8032's TEST 1, 2, and 3 keys; forged cases are signed with
  TEST 2 naming TEST 1's `kid`. The issuers are `issuer-a` and `issuer-b`, as in the
  README and the example, since D13's `vm-site` and `bm-site` name one issuing system's
  concepts. The builder serializes the JCS subset the vector uses and refuses anything
  else; a signing case with non-ASCII and control characters, held to RFC 8785's string
  example, keeps a signer that escapes non-ASCII from passing (41 F1).
- **Real-frp tests.** The default suite never fetches and never reads the gate's cache:
  only `FRPS_BIN` and `FRPC_BIN` give it binaries, so `make test` stays offline and fast
  on a machine where the gate has cached frp. Both binaries must report, by
  `--version`, the release the pins file names, so the gate cannot pass on an unpinned
  frp, and the gate prints the binaries' provenance — the verified archive's SHA-256, or
  the overrides, unverified (42 observation). The pin was taken from the archive GitHub
  served and cross-checked once, with the owner's grant, against the release's published
  checksums file; the tests never read that file.
- **Floor run.** `make test-floor` builds `.floor/.venv` (named `.venv` so the
  repository's scans skip it), installs the project's requirements with uv's
  `lowest-direct` resolution, and fails unless the installed versions equal the declared
  floors; `uv run --resolution` would relock `uv.lock`, so it is not used.
- **Shipping.** The systemd unit adds `DynamicUser=yes` beyond frps's hardening, since
  the plugin needs no privilege. The image runs as uid 10001, takes its version label
  from a build argument with no default (so the version is written only in
  `pyproject.toml`), uses `ENTRYPOINT ["frp-grant-admission"]` with a `serve` command
  arguments replace, and stops on SIGINT, since PID 1 ignores a SIGTERM it has no handler
  for. Adding the image to `make build` also added it to validation's image inventory
  (`scripts/change_namespace.py`) and taught the aggregate-target test that a bare build
  writes a commit tag. The README mounts the configuration's directory, never the file or
  a `subPath`, and says the plugin is PID 1 (45 O1, O2).

### Declined

- A vector case for the 4 KiB cap (D12's "each rule has a vector case"): its cases are
  over 4,000 characters of filler each, and a signer's conformance gains nothing from
  them; the cap is proven in `test_grant.py`. Adding them later is a builder edit and a
  regeneration.
- A per-body deadline: the 5-second socket timeout bounds each wait on the socket, as D12
  says, so a body trickled faster than that holds a thread longer. A deadline would be a
  design change.
- Refusing `FRPS_BIN` and `FRPC_BIN` under the gate: D5 makes them how another platform
  runs it, and the version check and printed provenance cover the risk.
- An `ARG VERSION` default (it would repeat `pyproject.toml`'s version), and reading the
  image's licence label from the project (another build argument for a value that does
  not change).
- A way to find the plugin's process under `shareProcessNamespace`, and naming the
  overrides' paths in the provenance line.

### Left unproven

- `serve`, SIGHUP through `docker kill`, and SIGINT as the stop signal were not run in
  the image; `check` was. The systemd unit was not run under systemd.
- PyJWT 2.15.1 may map an empty `aud` to `claim_missing` where 2.8.0 says
  `audience_mismatch`; no vector case holds it, and the floor run passing shows no case
  the vector has differs.
- 5.7's count of decisions after an frpc reload is a strong negative taken once the new
  proxy's decision is logged, not one a bounded test can make airtight.

### Closeout judgements

- **The word "relay" in the README.** The README keeps "relay" for the frps server it
  guards, as the delta spec and the reason texts do. D14 kept "relay" out of the tool's
  *name* as this repository's word; the README's rule is that it names no concept of an
  issuing system, and the relay is frp's server, not the issuer. Section 4 left this to
  the owner or a review; no review raised it, and closeout judged it compliant.
- **A test helper's `site_b` keyword.** `tests/integration/test_server.py` names its
  second-issuer switch `site_b`, a market word D4 keeps out of the tool. It is a test's
  local name, not an interface, and no review raised it; closeout, which edits no code,
  records it for whichever change next touches those tests.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The admission rule (D1, D2, D6, D12, D18, D19, D22), fail-closed admission, issuers and thumbprints (D3, D3a), no state and loopback only (D8, D13), validated reload (D9), the decision log (D10), the specification and vector at the lock and floors (D7, D23), the real-frp proof (D5) | `openspec/specs/frp-grant-admission/spec.md`, written by the archive from the delta |
| Why per-proxy grants, no state, loopback only, the issuer model and drain rule, thumbprint ids, explicit typing as the major version, no leeway and the port reuse it protects, where PyJWT ends, reload by validated SIGHUP, the real-frp proof, placement and shipping, and the limits (D1–D14, D18, D23) | `openspec/specs/frp-grant-admission/architecture.md` |
| The grant, signing, configuration, reason codes, log, vector and pins formats, supported frp version, installation, and operating rules (D2, D3, D3a, D5, D7, D9–D13) | `tools/frp-grant-admission/README.md` (sections 4, 5, 7) |
| `tools/` holds standalone infrastructure components, their targets and gate (D4, D5) | `tools/README.md#standalone-infrastructure-components` |
| A standalone component depends on no internal package; generic infrastructure does not belong in a market package, and a component publishes its interface for market code to conform to (D4, "Principles for `ARCHITECTURE.md`") | `docs/development/ARCHITECTURE.md#kind` |
| Registration and traffic are different proofs; real-process tests as a gated integration flavour (D5, "Principles for `ARCHITECTURE.md`") | `docs/development/TESTING.md#2-integration-tests` |
| The capability's index row (D14) | `openspec/specs/README.md#capabilities` |
| The plugin owns every rule it publishes, inheriting none that changes with a library's release (D18, D19, D22) | Not promoted, by the owner's direction: stays in this design's rationale for D18, D19, and D22 |
| Roadmap | No change: the plugin admits nothing until a relay runs it; no `ROADMAP.md` gap names this change |
| Campaign index | `openspec/changes/README.md`: this change's row set to `in closeout`, notes rewritten, and linked to its archive directory; the campaign graph line unchanged |
| D15, D16, D17, D20, D21 (cadence, the rename and the change's name, the PyJWT floor's reason) | Change history only: the floor is in `pyproject.toml`, and the rest is workflow bookkeeping |
| Notes for `prove-relay-provisioning` | That change's to adopt; they stay here |

## Open Questions

Deferred beyond this change:

- **Admission at login on a shared relay.** Revisit when the first site Arkhai does not
  control joins an Arkhai relay; likely a per-site credential signed by the site's key in
  client-wide metadata and checked on `Login`, so removing an issuer refuses its hosts'
  next logins.
- **A liveness probe for the sidecar** (45 O3). Revisit, as a `probe` command that sends
  an HTTP request and accepts any answer, if a deployment sees the plugin go quiet without
  exiting, or a cluster requires liveness probes.
