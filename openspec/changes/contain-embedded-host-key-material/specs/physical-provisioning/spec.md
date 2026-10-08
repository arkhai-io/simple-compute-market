## ADDED Requirements

### Requirement: Decrypted host key material does not outlive its operation

A host registered with embedded key material stores that material encrypted, and the provisioner MUST decrypt it to a file for the duration of an operation because the execution tool authenticates with a key file. That file MUST NOT survive the operation.

Every path that writes decrypted key material MUST remove it, including paths that fail. A failed authentication is the case most likely to leave material behind and the case most likely to be retried, so cleanup MUST NOT depend on an operation succeeding.

Decrypted material and the inventory naming it MUST be written into a location owned by the operation that created it, so that removal is a single action that cannot omit a file and cannot remove another operation's material. Concurrent operations against one host MUST NOT share or remove each other's key files.

#### Scenario: An operation against an embedded host succeeds

- **WHEN** a connectivity check or job completes against a host holding embedded key material
- **THEN** the decrypted key file existed for the operation and no decrypted key material remains afterwards

#### Scenario: An operation against an embedded host fails

- **WHEN** the operation raises before completing
- **THEN** no decrypted key material remains afterwards

#### Scenario: Two operations run against one host

- **WHEN** two operations against the same embedded host overlap
- **THEN** neither reads nor removes the other's key material

#### Scenario: A host is registered with a key path

- **WHEN** an operation runs against a host registered with a key path rather than embedded material
- **THEN** the rendered inventory names that path and no key material is written

### Requirement: Rendered inventories name a usable key location

Every rendered inventory MUST name a key location that an execution tool can authenticate with, or MUST state that it cannot represent the host. An inventory naming a placeholder that no component resolves MUST NOT be produced, because it fails authentication against a host that is reachable and resembles a network fault rather than a malformed inventory.

Where two components render inventories for the same registry rows, neither may rely on the other to substitute a value it did not write.

#### Scenario: An inventory is rendered for an embedded host

- **WHEN** an inventory is produced for a host holding embedded key material
- **THEN** it either names a key file that exists for the consumer's use, or the request is refused with the reason stated

#### Scenario: An inventory is rendered for a key-path host

- **WHEN** an inventory is produced for a host registered with a key path
- **THEN** it names that path and is usable by any consumer without further substitution
