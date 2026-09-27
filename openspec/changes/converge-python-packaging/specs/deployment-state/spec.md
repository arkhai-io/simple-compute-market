## ADDED Requirements

### Requirement: Internal distributions are consumed as wheels from the repository wheelhouse

Internal Python distributions MUST be built into the repository wheelhouse (`.dist`)
and consumed from it. A project MUST NOT resolve another repository distribution
through a relative or editable source path, and MUST NOT declare the wheelhouse's
location itself; the tool that syncs or locks the project supplies it. A Docker stage
that resolves internal packages MUST copy the wheelhouse from the build context, so a
wheel change invalidates that stage.

#### Scenario: A consumer resolves a sibling distribution

- **WHEN** a project that depends on another repository distribution is locked
- **THEN** its lock records that distribution from the local wheel registry, not from
  a source path

#### Scenario: A project declares a sibling source

- **WHEN** a project's `pyproject.toml` names a repository distribution through a
  relative source path, or declares a `find-links` location
- **THEN** the packaging check fails and names the project

### Requirement: Each distribution is one flat import package under src

Each repository Python distribution MUST build its wheel from exactly one top-level
import package located at `src/<package>` in its project, and its project environment
MUST install it editable. A project MUST NOT map a directory onto a different import
path, disable editable installation, or declare rebuild cache keys to compensate for
either.

#### Scenario: A module is edited

- **WHEN** a developer edits a module of the project under test
- **THEN** the next test run imports the edited module without a sync

#### Scenario: A project maps its directory onto a nested import path

- **WHEN** a wheel target includes files from outside `src/<package>` or places them
  under another import path
- **THEN** the packaging check fails and names the project

### Requirement: A project environment refreshes exactly the internal packages its lock installs

A rebuilt wheel keeps its version, so a sync keeps both an environment's installed copy
and the lock's recorded dependencies for it unless told otherwise. A project's `reinit`
MUST upgrade and reinstall every package its `uv.lock` resolves from a local wheel
registry, and MUST derive that set from the lock when it runs rather than list it.
Upgrading re-reads a same-version wheel's metadata and MAY rewrite the lock's recorded
dependencies; reinstalling replaces its installed code. Packages resolved from an index
or from source are not refreshed. If the set cannot be derived, the sync MUST NOT run.

Every project with tests whose lock resolves a package from a local wheel registry MUST
have a `reinit` target, and that target MUST delegate to the shared derivation without
naming packages.

#### Scenario: A rebuilt wheel gains a dependency without a version change

- **GIVEN** an internal wheel rebuilt at the same version with new code and a new
  dependency
- **WHEN** a consumer's `reinit` runs
- **THEN** the consumer environment has the new code and the new dependency, and its
  lock records the dependency

#### Scenario: A new internal dependency is refreshed without editing any list

- **WHEN** a project's lock gains a package resolved from `.dist` and its `reinit` runs
- **THEN** that package is upgraded and reinstalled with no edit to the project's
  Makefile

#### Scenario: The lock cannot be read

- **WHEN** `reinit` runs and the project's lock is missing or unparseable
- **THEN** it fails before syncing rather than syncing with no package refreshed

#### Scenario: A hand-written list is refused

- **WHEN** a `reinit` recipe, or a recipe it depends on in the same Makefile, names a
  package in an upgrade, reinstall, or refresh flag, or syncs without the shared
  derivation
- **THEN** the packaging check fails and names the project

### Requirement: An image installs its lock the way a project environment does

An image that installs a project's dependencies MUST install them from that project's
committed lock, used unmodified, with the same internal-package derivation and flags as
the project's `reinit`, so the image contains what the project's tests exercised. An
image that installs the project's own distribution MUST install it from the wheelhouse
at the version the project declares, without a version literal in the image definition.
An image definition MUST NOT list internal packages or rewrite a lock.

#### Scenario: A wheel is rebuilt without a version change

- **GIVEN** a wheel in `.dist` rebuilt with new code and a new dependency at the same
  version, and an image builder whose persistent cache holds the previous build
