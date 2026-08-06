# Tasks

## Status: discuss phase only — no implementation plan yet

This change carries forward scope `pools-8-capacity-projection-and-listing-hints`
deliberately deferred out of its own Section 6 (see `proposal.md`/`design.md`
for the full rationale, written to stand on its own). Nothing here has a
real implementation plan yet — the scope is well-understood from `pools-8`'s
own investigation, but re-grounding against the exact current code is still
owed before writing one, since the codebase will have moved on by the time
this change actually starts. Before any task list is written:

1. Re-confirm `resources`' commercial columns are still dead in the
   current default code path (a repo-wide grep, not assumed from
   `design.md`'s carried-forward finding).
2. Re-confirm the six e2e scenario files named in `proposal.md` are still
   the complete, accurate set of CSV-dependent files.
3. Resolve the open scope question in `design.md`: does the new
   pool-commercial-metadata admin endpoint need pool *creation*, or only
   editing an already-existing row?
4. Decide the actual trigger for starting this change at all — `pools-8`
   deliberately declined to define one (no fleet-wide deployment signal
   this product can observe), so this is a real decision for whoever picks
   this up, informed by this product's actual deployment/versioning
   strategy at the time, not something `pools-8` or this stub can specify
   in advance.

Once those are resolved, this file gets a real plan phase: the freeze
migration, the new admin endpoint, local-table code path removal, CSV
import removal, the e2e seeding migration, and the final `DROP` explicitly
deferred past even this change's own scope (a further follow-up, gated on
this change's own freeze having baked without a rollback).
