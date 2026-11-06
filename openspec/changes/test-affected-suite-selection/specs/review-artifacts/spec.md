## ADDED Requirements

### Requirement: A diff-derived review scope comes from the test selection

When no explicit project list or scope file is given, `make review-wheelhouse` MUST
take its projects from the test selection's machine-readable dry run over the diff,
keeping the locked projects it selects, and MUST select every locked project when
the selection falls back to the full test run. It MUST NOT keep a project or impact
table of its own.

#### Scenario: A kit changes

- **WHEN** `make review-wheelhouse` runs with no `REVIEW_PROJECTS` over a diff
  editing `kit/site/src/`
- **THEN** it bundles `kit/site` and every locked project the selection names as
  its dependent
