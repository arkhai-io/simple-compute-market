## MODIFIED Requirements

### Requirement: A real-provisioning target is a typed, versioned settings section

The real-provisioning scenarios' target MUST be read from a versioned settings section
loaded from a profile file the repository ignores, beside a committed example whose
values are visibly fictitious. The section MUST be validated before any stage runs: a
missing or misspelled field MUST fail naming the field, an unknown version MUST be
refused, and a field that does not belong to a host's domain or access mode MUST be
refused. Version 2 describes a list of hosts, at most one per domain, each with its
domain, its identity, the connection the provisioning service reaches it at (address,
user, port, and the path at which the service reads its key), its access — a relay
named by its identifier, or direct access with a tenant address — and the capacity it
sells; a VM host also states the listing shape its scenario publishes, which MUST fit
twice within its capacity, and a bare-metal host its physical machine identity and its
SSH host public key. A relay named by a host is resolved in the provisioning service
that host's scenario runs against. The section MUST NOT carry the private key the
provisioning service reaches hosts with, nor any relay token or key.

A VM target MAY name its capacity declaration through `resource_id`. The real
VM deal, purchase, qualification and reapply scenarios MUST use that identifier
for registration, listing adoption and capacity checks. Omitted, it MUST retain
`compute-e2e-real-001`. Each real VM purchase MUST refresh its site projections
before discovery, including with background lifecycle loops held, so host
diagnostics do not age out its source confirmation. Before a real purchase
approves payment, its region query MUST select its intended listing alone; an
empty, different or ambiguous result MUST refuse the purchase. Selecting a declaration MUST NOT bypass the site's
single-declaration-per-host invariant.

A bare-metal target MAY name its existing pool and capacity declaration through
`pool_id` and `resource_id`. When stated, the real deal, purchase, cleanup
qualification and reapply scenarios MUST reconcile those identifiers. Omitted,
they MUST retain their default scenario identifiers. Selecting an existing
declaration MUST NOT bypass refusal of another declaration for the same host or
physical machine.

#### Scenario: Qualification adopts a registered bare-metal declaration

- **WHEN** the target names the pool and resource already declared for its machine
- **THEN** registration reconciles that resource rather than creating another
  declaration, and reapply reports the selected resource
- **AND** a different declaration for the same host or physical machine is refused

#### Scenario: A field is misspelled

- **WHEN** the target section names a field the model does not define, or omits one it
  requires
- **THEN** the scenario fails before its first stage, naming the field

#### Scenario: A newer target reaches an older reader

- **WHEN** the section's version is one the scenario does not know
- **THEN** the scenario refuses it rather than interpreting it

#### Scenario: Relay access is requested under version 1

- **WHEN** a section states version 1, whatever access mode it names
- **THEN** it is refused with a message naming the version 2 profile and how its fields
  map

#### Scenario: A listing shape does not fit twice

- **WHEN** a VM host's listing shape exceeds half its capacity on any dimension
- **THEN** the target is refused, naming the dimension

#### Scenario: Relay access names a tenant address

- **WHEN** a host under relay access states a tenant address, or one under direct access
  names a relay
- **THEN** the target is refused, naming the field

A VM target MAY state its management SSH public key. A VM scenario registering a
host MUST state that pin when supplied. Otherwise it MUST obtain a registered pin
before declaring capacity, preserving a stored pin or observing and explicitly
capturing the presented key. A reapply MUST restate the pin held at registration
and verify that the management pins are retained. A bare-metal scenario MUST
state the target's management SSH public key at registration.

#### Scenario: Provisioning registration is reapplied with an existing pin

- **WHEN** a real VM or bare-metal scenario reapplies its host registration
- **THEN** the registered management SSH keys match those from before the reapply
