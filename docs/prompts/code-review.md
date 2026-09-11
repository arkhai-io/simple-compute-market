# Code review session prompt

This session we'll be working on the simple-compute-market project and code reviewing `feature or change`.

AGENTS.md and the documents it requires reading have very important context you should study:
* docs/development/ARCHITECTURE.md
* docs/development/TESTING.md
* docs/development/DEPLOYMENT_AND_CONFIG.md
* and openspec/README.md

## This review

The initial implementation work for this feature is attached as a diff. The zip has the current repo head prior to implementation.

I want you to provide an honest assessment on the direction of these changes:

1. If you were implementing this feature, what would you have done differently?

2. Review the validation strategy. Do the tests have appropriate coverage? For each significant claim of test coverage, state which level it actually operates at (unit against a mocked boundary, integration against a real in-process app, or something that would need a live multi-service environment neither of us can run here) — see `TESTING.md`'s level definitions and coverage-jurisdiction table. Pay particular attention to the interservice/integration layer: does an integration test exercise the real typed client, or does it construct requests by hand in a way that could silently diverge from what the real client sends?

3. Does the documentation comply with the repository documentation guidance in AGENTS.md, ARCHITECTURE.md, and openspec/README.md? Check claims against the actual files, not the prose describing them — if a task or note claims a file changed or a section was promoted, diff or open it and confirm, don't take the checkbox as evidence.
