## ADDED Requirements

### Requirement: Capability shape admissibility is owned by one kit

A foundation kit SHALL own the admissibility of capability shapes, depending only on the
capability-shape kit and the standard library, so storefronts, buyers, and pool
administration can all depend on it. It SHALL be the only reader of a shape bounds
declaration's contents: every other caller SHALL hold a parsed declaration and a
resolved policy as opaque values and SHALL pass a raw declaration to the kit unread.

The kit SHALL expose two groups of operations.

**Declaration handling:**

- parsing a raw declaration, returning a declaration or every problem found. Without a
  schema it SHALL check structure only; given a domain's capability schema it SHALL also
  check that every bounded path is a quantity field the schema defines. The kit SHALL
  know no family or field name.
- resolving declarations given highest tier first into a resolved policy, or every
  problem found. Each section SHALL own its merge rule. An empty range SHALL be a
  problem.

**Evaluation on a resolved policy**, neither returning unconditional bounds:

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
a dimension a shape omits never makes it inadmissible by its absence.

#### Scenario: A shape outside one bound

- **WHEN** a shape states a quantity above the resolved maximum for that field
- **THEN** the check returns one problem naming that field's path, and no problem for
  any field within its bounds

#### Scenario: A shape inside every bound

- **WHEN** every quantity a shape states lies within its field's resolved bounds
- **THEN** the check returns no problems

#### Scenario: A shape omits a bounded field

- **WHEN** a resolved policy bounds a field with a minimum and a shape does not state
  that field
- **THEN** the shape is admissible

#### Scenario: Admissible values are requested for one dimension

- **WHEN** the values for a bounded dimension are requested with a partial shape whose
  stated dimensions are admissible
- **THEN** the answer contains exactly the resolved range for that dimension and answers
  the greatest admissible value not above a requested one

#### Scenario: The partial shape is already inadmissible

- **WHEN** the values for one dimension are requested with a partial shape that states
  another dimension outside its bounds
- **THEN** the answer is empty

#### Scenario: A counter-shape is built one dimension at a time

- **WHEN** a policy fixes each dimension in turn to a value from the current answer for
  that dimension
- **THEN** no answer along the way is empty and the resulting shape has no problems

#### Scenario: Tiers merge per field

- **WHEN** a higher tier bounds only the maximum of a field and a lower tier bounds its
  minimum and maximum
- **THEN** the resolved policy takes the higher tier's maximum and the lower tier's
  minimum

#### Scenario: A higher tier omits a lower tier's bound

- **WHEN** a lower tier bounds a field and a higher tier states nothing for it
- **THEN** the resolved policy keeps the lower tier's bound

#### Scenario: Tiers merge to an empty range

- **WHEN** a lower tier states a minimum above a higher tier's maximum for one field
- **THEN** resolution returns a problem naming the field and both tiers' values, and no
  policy

#### Scenario: One tier is unusable

- **WHEN** any declaration given to resolution failed to parse
- **THEN** resolution returns its problems and no policy

#### Scenario: The kit is used by a domain it does not know

- **WHEN** declarations and shapes are expressed in a schema with no compute vocabulary
- **THEN** every operation behaves as for any other schema, and the kit imports nothing
  beyond the capability-shape kit and the standard library

### Requirement: Shape bounds declarations are sectioned and strict

A shape bounds declaration for one offering mode SHALL be a mapping of named constraint
sections, and the admissible region SHALL be the intersection of every section. The
`bounds` section SHALL map family to field to a mapping holding `min`, `max`, or both,
each a positive integer, with `min` not above `max`, and SHALL name each field at most
once. Its merge rule SHALL be per leaf: for each field's `min` and `max` the highest tier
stating it wins, and a tier that does not state a leaf SHALL leave a lower tier's value
in place. A section, or a key within a `bounds` field, that the kit does not define SHALL
make the declaration fail to parse rather than be ignored.

#### Scenario: A declaration carries an unknown section

- **WHEN** a declaration holds `bounds` and a section the kit does not define
- **THEN** parsing fails for the declaration as a whole

#### Scenario: A bounds field carries an unknown key

- **WHEN** a `bounds` field holds a key other than `min` and `max`
- **THEN** parsing fails

#### Scenario: A bound names an attribute

- **WHEN** a declaration is parsed with a domain's schema and bounds a field the schema
  defines as an attribute, or does not define
- **THEN** parsing fails naming that path

#### Scenario: A bound is inverted

- **WHEN** a `bounds` field states a `min` above its `max`
- **THEN** parsing fails, with or without a schema
