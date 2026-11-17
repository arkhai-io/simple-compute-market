## ADDED Requirements

### Requirement: The buyer reads injected time from a lane-time file

The buyer MUST install its process time source from `[time] source`, `"wall"` by default or `"injected"`. Under injected time it MUST read the time of the world from the file `[time] file` names, holding `{"now": <Unix seconds>}` parsed by the time component's rule, on every read, so a running command sees a new instant at its next read. A buyer configured for injected time with no `[time] file`, or whose file cannot be read or holds an invalid value, MUST refuse to start, naming the setting or the file. A later read that fails MUST fail the command, naming the file, and MUST NOT fall back to wall time.

#### Scenario: A running purchase sees an advance

- **WHEN** a `buy` with the watchdog is running under injected time and the harness writes a later instant to its file
- **THEN** the buyer's next probe and staleness judgement read the later instant

#### Scenario: The file is missing

- **WHEN** the buyer runs with `[time] source = "injected"` and its file does not exist
- **THEN** it refuses to start, naming the file

#### Scenario: The file holds an invalid instant

- **WHEN** a running buyer's next read finds `{"now": "1794821400"}` in its file
- **THEN** the command fails naming the file, and no read returns wall time
