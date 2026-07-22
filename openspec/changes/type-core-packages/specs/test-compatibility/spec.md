## ADDED Requirements

### Requirement: Package-level typing ratchets

Each package included in the typing campaign MUST expose an independently runnable typecheck with a declared pragmatic baseline. CI MUST run the aggregate of included passing checks, and new errors MUST NOT be hidden through broad public-module exclusions, blanket ignores, or unbounded `Any` substitutions.

#### Scenario: Package joins the aggregate check

- **WHEN** a package's public typing baseline is accepted
- **THEN** its focused check passes independently and becomes part of the CI aggregate without weakening existing package baselines

#### Scenario: Third-party library lacks typing

- **WHEN** an included public boundary depends on incomplete third-party types
- **THEN** any exclusion or adapter is narrow, documented by current rationale, and does not suppress checking of the repository-owned public contract
