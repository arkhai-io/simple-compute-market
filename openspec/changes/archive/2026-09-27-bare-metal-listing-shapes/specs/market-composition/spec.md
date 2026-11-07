## ADDED Requirements

### Requirement: The compute family shares one capability schema

The compute-family capability schema — the families `gpu`, `cpu`, `memory`, and `storage`,
their fields, and each field's flat name — MUST be owned by one compute-family domain package
that every compute domain binds. The VM and bare-metal domains MUST NOT each define a schema,
and neither MUST obtain the schema by importing the other. The package MUST depend only on
the standard library and the capability-shape foundation kit.

#### Scenario: Two compute domains flatten one shape

- **WHEN** the VM and bare-metal domains each flatten `{gpu: {count: 8, model: H200}, memory: {gib: 2048}}`
- **THEN** both produce `gpu_count: 8`, `ram_gb: 2048`, and `gpu_model: H200` through the
  same schema object

#### Scenario: The bare-metal storefront binds the schema

- **WHEN** the bare-metal storefront's import boundary is checked
- **THEN** it imports the compute-family package and no VM package

## MODIFIED Requirements

### Requirement: Family-grouped capability shapes share one flattening contract

A capability shape MUST be expressed in the family-grouped form: a mapping of family name to
a mapping of field name to a scalar value. One shared utility in a foundation kit that imports
only the standard library MUST validate that form's structure, flatten a shape into
quantities and attributes, and compute a canonical digest of a shape. The utility is capacity
vocabulary rather than part of the market core, because only markets that admit capacity
against declared supply have shapes; the market core MUST NOT carry it.

- **Schema.** Flattening MUST be driven by a schema the owning domain supplies. For each
  family field the schema states whether it is a quantity or an attribute, whether it is
  required, and its flat name. The utility MUST NOT contain any domain's family or field
  names.
- **Digest.** The canonical digest MUST be taken over the family-grouped form, so changing a
  schema's flat names does not change a shape's digest.
- **Refusals.** A shape naming a family or field its schema does not define, missing a
  required field, or carrying a value of the wrong kind MUST be refused with the offending
  path named.
- **Inverse.** The utility MUST build a family-grouped shape from flat quantities and
  attributes through a schema, as the exact inverse of flattening, refusing every flat name
  the schema does not define and every problem flattening would refuse.
- **One implementation.** Kit, role, and domain code that needs to validate, flatten,
  unflatten, or digest a capability shape MUST use this utility rather than a local
  implementation.

#### Scenario: The VM domain flattens a shape

- **WHEN** a VM shape `{gpu: {count: 1, model: H100}, memory: {gib: 64}}` is flattened with
  the VM schema
- **THEN** the result's quantities are `gpu_count: 1` and `ram_gb: 64` and its attributes
  are `gpu_model: H100`

#### Scenario: A schema renames a flat field

- **WHEN** a domain's schema changes the flat name of a field
- **THEN** the digest of every shape using that field is unchanged

#### Scenario: A shape names an undefined field

- **WHEN** a shape names a field the supplied schema does not define
- **THEN** flattening refuses it and names the family and field

#### Scenario: Structure is checked without a schema

- **WHEN** a shared kit validates a shape's structure without a domain schema
- **THEN** it accepts any well-formed family-grouped mapping and refuses only malformed
  structure

#### Scenario: A declaration is read back into a shape

- **WHEN** flat quantities `gpu_count: 8`, `ram_gb: 2048` and attribute `gpu_model: H200` are
  unflattened with the compute-family schema
- **THEN** the shape is `{gpu: {count: 8, model: H200}, memory: {gib: 2048}}`, and flattening
  it returns the same flat values

#### Scenario: A flat name is outside the schema

- **WHEN** a flat quantity the schema does not name is unflattened
- **THEN** the utility refuses it, naming the flat field
