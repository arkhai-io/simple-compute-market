## ADDED Requirements

### Requirement: Issue-discovery harness jurisdiction
The issue-discovery harness MUST NOT be treated as an additional level in the
layered verification hierarchy. Its jurisdiction is its own behavior — phase
configuration admissibility, failure classification, redaction, and issue
candidate production. A test proving product behavior MUST be placed at the
level that owns that behavior, not in the harness, and the harness MUST NOT be
used to obtain coverage a lower level could provide.

#### Scenario: A test is proposed for product reservation or scheduling behavior
- **WHEN** a new test would prove something about the product's own
  reservation, scheduling, or scarcity behavior
- **THEN** it is placed at the lowest level that can meaningfully prove it, and
  not in the harness

#### Scenario: A test is proposed for harness behavior
- **WHEN** the behavior under test is the harness's own — configuration
  admissibility, failure classification, redaction refusal, or candidate
  planning determinism
- **THEN** it belongs to the harness's locked suite

#### Scenario: The harness's own suite is collected by the repository test target
- **WHEN** the repository's aggregate test target runs
- **THEN** the harness's locked suite is not collected, and the exclusion is
  stated in permanent documentation with its reason

### Requirement: Harness phase configuration resolves against the current tree
Every repository entry point a harness phase configuration names MUST resolve in
the tree the configuration ships in. Loading a configuration MUST resolve each
entry point through the build system rather than by inspecting build files —
a build target by a no-execute dry run in its declared working directory, any
other command by locating its executable — and MUST fail the load, reporting
every unresolvable entry point together, rather than allowing execution to reach
a command that cannot run. Resolution MUST NOT execute any recipe. An
unresolvable entry point MUST be reported as a defect in the harness
configuration and MUST NOT be classified as a product failure or an environment
failure.

#### Scenario: A phase declares a working directory that no longer exists
- **WHEN** a phase configuration is loaded and one of its commands declares a
  working directory absent from the tree
- **THEN** the load fails naming that phase, that command, and that directory,
  and no phase executes

#### Scenario: A phase names a build target the directory does not define
- **WHEN** a phase configuration is loaded and a command invokes a build target
  not defined for its working directory
- **THEN** the load fails naming the target and the directory

#### Scenario: A named target depends on one that does not exist
- **WHEN** a phase configuration is loaded and a named build target resolves but
  one of its prerequisites does not
- **THEN** the load fails, because resolution is performed by the build system
  and covers the prerequisite chain

#### Scenario: A configuration is stale in several places at once
- **WHEN** a phase configuration is loaded and several commands name
  unresolvable entry points
- **THEN** every unresolvable entry point is reported from one load, rather than
  only the first

#### Scenario: A package is relocated and the configuration is not updated
- **WHEN** a package the harness exercises moves and the phase configuration
  still names its former location
- **THEN** the harness reports the stale configuration before running any phase,
  rather than producing an issue candidate attributing the failure to the
  product or to the environment
