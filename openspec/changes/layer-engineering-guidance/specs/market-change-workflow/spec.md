## MODIFIED Requirements

### Requirement: MCW-c4ek A change's closing checks enforce written rules

A change's closing checks MUST fail when a decision headed `D<n>` under its design's
`## Decisions` has no bullet starting `D<n>` in its proposal's knowledge to promote;
when a comment or docstring line its diff adds uses history wording on the check's
list; when a package version differs from its version at the merge-base with the
branch the change lands on by more than one SemVer step; when an import its diff adds
inside a function has no comment giving its reason; when a capability with a
specification has no row in the capability index, or a row links no capability; or
when the guidance check, `make check-guidance`, fails. The guidance check MUST fail,
over every guidance file, on missing `tags`; on zero or several layer tags; on a tag
in neither its layer's vocabulary table nor a lower one's; on a vocabulary row no file
uses; on a malformed table; on an exception row citing no guidance file or naming an
unknown kind; and on a link to a guidance file tagged with a higher layer. It MUST
also fail when a citation of a guidance file — a Markdown link or a quoted path —
carries an anchor that names no heading in that file, in any tracked Markdown file
outside the archived changes and `docs/prompts/`.

#### Scenario: A decision names no destination

- **WHEN** a design records `### D7` and the proposal's knowledge to promote has no
  bullet starting `D7`
- **THEN** the closing checks fail, naming D7

#### Scenario: A comment describes history

- **WHEN** a change's diff adds the comment "# previously read from the pool table"
- **THEN** the closing checks fail, naming the file and line

#### Scenario: A package is bumped twice

- **WHEN** a package at 0.4.0 on the merge-base is at 0.4.2 on the change's branch
- **THEN** the closing checks fail, naming the package and both versions

#### Scenario: A larger bump replaces a smaller one

- **WHEN** a package at 0.4.0 on the merge-base, bumped to 0.4.1 for a fix, is bumped
  to 0.5.0 for an incompatible edit
- **THEN** the version check passes

#### Scenario: A local import has no reason

- **WHEN** a change's diff adds an import inside a function with no comment beside or
  above it
- **THEN** the closing checks fail, naming the file and line

#### Scenario: A capability has no index row

- **WHEN** `openspec/specs/<capability>/spec.md` exists and the capability index has
  no row linking it
- **THEN** the closing checks fail, naming the capability

#### Scenario: A guidance link's section moved

- **WHEN** a skill links to `openspec/README.md#plan-closeout-requirements` after that
  section has moved to the workflow's closeout guidance
- **THEN** the guidance check fails, naming the link and its missing anchor

#### Scenario: Engineering guidance links upward

- **WHEN** a file tagged `engineering` links to a file tagged `repository`
- **THEN** the guidance check fails, naming both files
