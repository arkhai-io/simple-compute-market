## ADDED Requirements

### Requirement: Committed configuration outside the lanes never injects time

A static check MUST refuse `"injected"` as any party's time source in committed configuration outside the lanes' own: chart defaults, the local Helm release's values, production examples and shipped presets. The local Helm release MUST run on wall time; its validation scenarios MUST run in wall mode.

#### Scenario: A production example sets injected time

- **WHEN** a chart's production example values set a storefront's `[Time] source` to `"injected"`
- **THEN** the static check fails naming the file and the party

#### Scenario: The local release is validated

- **WHEN** pre-review validation runs its scenarios against the local Helm release
- **THEN** every party reports wall time, and the scenarios set no time
