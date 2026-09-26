# Tasks — bare-metal listing shapes

Unblocked: `bare-metal-publication-reads-pool-declarations` is complete. Design
decided; not yet planned.

## 1. Design

- [x] 1.1 Decide each open question in `design.md` and record the decision there.
      Decided: the compute-family schema; close and republish once; the nested
      `capabilities` mapping retired; overrides carry clauses and terms only.
- [x] 1.3 Audit the recorded decisions against the code and resolve what it
      invalidated. Recorded in `design.md`:
      - the compute-family schema moves to a new `domains/compute` package;
      - `kit/capability-shape` gains `unflatten_shape`;
      - the shape is derived from declared capacity and attributes, requiring `gpu`
        and exactly one `units`;
      - the derivation identity includes the shape digest, which amends "identity
        stays the Physical Resource" and replaces listings once without special code;
      - the claim carries the shape's attributes beside `units: 1`;
      - region is read from the pool hint, and a pool with none is held;
      - override HTTP handling moves into a framework-free kit route service, with
        status judged against the last accepted generation;
      - a minimal opening guard is added, and moves with
        `bare-metal-and-credits-domain-stacks` 4a;
      - bare metal gains a `pool-override` command: VM's command-line layer copied
        over the kit's typed client, calling the administrator API.
- [ ] 1.2 Plan the implementation, naming the files each decision touches, the focused
      and integration suites, and the permanent documentation destinations.

## 2. Closeout

- [ ] 2.1 The closeout task defined in
      `openspec/README.md#plan-closeout-requirements`, written out in full when this
      change is planned.
