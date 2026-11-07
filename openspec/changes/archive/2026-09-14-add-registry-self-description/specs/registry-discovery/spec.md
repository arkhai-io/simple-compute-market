## ADDED Requirements

### Requirement: Registry self-description is authority-authenticated

A registry MUST publish one strict descriptor containing its public base URL, display name, operator identity, stable authority name and active principal set, listing schema identity and version, and access posture. The descriptor MUST be returned at `/.well-known/arkhai/registry-descriptor.json` through the shared version 2 authenticated request and signed-response contract.

The authority principal MUST come from the active registry signer, the schema identity MUST come from the active filter specification, and the access posture MUST come from the active read gate. Operator-authored public fields MUST remain ordinary configuration, and signer credentials or read keys MUST NOT enter the descriptor.

A bootstrap client MUST verify the signed response against the principal set carried in the validated descriptor before returning it.

#### Scenario: Client inspects a public registry

- **WHEN** an authenticated buyer, seller, or service requests the well-known descriptor
- **THEN** the registry returns the complete descriptor under a response proof from the principal pinned in that descriptor

#### Scenario: Registry reads require a key

- **WHEN** the registry requires a read key
- **THEN** the descriptor remains readable without that key and declares `key-gated` posture with an acquisition pointer

#### Scenario: Descriptor configuration contradicts access policy

- **WHEN** a key-gated registry has no acquisition pointer or a public registry configures one
- **THEN** startup fails before the registry serves a contradictory descriptor

#### Scenario: Descriptor is used as a trust bootstrap

- **WHEN** a client verifies the signed response against the principal carried in the descriptor
- **THEN** the proof establishes credential possession but does not by itself establish third-party endorsement of the operator or URL
