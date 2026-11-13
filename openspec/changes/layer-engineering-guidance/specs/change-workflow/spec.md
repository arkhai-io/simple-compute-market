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

Every Markdown file in a capability's directory other than its specification, its
companion, and its index MUST be treated as that capability's guidance, whatever its
name and whether or not it is tagged. Wherever a step reads a capability's
specification and companion, it MUST also read every guidance file in that
capability's directory.

#### Scenario: Triage judges a finding against a capability

- **WHEN** a finding cites a capability whose directory holds a guidance file with an
  exception row
- **THEN** the triage session reads that file with the specification before deciding
  the finding's fix

#### Scenario: Implementing a section that touches a capability

- **WHEN** an implementation section changes code of a capability whose directory
  holds a tagged `testing.md`
- **THEN** the implementation session reads that file with the capability's
  specification and companion

### Requirement: CW-s7rq A skill restates guidance no stricter than its source

A skill that restates a rule of the repository's guidance MUST restate it briefly,
where its step applies the rule, and cite it; the restatement MUST NOT be stricter
than its source. A step that needs a stricter rule MUST propose amending the
guidance rather than restating it more strictly.

#### Scenario: A skill needs a stricter rule

- **WHEN** a step finds that the guidance's rule on test levels is too loose for the
  work it does
- **THEN** its skill keeps restating the rule as the guidance states it, and the
  step proposes amending the guidance

### Requirement: CW-b5cf An unattended step's calls take the forms its rules match

An unattended step MUST run one command per shell call. A path it would otherwise
reach by climbing with `..` after changing directory it MUST name from its
checkout's root or read through a tool its rules allow for reading, and a file its
rules refuse to a shell read it MUST read through such a tool. It MUST wait on a background command through the command's
`wait`, never by following the command's output.

#### Scenario: A step waits on a background suite

- **WHEN** an unattended implementation runs the suites in the background
- **THEN** it waits with `wait` on the output file for the line the suites print when
  they end, never with a following read of the file

### Requirement: CW-e3gt A step checks its entry before it works

Planning, the merge, closeout, and archive cleanup MUST ask the next-step computation
as they start, and go on only when it names them; archive cleanup MUST also go on
when it names a validation before cleanup, and then only on the owner's waiver of
that validation in the change's workflow log. A step that acts on a change's task
list MUST check the task list first, and stop when a numbered task sits under another
section's heading.

#### Scenario: Closeout started before the merge

- **WHEN** closeout is started while the computation names the merge
- **THEN** closeout stops, naming the merge, and changes nothing

### Requirement: CW-o9hd The orchestrating session tells the owner what it starts and leaves the owner's actions to them

The orchestrating session MUST say when it starts a long unattended turn. When the
owner tells it they closed an interactive step before it recorded its outcome, the
session MUST start nothing for that step and MUST give the owner the command to
resume or record it, never running it itself. After the owner hands back a step they
took over, it MUST read the change's files again before routing.

#### Scenario: The owner closed an interactive step before it recorded

- **WHEN** the computation names again a step the owner ran interactively, and the
  owner tells the orchestrating session they closed it before it recorded
- **THEN** the orchestrating session starts nothing for it and gives the owner the
  `record` command and the session to resume

### Requirement: CW-t2lw A triage's records take their written shapes

A triage MUST write each default acceptance's classification (CW-d5ac) on a line
labelled `Classification:`, and MUST report the default acceptances under the
heading "Accepted by default". It MUST make the default acceptances' fixes with the
round's other accepted fixes. Each ledger line MUST be one JSON object with the keys
`review`, `finding`, `section`, `lens`, `basis`, `severity`, `agent_position`,
`owner_disposition`, and `summary`; an entry revising an earlier one, a revision of
a revisit included, MUST begin its disposition `revises <review> <finding>:`, and a
revisit of the advancing exit MUST name the finding `next`. A review pasted from elsewhere MUST
be saved verbatim and triaged with any other review of its kind, the triage assigning
its findings' lens, basis, severity, and alternatives.

#### Scenario: The owner revises a revisit

- **WHEN** the owner changes a disposition they gave in revisiting a default
  acceptance
- **THEN** one ledger line records it, its disposition beginning `revises` and naming
  the review and finding

### Requirement: CW-w6vy Waivers are recommended and recorded where they are given

