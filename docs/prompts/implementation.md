# Implementation session prompt

This session we'll be working on the simple-compute-market project and
implementing `<change or section>`. `AGENTS.md` and the documents it
requires reading — `docs/development/ARCHITECTURE.md`,
`docs/development/TESTING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`,
and `openspec/README.md` — have very important context you should study.

## Documentation and implementation workflow

Follow the repository documentation guidance in `AGENTS.md` and the
documents it references.

Use a discuss → plan → implement workflow:

1. During discussion, we will clarify any outstanding design decisions
   and weigh alternative implementation options in this chat. At the
   end of the design phase, update the active
   `openspec/changes/<change>/` documents and return a packaged
   fileset.
2. During planning, preserve existing completed tasks and append or
   amend the implementation plan. Identify the exact files affected
   by each accepted design decision. End the plan with the closeout
   task defined in `openspec/README.md#plan-closeout-requirements`.
   Update the active `openspec/changes/<change>/` documents and
   return a packaged fileset.
3. During implementation
   a. implement the plan.
   b. run tests covering all code changes.
   c. pause for design review if the plan premise is invalidated by
      discovered code.
   d. ensure production comments describe present intent, invariants,
      and constraints and reference only stable permanent documentation
      when broader context is required.

`openspec/changes` is the temporary proposal, discussion, planning, and
migration layer. Production code must not reference it — see
`AGENTS.md`'s "Documentation ownership" for the full breakdown of what
belongs where.

## Deliverables

When returning implementation artifacts, include only updated files in
a zip in the original directory structure of the provided repository.

Represent a file requiring deletion by replacing its entire contents
with a single-line tombstone comment stating the reason, at the file's
original path:

```python
# TOMBSTONE: delete this file — <one-sentence reason>
```

Do not create a separate deletion manifest or a suffixed copy alongside
the original — one file, one mechanism. Tombstone references must not
remain in final production code or permanent documentation.
