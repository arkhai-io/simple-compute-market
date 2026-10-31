## ADDED Requirements

### Requirement: A relay proxy is admitted only for its granted port

The relay admission plugin MUST admit a proxy registration only when the proxy's type is `tcp`, its own `metadatas.grant` is a JWT signed with EdDSA by a configured issuer whose key identifier matches the grant's `kid`, the grant's audience equals that issuer's configured audience, its `port` equals the requested remote port and lies inside that issuer's configured range, and its expiry has not passed. It MUST refuse every other registration, a malformed request included, and MUST log each refusal's reason with the grant's subject, grant identifier, and key identifier, never anything secret.

#### Scenario: A valid grant is presented

- **WHEN** a client registers a `tcp` proxy whose grant is signed by a configured issuer for that proxy's remote port, within the issuer's range and unexpired
- **THEN** the relay admits the proxy

#### Scenario: A proxy carries no grant

- **WHEN** a client registers a proxy without a grant
- **THEN** the relay refuses the registration and the plugin logs why

#### Scenario: A grant names another port

- **WHEN** a grant's port differs from the requested remote port
- **THEN** the registration is refused

#### Scenario: A grant lies outside its issuer's range

- **WHEN** a correctly signed grant names a port outside its issuer's configured range
- **THEN** the registration is refused, including when the port lies inside another issuer's range

#### Scenario: A grant has expired or is forged

- **WHEN** a grant's expiry has passed, or its signature does not verify under its issuer's key
- **THEN** the registration is refused

### Requirement: The plugin holds no state and calls nothing

The plugin MUST decide each registration from the request and its configuration alone, MUST hold no state across requests, MUST make no outbound call, and MUST listen only on the address its configuration names.

#### Scenario: The issuing service is unreachable

- **WHEN** the service that signed a grant cannot be reached from the relay
- **THEN** the plugin decides the registration exactly as it would otherwise

### Requirement: The plugin owns its grant specification

The plugin MUST publish the grant's claims, where a grant is carried, its configuration format, and a test vector of keys, grants, and expected verdicts, and its own tests MUST hold its verifier to that vector. Its specification and configuration MUST name no concept of any particular issuing system.

#### Scenario: A signer checks conformance

- **WHEN** a signer in another system signs the vector's claims with the vector's key
- **THEN** the plugin's published verdict for that grant is the verdict the plugin returns
