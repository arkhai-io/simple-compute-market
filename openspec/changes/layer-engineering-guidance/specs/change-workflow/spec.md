## ADDED Requirements

### Requirement: CW-g7lt Every guidance file carries one layer tag

Every guidance file of an adopting repository MUST carry YAML frontmatter whose
`tags` hold exactly one layer tag: `engineering` for guidance that holds in a
repository using neither the workflow nor OpenSpec, `workflow` for guidance that
holds in any repository adopting the workflow and names nothing of one repository,
or `repository` for guidance that names the adopting repository's own packages,
services, tools, documents, or targets. Every other tag MUST appear in the
vocabulary table of the file's layer or of a lower one, engineering being the
lowest and repository the highest.

#### Scenario: A general rule with a market example

- **WHEN** a section stating how comments are written cites a capability of the
  adopting repository as its example
- **THEN** the rule is tagged `engineering` with a neutral example, and the
  repository's example moves to guidance tagged `repository`

#### Scenario: A file states no layer

- **WHEN** a guidance file's tags are `[testing, python]`
- **THEN** it does not satisfy the requirement until one layer tag is added

### Requirement: CW-d2rw Guidance never links to a higher layer

A guidance file MUST NOT link to a guidance file tagged with a higher layer:
engineering guidance links only to engineering guidance, and workflow guidance to
workflow or engineering guidance.

#### Scenario: Workflow guidance links to a repository document

- **WHEN** a file tagged `workflow` links to a file tagged `repository`
- **THEN** it does not satisfy the requirement, and the link is replaced by what the
  workflow guidance can state without the repository

### Requirement: CW-p9sa Guidance sits beside the system it pertains to

Repository guidance that pertains to one system MUST sit beside that system's
specification, in its capability directory; repository guidance spanning several
systems MUST sit in the repository's cross-system documentation. The guidance
placement part of closeout MUST check what a change added, moved, or rewrote against
this requirement and the layer test, move what is misplaced, and report a placement
needing a decision for the closeout review.

#### Scenario: A capability's testing guidance

- **WHEN** a section on how one capability's coverage divides between its packages'
  tests sits in a repository-wide testing document
- **THEN** it moves to a guidance file in that capability's directory

#### Scenario: Closeout finds a misplaced promotion

- **WHEN** a change's promotion writes a market rule into a file tagged
  `engineering`
- **THEN** closeout's guidance placement part moves it to repository guidance and
  re-points its citations before the citations are checked

### Requirement: CW-x4ex Exceptions to shared guidance are declared beside what they apply to

A repository's exception to shared guidance — selecting a case the shared guidance
leaves open, or overriding one of its rules — MUST be a row in a table headed
"Exceptions to shared guidance" with the columns `Shared rule`, `Kind` (`selects` or
`overrides`), `Here`, and `Reason`, sitting beside the component it applies to, or in
the repository's root guidance when it spans several systems. Narrowing a shared
rule is an ordinary repository rule and needs no row.

#### Scenario: A repository is public

- **WHEN** engineering guidance describes what may enter a private and a public
  repository, and the adopting repository is public
- **THEN** its root guidance holds a `selects` row citing the public case

#### Scenario: One capability departs from a shared rule

- **WHEN** one capability's tests patch a name the shared test-seam rule forbids
  patching
- **THEN** an `overrides` row sits in that capability's guidance, not in the root
  guidance

### Requirement: CW-n6dm Directories carry no meaning to the workflow

The workflow MUST NOT derive a guidance file's layer or tags from the directory
holding it; directories organize guidance for people, and the frontmatter alone
states its layer and tags.

#### Scenario: A workflow file in an engineering directory

- **WHEN** a file tagged `workflow` sits under `docs/guidance/engineering/`
- **THEN** it is workflow guidance, and moving it changes nothing the workflow does
  with it

### Requirement: CW-r8cg A step reads the guidance beside a capability

Wherever a step reads a capability's specification and companion, it MUST also read
every tagged guidance file in that capability's directory.

#### Scenario: Implementing a section that touches a capability

- **WHEN** an implementation section changes code of a capability whose directory
  holds a tagged `testing.md`
- **THEN** the implementation session reads that file with the capability's
  specification and companion

## MODIFIED Requirements

### Requirement: CW-l7hn A step's documents to load come from the configuration

The documents a step's skill loads MUST be `load.common` and `load.<step>`, printed
together by `config load <step>`; `config load common` MUST print `load.common`
alone, for a session no step runs; and the post-compaction hook MUST have a session
re-read `load.common`. An entry naming a directory MUST resolve to the Markdown files
beneath it, in sorted path order, each printed once.

#### Scenario: Design loads the roadmap

- **WHEN** the configuration lists the roadmap under `load.design`
- **THEN** `config load design` prints the common documents and the roadmap, and
  `config load plan` prints only the common documents

#### Scenario: A directory entry

- **WHEN** `load.common` names `docs/guidance/`, which holds
  `engineering/comments.md` and `workflow/closeout.md`
- **THEN** `config load common` prints both files' paths in sorted order in place of
  the directory, and the post-compaction hook names them
