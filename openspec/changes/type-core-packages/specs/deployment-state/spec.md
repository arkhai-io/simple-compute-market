## ADDED Requirements

### Requirement: Truthful typed-distribution packaging

A distribution that advertises PEP 561 typing MUST include `py.typed` in its built wheel and MUST install/import with the same supported public typing surface outside the source tree.

#### Scenario: Typed wheel is built

- **WHEN** an included distribution is built and inspected
- **THEN** the marker and supported package modules are present and a clean installed-consumer type fixture resolves them without repository paths

#### Scenario: Marker configuration regresses

- **WHEN** packaging omits `py.typed` or installs a different public module set than the typecheck covers
- **THEN** wheel verification fails before publication
