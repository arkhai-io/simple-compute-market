## ADDED Requirements

### Requirement: Provisioning time is configured and set on its system surface

The compute provisioning service MUST install its process time source from `time.source`, `"wall"` by default or `"injected"`. Under injected time it MUST serve `POST /api/v1/system/time` behind its administrator authentication, taking `{"now": <Unix seconds>}`, answering `{"source": "injected", "now": <Unix seconds>}` and refusing an earlier instant with `409 time_moves_forward` and an invalid body with `422 invalid_time`; its system status, `GET /api/v1/system/status`, MUST carry the time section. Its lease watchdog, lease termination and job engine MUST read the process time source for every instant they record or compare. The provisioning client MUST offer the setting call.

#### Scenario: A truncated lease ends at the set instant

- **WHEN** a lease truncated to 1794822300 is held by the paused lease watchdog, provisioning is set to 1794822300, and one watchdog cycle is stepped
- **THEN** the lease ends by expiry with effective instant and claimed deadline 1794822300

#### Scenario: A termination is stamped in lane time

- **WHEN** an injected provisioning service at 1794822300 terminates a lease
- **THEN** the lease-ended report states effective instant 1794822300

## MODIFIED Requirements

### Requirement: Each relay holds its own grant-signing key

Each relay MUST hold its own Ed25519 grant-signing private key, encrypted at rest under the deployment's configured encryption key. A relay definition entry MUST name the secrets-profile key holding it, read only when the relay is created; a relay created through the API with no key MUST be given one the service generates. A profile key's value MUST be the single-line standard base64 of an Ed25519 key's PKCS#8 DER, read after stripping surrounding whitespace; a value that is not MUST fail the import before any relay is created, naming the relay and the profile key and not disclosing the value. A key's identifier MUST be its RFC 7638 JWK thumbprint, the identifier the admission plugin derives from the public key. No read path MUST return a private key: relay reads MUST return the active key's identifier and public half, any staged key's, and each retired key's identifier with the time its grants remain valid until, each public half as the single-line base64 of its DER SubjectPublicKeyInfo, the form the plugin's configuration takes. Rotation MUST be two explicit operations: staging takes a private key supplied in the request, in the profile's form and under the same checks, or generates one when none is supplied, and returns its public half without signing with it; activating makes the staged key sign every later grant. A supplied private key MUST NOT appear in an access log, an error body, or the response. A retired key's grants MUST be reported valid until the latest grant expiry among the relay's unreleased leases allocated before, or in the same second as, the key's retirement, since a lease whose job was retried across a rotation may hold grants signed by more than one key, and whole-second times cannot tell a lease allocated just before the retirement from one just after it.

#### Scenario: A relay is read

- **WHEN** a relay is retrieved through the API
- **THEN** the response carries its active key's thumbprint and its public key as base64 SubjectPublicKeyInfo, and no private key material

#### Scenario: A key is staged

- **WHEN** an operator stages a new grant key for a relay
- **THEN** the service returns the new public key, and grants continue to be signed with the active key until the staged one is activated

#### Scenario: A job is retried across a rotation

- **WHEN** a job's attempt installs a grant signed with key A, key B is then activated, and a retry of the job signs its grant with B
- **THEN** the relay read reports A's grants valid until that lease is released or its grant expires, whichever is first

#### Scenario: A lease is allocated in the second its key is retired

- **WHEN** a lease is allocated in the same second as key A's retirement
- **THEN** the relay read reports A's grants valid at least until that lease's grant expiry while the lease is unreleased, and a lease allocated a second later does not extend it

#### Scenario: A definition entry names a malformed grant key

- **WHEN** the profile key a relay definition entry names holds a value that is not base64 PKCS#8 DER of an Ed25519 key, apart from surrounding whitespace
- **THEN** the import fails naming the relay and the profile key, without the value, and no relay is created

#### Scenario: A supplied key is staged

- **WHEN** an operator stages a private key supplied in the request
- **THEN** the response carries that key's public half and thumbprint, and neither the response, an error body, nor an access log carries the private key

#### Scenario: A definition entry names no grant key

- **WHEN** a relay definition entry names no grant-key profile key
- **THEN** the import fails naming the entry, and no relay is created without a key
