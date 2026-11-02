# frp-grant-admission Specification

## Purpose

Define the frps server plugin under `tools/frp-grant-admission/` that admits a proxy only for the remote port a signed grant names: the admission rule, failing closed, the issuer configuration and its reload, the decision log, the grant specification and conformance vector the plugin publishes, and its proof against pinned real frp. Byte-level formats are the tool's [README](../../../tools/frp-grant-admission/README.md); rationale and limits are the [architecture companion](architecture.md).

## Requirements

### Requirement: A proxy is admitted only for its granted port

The plugin MUST admit a `NewProxy` only when the proxy's type is `tcp`, it names no load-balancer group, its remote port is from 1 to 65535, and its own metadata (`content.metas.grant`, never `content.user.metas`) carries a grant of type `frp-grant+jwt`, signed with EdDSA by a configured key, whose audience is that key's issuer's, whose `port` equals the remote port and lies in that issuer's range, and which has not expired. Time checks MUST use the relay's clock with no leeway: a grant MUST be refused as expired from the moment the clock reaches its `exp`, and as not yet valid while its `nbf` or `iat` is later than the clock. A grant's `exp`, `nbf`, and `iat` MUST be JSON integers, and its `sub` and `jti`, when present, MUST be strings; a grant whose header carries `crit` MUST be refused as `grant_malformed`, and one whose header `typ` is not `frp-grant+jwt` as `grant_type_unsupported`, whether or not its signature verifies. The plugin MUST decide these header, time, and claim-type rules itself rather than through a verification library. It MUST refuse every other request.

#### Scenario: A valid grant is presented

- **WHEN** a client registers a `tcp` proxy whose grant is signed by a configured key for that proxy's remote port, within the key's issuer's range and unexpired
- **THEN** the plugin admits the proxy without changing it, and traffic reaches the client through the remote port

#### Scenario: A proxy carries no grant of its own

- **WHEN** a client registers a proxy with no grant in its own metadata, including when a grant is present only in the client-wide metadata
- **THEN** the plugin refuses the registration as `grant_missing`

#### Scenario: A grant names another port

- **WHEN** a grant's port differs from the requested remote port
- **THEN** the plugin refuses the registration as `port_mismatch`

#### Scenario: A grant lies outside its issuer's range

- **WHEN** a correctly signed grant names a port outside its issuer's configured range
- **THEN** the plugin refuses the registration as `port_outside_range`, including when the port lies inside another issuer's range

#### Scenario: A grant has expired, is forged, or names another audience

- **WHEN** a grant's expiry has passed, its signature does not verify under the key its `kid` names, or its audience is not its issuer's
- **THEN** the plugin refuses the registration as `grant_expired`, `signature_invalid`, or `audience_mismatch`

#### Scenario: A grant is presented at its expiry

- **WHEN** a grant is presented one second before its `exp`, and again when the relay's clock equals its `exp`
- **THEN** the plugin admits the first and refuses the second as `grant_expired`

#### Scenario: A grant is not yet valid

- **WHEN** a grant's `iat` or `nbf` is one second later than the relay's clock
- **THEN** the plugin refuses the registration as `grant_not_yet_valid`

#### Scenario: A grant's claim has the wrong type

- **WHEN** a correctly signed grant's `exp` is a string, its `jti` is an integer, or its `sub` is an object
- **THEN** the plugin refuses the registration as `grant_malformed`

#### Scenario: A forged grant carries a critical header

- **WHEN** a grant whose header carries `crit` is presented, its signature not verifying
- **THEN** the plugin refuses the registration as `grant_malformed`

#### Scenario: A proxy is not a plain tcp proxy

- **WHEN** a client registers a proxy whose type is not `tcp`, that names a load-balancer group, or whose remote port is 0
- **THEN** the plugin refuses the registration as `proxy_type_not_allowed`, `group_not_allowed`, or `port_invalid`

### Requirement: Admission fails closed

A relay running the plugin MUST refuse a proxy registration whenever the plugin does not answer with an admission, and a refused proxy MUST be admitted on its client's own retry once the plugin admits it, without restarting the client.

#### Scenario: The plugin cannot answer

- **WHEN** a client registers a proxy while the plugin is stopped, answers an HTTP error, or answers a malformed body
- **THEN** frps refuses the registration

#### Scenario: The plugin answers again

- **WHEN** the plugin admits again after refusing for any of those reasons
- **THEN** the same client's proxy is admitted on its retry, the client having not been restarted

### Requirement: Issuers bind keys to an audience and a port range

The plugin's configuration MUST group public keys under named issuers, each with one audience and one port range, and MUST derive each key's identifier as its RFC 7638 JWK thumbprint. Loading MUST refuse a key listed twice, two issuers with the same name, ranges of two issuers that overlap, an issuer with no keys, and a range outside 1 to 65535 or ending before it starts.

#### Scenario: Two issuers' ranges overlap

