## MODIFIED Requirements

### Requirement: The compute family shares one capability schema

The compute-family capability schema — the families `gpu`, `cpu`, `memory`, and `storage`,
their fields, and each field's flat name — MUST be owned by one compute-family domain package
that every compute domain binds. The VM and bare-metal domains MUST NOT each define a schema,
and neither MUST obtain the schema by importing the other. The package MUST depend only on
the standard library and the capability-shape foundation kit. The schema MUST require no
family: a shape names the families it describes, and a domain that needs a family states
that requirement in its own rules, as bare metal requires the GPU family for its listings.

#### Scenario: Two compute domains flatten one shape

- **WHEN** the VM and bare-metal domains each flatten `{gpu: {count: 8, model: H200}, memory: {gib: 2048}}`
- **THEN** both produce `gpu_count: 8`, `ram_gb: 2048`, and `gpu_model: H200` through the
  same schema object

#### Scenario: The bare-metal storefront binds the schema

- **WHEN** the bare-metal storefront's import boundary is checked
- **THEN** it imports the compute-family package and no VM package

#### Scenario: A shape without GPUs is flattened

- **WHEN** `{cpu: {count: 2}, memory: {gib: 2}, storage: {gib: 20}}` is flattened with the
  compute-family schema
- **THEN** the result's quantities are `vcpu_count: 2`, `ram_gb: 2`, and `disk_gb: 20`, and
  it carries no GPU field