- **WHEN** the image is built
- **THEN** it contains the new code and the new dependency

#### Scenario: A project's version is bumped

- **WHEN** a project's declared version changes and its image is rebuilt
- **THEN** the image installs that version with no edit to the image definition

#### Scenario: An image definition names packages

- **WHEN** a Dockerfile that copies `.dist` names a package in a refresh, upgrade, or
  reinstall flag, spells a repository distribution's version, rewrites a lock, or
  installs from the wheelhouse other than through the shared derivation
- **THEN** the packaging check fails and names the Dockerfile

### Requirement: Locks are refreshed without installing

The repository MUST provide one command that relocks projects against the current
wheelhouse, upgrading every internal package each lock resolves from it, without
creating or modifying any environment. Because a lock check cannot observe a
same-version wheel's changed dependencies, the command MUST relock every project it is
given rather than skipping those a check reports current.

#### Scenario: A dependency is added to a torch-bearing project

- **WHEN** a developer edits the project's dependencies and runs the lock command
- **THEN** its lock is rewritten from package metadata and no dependency is downloaded
  or installed

#### Scenario: Locks are current

- **WHEN** the lock command runs and nothing has changed
- **THEN** no lock changes

### Requirement: One Python version is declared for the repository

The repository MUST declare one Python version for project environments and images in
a single root declaration. Project environments MUST be created with it, and image
definitions MUST default to it. No other declaration of a Python version for syncing or
building MAY disagree with it.

#### Scenario: A project environment is created on a host with a newer Python

- **WHEN** `reinit` runs on a host whose default Python is newer than the declared one
- **THEN** the environment uses the declared version

#### Scenario: An image default disagrees

- **WHEN** a Dockerfile's Python version default, a Makefile's `--python` value, or a
  project-level version file differs from the root declaration
- **THEN** the packaging check fails and names the file

### Requirement: Packaging conventions are checked mechanically

One repository target MUST run every packaging check — environment setup, lock
currency, Python version, and project layout — and fail if any fails. Each check MUST
also be runnable alone. Lock currency MUST fail on a lock that is not current with its
project, and on a lock that pins an internal package at a version the tree does not
build.

#### Scenario: A lock pins a superseded internal version

- **WHEN** an internal distribution's declared version is bumped and a consumer's lock
  still pins the previous one
- **THEN** the packaging check fails and names the consumer and the package

#### Scenario: Every convention holds

- **WHEN** the packaging target runs on a tree that follows every convention
- **THEN** it succeeds without network access

### Requirement: Aggregate kit tests cover every kit

The aggregate kit test target MUST build prerequisite kit wheels and invoke every kit
subproject's default test suite. Standalone targets MAY remain for focused development,
but the aggregate MUST NOT silently omit a kit.

#### Scenario: A kit is added

- **WHEN** a kit subproject with a default test suite exists
- **THEN** the aggregate kit test target runs that suite

## MODIFIED Requirements

### Requirement: Packaging preserves provider separation

Marketplace builds MUST consume the hosted client only as an exact manifest-pinned wheel from release artifacts, not through editable sibling source, copied models, service wheel, source mounts, or a shared environment. Marketplace release records MUST pin marketplace source separately from the hosted manifest, client wheel, service image, public contract/schema, migration/provenance, repository/workflow, source, and capability identities. Updating the hosted client MUST move its exact pin and relock every consuming project, so every consumer environment installs the new exact wheel before marketplace package, type, or protected checks run.

#### Scenario: Developer initializes hosted support

- **WHEN** marketplace dependency initialization runs
- **THEN** it installs the exact verified client wheel into the marketplace environment without mounting or importing hosted service source

#### Scenario: Expanded client pin changes

- **WHEN** payer/profile/authorization consumption requires a new client release
- **THEN** marketplace lock and release evidence update the exact wheel/manifest together and stale environments fail verification

#### Scenario: Release artifacts are inspected

- **WHEN** marketplace wheels and storefront images are built
- **THEN** they contain no Stripe SDK, hosted service package, EVM gateway implementation, provider credential, or copied hosted model and signature module