- **WHEN** a configuration gives two issuers overlapping port ranges
- **THEN** the plugin refuses to load it, naming both issuers

#### Scenario: A key rotates within its issuer

- **WHEN** an issuer lists two keys and a grant signed by either is presented for a port in the issuer's range
- **THEN** the plugin admits it

#### Scenario: A grant names its key by thumbprint

- **WHEN** a grant's `kid` is the JWK thumbprint of a configured key
- **THEN** the plugin verifies the grant under that key and its issuer's audience and range

### Requirement: The plugin holds no state and calls nothing

The plugin MUST decide each registration from the request and its configuration alone, MUST hold no state across requests, MUST make no outbound call, MUST listen only on the loopback address its configuration names, and MUST handle `NewProxy` only, refusing any other operation.

#### Scenario: The issuing service is unreachable

- **WHEN** the service that signed a grant cannot be reached from the relay
- **THEN** the plugin decides the registration exactly as it would otherwise

#### Scenario: A registered proxy is not rechecked

- **WHEN** a reload removes the key a registered proxy's grant was signed with
- **THEN** that proxy keeps running, and is refused only when its client registers it again

### Requirement: Configuration reloads only when valid

On SIGHUP the plugin MUST re-read its configuration, replace the running configuration only when the new one loads, and otherwise keep the running configuration and log every problem; at startup it MUST refuse to start on a configuration that does not load. A configuration whose listen address is not an IPv4 address in `127.0.0.0/8` or the IPv6 address `::1`, a hostname included, MUST NOT load. The listen address MUST be bound only at startup: a reload that changes it MUST apply the rest of the configuration and log that the new address takes effect at restart. A `check` command MUST validate a configuration without affecting a running plugin and print each issuer with its range and its keys' identifiers.

#### Scenario: A configuration names a non-loopback listen address

- **WHEN** a configuration's listen address is `0.0.0.0`, a public address, or `localhost`, at startup, on SIGHUP, or under `check`
- **THEN** it does not load: the plugin refuses to start, keeps the running configuration, or `check` reports the problem

#### Scenario: A valid configuration is reloaded

- **WHEN** an issuer is added to the configuration and the plugin receives SIGHUP
- **THEN** the plugin admits that issuer's grants without a restart

#### Scenario: An invalid configuration is reloaded

- **WHEN** the configuration is edited into one that does not load and the plugin receives SIGHUP
- **THEN** the plugin keeps admitting under the configuration it was running and logs every problem found

### Requirement: Every decision is explained and logged

The plugin MUST answer every refusal with a stable reason code and a short text, which reaches the client, and MUST write one JSON log line per admission and per refusal, naming the proxy, its type and remote port, the grant's key identifier, subject, and grant identifier where present, and whether those claims were verified. It MUST never log a grant.

#### Scenario: A grant is refused

- **WHEN** the plugin refuses a registration
- **THEN** the client receives the reason code, and the plugin's log line carries the same reason

#### Scenario: A forged grant is refused

- **WHEN** a grant whose signature does not verify is presented
- **THEN** the log line marks its claims as not verified, and neither the line nor the reply contains the grant

#### Scenario: A client reload adds a proxy

- **WHEN** a client reloads its configuration to add one proxy beside a registered one
- **THEN** the plugin logs exactly one decision, for the new proxy

### Requirement: The plugin owns its grant specification

The plugin MUST publish the grant's claims and type, where a grant is carried, its signing serialization, its configuration format, its reason codes, the frp version it is tested against, and a test vector of a test key, verification cases with verdicts and reasons, and signing cases; its own tests MUST hold its verifier to that vector, at its locked dependencies and with each runtime dependency at the lowest release it declares. A grant type it does not implement MUST be refused, and claims it does not know MUST be ignored. Its specification MUST name no concept of any particular issuing system.

#### Scenario: A signer checks conformance

- **WHEN** a signer in another system serializes a signing case's header and claims as RFC 8785 JSON and signs them with the vector's key
- **THEN** it produces exactly the case's token

#### Scenario: A grant of another type is presented

- **WHEN** a correctly signed grant's type is `JWT` or absent
- **THEN** the plugin refuses it as `grant_type_unsupported`

#### Scenario: The vector runs at the declared floors

- **WHEN** the real-frp gate runs the plugin's unit tests with each runtime dependency at the lowest release the plugin declares
- **THEN** every verification case returns its verdict and reason, as it does at the locked release

### Requirement: The plugin is proven against pinned frp

The plugin's tests MUST run real `frps` and `frpc` at the version its pins file names, from archives verified against SHA-256 values pinned in the tool, through a gate that fails when those tests skip; its default suite MUST pass without network access.

#### Scenario: The gate runs without frp

- **WHEN** the real-frp gate runs and the frp tests skip or none run
- **THEN** the gate fails

#### Scenario: An archive does not match its pin

- **WHEN** a fetched frp archive's SHA-256 differs from the value the pins file records
- **THEN** the fetch fails and no binary is extracted
