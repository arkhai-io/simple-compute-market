## ADDED Requirements

### Requirement: MCW-c4ek A change's closing checks enforce written rules

A change's closing checks MUST fail when a decision headed `D<n>` under its design's
`## Decisions` has no bullet starting `D<n>` in its proposal's knowledge to promote;
when a comment or docstring line its diff adds uses history wording on the check's
list; when a package version differs from its version at the merge-base with the
branch the change lands on by more than one SemVer step; when an import its diff adds
inside a function has no comment giving its reason; or when a capability with a
specification has no row in the capability index, or a row links no capability.

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

### Requirement: MCW-s8gk The public-content checks refuse private keys and provider credentials

The public-content checks MUST refuse a private key, or a credential in a format one of
the scanner's provider-specific rules recognizes, in added content, a merge's own
resolution included, through a maintained secret scanner at a pinned release, whether
a key is wrapped at any length or written as one escaped string, reporting its
location without its content. They MUST pass a key block whose short body holds no key
material, however many such blocks share a file, and MUST pass the repository's
development fixtures: published development keys, public contract addresses, and code
that names a key.

#### Scenario: A key fixture carries no key material

- **WHEN** a test fixture holds a private-key block whose body is the word `fixture`
- **THEN** the public-content checks pass it

#### Scenario: Two key fixtures share a file

- **WHEN** an added file holds two private-key blocks, each with a short fixture body,
  one after the other
- **THEN** the public-content checks pass it, reading neither block as running into
  the other

#### Scenario: A key is added in a merge resolution

- **WHEN** an outgoing merge commit adds a private-key block with key material that
  neither of its parents holds
- **THEN** the public-content checks refuse it, naming the file and line without
  echoing the key

#### Scenario: A real key is staged

- **WHEN** a staged addition holds a private-key block with base64 key lines, wrapped
  at any length
- **THEN** the public-content checks refuse it, naming the file and line without
  echoing the key

#### Scenario: A key is embedded as one escaped string

- **WHEN** an added source line holds a private-key block as one string, its line
  breaks written as `\n` escapes, with key material for a body
- **THEN** the public-content checks refuse it, naming the file and line without
  echoing the key

#### Scenario: A provider token is staged

- **WHEN** a staged addition holds a token in a provider's published format, such as a
  GitHub personal access token
- **THEN** the public-content checks refuse it, naming the file and line without
  echoing the token

#### Scenario: A development fixture is added

- **WHEN** an added line holds one of Anvil's published development keys, a contract
  address, or the annotation `private_key: Ed25519PrivateKey`
- **THEN** the public-content checks pass it

### Requirement: MCW-u2dt An audit reports every scanner rule and gates nothing

An audit run on demand MUST report, by rule, file and line without content, what every
rule of the pinned scanner but its default private-key rule finds in the tracked tree,
and MUST gate nothing.

#### Scenario: The audit reports what the gate passes

- **WHEN** the tracked tree holds a random 40-character password with no provider
  format, and the owner runs the audit
- **THEN** the audit reports its rule, file and line without echoing it, exits
  successfully, and the public-content checks still pass the line

### Requirement: MCW-l5rv Every lock carries the lock revision the minimum uv writes

The packaging checks MUST fail when a committed lock carries a lock revision other than
the one the repository's minimum uv writes, and every command the repository provides
to relock a project or refresh its environment MUST first refuse a uv older than that
minimum; a plain `uv run` that relocks a changed project is not guarded, and the
revision check fails on what it writes before it lands.

#### Scenario: A lock is written by another uv release

- **WHEN** a committed `uv.lock` carries a lock revision other than the one the
  repository's minimum uv writes
- **THEN** the packaging checks fail, naming the lock and both revisions

#### Scenario: A lock is rewritten with an older uv

- **WHEN** a project is relocked, or a package's environment is refreshed, which may
  rewrite its lock, with a uv older than the repository's minimum
- **THEN** the command refuses before running uv, naming both versions
