---
tags: [workflow, openspec]
---

# OpenSpec documentation

OpenSpec separates the system's durable current contract from the temporary work
required to change it:

- `openspec/specs/<capability>/spec.md` is the capability's authoritative,
  implemented normative contract: its behaviour, ownership, invariants, and
  lifecycle semantics.
- Its companion may preserve, in freeform prose, durable current-state conceptual
  models, design motivation, trade-offs, relationships, and limitations. It does not
  replace normative requirements. The companion is
  `openspec/specs/<capability>/architecture.md`, or, in a capability organized by an
  index, its `README.md`, beside an `index.md`, with no `architecture.md`
  ([A capability organized by an index](#a-capability-organized-by-an-index)).
- `openspec/changes/<change>/` describes a transition: its proposal, design
  exploration and alternatives, unresolved questions, delta requirements, migration
  notes and temporary compatibility concerns, and implementation tasks
  ([A change's documents](changes.md)).
- `openspec/changes/archive/` records completed transitions after their durable
  results have been synchronized into `openspec/specs/` and, where they span
  capabilities, into the repository's cross-system documents.
- `openspec/config.yaml` supplies repository context and artifact-quality rules to
  the OpenSpec tool.

Production code does not depend on `openspec/changes/` for design context
([Change references](change-references.md)). Before a change is archived, the
durable knowledge it produced is promoted to the owning `spec.md`, its companion, or
the repository's cross-system documents — at closeout, after the code's last review
([Promotion](closeout.md#promotion)). OpenSpec validates and synchronizes `spec.md`
but ignores companion files and `index.md`, so every applicable change names their
promotion in `tasks.md` and its design-promotion record
([The design-promotion record](changes.md#the-design-promotion-record)).

## The capability index and the roadmap

A repository adopting the workflow keeps a canonical capability documentation index,
through which a reader finds every normative contract and companion; where it is,
and what it lists, are the repository's.

It keeps a roadmap too: the directional goals, the value each delivers, the current
state per goal, and which change owns each open gap. Goals and their gaps go to the
roadmap rather than to the capability index, which describes what the system is.

## Documentation placement

| Knowledge | Permanent home |
|---|---|
| Subsystem behaviour, package ownership, lifecycle, identifiers, and errors | `openspec/specs/<subsystem>/spec.md` |
| Subsystem conceptual models, durable rationale, trade-offs, relationships, and current limits | `openspec/specs/<subsystem>/architecture.md`, or `openspec/specs/<subsystem>/README.md` where the subsystem has an `index.md` |
| The organization of an indexed subsystem's requirements, by id | `openspec/specs/<subsystem>/index.md` |
| Directional goals, the value each delivers, current state per goal, and which change owns each open gap | the repository's roadmap |
| Proposed behaviour and unresolved alternatives | `openspec/changes/<change>/proposal.md` and `design.md` |
| Implementation sequence, files, validation, and manual migration work | `openspec/changes/<change>/tasks.md` |

The repository's own placement table names its cross-system documents beside these.
Permanent specifications may include short rationale needed to interpret a
requirement. Broader explanatory prose belongs in the capability's companion. Neither
document preserves the chronology of how a decision was reached.

## Capability documentation pattern

A subsystem's `spec.md` contains its purpose and normative requirements for
responsibilities, authority, dependencies, terminology, lifecycle, errors, retry,
idempotency, versioning, and other observable behaviour. Every requirement has
acceptance scenarios and may point to implementation or test evidence.

A companion — `architecture.md`, or `README.md` in a capability organized by an
index — may explain:

1. Conceptual models and major flows.
2. Why an authority or dependency boundary exists.
3. Ownership relationships and explicit non-responsibilities.
4. Alternatives and trade-offs that remain relevant to the current design.
5. Operational consequences and current limitations.
6. Links to adjacent capability contracts.

Both files describe the current system. Avoid wording such as "completed in POOLS-7"
or "formerly lived in". Planned and partially implemented behaviour remains in a
change until it is true. When architecture prose states behaviour implementations
must satisfy, add the corresponding normative requirement to `spec.md`.

### A capability organized by an index

A capability's documentation follows its specification: its documents take the
organization its requirements have. A component's `README.md` is its most
human-readable document, the one a reader new to the component starts from; the
procedural index of its requirements is a separate `index.md`. A capability may
organize its documentation by an index of requirement ids. One that does keeps:

```text
openspec/specs/<capability>/
  README.md     the component's human-readable description, with its diagrams,
                its sections following index.md's parts
  index.md      the specification's organization: parts and groups as a table of
                contents, each requirement by id with its link and a summary line,
                and the retired ids
  spec.md       flat requirements, each named "### Requirement: <ID> <name>"
  diagrams/     each diagram's source and its export
```

Its `README.md` is its companion, and it has no `architecture.md`. The order of
requirements in `spec.md` carries no meaning, since an archive appends a change's
added requirements at the end; `index.md` holds the organization.

- **Ids.** An id is the capability's prefix, in upper-case letters, a hyphen, and
  four characters from `[a-z0-9]` chosen at random (`CW-a8tf`), so that changes on
  different branches are unlikely to choose the same one, and the repository's index
  check catches it when they do. It encodes nothing of the organization, so a
  requirement keeps its id when the index moves it between groups. An id is never
  reused.
- **The index's shape.** `index.md` declares the prefix on a line of its own,
  `` Prefix: `CW` ``. Each requirement is a list item, or a table row, whose first
  cell is a link from its id to its heading in `spec.md`
  (`[CW-a8tf](spec.md#requirement-cw-a8tf-…)`), followed by its summary line, under
  the part and group it belongs to.
- **Retired ids.** When a change removes a requirement, its id moves to the items
  under `## Retired ids`, each beginning with the id and saying where its rule went.
- **Citing by id.** A requirement of an indexed capability may be cited by its id,
  such as `CW-a8tf`, so that the citation survives the requirement's renaming.

A change that adds a requirement to an indexed capability gives it a new id in its
delta's heading; closeout's promotion writes its index entry
([Promotion](closeout.md#promotion)).
