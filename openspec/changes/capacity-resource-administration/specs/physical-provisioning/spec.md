## ADDED Requirements

### Requirement: Host inventory is executor identity

Host inventory records MUST describe how to reach and dispatch work to a machine —
addressing, credentials, executor alias, pool membership, and enabled state — and
MUST NOT be the authoritative source of a Physical Resource's sellable capacity.
Capacity projection MUST read declared capacity resources rather than host inventory
columns.

#### Scenario: Host record carries a legacy capacity column

- **WHEN** a host record still holds a capacity value from before capacity
  declarations existed
- **THEN** capacity projection does not read it and the projected capacity comes from
  the declared capacity resource for that Physical Resource

#### Scenario: Host inventory is inspected for capacity authority

- **WHEN** the projection path is traced from host inventory to published capacity
- **THEN** no capacity dimension reaches the projection from a host inventory record

### Requirement: Legacy host capacity is derived into declarations

A compute provisioner MUST populate a capacity declaration for every host inventory
record that carries legacy capacity data and has no declaration of its own, so a
deployment configured only through host inventory retains its published capacity.
Derivation MUST NOT overwrite or merge into an existing declaration, and an
operator-supplied declaration MUST win over any derivable legacy value.

#### Scenario: Deployment configured only through host inventory

- **WHEN** a provisioner starts with host inventory carrying legacy capacity data and
  no capacity declarations configured
- **THEN** a declaration is derived for each such host and published capacity is
  unchanged from before declarations existed

#### Scenario: Operator declaration and legacy host value disagree

- **WHEN** a host carries a legacy capacity value and an operator has declared
  different capacity for the same Physical Resource
- **THEN** the operator's declaration is retained unchanged and no derivation occurs
  for that resource

### Requirement: Capacity definitions import at startup

A compute provisioner MUST import a configured capacity-definitions document before
serving requests, applying it as an idempotent difference against current
declarations on every startup rather than only when no declarations exist. A
configured document that cannot be read MUST fail startup rather than be skipped
silently, and the import MUST run after resource-pool definitions so a declaration
can reference an existing pool.

#### Scenario: Capacity definitions change between restarts

- **WHEN** an operator edits the configured capacity-definitions document and
  restarts the provisioner
- **THEN** the edited declarations are applied, rather than being ignored because
  declarations already existed

#### Scenario: Configured document is missing

- **WHEN** a capacity-definitions path is configured but no document exists there
- **THEN** startup fails rather than proceeding with stale or absent declarations

#### Scenario: No capacity definitions are configured

- **WHEN** no capacity-definitions path is configured
- **THEN** startup proceeds and declarations come only from derivation and the
  administration surface

#### Scenario: Declaration names a resource pool

- **WHEN** a capacity declaration references a resource pool defined in the
  pool-definitions document
- **THEN** the pool exists by the time the capacity import runs
