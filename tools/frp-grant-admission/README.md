# frp-grant-admission

An [frp](https://github.com/fatedier/frp) server plugin that admits a proxy only for
the remote port a signed grant names.

frps asks the plugin about every proxy a client registers (`NewProxy`). The plugin
admits the proxy only when the proxy's own metadata carries a grant signed by an
issuer the relay trusts, for exactly the remote port the proxy requests, inside that
issuer's port range, and not yet expired. Whoever allocates ports signs the grants;
the relay needs no account, list, or edit per client, and the allocator stays the
only authority over which port belongs to whom.

This README is the plugin's specification: the grant, how it is signed and carried,
the configuration, the refusal reasons, the log, and the test vector a signer checks
itself against. It is version **1.0** of the `frp-grant` specification. Within
`frp-grant 1.x`, a change never makes a conforming verifier refuse a grant an earlier
1.x version admitted, or admit one it refused.

## Installing

The plugin runs beside frps, on the same host or in the same network namespace, since
it listens on loopback only. It ships two ways; either serves a relay.

### As a program under systemd

`make build` writes the plugin's wheel to `dist/`. Install it into an environment of its
own with Python 3.11 or later, write the configuration — starting from
[`examples/config.toml`](examples/config.toml), with each issuer's own public keys in
place of its test keys — and run it under
[`examples/frp-grant-admission.service`](examples/frp-grant-admission.service), beside
frps's own unit. From this directory:

```sh
python3 -m venv /opt/frp-grant-admission
/opt/frp-grant-admission/bin/pip install dist/frp_grant_admission-*.whl
install -d /etc/frp-grant-admission
install -m 0644 config.toml /etc/frp-grant-admission/config.toml   # your configuration
/opt/frp-grant-admission/bin/frp-grant-admission check /etc/frp-grant-admission/config.toml
install -m 0644 examples/frp-grant-admission.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now frp-grant-admission
```

The unit runs the plugin as a user systemd allocates, so the configuration must be
readable by any user; it holds only public keys. `systemctl reload frp-grant-admission`
sends SIGHUP; the decision log is the unit's journal.

### As a container image

The [`Dockerfile`](Dockerfile) builds from this directory alone, labelled with the
plugin's version:

```sh
docker build --build-arg VERSION=<version in pyproject.toml> -t <image> .
```

The image runs `frp-grant-admission serve --config
/etc/frp-grant-admission/config.toml` as an unprivileged user, as the container's PID 1
with no shell in front of it, so a signal sent to the container reaches the plugin:
SIGHUP changes keys and ranges without restarting the frps beside it. Run it in frps's
network namespace, so that frps reaches it on loopback: as a sidecar in frps's pod, with
Compose's `network_mode: service:frps`, or with host networking.

Mount the directory holding `config.toml` at `/etc/frp-grant-admission`, read-only —
never the file alone, and never with a Kubernetes `subPath`. A single-file mount keeps
the file it first saw: once the file is replaced rather than rewritten in place, as many
editors and `sed -i` do, a reload still reads the old configuration, and its
`config_loaded` line lists the old keys. A `subPath` mount never receives a ConfigMap's
updates at all.

```sh
docker run -d --name frp-grant-admission --network container:frps \
  -v /etc/frp-grant-admission:/etc/frp-grant-admission:ro \
  <image>
docker kill -s HUP frp-grant-admission    # reload the configuration
```

As a sidecar in Kubernetes, put the configuration in a ConfigMap under the key
`config.toml`, mount the ConfigMap as a volume at `/etc/frp-grant-admission`, and reload
with `kubectl exec <pod> -c <container> -- sh -c 'kill -HUP 1'`. The kubelet updates a
mounted ConfigMap only after its sync delay, which can be a minute or more, so signal
once the mounted file shows the change, and confirm it by the keys in the
`config_loaded` line. In a pod with `shareProcessNamespace: true`, PID 1 is the pod's
pause process, not the plugin, so signal the plugin's own process instead. The kubelet's
TCP and HTTP probes cannot reach a loopback listener, and the plugin has no probe
command: a sidecar relies on its restart policy, and frps refuses every new proxy while
the plugin is down.

The image's arguments replace `serve` and its configuration path, so `docker run --rm
<image> check <path>` checks a file mounted at `<path>`. The image also carries the
example configuration, at `/app/examples/config.toml`. Its stop signal is SIGINT, on
which the plugin exits at once.

## What the plugin does and does not do

It does:

- decide `NewProxy` only, from the request and its configuration alone;
- admit plain `tcp` proxies with one explicit remote port, in no load-balancer group;
- explain every refusal to the client, and log every decision;
- reload its configuration on SIGHUP, keeping the running one when the new file does
  not load.

It does not:

- admit or refuse a client's login (`Login`): every holder of frps's token can still
  log in and open connections;
- revoke a grant: a grant is valid until its `exp`;
- recheck a registered proxy: frps asks once, when the proxy registers — at creation
  and again after every client reconnect — and never again while it runs;
- hold any state across requests, or call anything: it never contacts the issuer.

## The grant

A grant is a JWT signed with EdDSA over Ed25519 ([RFC 8037](https://www.rfc-editor.org/rfc/rfc8037)):

```text
header  {"alg": "EdDSA", "kid": "<key id>", "typ": "frp-grant+jwt"}
claims  {"aud": "<audience>", "port": <remote port>, "exp": <expiry>,
         "nbf": <not before>, "iat": <issued at>, "sub": "<subject>", "jti": "<grant id>"}
```

| Member | Required | Type | Meaning |
|---|---|---|---|
| `alg` | yes | string | `EdDSA`; any other value is refused |
| `kid` | yes | string | the signing key's id: its JWK thumbprint (below) |
| `typ` | yes | string | `frp-grant+jwt`: the grant's type and the specification's major version |
| `crit` | — | — | must be absent; a header carrying it is refused |
| `aud` | yes | string | the audience of the key's issuer; a list is refused |
| `port` | yes | integer | the one remote port the grant admits |
| `exp` | yes | integer | Unix seconds; the grant is refused from this second on |
| `nbf` | no | integer | Unix seconds; the grant is refused before this second |
| `iat` | no | integer | Unix seconds; the grant is refused before this second |
| `sub` | no | string | who the grant is for, logged and never otherwise read |
| `jti` | no | string | the grant's id, logged and never otherwise read |

"Integer" is a JSON integer: a string, a float, or `true` is refused. Any claim not in
the table is ignored, so an optional claim can be added compatibly.

A grant is at most 4096 bytes. It must stay valid for as long as its proxy runs,
because frps asks again after every reconnect; choose `exp` as the end of whatever
the port was granted for.

### Where a grant is carried

In the proxy's own metadata — `metadatas.grant` in frpc's configuration:

```toml
[[proxies]]
name = "example-ssh"
type = "tcp"
localIP = "127.0.0.1"
localPort = 22
remotePort = 6101
metadatas.grant = "eyJhbGciOiJFZERTQSIsImtpZCI6..."
```

frps sends it to the plugin as `content.metas.grant` in the `NewProxy` request. The
client-wide metadata (frpc's top-level `metadatas`, sent at login as
`content.user.metas`) is never read: it reaches frps only at login, so a grant there
could not change without ending every proxy the client carries. A proxy's own
metadata changes with an frpc reload, which registers only the proxies it changed.

### Types and versions

`typ` is the grant's major version. A verifier admits only the types it implements
and refuses every other, an absent `typ` and `JWT` included, so a token minted for
another purpose is never read as a grant ([RFC 8725](https://www.rfc-editor.org/rfc/rfc8725)
§3.11). A change that would make a conforming verifier refuse what this version
admits, or admit what it refuses, takes a new type, `frp-grant.v2+jwt`; a plugin
knowing both admits both while independent signers migrate one at a time.

`typ` and `crit` are checked from the header before the signature is verified.
Every check must pass, so the order changes only which refusal is reported.

### Key ids

A key's id is its [RFC 7638](https://www.rfc-editor.org/rfc/rfc7638) JWK thumbprint:
the unpadded base64url SHA-256 of `{"crv":"Ed25519","kty":"OKP","x":"<base64url raw
public key>"}`. The relay's configuration lists only public keys and derives each id
itself, so ids are unique across independent signers without anyone assigning them.
`frp-grant-admission check <file>` prints each configured key's id.

### Signing

A conforming signer serializes the header and the claims as
[RFC 8785](https://www.rfc-editor.org/rfc/rfc8785) (JCS) JSON, encodes each as
unpadded base64url, and signs `<header>.<claims>` with Ed25519. Ed25519 is
deterministic, so a signer reproduces each signing case of the vector byte for byte.
Canonical form is required of signers only: the plugin accepts any valid
serialization, padded segments included.

### Time

`exp`, `nbf`, and `iat` are compared with the relay's clock in whole seconds, with no
leeway: a grant is expired from the second the clock reaches `exp`, and not yet valid
while `nbf` or `iat` is later than the clock. A grant presented one second before its
`exp` is admitted; at `exp` it is refused.

No leeway is allowed because an allocator gives a port to someone else once its grant
has expired, and a leeway would let a copy of the old grant claim the port again in
the window after. Keep the relay's and the signers' clocks synchronized; an allocator
reissuing a port should wait past `exp` by more than the clocks can differ. A signer
whose clock runs ahead costs at most a refusal (`grant_not_yet_valid`) that frpc's own
retry clears.

## Admission

A `NewProxy` is admitted only when every check passes, in this order; the first that
fails is the refusal:

1. the body is at most 64 KiB, its next bytes never take longer than a 5-second socket
   timeout to arrive, and it is a JSON object whose `op` is `NewProxy` and whose
   `content` is an object;
2. `proxy_type` is exactly `tcp`;
3. `group` is absent or empty, so one proxy holds one port;
4. `remote_port` is an integer from 1 to 65535 (port 0, which asks frps to choose, is
   refused);
5. `content.metas.grant` holds a grant of at most 4096 bytes whose header is base64url
   of a JSON object;
6. the header's `kid` names a configured key;
7. the header's `typ` is `frp-grant+jwt`, and it carries no `crit`;
8. the signature verifies under that key with `alg` `EdDSA`, `aud` is the key's
   issuer's audience as one string, and `aud`, `exp`, and `port` are present;
9. `exp`, `nbf`, and `iat` are integers, the grant has not expired, and it is valid
   now;
10. `sub` and `jti`, when present, are strings;
11. `port` is an integer equal to `remote_port`, inside the key's issuer's range.

An admission answers frps `{"reject": false, "unchange": true}`: the plugin never
rewrites a proxy. A refusal answers HTTP 200 with
`{"reject": true, "reject_reason": "<code>: <text>"}`, which frps passes to frpc, so
the client's operator sees why in frpc's log and admin status.

frps refuses a proxy whenever the plugin does not answer with an admission — when it
is stopped, answers an HTTP error, or answers something frps cannot read — and frpc
retries a refused proxy on its own, so it is admitted once the plugin admits it,
without restarting frpc. frpc 0.61.1 retries 30 seconds after a refusal. The plugin
relies on these behaviours of frp, and its tests run each of them against the frp
release [below](#the-frp-it-is-tested-against).

### Reason codes

The codes are stable: a code never changes meaning. The texts may be reworded.

| Code | Refused because |
|---|---|
| `malformed_request` | the request is not a well-formed frps plugin request: over 64 KiB, not fully sent, not a JSON object, or without a string `op` or an object `content` |
| `operation_not_supported` | the operation is not `NewProxy` |
| `proxy_type_not_allowed` | the proxy is not `tcp` |
| `group_not_allowed` | the proxy names a load-balancer group |
| `port_invalid` | the remote port is not an integer from 1 to 65535 |
| `grant_missing` | the proxy's own metadata carries no grant |
| `grant_malformed` | the grant is not a string, is over 4096 bytes, is not a well-formed JWT, carries `crit`, or has an `exp`, `nbf`, `iat`, `sub`, or `jti` of the wrong type |
| `grant_type_unsupported` | the grant's `typ` is not `frp-grant+jwt` |
| `key_unknown` | the grant's `kid` names no configured key |
| `signature_invalid` | the signature does not verify under the key `kid` names, or `alg` is not `EdDSA` |
| `claim_missing` | `aud`, `exp`, or `port` is missing or `null` |
| `audience_mismatch` | `aud` is not the issuer's audience, or is a list |
| `grant_expired` | the relay's clock has reached `exp` |
| `grant_not_yet_valid` | `nbf` or `iat` is later than the relay's clock |
| `port_mismatch` | `port` is not an integer equal to the proxy's remote port |
| `port_outside_range` | `port` lies outside the key's issuer's range |

## Configuration

The configuration is one TOML file:

```toml
listen = "127.0.0.1:7300"

[[issuers]]
name = "issuer-a"
audience = "relay-1"
ports = { start = 6100, end = 6199 }
keys = [
  { public_key = "MCowBQYDK2VwAyEA11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=" },
]

[[issuers]]
name = "issuer-b"
audience = "relay-1"
ports = { start = 6200, end = 6249 }
keys = [
  { public_key = "MCowBQYDK2VwAyEAPUAXw+hDiVqStwqnTRt+vJyYLM8uxJaMwM1V8Sr0Zgw=" },
]
```

The keys shown are [RFC 8032](https://www.rfc-editor.org/rfc/rfc8032) §7.1's TEST 1
and TEST 2 public keys: published, deterministic test values whose private keys
anyone can read. Never use them on any network. The same file is
[`examples/config.toml`](examples/config.toml).

- `listen` is the address the plugin serves on: an IPv4 address in `127.0.0.0/8` or
  `[::1]`, then `:` and a port from 1 to 65535. Any other address is refused,
  `localhost` included, so the check never depends on a resolver. The plugin is a local
  seam of frps and must not be reachable from anywhere else.
- Each issuer is a signer of grants: `name` appears only in logs and errors, never in a
  grant; `audience` is the `aud` its grants carry; `ports` is its one inclusive range;
  `keys` lists one or more Ed25519 public keys, each the single-line standard base64 of
  its DER SubjectPublicKeyInfo, as `openssl pkey -in key.pem -pubout -outform DER |
  base64` prints it.
- A file does not load if it lists a key twice, names two issuers alike, gives two
  issuers overlapping ranges, gives an issuer no keys, has a range outside 1–65535 or
  ending before it starts, has a key that is not Ed25519, or has a missing, mistyped, or
  unknown field. Every problem in the file is reported at once.

Rotating a key is adding the new key to its issuer, then removing the old one once no
grant it signed is still in use.

frps calls the plugin through an `[[httpPlugins]]` entry in `frps.toml`:

```toml
[[httpPlugins]]
name = "grant-admission"
addr = "127.0.0.1:7300"
path = "/"
ops = ["NewProxy"]
```

### Reloading and checking

- `frp-grant-admission serve --config <file>` serves frps. It refuses to start,
  exiting non-zero, when the file does not load.
- On SIGHUP the plugin re-reads the file. A file that loads replaces the running
  configuration at once; requests already being decided finish under the one they
  started with. A file that does not load leaves the running configuration in place,
  and every problem is logged. `listen` is bound once, at startup: a reload changing it
  applies the rest of the file, and the new address takes effect at the next restart.
- `frp-grant-admission check <file>` loads a file exactly as startup and reload do,
  without touching a running plugin, and prints each issuer with its range and its
  keys' ids, or every problem and a non-zero exit.

### Operating rules

The plugin holds no state and cannot know its previous configuration, so these are
the operator's to keep:

- **Drain before refusing what was admitted.** A registered proxy is not rechecked
  until it registers again, so a change that would refuse a grant already admitted —
  narrowing a range, removing a key or an issuer, changing an audience — waits until
  every affected grant has ended. Otherwise the proxy keeps running until its client
  reconnects, and is then refused. Widening a range and adding a key or an issuer are
  safe at any time.
- **A signer grants only within its range.** A grant for a port outside its issuer's
  range is refused, and that refusal is the intended way a misconfigured signer fails.
- **Ranges lie within frps's `allowPorts`.** frps refuses a port outside it whatever
  the plugin answers, and the plugin does not read frps's configuration.

## The log

The plugin writes one JSON line to stderr per decision and per configuration load. A
grant is never written — a valid grant admits its port until it expires — nor is any of
the request's metadata.

```json
{"ts":"2027-01-01T00:00:00Z","event":"admit","proxy":"example-ssh","type":"tcp","remote_port":6101,"issuer":"issuer-a","kid":"kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k","sub":"host-1","jti":"grant-0001","exp":1798765200,"verified":true}
{"ts":"2027-01-01T00:00:05Z","event":"refuse","reason":"signature_invalid","proxy":"x","type":"tcp","remote_port":6150,"issuer":"issuer-a","kid":"kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k","sub":"host-9","jti":"grant-0042","exp":1798765200,"verified":false}
```

| Field | On | Value |
|---|---|---|
| `ts` | every line | UTC time of the decision or load |
| `event` | every line | `admit`, `refuse`, `config_loaded`, or `config_refused` |
| `reason` | `refuse` | the reason code |
| `proxy`, `type`, `remote_port` | decisions on a `NewProxy` with a `content` object, where it sent them | the proxy's name, type, and remote port |
| `issuer` | decisions, where the grant's `kid` names a configured key | the issuer's name |
| `kid`, `sub`, `jti`, `exp` | decisions, where the grant could be read and carries them | as the grant carries them |
| `verified` | decisions | whether the grant's signature, audience, required claims, and claim types passed, so that the logged claims are the issuer's — true too for a grant then refused for its time or its port |
| `trigger` | loads | `startup` or `reload` |
| `listen`, `issuers` | `config_loaded` | the address served, and each issuer's `name`, `audience`, `ports` (`start`, `end`), and `keys` (ids) |
| `listen_at_restart` | `config_loaded` on reload | a changed `listen` read from the file, which waits for a restart |
| `problems`, `kept` | `config_refused` | every problem; on reload, that the running configuration was kept |

When `verified` is false, the logged claims are whatever the sender wrote. JSON
encoding keeps them from forging a line; a number JSON cannot carry is logged as text.

## The test vector

[`vector/frp-grant-1.json`](vector/frp-grant-1.json) is this specification's test
vector. It holds:

- `specification`: the version it tests, `frp-grant 1.0`;
- `warning`: that every key in it is a published test key;
- `keys`: RFC 8032's TEST 1, 2, and 3 keys, each with its `name`, its `seed` and raw
  `public_key` in hex, `public_key_spki_base64` as the configuration writes it, and its
  `kid`. They are published test keys: never use them on any network;
- `configuration`: a configuration of two issuers with adjacent ranges, as TOML text;
- `verification`: cases of a `name`, a `time` (Unix seconds), a `proxy_type`, a
  `remote_port`, a `token`, and the expected `verdict` (`admit` or `refuse`) with its
  `reason` code (`null` on admission), each decided under `configuration`;
- `signing`: cases of a `name`, a `key` (the `name` of an entry in `keys`), a `header`,
  `claims`, and the exact `token` a conforming signer writes;
- `thumbprint`: a public key and its `kid`.

The plugin's own tests replay every verification case at two tested points: the
dependencies its lock pins, and each runtime dependency, PyJWT and `cryptography`, at
the lowest release the plugin declares. The declared ranges have no upper bound, and
PyJWT still decides parsing, the signature, `aud`, and the required claims, so no test
proves a verdict for a release between the two or above the lock. What every release
shares is the structure: the header, time, and claim-type rules are the plugin's own,
not the library's.

A signer conforms when, for each signing case, serializing `header` and `claims` as
JCS, encoding them as unpadded base64url, and signing with the named key's seed
reproduces `token` exactly, and when it derives each key's `kid` as the vector does. A
verifier conforms when it returns each verification case's verdict and reason.

## The frp it is tested against

The plugin is tested against frp **0.61.1**: its tests run that release's `frps` and
`frpc` against the plugin. They show a grant admitted and traffic carried through the
remote port; refusals for a missing grant, a grant only in client-wide metadata, a
forged signature, another port, another audience, an expired grant, a port outside its
issuer's range, and a proxy that is not `tcp`, each reaching frpc with its reason;
frps refusing while the plugin is stopped, answers HTTP 500, or answers a body that is
not JSON, and frpc's own retry admitting once the plugin answers; a registered proxy
outliving a reload that removes its key, and refused when a restarted frpc registers it
again; and an frpc reload asking only about the proxy it added. Every reason code is
proven against the plugin itself by the vector and the plugin's own tests.

[`frp-pins.toml`](frp-pins.toml) names that release and, for each platform, the official
release archive and its SHA-256:

```toml
version = "0.61.1"

[archives.linux_amd64]
url = "https://github.com/fatedier/frp/releases/download/v0.61.1/frp_0.61.1_linux_amd64.tar.gz"
sha256 = "bff260b68ca7b1461182a46c4f34e9709ba32764eed30a15dd94ac97f50a2c40"
```

- `version` is the frp release, for `frps` and `frpc` both.
- Each `archives.<os>_<arch>` table is one platform, named as frp names its release
  archives, with `url`, the official archive, and `sha256`, its SHA-256 in lowercase
  hex, computed from a download of the archive.

The format gains platforms as further `archives` tables and changes shape in no other
way, so other software may read it, to install and verify the same frp. An archive is
checked against its pinned SHA-256 before anything is extracted from it; the checksums
file published beside a release is never read, since it comes from the same place as
the archive.
