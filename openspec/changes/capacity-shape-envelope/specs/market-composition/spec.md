## ADDED Requirements

### Requirement: Capability shape admissibility is owned by one kit

A foundation kit SHALL own the admissibility of capability shapes, depending only on the
capability-shape kit and the standard library, so storefronts, buyers, and pool
administration can all depend on it. It SHALL be the only reader of a shape constraint:
every other caller SHALL hold a parsed declaration and a resolved policy as opaque
values, and SHALL obtain a stated listing shape's base shape from the kit rather than by
reading its constraints.

The kit SHALL expose two groups of operations.

**Declaration handling**, each given a tier label that every problem it returns, and
every problem resolution later returns about it, SHALL carry:

- splitting a stated listing shape into its base shape and either its declaration or its
  constraint problems. Without a schema it SHALL check structure only; given a domain's
  capability schema it SHALL also check that every constrained path is a quantity field
  the schema defines. The kit SHALL know no family or field name.
- parsing a constraint-only declaration, which states no offer.
- resolving declarations given highest tier first, with a schema, into a resolved policy
  or every problem found. Each constraint form SHALL own its merge rule. An empty range
  SHALL be a problem naming each tier's conflicting value.

**Evaluation on a resolved policy**, neither returning unconditional bounds:

- a check of a whole shape that returns every problem found, empty when the shape is
  admissible, each problem naming every `family.field` path it involves, a code, a
  message, and its tier. A shape malformed under the policy's schema SHALL be reported
  as problems; the schema's required fields SHALL NOT be checked.
- the values one dimension may take given a partial shape: those for which the partial
  shape, with that dimension set to the value, can still be completed to an admissible
  shape. Dimensions the partial shape does not state are free; a value it states for the
  requested dimension is ignored; an empty partial shape is valid. A dimension that is
  not a quantity the schema defines, or a partial shape malformed under the schema,
  SHALL raise an error carrying every problem.

The returned values SHALL be an opaque set answering membership, emptiness, the greatest
admissible value not above a given value, the least not below it, and its minimum and
maximum, where an absent maximum means unbounded and every accessor of an empty set
answers nothing. An answer SHALL be valid only for the partial shape it was computed
from. Fixing dimensions one at a time, in any order, each to a value from the current
answer SHALL never leave a later answer empty and SHALL end at an admissible shape.

A shape SHALL be admissible exactly when it can be completed to an admissible shape, so
a dimension a shape omits never makes it inadmissible by its absence.

#### Scenario: A shape outside one bound

- **WHEN** a shape states a quantity above the resolved maximum for that field
- **THEN** the check returns one problem naming that field's path and the tier that set
  the maximum, and no problem for any field within its bounds

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

#### Scenario: Values are requested for a field that is not a quantity

- **WHEN** the values are requested for an attribute, or for a path the schema does not
  define
- **THEN** the request raises an error naming the path, and no empty answer is returned

#### Scenario: Values are requested from an empty partial shape

- **WHEN** the values for a bounded dimension are requested with a partial shape stating
  nothing
- **THEN** the answer is that dimension's resolved range

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
- **THEN** resolution returns a problem naming the field and both tiers with their
  values, and no policy

#### Scenario: The kit is used by a domain it does not know

- **WHEN** declarations and shapes are expressed in a schema with no compute vocabulary
- **THEN** every operation behaves as for any other schema, and the kit imports nothing
  beyond the capability-shape kit and the standard library

### Requirement: Shape constraints are stated inline and strictly

A stated listing shape SHALL be able to give any quantity field a constraint mapping in
place of its scalar value. The mapping SHALL hold `offer`, `min`, `max`, or any of them
but not none; each SHALL be a positive integer, `min` SHALL NOT be above `max`, and an
`offer` SHALL lie within the field's own `min` and `max`. A plain scalar SHALL be
shorthand for a mapping holding only `offer`. The listing's base shape SHALL hold each
field's offer and SHALL omit a field whose mapping states none. An offer without `min`
or `max` SHALL NOT constrain the field. A constraint-only declaration SHALL use the same
field syntax without `offer`. Under the `min`/`max` merge rule, for each field's `min`
and `max` the highest tier stating it SHALL win, and a tier that does not state one SHALL
leave a lower tier's value in place. The admissible region SHALL be the intersection of
every constraint. A key the kit does not define SHALL make the shape's constraints
unreadable rather than be ignored.

#### Scenario: A field carries an unknown key

- **WHEN** a constraint mapping holds a key other than `offer`, `min`, and `max`
- **THEN** splitting returns a constraint problem naming the path and no declaration

#### Scenario: A constraint names an attribute

- **WHEN** a shape is split with a domain's schema and gives a constraint mapping to a
  field the schema defines as an attribute, or does not define
- **THEN** splitting returns a constraint problem naming that path

#### Scenario: An offer lies outside its own range

- **WHEN** a constraint mapping states an `offer` above its `max` or below its `min`
- **THEN** splitting returns a constraint problem, with or without a schema

#### Scenario: A constraint mapping is empty

- **WHEN** a field's constraint mapping states no key
- **THEN** splitting returns a constraint problem naming the path

#### Scenario: A field constrains without offering

- **WHEN** a shape gives `memory.gib` only a `max`
- **THEN** the base shape omits `memory.gib`, and the policy bounds a shape that states it

#### Scenario: An offer alone does not constrain

- **WHEN** a shape states `cpu.count` as a plain scalar and no tier bounds it
- **THEN** the base shape states that count, and a shape stating any other count is
  admissible on that field
