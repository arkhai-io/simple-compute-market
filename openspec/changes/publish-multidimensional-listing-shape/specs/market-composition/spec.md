## ADDED Requirements

### Requirement: Family-grouped capability shapes share one flattening contract

A capability shape MUST be expressed in the family-grouped form: a mapping of family name to
a mapping of field name to a scalar value. One shared utility in the dependency-light core
package MUST validate that form's structure, flatten a shape into quantities and attributes,
and compute a canonical digest of a shape.

- **Schema.** Flattening MUST be driven by a schema the owning domain supplies. For each
  family field the schema states whether it is a quantity or an attribute, whether it is
  required, and its flat name. The utility MUST NOT contain any domain's family or field
  names.
- **Digest.** The canonical digest MUST be taken over the family-grouped form, so changing a
  schema's flat names does not change a shape's digest.
- **Refusals.** A shape naming a family or field its schema does not define, missing a
  required field, or carrying a value of the wrong kind MUST be refused with the offending
  path named.
- **One implementation.** Kit, role, and domain code that needs to validate, flatten, or
  digest a capability shape MUST use this utility rather than a local implementation.

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
