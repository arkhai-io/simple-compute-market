## ADDED Requirements

### Requirement: The buyer reads injected time from a lane-time file

The buyer MUST install its process time source from `[time] source`, `"wall"` by default or `"injected"`. Under injected time it MUST read the time of the world from the file `[time] file` names, holding `{"now": <Unix seconds>}`, on every read, so a running command sees a new instant at its next read. A buyer configured for injected time whose file cannot be read or parsed MUST refuse to start, naming the file.

#### Scenario: A running purchase sees an advance

- **WHEN** a `buy` with the watchdog is running under injected time and the harness writes a later instant to its file
- **THEN** the buyer's next probe and staleness judgement read the later instant

#### Scenario: The file is missing

- **WHEN** the buyer runs with `[time] source = "injected"` and its file does not exist
- **THEN** it refuses to start, naming the file
