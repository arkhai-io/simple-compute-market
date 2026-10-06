## ADDED Requirements

### Requirement: Capability shape admissibility is a whole-shape contract

A foundation kit SHALL own the admissibility of capability shapes, depending only on the
capability-shape kit and the standard library, so storefronts, buyers, and pool
administration can all depend on it. It SHALL expose exactly two operations, both
taking shapes and neither returning unconditional bounds:

- a check of a whole shape that returns every problem found, empty when the shape is
  admissible, each problem naming every `family.field` path it involves, a code, and a
  message;
- the values one dimension may take given a partial shape: those for which the partial
  shape, with that dimension set to the value, can still be completed to an admissible
  shape. Dimensions the partial shape does not state are free; a value it states for the
  requested dimension is ignored.

The returned values SHALL be an opaque set answering membership, emptiness, the greatest
admissible value not above a given value, the least not below it, and its minimum and
maximum, where an absent maximum means unbounded. An answer SHALL be valid only for the
partial shape it was computed from. Fixing dimensions one at a time, in any order, each to
a value from the current answer SHALL never leave a later answer empty and SHALL end at
an admissible shape.

A shape SHALL be admissible exactly when it can be completed to an admissible shape, so
a dimension a shape omits never makes it inadmissible by its absence. No caller other
than the kit SHALL interpret a bounds declaration.

#### Scenario: A shape outside one bound

- **WHEN** a shape states a quantity above the maximum declared for that field
- **THEN** the check returns one problem naming that field's path, and no problem for
  any field within its bounds

#### Scenario: A shape inside every bound

- **WHEN** every quantity a shape states lies within its field's declared bounds
- **THEN** the check returns no problems

#### Scenario: A shape omits a bounded field

- **WHEN** a declaration bounds a field with a minimum and a shape does not state that
  field
- **THEN** the shape is admissible

#### Scenario: Admissible values are requested for one dimension

- **WHEN** the values for a bounded dimension are requested with a partial shape whose
  stated dimensions are admissible
- **THEN** the answer contains exactly the declared range for that dimension and answers
  the greatest admissible value not above a requested one

#### Scenario: The partial shape is already inadmissible

- **WHEN** the values for one dimension are requested with a partial shape that states
  another dimension outside its bounds
- **THEN** the answer is empty

#### Scenario: A counter-shape is built one dimension at a time

- **WHEN** a policy fixes each dimension in turn to a value from the current answer for
  that dimension
- **THEN** no answer along the way is empty and the resulting shape has no problems

#### Scenario: The kit is used by a domain it does not know

- **WHEN** a declaration and shapes are expressed in a schema with no compute vocabulary
- **THEN** both operations behave as for any other schema, and the kit imports nothing
  beyond the capability-shape kit and the standard library

### Requirement: Shape bounds declarations are sectioned and strict

A shape bounds declaration for one offering mode SHALL be a mapping of named constraint
sections, and the admissible region SHALL be the intersection of every section. The
`bounds` section SHALL map family to field to a mapping holding `min`, `max`, or both,
each a positive integer, with `min` not above `max`, and SHALL name each field at most
once. A section, or a key within a `bounds` field, that the reader does not define SHALL
make the declaration unreadable rather than be ignored. The kit SHALL check structure
without any family or field name; whether each path is a quantity field SHALL be checked
against the domain's schema.

#### Scenario: A declaration carries an unknown section

- **WHEN** a declaration holds `bounds` and a section the reader does not define
- **THEN** the declaration is unreadable as a whole

#### Scenario: A bounds field carries an unknown key

- **WHEN** a `bounds` field holds a key other than `min` and `max`
- **THEN** the declaration is unreadable

#### Scenario: A bound names an attribute

- **WHEN** a declaration bounds a field the domain's schema defines as an attribute, or
  does not define
- **THEN** the domain refuses the declaration as unreadable

#### Scenario: A bound is inverted

- **WHEN** a `bounds` field states a `min` above its `max`
- **THEN** the structural check reports it