A step MUST make a waiver's recommendation in the message it already sends the owner.
Planning that settled a design question itself MUST recommend a waiver of another
design review when a criterion of CW-q3dm holds, and the merge after the archive MUST
NOT
recommend waiving its validation after reconciling the change's own code. Validation
MUST take a standing waiver of its parts only from the owner's decision in the
workflow log, never from an instruction in its invocation. A standing waiver given as
a triage's disposition MUST be that triage's ledger line, and one given outside a
triage with no step's recommendation MUST stay in the workflow log alone. Archive
cleanup MUST record the owner's waiver of its validation of a correction as a ledger
line under the closeout review's record, its finding `validated`.

#### Scenario: A waiver given in a validation's invocation

- **WHEN** validation is started with an argument asking it to skip a part
- **THEN** it runs the part unless the change's workflow log holds the owner's
  decision waiving it

## RENAMED Requirements

- FROM: `### Requirement: CW-pkug Closeout changes documentation only`
- TO: `### Requirement: CW-pkug Closeout changes only inert paths`

## MODIFIED Requirements

### Requirement: CW-pkug Closeout changes only inert paths

Closeout MUST change only the repository's inert paths and changes' records; a
closeout part that would change any other path MUST return the change to
implementation.

#### Scenario: Closeout finds a comment that needs rewriting

- **WHEN** closeout's comment hygiene part finds a comment the change added that
  describes its history
- **THEN** closeout stops without editing it and the change returns to
  implementation for a fix round

#### Scenario: A citation to re-point lies inside a skill

- **WHEN** closeout's guidance placement part moves a section that a skill outside the
  inert paths cites
- **THEN** closeout does not re-point the skill's citation, and the change returns to
  implementation to re-point it

### Requirement: CW-n7ra The repository's inert paths

The repository's inert paths, `repository.inert-paths`, MUST name the paths a change
to which alters nothing validation or a code check would prove, other than a test
that checks a document for currency, which the next full run of the suites reads
again. An entry without a glob character MUST match a directory or a file whole; an
entry with one MUST match as a pattern over the whole path, `**` spanning any number
of directories. Where a repository declares none, the workflow's default MUST apply:
`openspec/` and every Markdown file, `**/*.md`. A declaration, an empty one included,
MUST replace the default; with an empty one, no path is inert and only changes'
records are exempt where a requirement exempts them.

#### Scenario: A repository marks images inert

- **WHEN** a repository declares `inert-paths = ["docs/", "assets/"]` and a commit
  after a pre-closeout review changes only `assets/logo.svg`
- **THEN** the computation accepts it without a new validation

#### Scenario: A repository marks every README inert

- **WHEN** a repository declares `inert-paths = ["docs/", "**/README.md"]` and a
  commit changes only `tools/README.md` and `README.md`
- **THEN** `run pre-commit` runs `pre-commit` alone, and after a pre-closeout review
  the computation accepts the commit without a new validation

#### Scenario: A repository declares no inert paths

- **WHEN** a repository's configuration has no `repository.inert-paths` and a commit
  changes only `guides/setup.md` and a capability's `spec.md` under `openspec/`
- **THEN** `run pre-commit` runs `pre-commit` alone, as the default makes both paths
  inert

#### Scenario: A repository declares an empty list

- **WHEN** a repository declares `inert-paths = []` and a commit changes only
  `guides/setup.md`
- **THEN** `run pre-commit` runs the functional hooks before `pre-commit`, since the
  empty declaration replaces the default

### Requirement: CW-l7hn A step's documents to load come from the configuration

The documents a step's skill loads MUST be `load.common` and `load.<step>`, printed
together by `config load <step>`; `config load common` MUST print `load.common`
alone, for a session no step runs; and the post-compaction hook MUST have a session
re-read `load.common`. An entry ending in `/` names a directory and MUST resolve to
the Markdown files beneath it, in sorted path order, each printed once; `config load`
MUST refuse, naming the entry, a directory entry that is missing, unreadable, or
holds no Markdown file.

#### Scenario: Design loads the roadmap

- **WHEN** the configuration lists the roadmap under `load.design`
- **THEN** `config load design` prints the common documents and the roadmap, and
  `config load plan` prints only the common documents

#### Scenario: A directory entry

- **WHEN** `load.common` names `docs/guidance/`, which holds
  `engineering/comments.md` and `workflow/closeout.md`
- **THEN** `config load common` prints both files' paths in sorted order in place of
  the directory, and the post-compaction hook names them

#### Scenario: A directory entry names nothing

- **WHEN** `load.common` names `docs/guidens/`, which does not exist
- **THEN** `config load common` fails, naming the entry, and the post-compaction hook
  tells the session the documents to re-read are unknown
