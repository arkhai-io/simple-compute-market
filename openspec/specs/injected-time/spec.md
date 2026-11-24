# Injected Time

## Purpose

This specification defines how every process reads the time of the world from one source — wall time by default, or injected time frozen at an instant a test sets and moved only forward — and the standalone time component under `tools/injected-time/` that provides it: the process source, the one rule reading a time value, the time file, and the framework-free route service each service binds. Each party's own setting, route and status are its capability's; lane time across a lane's parties is `test-compatibility`'s. The [architecture companion](architecture.md) explains why.

## Requirements

### Requirement: Each process reads the time of the world from one source

Every production process MUST read the time of the world — any instant it stores, signs, sends to another party, or compares with an instant another party knows — from one process time source its composition root installs, and from no other read. The source MUST be wall time unless the process's configuration sets `time.source = "injected"`; any other value MUST refuse startup, naming the setting and the value. A duration of the process's own activity — a timeout, a poll budget, a backoff, a rate-limiter window, a loop interval — MUST be measured on the monotonic clock. A repository check MUST refuse a direct wall-time read in production source and in the lane doubles: `time.time`, `time.time_ns`, `datetime.now`, `datetime.utcnow`, `datetime.today`, `date.today`, and argument-free `time.gmtime()` and `time.localtime()`.

#### Scenario: A module reads the current instant

- **WHEN** production code needs the current instant to record, sign, send or compare
- **THEN** it reads the process time source, and under injected time it reads the injected instant

#### Scenario: A timeout is measured

- **WHEN** a process bounds its own waiting while its injected time is held
- **THEN** the bound elapses on the monotonic clock, and the held injected instant does not stop it

#### Scenario: The source is misspelled

- **WHEN** a process starts with `time.source = "injectd"`
- **THEN** it refuses to start, naming `time.source` and `"injectd"`

#### Scenario: A direct wall-time read is added

- **WHEN** production source or a lane double calls `time.time()` or `datetime.now()` directly
- **THEN** the repository check fails naming the file and line

### Requirement: Injected time is frozen at the instant last set and moves only forward

An injected source MUST return exactly the instant last set, in Unix seconds, until it is set again. A set through the time-setting route MUST refuse an instant earlier than the current one, `409 time_moves_forward`, and change nothing. A service configured for injected time MUST start frozen at the wall instant it started; a process that reads its injected time from a time file, such as the buyer, MUST take the instant the file holds at each read, as `buyer-orchestration`'s "The buyer reads injected time from a lane-time file" requires.

#### Scenario: Time is held between sets

- **WHEN** an injected process is set to 1794821400 and real time passes
- **THEN** every read returns 1794821400 until the next set

#### Scenario: A backward set is refused

- **WHEN** an injected process at 1794822300 is set to 1794821400
- **THEN** the set is refused with `time_moves_forward` and the process still reads 1794822300

### Requirement: Lane time is an integer of Unix seconds read by one rule

A time value — the setting request's and answer's `now`, the status section's `now`, and the lane-time file's `now` — MUST be a JSON integer from 0 to 253402300799, never a boolean, a float or a string. The component MUST provide the one parser every reader uses. A setting request whose body is not exactly `{"now": <valid value>}` MUST be refused `422 invalid_time` and change nothing.

#### Scenario: A boolean is sent as the instant

- **WHEN** a setting request carries `{"now": true}`
- **THEN** it is refused `422 invalid_time` and the process's instant is unchanged

#### Scenario: A fractional instant is sent

- **WHEN** a setting request carries `{"now": 1794821400.5}`
- **THEN** it is refused `422 invalid_time`

### Requirement: The component is standalone

The time component MUST depend only on the standard library, name no market concept, and be published as its own distribution, with a structure test holding that boundary. It MUST provide the process source and its installation, the time value's parser, the forward-only set, the lane-time file's reader and writer, and a framework-free route service answering a setting request and the status time section. A service's HTTP binding of that route service MUST stay the service's own.

#### Scenario: The component's boundary is checked

- **WHEN** the component's structure test runs
- **THEN** it fails if the component imports any repository package or a third-party distribution

### Requirement: An injected process announces its time

A process configured for injected time MUST log that at startup. A service MUST report `{"time": {"source": "injected", "now": <Unix seconds>}}` on its status surface under injected time and `{"time": {"source": "wall"}}` under wall time; a process with no status surface, such as the buyer, announces its injected time only at startup. A process with an Arkhai payments section whose `livemode` is `true` MUST log a warning when its time is injected. Nothing MUST refuse injected time.

#### Scenario: Status shows injected time

- **WHEN** an operator reads the status of a service configured for injected time and set to 1794821400
- **THEN** its time section reports source `injected` and now 1794821400

#### Scenario: Injected time beside live payments

- **WHEN** a storefront configured for injected time has an Arkhai payments section with `livemode = true`
- **THEN** it starts, and logs a warning naming both settings

### Requirement: Database times production logic reads come from the source

A database time that production logic reads — a column a query orders, filters or expires by, or a decision compares — MUST be supplied by the application from the process time source, never computed by SQL. An audit-only column nothing reads MAY keep its SQL default. Each store's integration test MUST assert, under injected time, the times its read columns hold.

#### Scenario: A row is written under injected time

- **WHEN** a store writes a row whose expiry column its sweep compares, with the process at injected instant 1794821400
- **THEN** the stored time derives from 1794821400, not from the database's clock

### Requirement: An instance's time is changed only under injected time

A process's time source MUST be fixed by its configuration. The time-setting route MUST be mounted only on an instance configured for injected time; a wall-time instance MUST offer no way to change its time.

#### Scenario: An operator tries to set a wall-time instance's time

- **WHEN** an administrator sends a time-setting request to a service configured for wall time
- **THEN** no such route exists, and the service's time is unchanged
