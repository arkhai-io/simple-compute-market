# Code review session prompt

This session we'll be working on the simple-compute-market project and
code reviewing `<change or section>` changes. `AGENTS.md` and the
documents it requires reading — `docs/development/ARCHITECTURE.md`,
`docs/development/TESTING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`,
and `openspec/README.md` — have very important context you should study.

## Documentation and implementation workflow

Follow the repository documentation guidance in `AGENTS.md` and the
documents it references.

Use a discuss → plan → implement workflow:

1. During discussion, record unresolved alternatives and proposed
   decisions in the active `openspec/changes/<change>/` documents.
2. During planning, preserve existing completed tasks and append or
   amend the implementation plan. Identify the exact permanent
   documentation affected by each accepted design decision.
3. During implementation:
   a. implement and validate the plan;
   b. promote all accepted durable design knowledge into the
      appropriate `openspec/specs/<subsystem>/spec.md` or, for
      repository-wide concerns, `ARCHITECTURE.md`;
   c. update permanent documentation to describe the current system
      rather than recording that a change was completed;
   d. remove temporary, migration-oriented, and changelog-style
      commentary from production code;
   e. ensure production comments describe present intent, invariants,
      and constraints and reference only stable permanent documentation
      when broader context is required;
   f. complete the change's design-promotion record, mapping material
      decisions to their permanent documentation locations.

`openspec/changes` is the temporary proposal, discussion, planning, and
migration layer. Production code must not reference it — see
`AGENTS.md`'s "Documentation ownership" for the full breakdown of what
belongs where.

## Deliverables

When returning implementation artifacts as a zip, include only updated
files in the original directory structure of the provided repository.

Represent a file requiring deletion by replacing its entire contents
with a single-line tombstone comment stating the reason, at the file's
original path:

```python
# TOMBSTONE: delete this file — <one-sentence reason>
```

Do not create a separate deletion manifest or a suffixed copy alongside
the original — one file, one mechanism. Tombstone references must not
remain in final production code or permanent documentation.

## This review

The initial implementation work for this feature is attached as a diff.
The zip has the current repo head with these changes pending.

**Before answering anything below, confirm the zip's stated base actually
matches the current repository head.** A patch or diff generated against
a stale base can look internally consistent and still silently
reintroduce deleted files or revert content that was already corrected —
check this first, not as an afterthought.

I want you to provide an honest assessment on the direction of these
changes:

1. If you were implementing this feature, what would you have done
   differently?
2. Review the validation strategy. Do the tests have appropriate
   coverage? For each significant claim of test coverage, state which
   level it actually operates at (unit against a mocked boundary,
   integration against a real in-process app, or something that would
   need a live multi-service environment neither of us can run here) —
   see `TESTING.md`'s level definitions and coverage-jurisdiction table.
   Pay particular attention to the interservice/integration layer:
   does an integration test exercise the real typed client, or does it
   construct requests by hand in a way that could silently diverge from
   what the real client sends?
3. Does the documentation comply with the repository documentation
   guidance in `AGENTS.md`, `ARCHITECTURE.md`, and `openspec/README.md`?
   Check claims against the actual files, not the prose describing
   them — if a task or note claims a file changed or a section was
   promoted, diff or open it and confirm, don't take the checkbox as
   evidence.
4. How close are we to feature complete for `<change or section>`?
